# ADR Semana 3: Parser del campo PEDIDO

## Contexto
El campo PEDIDO de la Sheet de ventas viene como texto libre con la descomposición del pedido en un solo string, por ejemplo "144 dulces clasicos + 24 oreos clasicos". Este formato es cómodo para carga humana pero inutilizable para análisis: no permite responder preguntas básicas del negocio como "¿cuántas unidades de masa Clásica se vendieron?", "¿qué sabor es el más vendido?", o "¿cuántos pedidos incluyen Oreos?". Para habilitar cualquier análisis downstream, cada string debe descomponerse en items estructurados con sabor, masa y cantidad como campos separados.

## Decisiones
### Decisión 1: Output como lista de dicts

Elegimos que el parser devuelva una lista de diccionarios con claves 
`sabor`, `masa`, `cantidad` en lugar de tuplas posicionales. La razón 
principal es la legibilidad: al leer código consumidor, `item["sabor"]` 
autodocumenta qué campo se está accediendo, mientras que `item[0]` obliga 
a recordar el orden. La desventaja es un pequeño overhead de memoria y 
verbosidad, pero irrelevante para el volumen actual del proyecto.

**Alternativa descartada**: lista de tuplas. Más compacta pero menos 
explícita, y complica cualquier extensión futura (agregar un campo nuevo 
requeriría cambiar el orden en todo el código que consuma tuplas).


### Decisión 2: Inputs no parseables van a cuarentena, no se ignoran

El parser puede recibir strings que no cumplen el formato esperado 
(ej. `"oreos"` sin cantidad, strings vacíos, typos). Decidimos que estos 
casos se devuelvan en una lista aparte `no_parseados` junto con el resto 
del output, en lugar de lanzar una excepción o ignorarlos silenciosamente.

Lanzar excepción se descartó porque rompería la continuidad del pipeline: 
un solo string mal formado detendría toda la ingesta. Ignorar 
silenciosamente se descartó porque genera inconsistencia sin dejar rastro 
— pedidos válidos podrían perderse sin que nadie lo detecte, y el conteo 
de ventas quedaría subestimado sin explicación.

Con cuarentena, el pipeline sigue funcionando, y los casos raros quedan 
visibles para revisión manual. Es data engineering defensivo: mejor 
capturar que ocultar.

### Decisión 3: Validación contra el catálogo vive en dbt, no en el parser

El parser puede devolver combinaciones sintácticamente correctas pero 
semánticamente inválidas (ej. `Oreos / Integrales`, que no existe en el 
catálogo real de 8 SKUs). Decidimos que esta validación no viva en el 
parser Python, sino en la capa dbt.

El parser se mantiene "tonto": solo extrae estructura del string. No 
conoce reglas de negocio ni combinaciones válidas. Esta separación 
mantiene el código Python simple, testeable, y libre de acoplamiento 
con el modelo de datos del negocio.

En dbt vamos a tener un seed `productos_catalogo.csv` con las 8 
combinaciones válidas de (masa, sabor). Los modelos de staging podrán 
validar contra este catálogo usando tests declarativos de dbt 
(`relationships`, `accepted_values`), que corren automáticamente en 
cada `dbt test`. Los pedidos con combinaciones inválidas van a 
cuarentena para revisión manual.

### Decisión 4: Fallback de cantidad usando la columna CANTIDAD del sheet

Al correr el parser sobre los 221 pedidos reales, descubrimos que solo 
el 75% parseaba correctamente. Investigamos con queries SQL los 54 casos 
fallidos y encontramos un patrón claro: todos tenían el string PEDIDO 
sin cantidad al inicio (ej. `"dulces clasicos"`), pero la columna 
CANTIDAD del sheet sí tenía el número correcto.

El origen del problema es histórico: una versión vieja de la app upstream 
que carga los pedidos omitía la cantidad en la descripción cuando el 
pedido era de un solo item, porque la cantidad ya estaba en la columna 
paralela. La app fue actualizada después, pero la data histórica quedó 
con esa convención.

Decidimos agregar un parámetro `cantidad_default` al parser. Cuando el 
string no empieza con un dígito **y** no contiene `+`, el parser 
reconstruye el string prepending la cantidad recibida por parámetro y 
sigue el flujo normal. La restricción de "sin `+`" es crítica: si el 
pedido tiene múltiples items separados por `+`, cada item necesita su 
propia cantidad explícita. La CANTIDAD total del sheet corresponde al 
pedido completo y no puede repartirse automáticamente entre items.

Después de aplicar el fallback, el parse rate subió de 75% a 97%.

### Decisión 5: `masa_por_defecto` como parámetro configurable

Después del fallback de cantidad, quedaban 5 pedidos (2%) en cuarentena. 
Todos con strings de una sola palabra sin masa explícita (ej. `"Dulces"`, 
`"oreos"`). Investigando caso por caso, confirmamos que los 5 eran de 
masa Clásica: clientes distintos, carga manual, todos coherentes con el 
patrón del negocio donde Clásica es la masa dominante.

Como principio general, los defaults implícitos son peligrosos: 
introducen data sin trazabilidad y son difíciles de auditar. Sin 
embargo, cuando el default está soportado por evidencia empírica y 
declarado explícitamente, deja de ser implícito y pasa a ser una regla 
de negocio documentada.

Decidimos agregar un parámetro `masa_por_defecto` al parser, con default 
`None`. Cuando el parser recibe un chunk sin masa y no hay masa previa 
para heredar, usa el parámetro. Si el parámetro no se pasa, el chunk va 
a cuarentena (comportamiento original).

Lo hicimos configurable en vez de hardcodear `"Clásica"` porque distintos 
contextos van a necesitar reglas distintas. El pipeline actual (data 2026) 
usa `masa_por_defecto="Clásicos"`. El pipeline de backfill (data 
2024-2025, semana 11) puede necesitar otro default o ninguno, dependiendo 
de cómo era la convención en ese período. Con el parámetro, cambia la 
llamada, no el código del parser.

Con este cambio, el parse rate llegó al 100% sobre los 221 pedidos de 
2026.


## Consecuencias
## Consecuencias

### Ganancias

- **Habilitación de análisis**: preguntas de negocio que antes eran 
  imposibles de responder ahora son consultas SQL directas. Por ejemplo, 
  "¿cuántas unidades de masa Clásica se vendieron en julio?" ya se 
  puede responder desde el warehouse.
- **100% de parse rate** sobre los 221 pedidos de 2026. Cero pérdida de 
  data silenciosa.
- **Suite de 11 tests unitarios** que corren en segundos. Permite 
  refactorizar el parser en el futuro sin miedo a romper casos que 
  antes funcionaban.

### Costos

- La validación contra el catálogo depende de que la capa dbt corra. Si 
  el pipeline dbt no se ejecuta (por bug, falla de infraestructura, o 
  configuración incorrecta), los pedidos con combinaciones inválidas 
  no se detectan.
- El seed `productos_catalogo.csv` requiere mantenimiento manual: cada 
  vez que el negocio agregue un producto nuevo, hay que actualizar el 
  CSV para que dbt lo acepte.

### Deuda declarada

- **Reevaluar `masa_por_defecto` para el backfill (semana 11)**: el 
  parámetro `masa_por_defecto="Clásicos"` está justificado para data 
  2026 con evidencia empírica. Para la data histórica 2024-2025, esa 
  regla puede no aplicar (la convención pudo haber sido distinta). En 
  semana 11, al armar el pipeline de backfill, hay que investigar la 
  data histórica y decidir el default apropiado (puede ser otro valor, 
  o `None` para forzar cuarentena).