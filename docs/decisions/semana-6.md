# ADR Semana 6: Facts, dim_tarifa SCD Type 2, y matching de tarifas

## Contexto

Al terminar semana 5, teníamos las 3 dimensiones descriptivas del modelo 
(`dim_producto`, `dim_fecha`, `dim_cliente`) pero ningún fact. El 
warehouse tenía data limpia y catálogos canónicos, pero no podía 
responder preguntas centrales del negocio: cuánto se vendió, a quién, 
cuándo, y a qué precio.

Semana 6 completa el modelo dimensional agregando:
1. `dim_tarifa` con SCD Type 2 para preservar historia de precios.
2. `fact_pedidos` como cabecera de pedidos con FKs a dimensiones.
3. `fact_pedido_items` como detalle por (pedido × masa × sabor) parseando 
   el string PEDIDO con el parser Python de semana 3.
4. Definición del algoritmo de matching pedido-tarifa.

## Decisiones

### Decisión 1: `dim_tarifa` desde CSV histórico manual, no snapshots dbt

Para implementar SCD Type 2 en dbt había dos opciones:

- **Snapshots dbt**: feature nativa que monitorea una tabla source y 
  captura cambios automáticamente creando filas históricas.
- **Modelo tradicional desde CSV histórico**: leer un CSV pregenerado 
  con toda la historia y materializarlo como tabla.

Elegimos la segunda opción por una razón fundamental: **los snapshots 
solo capturan cambios desde el momento en que empiezan a correr**. No 
pueden reconstruir historia previa. En este proyecto necesitábamos la 
historia completa del año (3 versiones de precios por tarifa: enero-marzo, 
abril-junio, julio-vigente) para poder reconciliar pedidos históricos 
contra la tarifa vigente en el momento del pedido.

El CSV `precios_historicos.csv` fue armado manualmente con Claude Code 
tomando como input las planillas de precios de cada aumento. Contiene 
78 filas (26 tarifas × 3 versiones). Está gitignored por contener 
costos comerciales sensibles; se commiteó un `.example.csv` con estructura 
anonimizada.

**Deuda declarada**: cuando aumenten precios en el futuro, hay que 
agregar filas manualmente al CSV con el nuevo período de vigencia. 
Alternativa a mediano plazo: automatizar la captura vía snapshots una 
vez que ya tengamos la historia base cargada.

### Decisión 2: modelo Python de dbt para `fact_pedido_items`

El string PEDIDO ("192 Neutros Clásicos + 96 Neutros Integrales") 
requiere el parser Python de `ingestion/parsers.py`. Traducir esa 
lógica a SQL sería complejo, frágil, y perdería los tests unitarios 
existentes.

dbt soporta modelos escritos en Python (archivos `.py`). El adapter 
`dbt-duckdb` los ejecuta en un proceso separado y materializa el 
DataFrame devuelto. Aprovechamos esta feature para mantener toda la 
lógica de transformación dentro del pipeline dbt.

El modelo `fact_pedido_items.py`:
1. Lee `stg_pedidos` como Polars DataFrame.
2. Aplica `parse_pedido_string()` por cada fila.
3. Explota los items (una fila por masa × sabor dentro del pedido).
4. Normaliza mapping plural → singular (`Clásicos` → `Clásica`) para 
   matchear con `dim_producto`.
5. Joinea con `dim_producto` para obtener `producto_id`.

**Bug encontrado y documentado**: dbt-duckdb ejecuta el modelo Python 
desde `/tmp/`, no desde el directorio del proyecto. Los imports 
relativos (`from ingestion.parsers import ...`) fallan. Solución: agregar 
`PYTHONPATH=/workspace` como variable de entorno en `docker-compose.yml`. 
Ver commit `chore(docker): add PYTHONPATH to environment`.

**Bug adicional**: la data cruda del sheet tiene "clasicos" en minúscula 
y a veces sin tilde. Se agregó `.capitalize()` antes del mapping y 
variantes sin tilde al diccionario MASA_MAP.

