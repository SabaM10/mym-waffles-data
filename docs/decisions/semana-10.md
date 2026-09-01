# ADR Semana 10: Detección de reorder B2B con enfoque dual

## Contexto

Al terminar semana 9, teníamos el forecast semanal funcionando en producción
(SMA-4 con banda empírica, materializado como asset Dagster y consumido por
dashboard Metabase). Pero el forecast responde una pregunta agregada del
negocio ("¿cuántas unidades vamos a vender la semana que viene?") y no
resuelve el dolor operativo real que motivó el proyecto desde el inicio:
detectar cuándo un cliente B2B específico deja de pedir a tiempo.

La cadencia B2B de MyM Waffles es heterogénea. Cliente T sucursal 1 pide cada 9
días con muy poca variación; Cliente G pide cada 50 días con alta dispersión;
Cliente K pide cada 35 días con desvío casi tan grande como el
promedio. Un cliente "atrasado" no se puede definir con un umbral universal
en días absolutos: para cliente T sucursal 1, 20 días de silencio es escandaloso;
para cliente G, es dentro de lo esperable. La solución tiene que ser
personalizada por cliente y tiene que salir de la cadencia histórica de
cada uno.

Semana 10 aborda esta detección desde dos ángulos complementarios y no
competidores: un enfoque rule-based simple (umbral por cliente basado en
media y desvío del intervalo histórico) y un enfoque probabilístico más
rico (probabilidad continua vía CDF Normal ajustada a los intervalos
observados). Los dos coexisten porque responden preguntas distintas del
negocio: el rule-based dice "sí/no, ¿tengo que llamar a este cliente hoy?",
el probabilístico dice "¿cuán atípico es el silencio actual comparado con
su patrón histórico?".

Además, semana 10 cierra deudas específicas heredadas de semana 9:
extracción del modelo probabilístico del notebook exploratorio a código
productivo, y agregado de `scipy` como dependencia del container Dagster.

## Decisiones

### Decisión 1: Enfoque dual complementario, no competitivo

Ante la disponibilidad de dos posibles aproximaciones al problema
(rule-based estadísticamente simple vs probabilístico con CDF Normal), se
decidió implementar ambas y presentarlas como capas complementarias, no
como alternativas competidoras.

**Alternativa considerada**: elegir una sola. El rule-based es más simple
de entender, más fácil de auditar, y suficiente para la operación básica.
El probabilístico es más rico pero conceptualmente más complejo.

**Por qué se rechazó la elección monolítica**: cada enfoque responde una
pregunta distinta del negocio.

- El rule-based produce un flag binario (`alerta_reorder = TRUE/FALSE`).
  Es lo que necesita la operación diaria: "¿a quién llamo hoy?" Es
  información accionable inmediata, sin ambigüedad.
- El probabilístico produce una medida continua (0..1). Es lo que
  necesita el análisis: "¿este cliente está entrando en zona de riesgo o
  todavía está tranquilo?" Es información predictiva graduable.

Un flag binario no tiene granularidad para distinguir "cliente 4x atrasado
respecto a su patrón" de "cliente apenas por encima del umbral". Una
probabilidad continua no tiene un corte natural para acción operativa
("¿desde qué probabilidad tengo que llamar?"). Los dos juntos cubren
ambos usos.

**Ventaja emergente no anticipada**: al tener dos métodos independientes
con supuestos distintos operando sobre la misma data, la coincidencia en
los resultados funciona como validación cruzada. En la primera corrida con
data real, los 3 clientes que salieron en alerta rule-based coincidieron
exactamente con los 3 con mayor probabilidad en el probabilístico. Esa
coincidencia no era garantizada por construcción (los métodos tienen
umbrales y supuestos distintos), y refuerza analíticamente la señal. Este
tipo de validación cruzada es un argumento defensivo mucho más fuerte en
portfolio que cualquiera de los dos métodos aislado.

### Decisión 2: Exclusión de clientes ambiguos con listado paralelo

`int_b2b_cadencia` filtra explícitamente `es_ambiguo = FALSE` desde
`dim_cliente`. Los clientes marcados como ambiguos (aquellos donde el
canónico colapsa 2+ entidades reales, como el caso histórico de Cliente T
consolidado documentado en la Decisión 5 de semana 8) quedan fuera del
análisis.

**Alternativa considerada**: incluirlos con una advertencia visual, o
tratarlos con lógica especial que dividiera artificialmente sus pedidos
entre las entidades reales.

