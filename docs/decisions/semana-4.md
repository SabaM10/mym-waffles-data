# ADR Semana 4: Setup dbt + Staging

## Contexto

## Contexto

Al terminar semana 2, teníamos `raw.pedidos` y `raw.precios` en DuckDB con 
data cruda, tal como venía de Google Sheets. Faltaba transformarla: tipar 
columnas, limpiar formatos (precios con `$` y separadores, fechas 
`dd/mm/yyyy`, booleans string), y armar el modelo dimensional que 
alimentaría los dashboards.

Podríamos haber escrito esto en Python puro con scripts SQL sueltos, pero 
teníamos tres problemas concretos por delante:

1. **Dependencias**: cada transformación depende de otras. Sin una 
   herramienta específica, hay que declarar manualmente el orden de 
   ejecución y mantenerlo actualizado cuando cambia el pipeline.

2. **Validación**: reglas como "esta columna no puede ser null" o "estos 
   valores solo pueden ser X, Y, Z" se implementan como código imperativo 
   ad-hoc por cada tabla. Difícil de mantener y de reutilizar.

3. **Trazabilidad**: sin lineage automático, responder "¿de dónde sale 
   esta métrica del dashboard?" requiere leer manualmente todos los 
   scripts en orden hasta reconstruir la cadena.

Decidimos incorporar dbt como capa de transformación porque resuelve los 
tres problemas de forma nativa: dependencias declaradas con `ref()`, 
tests declarativos en YAML, y lineage automático.

## Decisiones

### Decisión 1: dbt como herramienta de transformación

Elegimos dbt-core sobre otras alternativas (SQLMesh, Dataform, scripts SQL 
con orquestador manual) por tres razones concretas:

**Adopción**: dbt es el estándar de facto en la industria. Casi todas las 
ofertas de Data / Analytics Engineering lo mencionan como requisito o 
plus. Aprenderlo tiene retorno de carrera claro.

**Integración con el stack existente**: el adapter `dbt-duckdb` es maduro 
y bien mantenido. Otras herramientas modernas (SQLMesh) también lo 
soportan pero con menos documentación y ejemplos.

**Costo**: `dbt-core` es open source y gratuito. Alineado con la filosofía 
del proyecto (cero cloud, cero costo). La versión comercial (`dbt Cloud`) 
solo agrega orquestación gestionada, que ya cubrimos con Dagster.

Un beneficio adicional relevante al perfil profesional: dbt tiene 
features específicamente valoradas en auditoría — tests declarativos 
versionados en git, lineage automático, documentación como código, 
historial de ejecuciones. Todo lo que un auditor quiere ver como evidencia.

### Decisión 2: `profiles.yml` adentro del repo

La convención tradicional en dbt es mantener `profiles.yml` en `~/.dbt/`, 
fuera del repo. Esto tiene sentido en la mayoría de proyectos, donde el 
archivo contiene credenciales reales al warehouse cloud (Snowflake, 
BigQuery, Redshift): password, account name, warehouse identifier. 
Commitear eso a git expondría los accesos a quien tenga acceso al 
repositorio.

En nuestro caso, la situación es distinta. DuckDB es un archivo local, 
no requiere credenciales para conectarse. Nuestro `profiles.yml` solo 
contiene el path al archivo, y ese path se resuelve dinámicamente vía 
`env_var('DUCKDB_PATH')`, cuyo valor real vive en `.env` (gitignored).

Decidimos ubicar `profiles.yml` en `dbt_project/profiles.yml` (adentro 
del repo) porque:

1. No hay secrets que exponer: la referencia via `env_var()` mantiene los 
   valores reales fuera del código versionado.

2. Simplifica el setup en nuevas máquinas: al clonar el repo, el 
   `profiles.yml` ya está donde dbt lo busca, no hay que crear archivos 
   en directorios del sistema.

3. La configuración de conexión queda documentada como parte del código 
   del proyecto, no como conocimiento tribal.

Para que dbt encuentre el archivo, seteamos la variable de entorno 
`DBT_PROFILES_DIR=/workspace/dbt_project` en el `.env` y en 
`docker-compose.yml`, dado que por default dbt busca en `~/.dbt/`.