### Decisión 3: sin `bridge_pedido_tarifa` — matching 1:1 por item

Inicialmente se consideró implementar una tabla puente 
`bridge_pedido_tarifa` para resolver una relación muchos-a-muchos entre 
pedidos y tarifas. Esta decisión se revirtió al aclarar las reglas 
reales del negocio.

**Regla de matching real** (definida con el dueño del negocio):

Para cada item del pedido (masa, sabor, cantidad):
1. Buscar en `dim_tarifa` la fila donde: producto matchea, unidades_pack 
   iguala la cantidad, y la vigencia contiene la fecha del pedido.
2. Si matchea exacto → esa tarifa.
3. Si no matchea → tomar el pack inmediatamente inferior con el mismo 
   producto y vigencia. Precio del item = `precio_unitario × cantidad_real`.
4. Si la cantidad supera el pack mayor (96), usar `precio_unitario_pack_96 × cantidad`.

**El cliente no importa para el pricing** (B2C y B2B pagan lo mismo). 
El segmento (MINORISTA/MAYORISTA/PROMO) queda determinado por qué tarifa 
matchea, no por reglas separadas por tipo de cliente.

**PROMO se aplica solo cuando el string PEDIDO lo indica explícitamente**. 
No se deduce automáticamente por múltiples sabores.

**Conclusión**: cada item se resuelve independientemente contra una única 
tarifa. La relación item-tarifa es 1:1, no muchos-a-muchos. Sin N:M, no 
hay necesidad de bridge — basta con una FK directa `tarifa_id` en 
`fact_pedido_items`.

**Deuda declarada**: la implementación del matching en sí (agregar la 
columna `tarifa_id` calculada a `fact_pedido_items`) queda pendiente y 
se resuelve en semana 7. Requiere lógica de matching contra `dim_tarifa` 
que respete la vigencia por fecha.

### Decisión 4: FKs de cliente y fecha en `fact_pedidos`, no en `fact_pedido_items`

`fact_pedidos` (cabecera) tiene FKs a `dim_cliente`, `dim_fecha` (emisión 
y entrega). `fact_pedido_items` (detalle) tiene FK solo a `dim_producto` 
y a `fact_pedidos` (vía `pedido_id`).

**Razón**: los items heredan cliente y fecha del pedido padre. Duplicar 
esas FKs en cada item sería redundante y agregaría carga de mantenimiento 
sin beneficio analítico claro (siempre se puede joinear con `fact_pedidos` 
si es necesario).

**Deuda menor**: si los queries analíticos requieren muchos joins 
frecuentes entre `fact_pedido_items` y `fact_pedidos` solo para obtener 
cliente/fecha, evaluar denormalizar esas FKs en el fact de items para 
mejorar performance.

### Decisión 5: bug de join explosivo por falta de DISTINCT

Al construir `fact_pedidos`, el JOIN inicial multiplicó las filas: 
esperábamos 222 pedidos y obtuvimos 939. La causa: el CTE 
`clientes_normalizados` no tenía `DISTINCT`, así que cada `cliente_raw` 
aparecía tantas veces como pedidos hizo ese cliente. Al joinear con el 
mapping y `dim_cliente`, cada fila se multiplicaba por el número de 
apariciones del cliente.

**Fix**: `SELECT DISTINCT cliente_raw, nombre_normalizado` en el CTE de 
normalización. El total volvió a 222 (223 con un pedido nuevo del día).

**Aprendizaje**: cuando un fact tiene muchas más filas de las esperadas, 
casi siempre es un JOIN mal diseñado. Verificar los cardinalidades de 
las tablas intermedias antes de joinear.

### Decisión 6: Veganos como cuarentena implícita, no filtrado