**Por qué se rechazaron**: cuando un canónico colapsa dos sucursales
independientes, la cadencia calculada no representa a ninguna de las dos.
Si Cliente T consolidado tiene 2 sucursales pidiendo cada 14 días
desfasadas 7 días, la cadencia agregada mide 7 días con desvío bajo, y
el sistema jamás dispara alerta aunque una sucursal esté genuinamente
atrasada. Los intervalos son artificiales, la media está sesgada, el
desvío también.

**Por qué no ocultarlos completamente**: siguiendo el principio "declarar
en vez de esconder" heredado de semanas anteriores, los clientes ambiguos
no se filtran silenciosamente. Aparecen en `dim_cliente` con
`es_ambiguo = TRUE` y su exclusión del análisis está documentada. Si un
consumidor del warehouse consulta por qué Cliente T histórica no aparece en
las alertas, puede rastrear la lógica: filtro explícito por
`es_ambiguo = FALSE`, cliente marcado como ambiguo en la dimensión,
justificación en semana 8.

**Nota práctica**: en la data actual, la exclusión afecta mayormente al
Cliente T consolidado histórico. Post-separación operativa, "Cliente T
sucursal 2" y "Cliente T sucursal 1" son canónicos separados no ambiguos, y
ambos entran normalmente al análisis. La exclusión tiene poco costo
práctico y mucho valor conceptual.

### Decisión 3: Umbral mínimo de 4 pedidos históricos por cliente

`int_b2b_cadencia` incluye la cláusula `HAVING count(*) >= 4` para
descartar clientes con historia insuficiente.

**Justificación estadística**: con 4 pedidos se pueden calcular 3
intervalos, mínimo matemático para que `stddev_samp` no devuelva NULL
(que requiere n >= 2). Con 3 intervalos, la estimación de sigma es
todavía pobre pero funcional. Con menos, no hay señal.

**Alternativa considerada**: umbral más alto (6 o más pedidos) para
mejorar la calidad de la estimación estadística.

**Por qué se rechazó umbral más alto para el rule-based**: sacrificar
cobertura sin beneficio proporcional. Los clientes con 4-5 pedidos son
minoría, y aunque su estimación tenga más incertidumbre, tener un
umbral personalizado ruidoso es mejor que no tener umbral. El
rule-based es la capa laxa; el probabilístico es la capa que se preocupa
por la calidad estadística.

**Consecuencia**: en la data actual, 13 clientes B2B pasan el filtro.
Los que quedan fuera son casos genuinos de historia insuficiente (nuevos,
esporádicos con pocas apariciones) donde el sistema no tiene evidencia
para pronunciarse.

### Decisión 4: `umbral_alerta_desvios_b2b` como variable dbt

El umbral de alerta rule-based se define como:

```
umbral_alerta_dias = intervalo_promedio + N * intervalo_desvio
```

Donde `N` viene de la variable dbt `umbral_alerta_desvios_b2b` (default
`1.0`).

**Justificación**: los umbrales estadísticos son convenciones tentativas,
no reglas fijas del negocio. La regla "promedio + 1σ" corresponde
aproximadamente al percentil 84 de una distribución normal, y es un punto
de partida razonable, pero puede resultar demasiado estricto o demasiado
laxo según cómo se comporte la data real del negocio.

Con variable, tunear el umbral es un cambio de YAML y una re-materialización
del mart afectado, no un cambio de SQL. Coherente con el patrón adoptado
en semana 8 para `umbral_coincide_ars` y `umbral_discrepancia_grande_ars`.

**Consecuencia operativa**: después de 6-8 semanas de uso real, se puede
tunear el umbral con evidencia empírica. Si aparecen muchos falsos
positivos (alertas que no eran), subir a 1.5. Si aparecen bajas sorpresa
sin alerta previa, bajar a 0.5. Documentar el cambio como decisión con
evidencia, no como corazonada.

### Decisión 5: `ratio_atraso` como métrica principal de severidad, no flag booleano

El mart `rpt_alertas_reorder_b2b` incluye:

- `alerta_reorder`: flag booleano (`dias_desde_ultimo > umbral_alerta_dias`).
- `dias_de_atraso`: diferencia absoluta (`dias_desde_ultimo - umbral_alerta_dias`).
- `ratio_atraso`: métrica multiplicativa (`dias_desde_ultimo / umbral_alerta_dias`).

Se decidió que `ratio_atraso` es la métrica principal para ordenar
alertas por severidad, y las otras dos son complementarias.

**Justificación**: el flag booleano no distingue entre "cliente 4x sobre
su umbral" (alerta severa, Cliente T sucursal 1 con ratio 4.33) y "cliente
apenas por encima del umbral" (alerta débil, Cliente K con ratio
1.12). Los dos son `TRUE`, pero requieren atención muy distinta.

