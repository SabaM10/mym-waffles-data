# Modelo de datos

Modelo dimensional del warehouse: grain de cada tabla, cómo se puebla, y qué
casos conocidos quedan fuera. El razonamiento del stack está en `arquitectura.md`;
la lógica de precios en `pricing.md`.

---

## 1. Por qué modelo dimensional

Al terminar la capa de staging, la data estaba tipada y limpia, pero armar
dashboards directamente desde ahí no era viable por tres problemas:

1. **Entidades fragmentadas.** `cliente_raw` tenía variantes ortográficas del
   mismo cliente tratadas como clientes distintos. Un análisis de ventas por
   cliente lo mostraba cuatro veces con totales partidos.
2. **Sin atributos derivados.** `fecha_emision` es un DATE. Preguntas como "¿qué
   mes vende más?" requieren atributos calculados que el dato crudo no trae.
3. **Sin catálogos oficiales.** Lo que aparece en los pedidos refleja lo vendido,
   no el catálogo completo de productos.

El star schema de Kimball resuelve los tres de forma natural: entidades canónicas
en tablas `dim_*`, eventos en tablas `fact_*`, unidos por claves foráneas.

**Alternativas descartadas**: Inmon (3NF) es adecuado para organizaciones grandes
con equipos dedicados; overkill acá. Data Vault apunta a auditabilidad extrema con
~10x más tablas; su complejidad no se justifica para este volumen. Kimball es
además el modelo que Metabase está diseñado para consumir.

---

## 2. Convención de nombres

| Prefijo | Capa | Qué es |
|---|---|---|
| `stg_` | staging | Tipado y limpieza, 1:1 contra la fuente |
| `int_` | intermediate | Lógica intermedia, no se consume directo |
| `dim_` | marts | Dimensión: entidad canónica descriptiva |
| `fact_` | marts | Hecho: evento del negocio |
| `rpt_` | marts | Reporte derivado de reglas de negocio (SQL) |
| `mart_` | marts | Modelo con lógica estadística (Python) |

La distinción `rpt_` / `mart_` importa al leer el repo: `rpt_` es determinístico y
auditable leyendo el SQL; `mart_` involucra un modelo estadístico cuyo resultado
depende de parámetros.

---

## 3. Dimensiones

### `dim_producto` — grain: un SKU válido

Poblada desde el seed `productos_catalogo.csv` con las 8 combinaciones válidas de
masa × sabor. El modelo agrega surrogate key (`producto_id` como MD5), nombre de
display y metadata.

**Por qué seed y no `VALUES` en el SQL**: el catálogo es conocimiento de negocio
que cambia sin que cambie la lógica. Agregar un producto es agregar una fila a un
CSV —editable por alguien que no sabe SQL— y el diff en git es legible. Además el
mismo seed alimenta la dimensión y sirve de referencia para los tests
`relationships`, evitando duplicar el listado en dos lugares.

### `dim_fecha` — grain: un día

Generada con `generate_series` entre 2024-01-01 y 2027-12-31 (1.461 filas), con
atributos derivados calculados en SQL: `nombre_mes` y `nombre_dia` en español,
`es_finde_semana`, `trimestre`.

**Por qué autogenerada y no seed**: el calendario es mecánico, no requiere criterio
humano. Extender el rango es cambiar una fecha en el SQL. Y los cálculos —días de
semana, años bisiestos— los hace el motor, sin riesgo de error humano.

**El contraste con `dim_producto` es la regla general**: los seeds sirven cuando la
data requiere decisiones humanas; los modelos autogenerados cuando es derivable por
reglas universales. "Oreo integral no existe" es una regla de negocio; "el 3 de
marzo de 2026 fue martes" no lo es.

### `dim_cliente` — grain: un cliente canónico

La dimensión con más lógica del modelo. Los nombres en crudo traían variaciones
ortográficas, acentos inconsistentes, nombres ambiguos y nombres de persona que
ocultan un negocio. Se resuelve en tres capas:

