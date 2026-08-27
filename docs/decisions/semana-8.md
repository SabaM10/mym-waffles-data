# ADR Semana 8: Reconciliación de precios y auditoría del matching de tarifas

## Contexto

El roadmap de semana 8 declaraba dos entregables: dashboard "Ventas
semanales" y dashboard "Descuentos implícitos" (diferencia entre
`precio_sheet` y `precio_calculado`). Al iniciar la semana se
detectaron problemas conceptuales y varios bugs de datos que hicieron
que la semana pivotara de "armar dashboards" a "auditar y corregir el
pipeline de reconciliación antes de dashboardear".

Al empezar, el modelo dimensional ya producía `precio_item_ars` en
`fact_pedido_items` (calculado por la función `buscar_tarifa`
incorporada al modelo Python). En el papel, esto habilitaba comparar
contra `precio_total_ars` del sheet. Una primera reconciliación
exploratoria arrojó 67% de coincidencia exacta y 20% de discrepancias
grandes, sin claridad sobre las causas.

La auditoría caso por caso reveló tres tipos de causas para las
discrepancias, todas con orígenes distintos:

- Items de masa Proteica, declarada fuera del modelo de pricing en
  semana 6, pero que igualmente estaban recibiendo un precio calculado
  con la tarifa Clásica (asignación falsa).
- Pedidos históricos de Cliente A donde una fila del sheet contenía en
  realidad dos pedidos consolidados de sucursales distintas.
- Un bug del SCD Type 2: el CSV `precios_historicos.csv` declaraba el
  corte del aumento de marzo el 31/03, pero el aumento real había
  arrancado el 25/03.

Además, la premisa del roadmap de "detectar descuentos implícitos" fue
rechazada por conocimiento del negocio: MyM Waffles nunca cobra por
debajo de la lista de precios. Toda discrepancia sheet vs calculado
es, por definición, un error o una data no modelada. El propósito del
dashboard cambió en consecuencia.

## Decisiones

### Decisión 1: Reencuadre del dashboard como "Reconciliación / Detección de errores"

Se descarta la denominación "descuentos implícitos" del roadmap. Se
adopta "reconciliación" como concepto y "detección de errores de carga
y anomalías" como propósito operativo.

**Justificación**: el dueño del negocio confirmó que MyM Waffles nunca
cobra por debajo de la lista de precios. Toda discrepancia entre
`precio_sheet` y `precio_calculado` cae en uno de estos grupos:

- Error de carga humana en el sheet (cantidad no coincide con
  descripción, precio mal tipeado).
- Producto fuera de scope del modelo (proteicos, veganos).
- Bug del pipeline (matching de tarifas mal implementado, SCD Type 2
  con fechas incorrectas).
- Data histórica legítima pero mal estructurada (pedidos consolidados
  de múltiples sucursales bajo un solo cliente).
- Descuentos operativos por gentileza (post-aumento, algunos pedidos
  siguen con precio viejo unos días).

El dashboard funciona como herramienta de auditoría de calidad de
datos, no como reporte comercial. Este reencuadre también encaja mejor
con el perfil de portfolio hacia IT Audit.

### Decisión 2: Nulificar `tarifa_id`, `precio_unitario_aplicado_ars`, `precio_item_ars` para masa Proteica en `fact_pedido_items`

Se modifica la función `buscar_tarifa` en `fact_pedido_items.py` con
un guard clause al inicio que devuelve `None` en las tres columnas
cuando la masa es `"Proteica"`.

**Alternativa considerada**: dejar el matcher como estaba (proteicos
asignados a tarifa Clásica), filtrar proteicos en el mart de
reconciliación downstream, o tratar proteicos como quarantine con test
rojo permanente (patrón de Veganos, Decisión 6 semana 6).

**Por qué la rechacé**: el matcher sin cambios miente (asigna a
proteicos precio de tarifa Clásica que no aplica); filtrar downstream
solo oculta el problema en un nivel más arriba pero el fact sigue
mintiendo; y el patrón de Veganos como quarantine no escala porque
proteicos son mucho más frecuentes (11 items vs 1), y N filas rojas
diluye la señal en vez de amplificarla.

**Fix**: guard clause al principio de `buscar_tarifa`:

```python
if masa == "Proteica":
    return {"tarifa_id": None, "precio_unitario": None, "precio_total": None}
```

**Consecuencia verificada**: los 11 items de masa Proteica del año
2026 pasaron a tener las tres columnas en null. La modificación no
rompió ningún test existente porque los tests `not_null` sobre
`tarifa_id` no estaban declarados en `fact_pedido_items`. El caso
histórico de Veganos (1 item) sigue documentado como test rojo
conocido según Decisión 6 semana 6.