`ratio_atraso` es adimensional (no depende de la escala de cadencia del
cliente) y comparable entre clientes. Un cliente que pide cada 9 días con
ratio 2.0 (18 días de silencio) es tan severo como uno que pide cada
50 días con ratio 2.0 (100 días de silencio). En ambos casos, la señal
es "está al doble de su patrón esperado".

**Consecuencia**: el dashboard usa `ratio_atraso` como métrica principal
de ordenamiento y para el formato condicional (semáforo). El flag
`alerta_reorder` se conserva porque simplifica los filtros directos en
Metabase y KPIs (contar alertas), pero visualmente el usuario ve la
severidad graduada, no un binario.

### Decisión 6: Modelo Normal en vez de lognormal para el probabilístico

`ingestion/b2b_reorder.py` ajusta una distribución Normal `N(mu, sigma)`
a los intervalos históricos de cada cliente, y usa CDF para calcular la
probabilidad de reorder.

**Alternativa considerada**: distribución lognormal, teóricamente más
correcta para tiempos entre eventos (asimétrica, solo positiva, cola
larga hacia arriba).

**Por qué Normal**: por tres razones combinadas.

1. **Consistencia con el notebook de W9**: el modelo probabilístico se
   exploró originalmente en `notebooks/forecast_exploration.ipynb` como
   Normal. Extraerlo tal cual a producción respeta el trabajo ya hecho y
   evita reintroducir decisiones ya tomadas.
2. **Simplicidad interpretativa**: `scipy.stats.norm.cdf(x, mu, sigma)`
   es una línea. Lognormal requeriría trabajar con `log(intervalos)`,
   ajustar la Normal sobre esos logs, y desloguear. Complejidad
   marginal sin ganancia proporcional para el volumen actual de data.
3. **Impacto práctico despreciable**: el "sesgo teórico" de la Normal es
   asignar probabilidad no-nula a intervalos negativos. Para clientes con
   coeficiente de variación alto (sigma/mu grande), esto genera un pequeño
   "goteo" de probabilidad en la zona sin sentido físico. En la práctica,
   la CDF en la región relevante (dias_desde_ultimo positivos) se
   diferencia poco entre las dos distribuciones.

**Deuda declarada**: si en operación real aparecen problemas de
calibración específicos (por ejemplo, clientes con historia larga donde
la Normal predice mal), migrar a lognormal.

### Decisión 7: Umbral 4 pedidos para el probabilístico + columna `confianza_estimacion`

`mart_b2b_reorder_probabilistico` incluye los mismos clientes que
`int_b2b_cadencia` (mínimo 4 pedidos, mismo umbral que rule-based), pero
agrega la columna `confianza_estimacion` categórica basada en la cantidad
de pedidos históricos:

- `total_pedidos < 6`: `BAJA`
- `total_pedidos entre 6 y 9`: `MEDIA`
- `total_pedidos >= 10`: `ALTA`

**Alternativa considerada**: umbral más alto (6+) para el probabilístico,
sacando del análisis a los clientes con historia corta.

**Por qué se rechazó**: excluir clientes con menos historia habría
sacado, entre otros, a Cliente G, que fue el ejemplo prototípico de la
exploración en semana 9 (5 pedidos históricos). El umbral 4 mantiene la
cobertura del rule-based, y la columna `confianza_estimacion` traslada al
consumidor del mart la información necesaria para interpretar los
resultados con matiz.

**Justificación conceptual**: coherente con el principio "declarar en
vez de esconder" del proyecto. En vez de decidir por el usuario qué
clientes son "confiables" y esconder el resto, se muestran todos con
metadata explícita sobre la calidad de la estimación. Un usuario técnico
puede filtrar por `confianza_estimacion IN ('MEDIA', 'ALTA')` si lo
desea; un usuario operativo puede leer la columna en el dashboard y
saber que "Cliente K en 90% con confianza BAJA" es una alerta
menos sólida que "Cliente B en 8.5% con confianza ALTA".

**Consecuencia**: el dashboard operativo puede usar la columna para
matizar el semáforo (ejemplo: un cliente en zona roja con confianza BAJA
podría mostrarse con un ícono adicional de "estimación incierta").

### Decisión 8: Separación arquitectónica en dos capas (funciones puras + modelo dbt Python)

El código probabilístico se separa en dos archivos con propósitos
distintos:

- `ingestion/b2b_reorder.py`: funciones puras (`calcular_probabilidad_reorder`,
  `calcular_z_score`, `clasificar_confianza`, `generar_reorder_probabilistico`).
  Sin dependencia de dbt, DuckDB, Dagster o infra. Testeable con pytest
  sin necesidad de warehouse ni container.