### Decisión 3: macro custom para eliminar el prefijo `main_`

Por default, el adapter `dbt-duckdb` genera nombres de schema compuestos: 
al declarar `schema: staging` en un modelo, dbt crea la tabla en 
`main_staging.stg_pedidos` en lugar de `staging.stg_pedidos`. Este 
comportamiento es intencional, heredado de la convención dbt para 
warehouses tipo BigQuery donde ayuda a evitar colisiones entre 
proyectos. En DuckDB es innecesario y contraproducente.

El problema práctico: los nombres compuestos rompen la organización 
lógica que definimos (`raw`, `staging`, `intermediate`, `marts`). En vez 
de queries limpios como `SELECT * FROM staging.stg_pedidos`, terminamos 
con `SELECT * FROM main_staging.stg_pedidos`, que mezcla el concepto de 
"database" con el de "schema" y complica el mental model del warehouse.

Decidimos sobrescribir el comportamiento con una macro custom en 
`dbt_project/macros/generate_schema_name.sql`. La macro instruye a dbt a 
usar el nombre del schema tal como se declara, sin agregar prefijos:

```sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

Es un patrón conocido en proyectos dbt con DuckDB: la macro se resuelve 
una vez y ya funciona para todos los modelos.

### Decisión 4: sources declarados explícitamente en `sources.yml`

Cuando construimos los primeros modelos de staging, había dos formas de 
referenciar las tablas raw:

- Hardcodear el nombre: `select * from raw.pedidos`.
- Declararlas como sources y usar `select * from {{ source('raw', 'pedidos') }}`.

Elegimos la segunda por tres razones concretas:

**Refactor seguro**: si mañana renombramos una tabla raw (por ejemplo, 
`raw.pedidos` → `raw.pedidos_v2`), con la primera opción hay que buscar 
y reemplazar en todos los modelos que la usen — un solo olvido rompe el 
pipeline silenciosamente. Con sources, se cambia una línea en 
`sources.yml` y todos los modelos siguen funcionando.

**Lineage visible**: dbt genera un DAG automático que muestra las 
dependencias entre modelos. Con `ref()` y `source()`, ese DAG incluye 
las tablas raw como nodos con ícono propio. Sin sources declarados, los 
modelos staging aparecen huérfanos, como si salieran de la nada, y se 
pierde la trazabilidad hasta el origen.

**Freshness checks**: dbt permite declarar en `sources.yml` un umbral de 
antigüedad esperable ("esta tabla no debería tener más de 24 horas"). 
Corriendo `dbt source freshness` alerta si el pipeline de ingesta falló 
y la data quedó vieja. Es red de seguridad automática que solo funciona 
con sources declarados.

El costo de esta decisión es escribir el archivo `sources.yml` con 
metadata de cada tabla raw. Bajo, y compensa el beneficio en 
mantenibilidad y observabilidad.

### Decisión 5: Filosofía de staging — tipar y limpiar, no modelar

Al construir `stg_pedidos.sql` y `stg_precios.sql`, teníamos que decidir 
hasta dónde llegaba la responsabilidad de la capa de staging. La regla 
que adoptamos: **staging tipa y limpia formato; los modelos posteriores 
aplican lógica de negocio**.

**Lo que va en staging**:

- Renombrar columnas al estándar del proyecto (snake_case, sin caracteres 
  especiales).
- Casts de tipos: varchar a INTEGER, DECIMAL, DATE, BOOLEAN.
- Limpieza sintáctica de formatos: quitar `$` y separadores de miles de 
  precios, parsear fechas `dd/mm/yyyy`, convertir strings TRUE/FALSE a 
  booleans.
- Generación de surrogate keys (`pedido_id` como hash MD5).
- Trim de espacios sobrantes.

**Lo que NO va en staging**:

- Normalización de nombres de cliente (variantes ortográficas del mismo 
  cliente). Vive en `int_clientes_normalizados`.
- Mapping manual a nombres canónicos. Vive en `dim_cliente`.
- Clasificación de tipo de cliente (B2B/B2C). Vive en `dim_cliente`.
- Validación contra catálogos (SKUs válidos, segmentos permitidos). Vive 
  en tests de dbt y en modelos de marts.
- Agregaciones, métricas, cálculos derivados. Van en marts.

El principio detrás: **staging es una capa de traducción sintáctica**, no 
semántica. Cualquier consumidor de staging debería obtener data tipada 
correctamente pero sin asumir que ya se aplicaron reglas de negocio.

**Excepción documentada: `MP → MercadoPago`**. La columna `metodo_pago` 
en raw tiene dos valores: `Efectivo` y `MP` (abreviación de MercadoPago). 
El valor canónico del negocio es `MercadoPago`. Aplicamos la traducción 
en staging con un `case when`:

```sql
case
    when upper(trim(PAGO)) = 'MP' then 'MercadoPago'
    else trim(PAGO)