**Capa 1 — normalización automática** (`int_clientes_normalizados`). Reglas
mecánicas en SQL: `lower`, `trim`, quitar acentos, colapsar espacios múltiples.
Resuelve todo lo puramente ortográfico.

**Capa 2 — mapping manual** (`client_name_mapping.csv`). Seed con estructura
`nombre_normalizado → cliente_canonico + tipo_cliente + es_ambiguo`, poblado con
conocimiento del negocio. La capa 1 reduce drásticamente su tamaño: sin ella
habría una fila por cada variante ortográfica de cada cliente.

**Capa 3 — cuarentena** (`necesita_mapping`). Cuando un nombre normalizado no
matchea con el mapping, la fila queda marcada como `true` y con canónico
`"Desconocido: <nombre>"`. Es la red que hace visible a un cliente nuevo en vez de
dejarlo pasar inadvertido.

Cada capa resuelve un problema distinto: la 1 automatiza lo automatizable, la 2
captura el criterio humano, la 3 garantiza que nada quede oculto.

> **Nota de privacidad**: `client_name_mapping.csv` contiene nombres reales de
> clientes y está gitignored. El repo incluye `client_name_mapping.example.csv`
> con estructura idéntica y datos anonimizados, suficiente para correr el
> pipeline completo. El transporte del CSV real entre máquinas se hace por canal
> privado cifrado.

### `dim_tarifa` — grain: una tarifa por período de vigencia (SCD Type 2)

Preserva la historia de precios: cada tarifa tiene una fila por período de
vigencia, con `valid_from` / `valid_to` y su propio `tarifa_id`. Un pedido de mayo
matchea contra la tarifa vigente en mayo.

**Por qué desde CSV histórico y no con snapshots de dbt**: los snapshots solo
capturan cambios **desde que empiezan a correr**. No pueden reconstruir historia
previa, y acá hacía falta el año completo para reconciliar pedidos históricos. El
detalle está en `pricing.md`.

---

## 4. Hechos

### `fact_pedidos` — grain: un pedido

Cabecera, con FKs a `dim_cliente` y a `dim_fecha` (emisión y entrega), y el total
del sheet para reconciliación.

**Bug de referencia**: el JOIN inicial devolvía 939 filas para 222 pedidos. Causa:
el CTE de normalización de clientes no tenía `DISTINCT`, así que cada
`cliente_raw` aparecía tantas veces como pedidos había hecho ese cliente y cada
fila se multiplicaba. Cuando un fact tiene muchas más filas de las esperadas,
casi siempre es un JOIN con cardinalidad mal entendida.

### `fact_pedido_items` — grain: pedido × masa × sabor

Detalle, obtenido parseando el campo de texto libre del pedido
(`"192 Neutros Clásicos + 96 Neutros Integrales"`) y explotándolo en una fila por
item. Tiene FK a `dim_producto`, FK a `fact_pedidos` vía `pedido_id`, y la
`tarifa_id` resuelta por el matching.

**Es un modelo Python de dbt**, no SQL. El parser vive en `ingestion/parsers.py`
con su suite de tests unitarios; traducir esa lógica a SQL sería frágil y perdería
los tests. `dbt-duckdb` ejecuta el `.py` y materializa el DataFrame devuelto.

**Por qué las FKs de cliente y fecha viven solo en la cabecera**: los items las
heredan del pedido padre. Duplicarlas sería redundante sin beneficio analítico
claro. Si los joins frecuentes llegan a doler, se evalúa denormalizar.

---

## 5. Marts

