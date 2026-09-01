# ADR Semana 12: Cierre, auditoría de PII y publicación

## Contexto

Al terminar semana 10 el proyecto estaba funcionalmente completo: pipeline
end-to-end orquestado, modelo dimensional con reconciliación de precios, forecast
semanal validado por backtesting, y detección de reorder B2B en dos capas
complementarias, todo consumible desde Metabase.

Semana 12 no agrega capacidades. Agrega **acceso**: convierte un proyecto que
funciona en la máquina del autor en un repositorio público que un tercero puede
leer, entender y ejecutar. El trabajo se divide en cuatro frentes: eliminar
información sensible del repositorio y su historial, verificar que la
configuración documentada alcance para reproducir el entorno, escribir la
documentación transversal que los ADRs semanales no cubren, y formalizar qué
queda fuera del scope entregado.

La semana 11 del roadmap original (backfill histórico 2024-2025) se descarta del
scope entregado. La justificación está en la Decisión 4.

---

## Decisiones

### Decisión 1: Auditoría de PII sobre working tree e historial completo, previa a publicar

Antes de cambiar la visibilidad del repositorio se ejecutó una auditoría de
información personal identificable. El alcance incluyó explícitamente el
**historial de git**, no solo el estado actual del working tree.

**Justificación del alcance**: git conserva los objetos de commits anteriores.
Un archivo eliminado o un dato corregido siguen siendo recuperables por cualquiera
que clone el repositorio. Limpiar únicamente el estado actual da una sensación
falsa de seguridad: el dato sigue publicado, solo que un paso más abajo.

La auditoría se estructuró en tres frentes, con métodos distintos porque los
mecanismos de protección que aplican a cada uno son distintos:

**Frente 1 — Working tree.** Inventario de archivos trackeados (`git ls-files`) y
verificación de que los patrones de `.gitignore` efectivamente aplican a los
archivos sensibles (`git check-ignore -v`). Se verificó archivo por archivo en
lugar de asumir que el patrón escrito funciona: un archivo ya trackeado sigue
trackeado aunque después se agregue al `.gitignore`.

**Frente 2 — Historial.** Búsqueda por contenido con `git log -S` sobre todos los
refs, más detección de patrones estructurados de credenciales.

**Frente 3 — Contenido embebido.** Nombres reales escritos dentro de archivos que
sí se publican. Es el frente que ningún `.gitignore` puede cubrir y el que más
riesgo tenía.

**Resultado**: cero hallazgos en código productivo, modelos SQL, modelos Python y
suite de tests. **Todos los hallazgos estaban en ADRs.**

Este resultado es en sí mismo un hallazgo de auditoría. La disciplina de gitignore
y de fixtures anonimizados funcionó donde estaba declarada. Lo que falló fue la
documentación en prosa, donde escribir el nombre real del cliente es lo natural
—se está documentando una decisión *sobre ese caso concreto*— y donde no había
ninguna barrera técnica que lo impidiera.

**Remediación**: reemplazo por placeholders consistentes entre documentos,
conservando la categoría del cliente cuando el argumento técnico la requería
(por ejemplo, "negocio que se dividió en dos sucursales" cuando la decisión
depende de ese hecho). Reescritura del historial con `git filter-repo`. El mapeo
placeholder → nombre real se conserva fuera del repositorio.

**Condiciones que hicieron barata la reescritura**: repositorio privado, sin
forks, sin colaboradores, sin CI que dependa de SHAs. Estas condiciones dejan de
cumplirse en el momento en que el repo se hace público, lo que convierte a la
auditoría previa en la última oportunidad de bajo costo.

### Decisión 2: El filtrado de candidatos por longitud generó un falso negativo

El diccionario de términos a buscar se construyó desde el seed de mapping de
clientes, que es la lista real y exhaustiva. El primer barrido devolvió
prácticamente todos los archivos del repositorio como coincidencia: ruido, no
señal.

El diagnóstico fue correcto —había términos genéricos contaminando— pero la
heurística de corte fue equivocada. Se descartaron todos los términos de cuatro
caracteres o menos, bajo el criterio de que un término tan corto es una subcadena
que aparece dentro de cualquier palabra.

**El criterio falló**: un cliente B2B con nombre de cuatro caracteres quedó fuera
del barrido. Se detectó recién al releer los ADRs manualmente, apareciendo doce
veces en dos documentos. La detección fue por revisión humana, no por el
procedimiento automático.

