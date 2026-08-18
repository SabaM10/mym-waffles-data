# ADR Semana 5: Dimensiones del modelo

## Contexto

## Contexto

Al terminar semana 4, teníamos `stg_pedidos` y `stg_precios` con data 
tipada y limpia sintácticamente. Pero armar dashboards directamente 
desde staging no era viable por tres problemas concretos:

**1. Fragmentación de entidades**. La columna `cliente_raw` de 
`stg_pedidos` tenía múltiples variantes del mismo cliente (`"Ale"`, 
`"ale"`, `"Ale "`, `"ALE"`) tratadas como clientes distintos. Un 
análisis de ventas por cliente mostraría a "Ale" cuatro veces con 
totales fragmentados, en vez de una sola vez con el total real.

**2. Falta de atributos derivados**. `stg_pedidos.fecha_emision` es un 
DATE, pero preguntas como "¿qué mes vende más?" o "¿cuánto vendo en 
fines de semana vs días de semana?" requieren atributos calculados 
(`nombre_mes` en español, `es_finde_semana`, `trimestre`) que no vienen 
con el dato crudo.

**3. Ausencia de catálogos oficiales**. Para responder "¿qué 
combinaciones válidas de masa y sabor existen?" no alcanza con lo que 
aparece en `stg_pedidos` (solo refleja lo vendido, no el catálogo 
completo). Necesitamos una fuente de verdad separada del histórico de 
transacciones.

Adoptamos el modelo dimensional (Kimball star schema) porque resuelve 
los tres problemas de forma natural: entidades canónicas viven en 
tablas `dim_*` (una fila por cliente único, por producto único, por 
fecha con sus atributos), y los hechos referencian a las dimensiones 
vía claves foráneas.

## Decisiones

### Decisión 1: modelo dimensional Kimball (star schema)

Elegimos el enfoque Kimball (star schema) sobre alternativas como Inmon 
(3NF normalizado) o Data Vault por su simplicidad y adecuación al 
proyecto.

**Alternativas consideradas**:

- **Inmon (3NF)**: warehouse normalizado como base de datos relacional 
  clásica. Muy adecuado para empresas grandes con equipos dedicados y 
  necesidad de integridad extrema. Overkill para un proyecto chico 
  mantenido por una persona.

- **Data Vault**: enfoque con hubs, links, satellites, diseñado para 
  auditabilidad total y flexibilidad extrema ante cambios. Usado en 
  farmacéuticas, bancos, empresas con regulación fuerte. Su complejidad 
  (10x más tablas que Kimball) no se justifica para el volumen y alcance 
  del proyecto.

**Por qué Kimball es el más apropiado**:

- **Escala del proyecto**: 221 pedidos, 76 clientes, 8 SKUs. Alternativas 
  más pesadas serían sobreingeniería.
- **Consumidor principal**: Metabase, que está diseñado para consumir 
  modelos dimensionales. Star schema encaja naturalmente.
- **Mantenido por una persona**: Kimball es el más simple de sostener 
  sin equipo dedicado.
- **Skill portable**: es el estándar en la industria para BI. Aprenderlo 
  tiene retorno de carrera claro (aparece en la mayoría de ofertas de 
  Data / Analytics Engineering).
- **Mapping natural al negocio**: las entidades (cliente, producto, 
  fecha, tarifa) mapean directo a dimensiones. Los eventos (pedidos) 
  mapean directo a hechos. No forzamos el modelo.

### Decisión 2: `dim_producto` como seed CSV

Poblamos `dim_producto` desde un seed CSV (`productos_catalogo.csv`) en 
vez de hardcodear las 8 combinaciones válidas como `VALUES` en el SQL 
del modelo.

**Ventajas concretas del seed sobre VALUES hardcodeadas**:

1. **Facilidad de mantenimiento**: agregar un producto nuevo (por 
   ejemplo, si empezamos a vender "Integral / Oreo") requiere agregar 
   una fila al CSV. Con VALUES, habría que editar el SQL del modelo.

2. **Accesibilidad**: un CSV puede ser editado por alguien sin 
   conocimientos de SQL — abrir con Excel/Sheets, agregar fila, guardar. 
   El modelo SQL requiere entender la sintaxis de dbt y la estructura del 
   query.

3. **Fuente única de verdad**: el mismo `productos_catalogo.csv` va a 
   alimentar `dim_producto` y también va a servir como referencia para 
   validar combinaciones en tests dbt (`relationships` o `accepted_values` 
   contra el catálogo). Duplicar el listado en dos lugares (SQL del 
   modelo + otro seed para validación) generaría deuda de sincronización.

4. **Versionado limpio**: los cambios al catálogo aparecen como diffs 
   claros en git (una fila agregada/removida), no como cambios en SQL 
   que requieren lectura contextual.

`dim_producto.sql` lee el seed vía `{{ ref('productos_catalogo') }}` y 
agrega columnas derivadas: surrogate key (`producto_id` como MD5), 
`nombre_producto` para display, y metadata (`created_at`).

### Decisión 3: `dim_fecha` autogenerada con `generate_series`

Poblamos `dim_fecha` con un modelo SQL que usa `generate_series` para 
crear una fila por día entre 2024-01-01 y 2027-12-31 (1461 filas), y 
calcula los atributos derivados (`nombre_mes`, `nombre_dia`, 
`es_finde_semana`, `trimestre`, etc.) con funciones SQL puras (`extract`, 
`case when`).

**Alternativa descartada**: seed CSV con las 1461 filas pregeneradas.

**Ventajas de autogenerar**:

- **Extender el rango es trivial**: si mañana queremos agregar hasta 
  2030, cambiamos una fecha en el SQL. Con seed CSV habría que 
  pregenerar tres años más de filas en un archivo externo.