| Modelo | Grain | Qué responde |
|---|---|---|
| `rpt_ventas_semanales` | semana | Total vendido, split B2B/B2C, tendencia |
| `rpt_reconciliacion_pedidos` | pedido | ¿El precio del sheet coincide con el calculado? |
| `mart_forecast_semanal` | semana futura | Proyección + banda de confianza empírica |
| `mart_forecast_backtest` | predicción histórica | Accuracy del modelo, validada walk-forward |
| `int_b2b_cadencia` | cliente B2B | Intervalo promedio entre pedidos, desvío, días desde el último |
| `rpt_alertas_reorder_b2b` | cliente B2B | Alerta por regla: ¿está atrasado? |
| `mart_b2b_reorder_probabilistico` | cliente B2B | Probabilidad de que el reorder ya haya vencido |

### Detección de reorder: dos capas complementarias

Es el caso de uso principal del negocio y está resuelto con dos modelos que **no
compiten entre sí**.

La **capa por reglas** (`rpt_alertas_reorder_b2b`) marca alerta cuando los días
desde el último pedido superan el intervalo promedio más un desvío estándar. Usa
`ratio_atraso` como métrica de severidad. Es transparente y explicable en una
frase.

La **capa probabilística** (`mart_b2b_reorder_probabilistico`) modela la cadencia
histórica de cada cliente con una CDF normal y devuelve `probabilidad_reorder_ya`.
El umbral es configurable vía la variable dbt `umbral_alerta_desvios_b2b`, y cada
fila trae `confianza_estimacion` (BAJA/MEDIA/ALTA) según cuántos pedidos históricos
sustentan la estimación.

La validación cruzada es fuerte: los clientes que las reglas marcan también
puntúan alto en probabilidad. **El valor está en las divergencias** — ahí es donde
la capa probabilística aporta información que la regla no ve.

**Mínimo de 4 pedidos** para entrar al modelo probabilístico. Es un trade-off
entre cobertura y confiabilidad estadística, y `confianza_estimacion` lo hace
visible en lugar de esconderlo.

### Forecast

Modelo SMA-4 sobre la serie semanal, elegido por backtesting con walk-forward
validation y sliding window de 8 semanas. Le gana a naive por 34% de MAE — margen
sustancial, que es el criterio explícito adoptado para justificar cualquier
complejidad sobre el baseline.

La banda de confianza es **empírica** (percentiles de los errores reales del
backtesting), no paramétrica. La distribución de errores resultó marcadamente
asimétrica, cosa que una banda simétrica basada en supuesto de normalidad hubiera
ocultado.

**Contexto que condiciona todo el modelo**: la serie tiene un cambio de régimen
estructural confirmado a fines de marzo de 2026 (pérdida de clientes B2B más caída
de consumo B2C). Cualquier modelo entrenado sobre la serie completa sin considerar
el quiebre sobrepredice sistemáticamente. La sliding window fija fuerza al modelo
a olvidar el régimen viejo; una expanding window habría promediado ambos.

---

## 6. Casos conocidos fuera del modelo

Documentados a propósito. Aparecen en los dashboards y hay que saber leerlos.

| Caso | Tratamiento | Por qué |
|---|---|---|
| Masa discontinuada (1 item histórico) | Test `not_null` en rojo permanente | El test rojo es la señal. Filtrar ocultaría el caso. |
| Masa proteica (fuera del scope de pricing) | `tarifa_id` y precios en null | Asignarle tarifa de otra masa sería mentir. Con 11 items, dejarlos en rojo diluiría la señal del caso anterior. |
| Pedidos históricos consolidados de dos sucursales | Aceptados como no corregibles | 6 de 224 casos, patrón discontinuado. Corregirlos exigiría reescribir historia del warehouse. Se excluyen del análisis B2B de forma consistente. |
| Pedidos mayores al pack máximo modelado | No reconciliables | El matcher extrapola el precio unitario del pack mayor, que no refleja el precio negociado real. |

El criterio común: **exponer antes que ocultar**. Cada uno de estos casos es
visible en el dashboard de reconciliación en lugar de estar filtrado.

---

## Referencias

- Stack y capas: `arquitectura.md`
- Precios, SCD Type 2 y reconciliación: `pricing.md`
- Decisiones semana a semana: `docs/decisions/`