Había un pedido histórico con masa "Veganos", una masa discontinuada 
(un solo pedido en todo el año). Al buscar en `dim_producto`, no matchea, 
y `producto_id` queda NULL. Como el `pedido_item_id` se calcula como 
hash de otros campos incluyendo `producto_id`, ese hash también queda NULL.

Esto causa que el test `not_null_fact_pedido_items_pedido_item_id` falle 
con 1 fila.

**Opciones consideradas**:
- Filtrar los items sin `producto_id` del modelo (perdemos data honesta).
- Cambiar el test a `not_null where producto_id is not null` (test más laxo 
  pero explícito).
- Dejar el test fallando y documentar la excepción.

Elegimos la tercera. **El test rojo es información**: cada vez que 
alguien corre `dbt test`, el warehouse dice "hay 1 caso conocido de 
producto descatalogado". Es una nota permanente sobre la historia del 
negocio (existió un producto vegano, ya no se vende) que aparece cada 
vez que se ejecuta el pipeline.

Filtrar ocultaría la información. Cambiar el test lo debilitaría. Dejar 
el fail documentado mantiene la señal viva.

## Consecuencias

### Ganancias

- **Modelo dimensional funcional end-to-end**: 4 dimensiones + 2 facts. 
  El warehouse puede responder preguntas complejas via joins simples.
- **SCD Type 2 andando**: cada tarifa tiene 3 versiones históricas 
  cada una con su propio `tarifa_id`. Un pedido de mayo matchea con la 
  tarifa vigente en mayo, uno de julio con la vigente en julio.
- **240 items parseados desde 223 pedidos**: la descomposición 
  automática de pedidos multi-item habilita análisis por masa/sabor.
- **Integridad referencial validada**: tests `relationships` de dbt 
  confirman que todos los FKs son consistentes.
- **Modelo Python de dbt funcionando**: aprendizaje transferible a 
  cualquier proyecto donde se necesite lógica Python dentro de un 
  pipeline dbt.

### Costos

- **Complejidad de setup del modelo Python**: dbt-duckdb ejecuta el 
  modelo Python en un contexto separado (`/tmp/`) sin acceso al 
  PYTHONPATH del container por defecto. Requirió configuración adicional 
  en `docker-compose.yml` y debugging que no era obvio del mensaje de 
  error inicial.
- **Mantenimiento manual de `precios_historicos.csv`**: cada nuevo 
  aumento de precios requiere edición manual del CSV con las nuevas 
  fechas de vigencia. Fácil de olvidar; posible fuente de bugs futuros.
- **Datos históricos frágiles**: si alguien cambia un `producto_desc` 
  o `segmento` en el sheet de precios (cambia el naming), los 
  `tarifa_id` (hashes) de nuevas versiones no van a matchear con las 
  filas históricas del CSV. Se rompe la trazabilidad SCD Type 2.

### Deuda declarada

- **Implementar el matching de tarifas en `fact_pedido_items`**: agregar 
  columna `tarifa_id` calculada según las reglas definidas en la 
  Decisión 3. Es la parte más importante que queda pendiente para 
  poder calcular `precio_unitario_aplicado` y hacer reconciliación con 
  `precio_total_ars` del pedido.
- **ADR de semana 6** (este documento).
- **Cuando aumenten precios**, agregar filas manuales a 
  `precios_historicos.csv`.
- **Migrar a `incremental`** cuando `fact_pedidos` crezca (500k+ filas). 
  Hoy `table` funciona bien con 223 filas.
- **Revaluar mapping MASA_MAP** en `fact_pedido_items.py` cuando se haga 
  el backfill 2024-2025 (semana 11): puede haber variantes ortográficas 
  históricas no cubiertas.
- **Test rojo conocido**: `not_null_fact_pedido_items_pedido_item_id` 
  falla por el pedido histórico de "Veganos". Documentado en Decisión 6.
- **Considerar denormalización de cliente_id/fecha_id en 
  `fact_pedido_items`** si los queries analíticos lo justifican 
  (Decisión 4).