# ADR Semana 13: El pipeline publica para el panel operativo

## Contexto

Hasta acá el pipeline tenía un solo consumidor: Metabase, en la misma notebook
donde corre. El negocio, en cambio, se maneja desde otro lado: un panel web
mobile-first (repo `SabaM10/waffles`, publicado en Vercel) donde se cargan
pedidos, se descuenta stock y se decide qué producir. Ese panel lee y escribe
Google Sheets a través de Apps Script.

Las dos preguntas que el pipeline sabe contestar ("¿quién tendría que haber
pedido y no pidió?" y "¿cuánto se va a vender la semana que viene?") son
justamente las que el panel no podía contestar. Faltaba el puente.

El supuesto inicial era que llevar el pipeline al panel exigía hostearlo o
exponer una API, algo desproporcionado para un dato que cambia una vez por
semana. No hace falta: las dos puntas ya hablan Google Sheets.

## Decisiones

### Decisión 1: Una planilla nueva, no pestañas en VENTAS 2026

La primera idea fue escribir los resultados en pestañas nuevas de VENTAS 2026.
Eso obligaba a darle al service account permiso de Editor sobre la planilla
transaccional, la fuente única de verdad de los pedidos. Un error en el asset
que publica (un `clear()` sobre la pestaña equivocada) borraría ventas reales.

Se eligió una planilla aparte, "MyM Pipeline". El service account es Editor sólo
de esa y conserva lectura sobre VENTAS 2026. El principio es el de mínimo
privilegio: el componente que escribe sólo puede escribir donde le corresponde.
Como beneficio lateral, el Apps Script de pedidos (publicado, con lógica de
stock y concurrencia) no se toca: el lector es un script aparte, de sólo lectura,
con su propia URL.

El costo es una planilla y una URL más que administrar. Se acepta.

### Decisión 2: Forecast por SKU, con su propio backtest por SKU

El forecast de semana 9 es un número total. Para el panel no alcanza: la
decisión operativa es qué masa y qué sabor producir, y la mezcla es muy
despareja (clásica dulce domina).

`mart_forecast_semanal_sku` aplica el mismo SMA-4 a cada una de las 8
combinaciones del catálogo. Dos detalles importan. Primero, todas las series
comparten la grilla de semanas del total y se rellenan con ceros: un SKU que se
vende poco se pronostica con sus semanas en cero, no sólo con las semanas en
que vendió. Segundo, la mejora del 34% de MAE sobre naive se midió sobre el
total y no se traslada sola a series más ralas. Cada SKU tiene su propio
backtest walk-forward y se publican el MAE de SMA-4 y el de naive lado a lado,
para que se vea dónde el modelo le gana al baseline y dónde no.

Como SMA es lineal, la suma de las predicciones centrales por SKU es igual al
forecast total. Las bandas no son aditivas y no se suman.

Las bandas se recortan en cero. La banda superior, redondeada hacia arriba, es
lo que el panel usa como "producir para estar tranquilos".

### Decisión 3: El estado de cada cliente se calcula en dbt, no en el panel

`rpt_panel_clientes_semana` junta la regla de semana 10, la probabilidad y lo
que suele pedir cada cliente, y le asigna un `estado_semana`: `atrasado` si la
regla ya disparó, `le_toca` si la fecha esperada del próximo pedido (último
pedido más el intervalo promedio) cae en esta semana, `al_dia` si no. La lógica
queda testeada y versionada acá; el panel sólo la muestra.

### Decisión 4: El contrato está versionado y es texto

`ingestion/panel.py` fija los nombres de columna y `CONTRATO_VERSION`. Las
fechas viajan como texto ISO y se escriben con `value_input_option="RAW"`, para
que Sheets no las reinterprete según el locale. El panel valida la versión y,
si no la conoce, muestra un aviso en vez de datos mal leídos.

## Consecuencias

### Ganancias

El panel muestra, en una vista propia, a qué clientes llamar esta semana y
cuánto producir de cada SKU, sin hosting nuevo y sin tocar el script de pedidos.

### Costos

El dato tiene la frescura de la última corrida del pipeline, que sigue siendo
manual. El panel muestra la fecha de generación para que eso se vea.

### Deuda declarada

El corte de semana es el de semana 9: la semana en curso entra como cerrada. Si
el pipeline se corre un lunes, la última semana tiene un día de datos y el SMA-4
tira para abajo. Mientras la corrida sea manual, conviene correrlo de viernes a
domingo. Se reevalúa cuando el schedule se active.

## Referencias

- `dbt_project/models/marts/mart_forecast_semanal_sku.py`
- `dbt_project/models/marts/rpt_panel_clientes_semana.sql`
- `ingestion/panel.py`
- `serving/apps_script/lector_panel.gs`
- Panel: `SabaM10/waffles`, `src/semana.js`