end as metodo_pago
```

**Por qué la excepción es aceptable**: es un solo mapping simple. Dejar 
`MP` en staging obligaría a todos los modelos posteriores a saber que 
"MP y MercadoPago son lo mismo", propagando complejidad. Traducirlo una 
vez en staging elimina esa carga.

**El límite conceptual**: si tuviéramos 20 mappings, ya no correspondería 
a staging. Requeriría un modelo intermedio dedicado con un seed CSV de 
normalización. Pero para 1 mapping trivial, staging es el lugar más 
económico.

### Decisión 6: Materializaciones — staging como view, marts como table

Configuramos en `dbt_project.yml` las materializaciones por defecto según 
capa:

```yaml
models:
  mym_waffles:
    staging:
      +materialized: view
    intermediate:
      +materialized: view
    marts:
      +materialized: table
```

**Staging como view**: los modelos de staging son transformaciones simples 
sobre raw (renombrar, tipar, limpiar). No vale la pena guardar la data 
resultante porque:
- Cambia cada vez que la ingesta actualiza raw.
- Es rápido de recomputar (una vista es una query almacenada, no data).
- Los cambios en raw se reflejan al instante al consultar la vista, sin 
  necesidad de re-materializar.

**Marts como table**: los modelos de marts son la capa consumida por 
dashboards (Metabase). Materializarlos como table evita recomputar joins 
y agregaciones en cada consulta. Un dashboard que se abre 20 veces al 
día no debería ejecutar los mismos joins pesados cada vez. Con table, la 
data está pre-calculada y guardada; las queries son lookups directos.

**Intermediate como view**: la capa intermedia (`int_clientes_normalizados`) 
sigue el mismo criterio que staging — lógica compartida que se recalcula 
rápido, no vale la pena persistir.

**Consideración futura: `incremental`**. Hoy `fact_pedidos` va a tener 221 
filas; rematerializar la tabla entera toma milisegundos. Si el warehouse 
crece (ej. 500.000 pedidos en algunos años), la materialización `table` 
podría volverse lenta. En ese caso migraríamos a `incremental`, que solo 
procesa las filas nuevas desde la última corrida. **Deuda declarada** 
para cuando el volumen lo justifique.

### Decisión 7: tests dbt como red de seguridad automatizada

Agregamos tests declarativos a los modelos de staging usando el sistema 
nativo de dbt. En total, 14 tests distribuidos en `stg_pedidos.yml` y 
`stg_precios.yml`.

**Tests declarativos vs imperativos**: dbt permite declarar los tests en 
YAML, no como código SQL a mano. Por ejemplo:

```yaml
- name: pedido_id
  tests:
    - unique
    - not_null