### Decisión 3: Corrección de `valid_to` del intervalo pre-aumento en `precios_historicos.csv` del 31/03 al 24/03

Durante la auditoría se descubrió que el CSV `precios_historicos.csv`
declaraba `valid_to = 2026-03-31` para el intervalo de tarifas
enero-marzo, pero la verificación contra el sheet mostró que el
aumento se había aplicado desde el 25/03 (todos los pedidos del 25/03
en adelante cobraron precios nuevos). Los 6 días entre 25/03 y 31/03
estaban siendo reconciliados contra la tarifa vieja, generando falsos
negativos (pedidos correctamente cobrados aparecían como "descuentos").

**Fix**: script one-off (`scratch_fix_corte_marzo.py`, gitignored) que
recorre el CSV y aplica dos cambios por cada tarifa afectada:
`valid_to` de `2026-03-31` a `2026-03-24`, y `valid_from` de
`2026-04-01` a `2026-03-25`. Total: 26 tarifas × 2 ediciones = 52
cambios verificados. Backup del CSV guardado antes de correr el script
(`precios_historicos.csv.bak`, también gitignored).

**Justificación**: la fuente de verdad de cuándo se aplicó el aumento
es el sheet, no el CSV. El CSV había sido armado en semana 6 con una
fecha "prolija" (fin de mes) para simplificar la carga inicial. La
corrección hace que el modelo refleje la realidad operativa.

**Aprendizaje**: los cortes de SCD Type 2 declarados manualmente
tienen que validarse contra la data cruda del negocio, no confiar en
la fecha "prolija". Si el CSV se arma primero y no se cruza con las
transacciones reales, cualquier desfasaje pasa inadvertido y solo
aparece como discrepancia en el dashboard, sin trazabilidad hacia la
causa.

**Consecuencia verificada**: 9 pedidos que estaban en
`DISCREPANCIA_GRANDE` pasaron a `COINCIDE`. La coincidencia exacta
total subió de 67% a 71.4%.

### Decisión 4: No corregir el CSV para el corte de julio, aunque haya excepciones documentables

El corte del intervalo 2 al 3 (aumento de julio) fue verificado contra
el sheet y se confirmó que el CSV está correcto: los precios nuevos
empezaron el 01/07/2026. Sin embargo, se detectaron al menos 2
pedidos post-aumento (Cliente C del 03/07 y Cliente T del 04/07)
que quedaron facturados con precio viejo, probablemente por gentileza
operativa.

Se decide **no ajustar el CSV** para "absorber" estas excepciones. El
corte oficial se mantiene en 01/07.

**Justificación**: se establece como regla que las fechas de vigencia
en `precios_historicos.csv` reflejan las fechas oficiales del aumento
comunicado, no las fechas de aplicación efectiva pedido por pedido.
Si el CSV se ajustara para tapar estos casos, se perdería la señal
que el dashboard justamente debe exponer.

**Consecuencia**: estos pedidos aparecen en el dashboard como
`DISCREPANCIA_CHICA` documentada. Es data honesta: efectivamente
cobraron menos que la lista, y esa información sirve para que el
negocio decida si acepta la práctica o la limita en el futuro.

### Decisión 5: Aceptar pedidos históricos de Cliente A consolidados como "data no corregible"

Se identificaron 6 pedidos del cliente A (3 con cantidad 128 en
enero, 3 con cantidad 112 en febrero-marzo) que muestran discrepancia
sistemática. Investigación con el dueño reveló que estos pedidos son
en realidad la suma de dos pedidos distintos (una sucursal + otra),
cargados como una sola fila porque la segunda sucursal aún no se
diferenciaba en el sistema de carga. A partir de una fecha posterior,
los pedidos se cargan separados por sucursal .

Se decide **no corregir retroactivamente** estos 6 casos.

**Justificación**:

- Son pocos casos (6 de 224 pedidos, 2.7%).
- El patrón no se repite después de la división operativa.
- Corregirlos requeriría crear la segunda sucursal retroactivamente
  en `dim_cliente` y reasignar items, modificando la historia del
  warehouse.
- El costo de la corrección supera el beneficio analítico.

**Consecuencia**: estos casos aparecen en el dashboard de
reconciliación como `DISCREPANCIA_CHICA` documentada. Se acepta como
ruido histórico conocido.

### Decisión 6: Nuevo mart `rpt_reconciliacion_pedidos` con categorización por tipo de discrepancia

Se crea el modelo
`dbt_project/models/marts/rpt_reconciliacion_pedidos.sql` con una fila
por pedido, comparando precio del sheet contra precio calculado, y
clasificando cada pedido en una de cuatro categorías:

- **`COINCIDE`**: `abs(diferencia_ars) < umbral_coincide_ars`.
  Reconciliación perfecta.
