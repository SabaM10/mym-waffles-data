# ADR Semana 14: Sólo semanas cerradas, y siempre se predice la semana que viene

## Contexto

El forecast se publica al panel del negocio (ADR semana 13), y el dueño lo corre a
mano desde su notebook cuando puede. Hasta acá, la semana en curso entraba a la
serie como si estuviera cerrada. Corrido un miércoles, esa semana tenía tres días de
ventas, el SMA-4 la promediaba como si fuera entera y el pronóstico salía bajo. La
consigna operativa era "correlo de viernes a domingo", y el ADR de semana 13 lo dejó
anotado como deuda.

Revisando el código para resolverlo apareció algo más: el ADR de semana 9 (decisión
6) ya decía que en producción la semana en curso se filtra
(`fecha_emision < DATE_TRUNC('week', CURRENT_DATE)`). El código filtraba con
`< lunes de la semana próxima`, o sea que la incluía. La decisión estaba tomada; el
código no la cumplía.

## Decisiones

### Decisión 1: La semana en curso no entra nunca

`corte_semanas_cerradas(hoy)` devuelve el lunes de la semana en curso, y es el límite
exclusivo de las tres series (backtest, total y por SKU). Con un día de datos o con
cinco, la semana en curso es igual de incompleta. Así el resultado es el mismo se
corra el día que se corra, que es lo que el dueño necesita para no pensar en eso.

### Decisión 2: Se predice siempre la semana que viene, a dos pasos

Lo que el panel muestra es "la semana que viene": la primera que todavía no empezó
(`semana_a_predecir`). Entre la última semana cerrada y esa está la semana en curso,
así que el salto es siempre de dos semanas (`HORIZONTE_SEMANAS = 2`).

**Alternativa descartada**: predecir la semana en curso (un paso). Corrido un
viernes, el panel diría cuánto producir para una semana que está terminando.

### Decisión 3: El backtest se mide al mismo horizonte

`walk_forward_backtest` suma un parámetro `horizonte`: con 2, la historia de cada
predicción termina dos semanas antes de la semana evaluada. Es lo que pasa en
producción, y es lo que hace honesta la banda: los errores a dos semanas son algo
más grandes que a una, y una banda medida a un paso prometería un "19 de cada 20"
que no se cumple. El MAE de SMA-4 contra naive, por SKU, también se mide a dos pasos.

La mejora del 34% sobre naive (semana 9) se midió a un paso. Hay que volver a medirla
a dos con los datos reales: con un SMA la ventaja tendría que mantenerse o crecer
(naive a dos pasos repite un valor más viejo), pero eso se verifica, no se supone.

### Decisión 4: Las semanas sin ventas al final de la serie son ceros

Antes la grilla de semanas terminaba en la última semana con pedidos. Una semana
cerrada sin ventas justo antes del corte quedaba afuera, y el SMA-4 promediaba
cuatro semanas que no eran las últimas cuatro. Ahora la grilla termina en la última
semana cerrada, tenga o no ventas: es la decisión 7 de semana 9 (gaps = cero)
aplicada también al final.

## Consecuencias

El pipeline se puede correr cualquier día. En los datos sintéticos de prueba, corrido
un jueves, el central pasó de 182 a 217 unidades: la diferencia era la semana a
medias. El modelo pasa a llamarse `sma_4_v8_h2` en los marts.

Costo: los pedidos de la semana en curso no informan el pronóstico. Para un SMA-4
sobre semanas eso es correcto (una semana a medias es un dato falso, no un dato
parcial), y los pedidos ya cargados se ven en el panel por otro lado: entran en
"Libres" como demanda pendiente.

## Referencias

- `ingestion/forecast.py`: `corte_semanas_cerradas`, `semana_a_predecir`,
  `serie_semanal_total`, `walk_forward_backtest(horizonte=...)`.
- `dbt_project/models/marts/mart_forecast_backtest.py`, `mart_forecast_semanal.py`,
  `mart_forecast_semanal_sku.py`.
- ADR semana 9, decisiones 6 y 7. ADR semana 13, deuda declarada.
