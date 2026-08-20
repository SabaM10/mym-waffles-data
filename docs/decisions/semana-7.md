# ADR Semana 7: Orquestación con Dagster

## Contexto

Al terminar semana 6, el pipeline de datos funcionaba correctamente pero
estaba distribuido en varios comandos independientes ejecutados a mano:

- `python -m ingestion.pedidos` para cargar `raw.pedidos` desde Sheets.
- `python -m ingestion.precios` para cargar `raw.precios` desde Sheets.
- `dbt seed && dbt run && dbt test` para transformar todo lo anterior en
  el modelo dimensional.

El orden de ejecución vivía en la cabeza del operador (yo). Si alguien
corría dbt antes de la ingesta, dbt trabajaba sobre datos obsoletos sin
avisar. No había logs centralizados, no había retry automático, no había
visibilidad del estado del pipeline, y no había forma de re-materializar
una parte específica sin correr todo.

Semana 7 introduce Dagster como orquestador de assets: cada tabla del
warehouse pasa a ser un "asset" con dependencias explícitas, y todo el
pipeline queda declarado como un DAG (Directed Acyclic Graph) que Dagster
ejecuta en orden correcto, con logs, visibilidad, y capacidad de
re-materialización granular.

## Decisiones

### Decisión 1: Assets Python autocontenidos, sin resources dedicados de DuckDB/gspread

Dagster promueve un patrón donde cada dependencia externa (conexión a
base de datos, cliente API, config) se declara como un **resource** y se
inyecta en los assets que la necesitan. Este patrón habilita testing con
mocks, cambio de ambientes (prod/staging), y separación de concerns.

Sin embargo, los assets `raw.pedidos` y `raw.precios` de este proyecto
**no usan resources dedicados** para DuckDB ni gspread. En su lugar,
llaman internamente a funciones de `ingestion/pedidos.py` y
`ingestion/precios.py`, que instancian sus propias conexiones vía
`get_config()` y clientes gspread ya construidos.

El único resource dedicado es `dbt` (`DbtCliResource`), porque
`dagster-dbt` requiere pasarlo explícitamente a la función decorada con
`@dbt_assets`.

**Justificación**: refactorizar `ingestion/*.py` para recibir conexiones
inyectadas requeriría cambiar la firma de funciones que ya funcionan y
tienen tests unitarios. El beneficio (más "canónico") no compensa el
costo (refactor con riesgo de regresión) mientras no aparezca una
necesidad concreta: testing con mocks, múltiples ambientes, o cambio de
credenciales sin tocar código.

**Aprendizaje**: la "mejor práctica" de un framework no siempre justifica
un refactor. Cuando el código existente es simple, autocontenido, y
tiene tests, envolverlo en un asset sin cambiarlo internamente es una
decisión válida.

**Deuda declarada**: cuando aparezca la primera necesidad real de mockear
gspread o cambiar la path del DuckDB por ambiente, migrar a resources
inyectados.

### Decisión 2: Fusión Python ↔ dbt vía `key_prefix`

Cuando `dagster-dbt` importa el manifest de dbt, genera automáticamente
un asset por cada `source` declarado en `sources.yml`. En este proyecto,
`raw.pedidos` y `raw.precios` están declarados como sources.

Al mismo tiempo, los assets Python `raw_pedidos` y `raw_precios`
también generan sus propios `AssetKey`. Sin ajuste, la UI de Dagster
muestra **4 assets duplicados**: dos Python y dos sources dbt, con las
mismas tablas pero desconectados entre sí. El DAG queda partido en dos
islas: los assets Python arriba, los assets dbt abajo, sin flechas que
conecten ambos.

**Fix**: cambiar los decorators a `@asset(key_prefix=["raw"], name="pedidos")`.
Con eso el `AssetKey` del asset Python es `["raw", "pedidos"]`, que
matchea exactamente con el `AssetKey` autogenerado del source dbt. Cuando
Dagster encuentra dos assets con la misma key, los fusiona: pasa a haber
un solo asset `raw.pedidos` que Python materializa y del cual dbt
depende downstream.