- **Cero riesgo de error humano**: los cálculos de fecha (nombres en 
  español, días de semana, años bisiestos) los hace el motor de DuckDB, 
  que implementa el calendario gregoriano completo sin fallar. Un CSV 
  pregenerado con esa lógica podría tener typos, errores de conversión 
  o bisiestos mal calculados.

- **Coherencia con la naturaleza del dato**: el calendario es mecánico, 
  no requiere decisiones de negocio. Cualquier información en un calendario 
  (¿qué día de la semana fue X?) es derivable sin ambigüedad.

**Por qué `dim_producto` sí usa seed y `dim_fecha` no**:

La diferencia es qué tipo de conocimiento requiere generar la data. El 
catálogo de productos requiere criterio humano — "Oreo Integral no existe" 
es una regla de negocio, no algo derivable. El calendario, en cambio, es 
puramente mecánico. Los seeds sirven cuando hay decisiones humanas; los 
modelos autogenerados sirven cuando la data es derivable por reglas 
universales.

### Decisión 4: `dim_cliente` con estrategia de 3 capas

Los nombres de cliente en raw tenían múltiples fuentes de suciedad:

- Variaciones ortográficas: `"Ale"`, `"ale"`, `"Ale "`, `"ALE"`.
- Con y sin acentos: `"Auténtica"`, `"autentica"`, `"la Auténtica"`.
- Nombres ambiguos: `"terraza"` puede referirse a 2 sucursales distintas.
- Nombres que ocultan negocios: `"cliente b"` es en realidad "Cliente B 
  Mejia" (nombre del dueño usado como shorthand del negocio).

Diseñamos una estrategia de 3 capas para resolverlo:

**Capa 1 — Normalización automática (`int_clientes_normalizados`)**

Modelo intermedio SQL que aplica reglas mecánicas: `lower`, `trim`, 
`strip_accents`, y `regexp_replace` para colapsar espacios múltiples. 
Resuelve variaciones puramente ortográficas.

Sola no alcanza: reduce fragmentos pero no puede inferir equivalencias 
semánticas ("cliente b" = "Cliente B") ni identificar ambigüedades 
("terraza" = 2 sucursales).

**Capa 2 — Mapping manual (`client_name_mapping.csv`)**

Seed CSV con estructura `nombre_normalizado → cliente_canonico + 
tipo_cliente + es_ambiguo`. Poblado manualmente con conocimiento del 
negocio.

La normalización automática (capa 1) reduce dramáticamente el tamaño de 
este mapping. Sin capa 1, habría que mapear 4 filas para "Ale" (una por 
cada variante ortográfica). Con capa 1, se colapsa a una sola fila 
(`ale → Ale`).

**Capa 3 — Cuarentena implícita (`necesita_mapping`)**

`dim_cliente` incluye una columna booleana `necesita_mapping`. Cuando un 
nombre normalizado no matchea con ninguna fila del mapping, queda 
marcado como `true` y con canónico `"Desconocido: <nombre>"`.

Es la red de seguridad para clientes nuevos que aparecen sin haber sido 
mapeados. Sin esta capa, un cliente nuevo pasaría inadvertido; con ella, 
queda visible para agregarlo al mapping en la próxima iteración.

**Por qué las 3 capas juntas**:

Cada capa resuelve un tipo de problema distinto. La 1 automatiza lo que 
se puede automatizar (bajando costo de mantenimiento). La 2 captura el 
criterio humano imposible de automatizar. La 3 asegura que ningún caso 
quede oculto. Saltear cualquiera de las tres degrada el resultado.

### Decisión 5: `client_name_mapping.csv` gitignored, `.example.csv` en el repo

El archivo `client_name_mapping.csv` contiene los nombres reales de 
clientes del negocio (con su clasificación B2B/B2C y ambigüedades). Es 
data personal y comercial que no corresponde exponer públicamente.

**Por qué el CSV real no va al repo**:

Está gitignored (`dbt_project/seeds/client_name_mapping.csv` listado 
explícitamente en `.gitignore`). Commitear nombres reales de clientes 
sería una filtración de datos personales de terceros y de información 
comercial sensible del negocio (segmentación de cartera). Aunque el 
repo es privado, buenas prácticas dictan que datos personales no viven 
en git — cualquier compromiso futuro del repositorio los expondría.

**Por qué SÍ va un `.example.csv`**:

Commiteamos `client_name_mapping.example.csv` con estructura idéntica 
al real pero con datos anonimizados (`cliente ejemplo b2c`, 
`Cliente Ejemplo B2C`, etc.). Cumple dos funciones:

- **Documentación viva**: alguien que clone el repo puede ver el schema 
  esperado del mapping sin necesidad de acceder al real.
- **Setup reproducible**: permite ejecutar el pipeline completo con data 
  de prueba, útil para testing o para armar un dataset dummy más 
  extenso a futuro.

**Cómo se transfiere el CSV real entre entornos**:

Como el CSV no está en git, hay que transferirlo manualmente al setear 
una PC nueva o al colaborar con otra persona. Canales aceptables: 
pendrive físico, password manager con función de compartir archivos, 
servicios de transferencia end-to-end encrypted, o drive personal 
privado. Canales explícitamente descartados: mail común (Gmail/Outlook 
lo almacenan indefinidamente), WhatsApp, o cualquier nube compartida 
sin cifrado — un compromiso de esos canales expondría los datos.

En el README del proyecto se documenta el workflow: al clonar en una 
máquina nueva, copiar el `.example.csv` como base o pedir el real por 
canal privado.
## Consecuencias

[después]