- **`DISCREPANCIA_CHICA`**: `abs(diferencia_ars) between
  umbral_coincide_ars and umbral_discrepancia_grande_ars`. Discrepancia
  menor, revisable pero no crítica.
- **`DISCREPANCIA_GRANDE`**: `abs(diferencia_ars) >
  umbral_discrepancia_grande_ars`. Requiere auditoría manual.
- **`SIN_TARIFA_MODELADA`**: al menos un item del pedido tiene
  `tarifa_id` null (proteicos, veganos, o cualquier producto futuro
  fuera de scope). Precedencia sobre las demás categorías.

Distribución al cierre de la semana: `COINCIDE` 160 (71.4%),
`DISCREPANCIA_CHICA` 29 (12.9%), `DISCREPANCIA_GRANDE` 24 (10.7%),
`SIN_TARIFA_MODELADA` 11 (4.9%).

**Justificación de la precedencia**: si un pedido tiene proteicos, cae
en `SIN_TARIFA_MODELADA` aunque el resto del pedido cuadre. La
contaminación por items faltantes hace que cualquier comparación
numérica sea engañosa. Priorizar esta categoría evita clasificar como
"discrepancia grande" un pedido que en realidad no se puede reconciliar
por diseño.

Columnas del mart: `pedido_id`, `fecha_emision`, `cliente_id`,
`cliente_canonico`, `tipo_cliente`, `cantidad_total`,
`precio_sheet_ars`, `precio_calculado_ars`, `diferencia_ars`,
`diferencia_pct`, `items_totales`, `items_sin_tarifa`,
`tipo_discrepancia`.

### Decisión 7: Umbrales como variables dbt, no hardcodeados

Los umbrales `umbral_coincide_ars` (default 1) y
`umbral_discrepancia_grande_ars` (default 1000) se declaran en
`dbt_project.yml` como variables:

```yaml
vars:
  umbral_coincide_ars: 1
  umbral_discrepancia_grande_ars: 1000
```

**Justificación**: los umbrales son convenciones tentativas, no reglas
fijas del negocio. Ajustarlos según cómo se distribuya la data real es
esperable. Con variables, la modificación no requiere editar SQL ni
recompilar el modelo — se edita el YAML o se pasa por línea de
comandos con `--vars`.

**Consecuencia (menor)**: cualquier consulta manual contra el mart que
quiera reproducir la categorización tiene que conocer los umbrales
vigentes. Como los umbrales viven en `dbt_project.yml`, están
versionados y auditables.

### Decisión 8: `cliente_canonico` denormalizado en el mart

`rpt_reconciliacion_pedidos` incluye la columna `cliente_canonico`
obtenida por join con `dim_cliente`, en lugar de dejar solo el FK
`cliente_id` y forzar el join en cada consulta downstream.

**Justificación**: el mart tiene un propósito claro de auditoría y sus
consumos van a filtrar frecuentemente por cliente. Pre-joinearlo
reduce fricción operativa sin agregar complejidad al modelo. El costo
(una columna redundante en un mart de ~224 filas) es despreciable.

**Trade-off asumido**: si en el futuro `dim_cliente.cliente_canonico`
cambia (por ejemplo, se renombra un cliente), el mart tiene que
rebuildearse para reflejarlo. Con `table` como materialización y
rebuild automático en cada corrida de Dagster, este costo es
transparente.

### Decisión 9: Tests dbt para robustez del mart

Se agregan tests declarativos en `rpt_reconciliacion_pedidos.yml`:

- `unique` y `not_null` sobre `pedido_id` (garantiza grain "una fila
  por pedido").
- `relationships` de `pedido_id` a `fact_pedidos` y de `cliente_id` a
  `dim_cliente` (integridad referencial).
- `not_null` sobre `fecha_emision`, `precio_sheet_ars`, `cliente_id`,
  `tipo_discrepancia`.
- `accepted_values` sobre `tipo_discrepancia` con las 4 categorías
  canónicas.

**Alternativa considerada**: agregar tests `not_null` sobre
`precio_calculado_ars`, `diferencia_ars` y `diferencia_pct`.

**Por qué la rechacé**: estos campos son null por diseño en la
categoría `SIN_TARIFA_MODELADA`. Un `not_null` los rompería para 11
pedidos. La alternativa sería un test custom `not_null_where` que
excluya esa categoría, pero se dejó como deuda menor para no complicar
la primera versión del mart.

**Consecuencia verificada**: 9 tests corriendo, todos en verde.

## Consecuencias

### Ganancias

- **Reconciliación funcional end-to-end**: el warehouse puede comparar
  precio del sheet contra precio calculado para cada pedido, y
  categoriza automáticamente cada uno. Base para auditoría continua.
- **Bug del SCD Type 2 detectado y corregido**: la práctica de auditar
  la data cruda contra la lógica del modelo reveló un error que no era
  visible desde ningún test automático. Aprendizaje transferible: los
  cortes de SCD Type 2 declarados manualmente deben validarse contra
  la data real, no confiar en la fecha "prolija".
- **Regla operativa clara sobre fechas de aumento**: las fechas
  oficiales del aumento se preservan en el CSV; las excepciones
  operativas se dejan expuestas en el dashboard como señal, no se
  tapan.
- **Categorización explícita de discrepancias**: en lugar de un "hay
  20% de discrepancias sin explicación", ahora hay 4 categorías con
  criterios claros. `SIN_TARIFA_MODELADA` distingue "no puedo
  comparar" de "puedo comparar y no coincide".
- **Mart consumible directo por Metabase**: con `cliente_canonico`
  denormalizado y categoría preclasificada, los dashboards no
  requieren lógica adicional en la herramienta de consumo.
- **9 tests dbt protegiendo el mart**: cualquier cambio futuro
  upstream que rompa la integridad del mart se detecta
  automáticamente.
- **Cierre de deuda de semana 7**: el archivo vacío
  `int_item_tarifa_match.sql` fue eliminado. El matching real vive en
  `fact_pedido_items.py` (modelo Python), no en un modelo SQL
  intermedio como se había planeado originalmente.

### Costos

- **Descubrimiento del bug del CSV solo por casualidad**: el corte del
  25/03 se detectó porque un caso puntual llamó la atención durante
  la auditoría. Puede haber otros cortes cargados con fechas
  "prolijas" que no coinciden con el aumento real y que aún no se
  detectaron.
- **Semana desviada de la planificación original**: el roadmap
  declaraba dashboards Metabase como entregable. La auditoría del
  matching consumió la mayoría de la semana. Metabase queda diferido,
  la deuda se traslada.
- **Data histórica legítima aparece como "outlier"**: los pedidos
  consolidados de Cliente A y los descuentos por gentileza post-01/07
  van a mostrarse siempre en el dashboard como discrepancias. Es
  intencional (mejor exponer que ocultar), pero requiere que el
  usuario del dashboard sepa interpretarlos.

### Deuda declarada

- **Flag `es_negociado` o `es_gentileza` en el sheet**: para poder
  distinguir en el dashboard los descuentos legítimos (aunque hoy el
  negocio no da como regla, sí ocurren casos operativos) de los
  errores de carga o bugs. Requiere agregar una columna al sheet
  fuente y modificar el pipeline de ingesta. Fuera del scope
  inmediato.
- **Auditoría de otros cortes de tarifa históricos**: el bug del
  25/03 se detectó por casualidad. Correr una reconciliación
  sistemática después de cada aumento futuro, no solo confiar en la
  fecha "prolija" cargada al CSV.
- **Backfill 2024-2025 (semana 11) hereda este problema**: si el CSV
  histórico para años anteriores se arma con fechas prolijas, va a
  repetir el mismo bug. Cuando llegue semana 11, validar cada corte
  contra la data real antes de dar por bueno el CSV.
- **Test rojo conocido de Veganos**: sigue vigente desde semana 6,
  ahora acompañado del tema Proteica manejado con nulls (no genera
  test rojo, pero es información latente).
- **Pack de 400 unidades sin modelar**: el pedido de Cliente G (400
  unidades, cliente B2B) no matchea contra ningún pack de
  `dim_tarifa` porque el máximo modelado es 96. El matcher hace
  `precio_unitario_96 × 400`, que no refleja la realidad del precio
  negociado. Requiere decidir si se agregan packs jumbo al CSV o si
  se acepta que "pedidos > 96 unidades" quedan como no reconciliables.
- **Deprecation warnings de sintaxis vieja de tests dbt**: 3 warnings
  de `MissingArgumentsPropertyInGenericTestDeprecation` en
  `dim_cliente.yml` y `rpt_reconciliacion_pedidos.yml`. Migración
  pendiente a la sintaxis nueva con `arguments`. Ya declarada en el
  ADR de semana 7.
- **Test custom `not_null_where` para `SIN_TARIFA_MODELADA`**:
  actualmente el mart no valida que `precio_calculado_ars`,
  `diferencia_ars` y `diferencia_pct` sean not null cuando
  `tipo_discrepancia != 'SIN_TARIFA_MODELADA'`. Agregarlo cuando
  aparezca la necesidad concreta.
- **Metabase pendiente**: el entregable visual original del roadmap
  (dashboards en Metabase) queda para completar. Decisiones
  pendientes: driver DuckDB community vs export a Postgres,
  estructura de los dashboards, filtros por defecto.