**Aprendizaje**: en una auditoría, el falso negativo y el falso positivo no tienen
el mismo costo. Un falso positivo cuesta un minuto de revisión; un falso negativo
es un dato personal publicado. Toda heurística de filtrado en este contexto debe
sesgarse deliberadamente hacia el ruido, y los descartes tienen que revisarse a
mano en lugar de aplicarse en bloque.

**Corrección aplicada**: revisión individual de cada término descartado, mirando el
contexto de la línea antes de decidir. Esa revisión también confirmó falsos
positivos legítimos —un nombre de pila que resultó ser una subcadena de una
palabra común en castellano— que un reemplazo automático habría corrompido.

**Consecuencia declarada**: el procedimiento actual depende de que el seed de
mapping esté completo. Un cliente que nunca haya entrado al mapping no aparece en
el diccionario y por lo tanto no se busca. Para un repositorio ya público, una
auditoría futura debería complementarse con detección de patrones de nombre propio
sobre los archivos de documentación.

### Decisión 3: Sincronización de `.env.example` verificada por comparación, no por lectura

Se comparó el conjunto de variables de entorno que el código efectivamente consume
—extraídas de las llamadas a `os.environ` y `os.getenv` en los módulos Python, y
de las interpolaciones `${...}` en `docker-compose.yml`— contra las declaradas en
`.env.example`.

**Resultado**: seis variables faltantes, incluidas las cinco de conexión a la capa
de serving Postgres. Un tercero que clonara el repositorio y siguiera el README
habría obtenido un `KeyError` sin contexto en el primer intento de exportar marts.

**Justificación del método**: la verificación por lectura visual no escala y no es
reproducible. La comparación por comando se puede repetir después de cada cambio y
devuelve un resultado binario.

**Hallazgo lateral**: una variable aparece en el código Python pero no en
`docker-compose.yml`, porque dentro de la red de containers el host se resuelve
por nombre de servicio. Solo importa cuando un proceso corre fuera del container
—por ejemplo un notebook en el entorno virtual local. Se documentó con un
comentario explícito en `.env.example`, ya que es exactamente el tipo de
diferencia que hace fallar un setup sin dar pistas.

**Riesgo aceptado y documentado**: `POSTGRES_PASSWORD` tiene un valor por defecto
de desarrollo. Si la variable no está definida, el stack levanta con una
credencial débil en lugar de fallar. Es aceptable en un entorno local; en un
despliegue real el default debería removerse para que la ausencia sea un error
ruidoso. Se documenta como limitación conocida en `arquitectura.md` en lugar de
corregirse, porque el entorno objetivo del proyecto es local.

### Decisión 4: Semana 11 (backfill 2024-2025) diferida, no abandonada

El roadmap original declaraba para semana 11 la carga del histórico 2024-2025 con
parser lenient, tabla de cuarentena separada, reconstrucción de tarifas históricas
por regla de inflación, y columna `data_source_version` en los marts.

Se decide **excluirla del scope entregado** y documentarla como extensión futura.

**Justificación**: el backfill no es una repetición del pipeline actual sobre más
filas. Es un problema distinto que requiere, como mínimo:

- Un parser tolerante para convenciones de carga que ya no se usan, con reglas
  posiblemente distintas por período.
- Reconstrucción de tarifas históricas por regla inflacionaria, sin planillas de
  respaldo para validar contra la realidad.
- Una tabla de cuarentena y un criterio de aceptación para filas que no parsean.
- Versionado de origen en los marts, para que ningún análisis mezcle datos
  reconstruidos con datos verificados sin advertirlo.

**El riesgo principal es de calidad, no de esfuerzo.** El ADR de semana 8 dejó
declarado que armar un CSV de tarifas con fechas "prolijas" sin validarlas contra
transacciones reales genera discrepancias sistemáticas sin trazabilidad. Para
2026 ese error se detectó porque existían las planillas originales del aumento.
Para 2024-2025 no existen: las tarifas se reconstruirían por regla, y no habría
forma de distinguir un error de reconstrucción de una anomalía real del negocio.

Incorporar datos históricos con esa incertidumbre contaminaría el forecast y la
detección de reorder, que hoy operan sobre data verificada.

**Consecuencia**: el warehouse cubre 2026. El razonamiento se documenta en el
README bajo "Roadmap futuro" con su fundamento técnico, para que la ausencia se
lea como límite de scope deliberado y no como trabajo pendiente.

### Decisión 5: Documentación transversal separada de los ADRs semanales