**Consecuencia**: el DAG visual en la UI se ve conectado end-to-end,
desde la ingesta hasta el mart final. Esto habilita ver lineage completo,
detectar assets huérfanos (ver deuda 1), y planear re-materializaciones
parciales correctamente.

### Decisión 3: Schedule diario deshabilitado por default

Semana 7 declara un schedule cron (`daily_refresh_schedule`) que dispara
"Materialize all" todos los días a las 06:00 UTC. Sin embargo, el
schedule está declarado con `DefaultScheduleStatus.STOPPED`.

**Justificación**: el pipeline hoy corre en la máquina local del
desarrollador (Docker Desktop en Windows), que no está prendida 24/7.
Activar el schedule sería inútil: los ticks a las 6 AM UTC (3 AM Buenos
Aires) van a caer en momentos donde la máquina está apagada, generando
solo logs de "missed ticks" sin ejecución real.

Al mismo tiempo, dejar el schedule **declarado en código** aunque
deshabilitado tiene valor: cuando el proyecto se despliegue a un server
24/7 (fase futura), activarlo requiere solo un toggle en la UI. La
lógica de "cuándo y qué correr" ya está codificada y versionada.

**Trade-off asumido**: hay una decisión implícita de que el schedule es
"documentación ejecutable" del comportamiento esperado en producción,
no algo que funcione hoy. Esta distinción tiene que estar clara en el
README para evitar que alguien active el schedule sin entender la
consecuencia.

**Deuda declarada**: cuando se active en producción, revisar timezone
(hoy UTC, probablemente debería ser `America/Argentina/Buenos_Aires`).

### Decisión 4: Path absoluta en `.env` para `DUCKDB_PATH`

El archivo `.env` original tenía `DUCKDB_PATH=./data/mym_waffles.duckdb`
(path relativa). Cuando dbt corría desde la terminal (`docker compose
exec dagster dbt run`), la path relativa se resolvía correctamente
contra `/workspace`, dando `/workspace/data/mym_waffles.duckdb`.

Sin embargo, cuando `dagster-dbt` ejecuta `dbt build` internamente, hace
`cd /workspace/dbt_project` antes de invocar dbt. En ese contexto, la
misma path relativa `./data/mym_waffles.duckdb` se resuelve a
`/workspace/dbt_project/data/mym_waffles.duckdb`, que no existe. Error:
`IO Error: Cannot open file`.

**Fix**: cambiar la variable a path absoluta:
`DUCKDB_PATH=/workspace/data/mym_waffles.duckdb`.

**Aprendizaje**: paths relativas en variables de entorno son frágiles
cuando el proceso que las consume puede tener un CWD (current working
directory) distinto al que asume el desarrollador. Para servicios que
corren como subprocess (dbt bajo Dagster, workers, jobs distribuidos),
las paths absolutas son más robustas.

**Consecuencia (menor)**: el proyecto queda atado a que el container
monte el código en `/workspace` específicamente. Esta convención ya
existía implícitamente en `PYTHONPATH`, en el `docker-compose.yml`, y en
la path de dbt. Formalizarla en `.env` no agrega acoplamiento nuevo.

### Decisión 5: `PYTHONPATH` explícita en `docker-compose.yml`

El modelo Python de dbt `fact_pedido_items.py` importa desde
`ingestion.parsers`. Este import requiere que `PYTHONPATH` incluya
`/workspace` (la raíz del proyecto).

Ese fix fue implementado y documentado en semana 6 (ADR de semana 6,
Decisión 2). Sin embargo, al arrancar semana 7 el bug reapareció:
`ModuleNotFoundError: No module named 'ingestion'`.

**Diagnóstico**: `PYTHONPATH` no estaba seteada en el env del container
(ni en bash session ni en PID 1). El fix original de semana 6 se había
perdido en algún cambio no rastreado del `docker-compose.yml`, o quizás
estaba en un `.env` que no se sincronizó entre las dos máquinas donde
trabajo.

**Fix**: agregar `PYTHONPATH: /workspace` en la sección `environment`
del service `dagster` en `docker-compose.yml`. Esta vez queda en el
compose (versionado en git), no en `.env` (gitignored), para reducir
riesgo de que se pierda en migraciones entre máquinas.