- `dbt_project/models/marts/mart_b2b_reorder_probabilistico.py`: modelo
  Python de dbt. Envoltorio mínimo que lee `int_b2b_cadencia` vía
  `dbt.ref`, aplica las funciones puras, y devuelve el DataFrame para
  que dbt-duckdb lo materialice.

**Justificación**: es el mismo patrón adoptado en semana 9 para
`forecast.py` y sus marts asociados. Separar lógica pura de orquestación
tiene tres ventajas concretas:

1. **Testeo aislado**: las funciones puras se testean con pytest sin
   necesidad de tener DuckDB, dbt o Dagster corriendo. Los 27 tests
   unitarios de `test_b2b_reorder.py` corren en menos de 1 segundo.
2. **Refactor seguro**: cambios en la lógica estadística no requieren
   tocar código de infraestructura, y viceversa.
3. **Aprendizaje transferible**: el patrón "función pura + envoltorio
   dbt Python" es reutilizable en cualquier proyecto que combine lógica
   Python compleja con orquestación dbt. Semanas anteriores lo aplicaron;
   semana 10 lo consolida como convención del proyecto.

### Decisión 9: Dashboard con dos tabs para audiencias distintas

El dashboard "Alertas Reorder B2B" se estructuró en dos pestañas:

- **Operativo** (default): pensado para uso diario por la socia del
  negocio. Lenguaje 100% humano ("Contactar ya", "Suele pedir cada X
  días"). Sin métricas técnicas visibles. Se lee en 5 segundos.
- **Análisis**: pensado para uso técnico y para portfolio. Muestra el
  detalle de las métricas rule-based y probabilístico, con la tabla de
  auditoría cruzada que evidencia la coincidencia entre los dos
  enfoques.

**Alternativa considerada**: un solo dashboard con las 4 preguntas
técnicas y textos explicativos que ayudaran al lector no técnico.

**Por qué se rechazó**: en la primera versión del dashboard, con solo
las 4 preguntas técnicas, la socia del negocio no pudo leer la
información con facilidad. Los términos "CDF Normal", "1σ",
"probabilístico", "ratio_atraso" son ruido para quien necesita saber
"a quién llamar hoy". Al mismo tiempo, sacar esos términos habría
degradado el valor del dashboard como artefacto de portfolio.

**Consecuencia**: cada audiencia ve la vista adecuada. El tab operativo
es la default (la socia entra y no tiene que navegar), y el tab de
análisis está a un click para quien quiera profundizar. En portfolio,
mostrar la existencia de los dos tabs demuestra pensamiento explícito
sobre el consumidor del dato, no solo sobre el pipeline técnico.

### Decisión 10: Cadencia de materialización semanal, alineada con el ciclo del negocio

El pipeline no se corre diariamente. Se materializa una vez por semana
(idealmente viernes o sábado, cuando la semana operativa ya cerró en el
Sheet fuente), a través de "Materialize all" manual en la UI de Dagster.

**Justificación**: el ciclo de decisión del negocio B2B de MyM Waffles
es semanal. Los pedidos se coordinan por semana, la producción se
planifica por semana, las alertas se accionan por semana. Correr el
pipeline con más frecuencia que ese ciclo no agrega información
accionable, solo genera fricción operativa y ruido visual (números que
se mueven +1 día sin cambio operativo real).

Adicionalmente, el forecast (semana 9) es explícitamente semanal
(`mart_forecast_semanal` predice unidades por semana ISO), y la ingesta
es full-refresh (decisión de semana 2), por lo que correr diariamente no
acelera ni refina ningún cálculo.

**Consecuencia**: 5-10 minutos de operación por semana. La rutina es
prender Docker, click en "Materialize all", revisar el dashboard tab
Operativo, actuar sobre las alertas.

**Nota**: el schedule diario declarado en semana 7 sigue existiendo en
código pero deshabilitado. La decisión de operación semanal no lo
reemplaza; simplemente refleja el uso real actual. Si en el futuro el
proyecto se despliega a un server 24/7 con datos que se actualicen más
frecuentemente, el schedule puede activarse y esta convención se
revisita.

## Consecuencias

### Ganancias

- **Detección de reorder B2B funcional end-to-end**: el warehouse
  responde con precisión "¿qué clientes están atrasados según su patrón
  histórico?", con dos métricas complementarias (booleano operativo +
  probabilidad continua) que cubren tanto la necesidad de acción como
  la de análisis.