```

La alternativa imperativa sería escribir queries SQL manuales para cada 
verificación (`SELECT COUNT(*) FROM ... GROUP BY ... HAVING ...`), 
específicas a cada tabla y mantenidas a mano. Los tests declarativos son 
más concisos, reutilizables, y se ven automáticamente en la documentación 
de dbt.

**Tipos de test que usamos**:

- `unique`: para surrogate keys que no pueden repetirse (`pedido_id`, 
  `tarifa_id`).
- `not_null`: para columnas críticas donde vacío significa data corrupta 
  (`cliente_raw`, `cantidad_total`, `fecha_emision`).
- `accepted_values`: para columnas con dominio cerrado de valores 
  válidos (`metodo_pago` acepta solo `Efectivo` o `MercadoPago`; 
  `segmento` acepta solo `MINORISTA`, `PROMO`, `MAYORISTA`, `PROTEICO`).

**Detección temprana**: el valor de los tests se ve cuando algo falla. 
Ejemplo real: el test `accepted_values` en `metodo_pago` reveló que la 
columna traía `MP` en 153 filas (además de `Efectivo`), un valor que no 
estaba en la lista de aceptados. Sin ese test, `MP` habría viajado a 
través de todo el pipeline sin que nadie se entere, y el problema se 
habría descubierto recién al ver el dashboard con tres métodos de pago 
distintos (`Efectivo`, `MP`, `MercadoPago`) en vez de dos. Corregir en 
staging es fácil; corregir con métricas ya publicadas y auditadas es 
mucho más caro.

Los tests corren con `dbt test` y se pueden encadenar en el pipeline 
(`dbt run && dbt test`). En un pipeline productivo, si los tests fallan, 
el flujo se detiene antes de que la data corrupta llegue a la capa 
consumida por dashboards.


## Consecuencias

## Consecuencias

### Ganancias

- **Detección temprana de bugs**: los tests declarativos revelaron valores 
  inesperados antes de que llegaran a la capa de análisis. Ejemplo real: 
  el test `accepted_values` en `metodo_pago` detectó que la columna traía 
  `MP` en 153 filas, un valor no anticipado que hubiera aparecido recién 
  en el dashboard con métricas ya publicadas.
- **Refactor sin miedo**: modificar `pedidos.py` (fix del espacio en 
  `EMISIÓN`) requirió solo re-correr `dbt run && dbt test` para 
  verificar que nada se rompió aguas abajo. Sin dbt, habría requerido 
  ejecutar y validar cada transformación manualmente.
- **Ambiente reproducible desde cero**: al migrar a una PC nueva, 
  `dbt seed && dbt run && dbt test` reconstruyó el warehouse completo. 
  Sin dbt, habría requerido ejecutar cada script en el orden correcto y 
  validar manualmente cada resultado intermedio.
- **Modularidad**: agregar dimensiones nuevas (`dim_producto`, 
  `dim_fecha`, `dim_cliente`) se hizo con modelos independientes que dbt 
  encadenó automáticamente vía `ref()`. Nunca tuvimos que reordenar 
  dependencias a mano.

### Costos

- **Curva de aprendizaje**: dbt agrega vocabulario nuevo (sintaxis Jinja, 
  YAML declarativo, convenciones staging/intermediate/marts, comandos 
  CLI). La primera semana con dbt es intensa. Es un costo que cualquier 
  persona nueva al proyecto va a pagar también.
- **Complejidad de setup**: dbt requiere configuración adicional 
  (`dbt_project.yml`, `profiles.yml`, macros custom, variables de entorno 
  como `DBT_PROFILES_DIR`). Cada uno de esos artefactos es un lugar más 
  donde algo puede fallar.
- **Debug menos directo**: cuando algo falla en dbt (por ejemplo, el 
  prefijo `main_` que apareció al principio, o el error de `profiles.yml` 
  no encontrado), la traza de error no siempre apunta a la causa raíz. 
  Requiere conocer las convenciones internas.

### Deuda declarada

- **Migrar a `incremental` cuando el volumen justifique**: hoy 
  `fact_pedidos` tiene 221 filas y `table` funciona bien. Si el 
  warehouse crece (ej. 500.000+ pedidos), rematerializar la tabla 
  completa en cada corrida se volvería lento. En ese caso, migrar a 
  `incremental` para procesar solo las filas nuevas.
- **Refactorizar `MP → MercadoPago` si aparecen más mappings**: hoy es 
  una excepción justificada de 1 mapping en staging. Si empiezan a 
  aparecer más normalizaciones similares (ej. 5+ métodos de pago con 
  variantes), habría que mover la lógica a un modelo intermedio con seed 
  CSV dedicado.
- **Reconstruir el histórico de precios**: `dim_tarifa` (semana 6) va a 
  requerir SCD Type 2 para preservar la historia de aumentos. Hay que 
  poblar manualmente el CSV histórico antes de arrancar semana 6, ya que 
  los snapshots de dbt solo capturan cambios a partir del momento en que 
  empiezan a correr.