Se agregan tres documentos a `docs/`: `arquitectura.md`, `modelo.md` y
`pricing.md`. Se agrega también un bloque `__overview__` que reemplaza la página
de bienvenida por defecto del catálogo de dbt.

**Justificación**: los ADRs son cronológicos y responden "por qué se decidió esto
en este momento". No responden "cómo funciona el sistema hoy", que es la pregunta
de alguien que llega al repositorio sin contexto. Reconstruir el estado actual
leyendo diez ADRs en orden es fricción innecesaria.

La división es deliberada: los ADRs conservan el proceso, incluidas las
exploraciones descartadas y los bugs encontrados; los documentos transversales
describen el resultado. Ninguno reemplaza al otro y los transversales referencian
a los ADRs para el detalle.

**Consecuencia**: hay ahora dos fuentes que describen las mismas decisiones desde
ángulos distintos, con riesgo de divergencia si una se actualiza sin la otra. Se
mitiga con la regla de que los ADRs son inmutables una vez cerrados —registran lo
que se decidió entonces— y solo los documentos transversales se actualizan.

---

## Consecuencias

### Ganancias

- **Repositorio publicable sin información sensible**, verificado sobre el
  historial completo y no solo sobre el estado actual.
- **Setup reproducible por un tercero**: `.env.example` sincronizado con lo que el
  código consume, y seeds `.example.csv` que permiten correr el pipeline completo
  sin acceso a los datos reales.
- **Documentación en tres niveles**: catálogo de dbt para el detalle por modelo,
  documentos transversales para el estado actual del sistema, ADRs para el
  proceso de decisión.
- **Pipeline sin warnings**: la suite de dbt corre sin deprecations, cerrando
  deuda declarada desde semana 7.
- **Procedimiento de auditoría de PII reutilizable**, con su error metodológico
  documentado.

### Costos
Me llevo demasiado tiempo el tener que auditar todos los archivos, ya que habia dejado perdidos muchos nombres de clientes,
y esto representa informacion sensible para con mi negocio.
Fue un trabajo tedioso y repetitivo.


### Deuda declarada

- **Backfill 2024-2025**: diferido según Decisión 4. Documentado en el README como
  extensión futura.
- **Auditoría de PII dependiente del seed de mapping**: un cliente ausente del
  mapping no entra al diccionario de búsqueda y no se detecta.
- **`POSTGRES_PASSWORD` con default de desarrollo**: remover antes de cualquier
  despliegue fuera de local.
- **Test dbt en rojo permanente**: caso de producto descatalogado, documentado
  desde semana 6. Se publica así a propósito.
- **Schedule de Dagster declarado pero deshabilitado**: requiere fijar
  `execution_timezone` antes de activarse en un entorno 24/7.
- **CI de datos**: los tests de dbt corren en cada materialización pero no hay gate
  automático por push.

---

## Retrospectiva

### Qué se aprendió
De este proyecto me llevo mucho conocimiento y ganas de aprender aun mas sobre todo lo que es ciencia de datos, me enseño que
cualquier dataset puede ser util si el problema elegido es el adecuado.
Aprendi a descartar mucha informacion de ruido del forecast lo cual me permitio saber con mas exactitud las probabilidades de reorder.
Poder discernir en que es mas importante y que no.
### Qué falló
Me tuve que arrepentir y dejar de lado por ahora el backfill historico, ya que a medida que avanzaba con la normalizacion me di cuenta que no iba a poder cumplir con los plazos que me propuse ya que ya me habia llevado mas de lo normal los datos que estaban "bien" entonces no me queria imaginar cuanto me iba a llevar hacerlo con tablas que estaban muy mal hechas.
### Qué haría distinto
Lo que hubiese hecho distinto, es haberme planteado para el negocio tener una base de datos distinta y bien diagramada que no sea google sheets jajajaaj.
En relacion al proyecto, la verdad que nada, cada paso que avanzaba me generaba una enseñanza, por lo que volveria a transitarlo de la misma manera.
### Próximos pasos
A futuro la idea es que este proyecto colapse junto con la app de gestion para asi tener un sistema central que maneje todo y a la vez sea todo cada vez mas automatico, que se expanda a reposicion de insumos para producir nuevamente los waffles, que envie notificaciones a mi celular o pc todas las semanas diciendo quien o cuantos pedidos va a haber y por que.

---

## Referencias

- Arquitectura del sistema: `docs/arquitectura.md`
- Modelo dimensional: `docs/modelo.md`
- Precios y reconciliación: `docs/pricing.md`
- Decisiones semanales previas: `docs/decisions/`