- **Validación cruzada como propiedad emergente**: los dos enfoques
  independientes coinciden en los 3 clientes de alerta rule-based con
  los 3 de mayor probabilidad probabilístico. Es evidencia analítica más
  fuerte que cualquiera de los dos enfoques aislado, y funciona como
  argumento defensivo en portfolio.
- **Divergencia informativa entre enfoques**: Cotta Cafe aparece con
  `alerta_reorder = FALSE` pero probabilidad 52%. Es el tipo de señal
  que el rule-based no puede capturar y donde el probabilístico agrega
  valor concreto. Justifica que las dos capas coexistan.
- **Columna `confianza_estimacion` que permite interpretar probabilidad
  con matiz**: el consumidor sabe que "90% con confianza BAJA" no es lo
  mismo que "8% con confianza ALTA". Traslada la incertidumbre
  estadística al consumidor de forma explícita en vez de esconderla.
- **Dashboard con dos audiencias claras**: la socia del negocio tiene un
  tab operativo sin jerga que le indica exactamente a quién llamar. El
  auditor técnico tiene un tab de análisis con toda la profundidad
  metodológica. Un solo dashboard, dos consumos.
- **Cierre de dos deudas de semana 9**: extracción del modelo
  probabilístico del notebook a `ingestion/b2b_reorder.py` como módulo
  dedicado, y agregado de `scipy` como dependencia del container Dagster.
- **Incorporación de `dbt_utils` como infra estándar del proyecto**:
  habilita tests `accepted_range` y otras utilidades reutilizables en
  W12 y futuras extensiones.
- **27 tests pytest + 23 tests dbt en verde**: cobertura amplia entre
  funciones puras, orquestadores, integridad de marts y accepted_values
  de columnas categóricas.

### Costos

- **Complejidad de mantenimiento del modelo dual**: son dos artefactos
  paralelos que hay que mantener sincronizados conceptualmente. Cambios
  en `int_b2b_cadencia` afectan a los dos marts; cambios en la lógica
  probabilística requieren revisar si el rule-based sigue siendo
  coherente. El costo es aceptable para el tamaño actual del proyecto
  pero crecerá con extensiones futuras.
- **Sensibilidad de las estimaciones a la cantidad de pedidos**: los
  clientes con 4-5 pedidos tienen probabilidades muy volátiles semana a
  semana. La columna `confianza_estimacion` mitiga esto para el
  consumidor, pero no elimina la volatilidad subyacente. Si en el futuro
  entra un cliente B2B nuevo con historia muy corta, va a aparecer
  ruidoso en el dashboard hasta acumular datos.
- **Distribución Normal con sesgo teórico conocido**: para clientes con
  coeficiente de variación alto (sigma/mu grande), la Normal asigna
  probabilidad no-nula a intervalos negativos, lo que carece de sentido
  físico. En la práctica no afecta la lectura del dashboard, pero es una
  imperfección teórica que puede requerir migración a lognormal si en
  operación real aparecen problemas de calibración.
- **Umbrales estáticos hasta que haya evidencia operativa**:
  `umbral_alerta_desvios_b2b = 1.0` y los cortes de confianza (4/6/10)
  son puntos de partida razonables pero no están calibrados contra data
  real. Requieren 6-8 semanas de uso operativo para tunear con
  evidencia.

### Deuda declarada

- **ADR de semana 10** (este documento).
- **Tuneo empírico de umbrales**: después de 6-8 semanas de uso real,
  reevaluar `umbral_alerta_desvios_b2b` y los cortes de
  `confianza_estimacion` con evidencia. Llevar registro semanal manual
  de aciertos y fallos para poder tomar la decisión con criterio.
- **Migración a distribución lognormal**: solo si en operación real
  aparecen problemas de calibración del modelo Normal actual. Cambio
  mecánicamente simple pero requiere validar mejora empírica antes de
  aplicarlo.
- **Mart de evaluación operativa** (`mart_alertas_evaluacion`,
  potencial): grano semanal, calcularía métricas del tipo "de las
  alertas emitidas la semana X, cuántas resultaron en reorder efectivo".
  Cierre del loop entre modelo, uso y ajuste. Fuera del scope de W10 y
  W12; potencial post-portfolio.
- **Portabilidad de dashboards Metabase**: los dashboards viven en el
  container Postgres de Metabase, no en git. Al clonar el repo en una
  máquina nueva, no están. Documentar en README el paso de recreación
  manual, o hacer export/import de dashboards Metabase.
- **Ampliación del enfoque probabilístico a B2C**: hoy solo se aplica a
  B2B por decisión de negocio (el reorder B2C es más impredecible por
  volumen y menos crítico operativamente). Si en el futuro el negocio
  quiere señales de retención B2C, el modelo puede ampliarse.