**Aprendizaje**: los fixes de infraestructura que dependen de env vars
son propensos a "perderse silenciosamente" si viven en archivos
gitignored. Cuando la configuración es requerida para el correcto
funcionamiento del pipeline (no un secreto), va en el compose, no en
`.env`.

## Consecuencias

### Ganancias

- **Pipeline entero ejecutable con un click**: "Materialize all" en la UI
  corre ingesta + seeds + staging + dims + facts + marts + tests en el
  orden correcto. Duración total: ~1 minuto 10 segundos para el pipeline
  completo (2 assets Python + 87 nodos dbt).
- **Visibilidad del estado del pipeline**: la UI muestra el DAG completo,
  qué asset se materializó por última vez, cuándo, y con qué resultado.
  Reemplaza el modelo mental que antes vivía en la cabeza del operador.
- **Detección de assets huérfanos**: el DAG visual reveló que
  `int_item_tarifa_match` (creado en semana 6) no está conectado a
  ningún otro asset. Ningún modelo hace `ref('int_item_tarifa_match')`.
  Es información valiosa que sería difícil de ver leyendo el código.
- **Base para automatización futura**: el schedule diario está declarado
  y listo para activarse cuando el pipeline se despliegue a un server
  24/7. No requiere cambio de código, solo un toggle en la UI.
- **Tests de integración de la definición**: 4 tests pytest validan que
  la definición de Dagster carga sin errores y contiene los assets, jobs
  y schedules esperados. Cualquier cambio futuro que rompa la estructura
  falla en pytest antes de aparecer en la UI.
- **Aprendizaje transferible**: el patrón "asset Python + `dbt_assets`
  auto-generados + fusión vía `key_prefix`" es reutilizable en cualquier
  proyecto que combine ingesta Python con transformación dbt.

### Costos

- **Configuración de env vars frágil en subprocess de `dagster-dbt`**:
  ni `DUCKDB_PATH` (relativa) ni `PYTHONPATH` propagaban correctamente
  al subprocess que ejecuta `dbt build`. Ambos requirieron fixes
  explícitos (path absoluta en un caso, declaración en compose en el
  otro). El comportamiento no está documentado claramente en
  `dagster-dbt` y requirió debugging iterativo.
- **Curva de aprendizaje de Dagster**: la API cambia entre versiones
  (varios métodos usados en tutoriales viejos ya no existen o cambiaron
  de nombre: `get_asset_graph` vs `resolve_asset_graph`, `all_asset_keys`
  vs `get_all_asset_keys`). Requiere buscar la doc de la versión
  específica instalada.
- **Ruido visual en el DAG**: los seeds `.example.csv` (versiones
  anonimizadas para portfolio) aparecen como assets en la UI, aunque no
  forman parte del pipeline real. Confunde a la primera lectura del DAG.

### Deuda declarada

- **`int_item_tarifa_match` desconectado del DAG**: chequear si
  `fact_pedido_items` debería estar consumiendo `tarifa_id` desde este
  modelo intermedio. Si sí, la lógica de matching implementada en
  semana 6 no está siendo aplicada. Si no, el modelo intermedio es
  código muerto que hay que borrar. Determinar cuál de las dos.
- **Seeds `.example.csv` como assets**: excluirlos de la carga de dbt
  para limpiar el DAG visual. Alternativa: moverlos fuera de la carpeta
  `seeds/` (por ejemplo a `docs/seed_examples/`).
- **13 deprecation warnings de sintaxis vieja de tests dbt**: migrar de
  `tests: [accepted_values: {values: [...]}]` a la sintaxis nueva con
  `arguments`. No urgente, va a romper en dbt 2.x.
- **Timezone del schedule**: hoy `0 6 * * *` interpretado como UTC.
  Antes de activar en producción, agregar
  `execution_timezone="America/Argentina/Buenos_Aires"` al
  `ScheduleDefinition` para que corra a las 6 AM hora local.
- **Comportamiento de env vars en subprocess de `dagster-dbt`**:
  investigar si hay una forma "canónica" de pasar env vars al subprocess
  (por ejemplo vía config del `DbtCliResource`) en lugar de depender del
  env del container completo. Bajo prioridad porque el fix actual
  funciona.