# ADR Semana 9: Forecast semanal de unidades

## Contexto

El roadmap declaraba como entregable un dashboard con proyección de la
próxima semana más banda de confianza, respaldado por un asset Dagster
que corriera un modelo estadístico (media móvil o Holt-Winters) y un
mart `mart_forecast_semanal`. Al iniciar la semana quedó claro que el
contexto de la data imponía tres restricciones que definían todo lo
demás:

**1. Volumen escaso.** Al cierre de semana 8 el warehouse tenía 33
semanas de data 2026 (enero a agosto). Esto descarta de arranque los
modelos que requieren varios ciclos estacionales completos para
estimar parámetros: Holt-Winters con estacionalidad anual necesita
mínimo 2 años, ARIMA con parámetros ricos requiere series más largas
para estabilizar la estimación, y cualquier enfoque ML supervisado
sobre 33 puntos es sobreingeniería estadísticamente indefendible.

**2. Cambio de régimen detectado.** La media móvil de 4 semanas
superpuesta sobre la serie cruda reveló que la serie pasó de un nivel
promedio de ~880 unidades/semana (enero-marzo) a ~500 unidades/semana
(junio-agosto), con una transición entre fines de marzo y mediados de
junio. Investigación con el dueño del negocio confirmó dos causas: caída
de consumo B2C generalizada y pérdida de algunos clientes B2B. Es un
cambio estructural real, no un valle temporal. Cualquier modelo
entrenado con la serie completa sin considerar este quiebre va a
sobrepredecir sistemáticamente.

**3. Alta volatilidad semana a semana.** Aun dentro del régimen actual,
la serie oscila entre valles de ~200 y picos de ~1000 unidades. Esto
implica que la banda de confianza cualquiera sea el modelo elegido va a
ser ancha, y que hay que ser honestos sobre el ruido irreductible del
negocio.

Se decidió además ampliar el scope original de la semana para que el
trabajo sirva de puente hacia semana 10 (detección de anomalías de
reorder B2B). Concretamente, se exploró una descomposición de la serie
que aislara al cliente B2B más atípico (Cliente G), con la doble intención de
mejorar el forecast y adelantar la exploración de cadencia B2B.

## Decisiones

### Decisión 1: Sliding window fija de 8 semanas para el backtesting

El backtesting se hace con walk-forward validation, patrón estándar
para series temporales que evita data leakage al entrenar siempre solo
con data anterior al punto que se predice. Dentro del walk-forward había
que elegir entre expanding window (la ventana de entrenamiento crece a
cada paso, acumulando toda la historia) y sliding window (la ventana
tiene tamaño fijo, descarta las semanas más viejas cada vez que agrega
una nueva).

**Alternativa considerada**: expanding window desde el inicio de la
serie. Es lo que se enseña en la mayoría de los tutoriales por default.

**Por qué se rechazó**: expanding window asume proceso estable. Cuando
el proceso subyacente cambia (structural break confirmado en marzo), la
ventana expandida termina promediando régimen viejo con régimen nuevo.
Sliding window de tamaño fijo obliga al modelo a "olvidar" data vieja y
adaptarse al régimen local. En este proyecto, con quiebre confirmado y
posibilidad de nuevos quiebres futuros, sliding window es la elección
robusta.

Se eligió **ventana 8 semanas** como equilibrio entre suficiente
historia para promediar ruido semana a semana y suficiente adaptabilidad
para capturar el régimen actual. Con 33 semanas de data, la ventana 8
produce 25 predicciones evaluables en backtesting, cantidad razonable
para comparar modelos.

**Consecuencia**: si en producción aparece otro cambio de régimen, el
modelo se va a adaptar automáticamente en ~4-6 semanas. Los primeros
resultados post-cambio van a tener errores más altos hasta que la
ventana termine de "olvidar" el régimen anterior. Aceptable dado que la
alternativa (reentrenamiento manual) requiere intervención humana.

### Decisión 2: Modelos parsimoniosos (naive, SMA-4, EWMA), no ARIMA ni ML

Se probaron tres modelos, todos con la misma firma
(`serie_historica -> float`) para permitir un backtesting genérico:

- **Naive**: predicción = último valor observado. Baseline obligatorio.
- **SMA-4**: predicción = promedio de las últimas 4 semanas. Suaviza
  ruido individual.
- **EWMA (alpha=0.5)**: predicción = promedio ponderado exponencial con
  más peso a las semanas recientes.

**Alternativas consideradas y descartadas**:

- **Holt lineal (nivel + tendencia)**: con 33 semanas y régimen
  cambiante, la estimación de tendencia iba a ser muy inestable, viendo
  tendencias donde solo hay ruido.
- **Holt-Winters con estacionalidad**: requiere 2+ ciclos estacionales
  completos. Con estacionalidad anual (52 semanas) es imposible. Se
  consideró estacionalidad mensual (4 semanas, ~8 ciclos disponibles)
  pero la señal iba a ser débil y contaminada por el ruido de "semana
  del mes" desalineada con semanas ISO.
- **ARIMA**: necesita más data para estabilizar la estimación de sus
  múltiples parámetros. Con este volumen los coeficientes serían muy
  inciertos.
- **Modelos ML (Prophet, XGBoost, LSTM)**: sobreingeniería absoluta con
  33 puntos. Estadísticamente indefendible; en portfolio se lee como
  desconocimiento del principio de parsimonia.

**Regla explícita adoptada**: cualquier modelo más complejo que naive
debe ganarle por margen sustancial en MAE (no solo marginal) para
justificar su complejidad. Sin esto, gana la simpleza.

**Resultado en backtesting (25 predicciones, sliding window 8)**:

| Modelo | MAE | MAE mediano | Peor error |
|---|---|---|---|
| SMA-4 | 212 | 177 | 707 |
| EWMA (α=0.5) | 230.6 | 184.3 | 709.8 |
| Naive | 321.9 | 266.0 | 900.0 |

**Ganador: SMA-4**. Mejora del 34% sobre naive (mejora sustancial,
justifica la complejidad). Le gana al EWMA por margen chico pero
consistente (mejor MAE, mejor mediana y menor peor error). Se descartó
EWMA por no aportar ventaja proporcional a su parámetro adicional
(alpha), y porque en régimen relativamente estable el EWMA no logra
cobrar su capacidad de adaptación a cambios.

### Decisión 3: Backtesting sobre la serie completa, no solo régimen actual

Existían dos opciones para el backtesting:

**Alternativa A**: entrenar y evaluar solo con el régimen actual
(~13 semanas desde junio). Ventaja: representatividad exacta del proceso
que operará el modelo en producción. Desventaja: solo 5 predicciones
evaluables → poder estadístico prácticamente nulo para comparar modelos.

**Alternativa B (elegida)**: usar la serie completa (33 semanas) para
generar 25 predicciones evaluables, aceptando que las primeras
predicciones evalúan el modelo sobre un régimen distinto al operativo
actual.

**Justificación**: comparar tres modelos con 5 datos no permite decidir
nada con confianza estadística. Con 25 datos se pueden calcular MAE
promedio, MAE mediano, peor error, y ver patrones temporales de error.
La contaminación por régimen viejo se mitiga porque la sliding window
de 8 semanas obliga al modelo a "olvidar" data lejana rápido, y porque
el objetivo del backtesting es comparar modelos entre sí (todos
igualmente contaminados), no estimar accuracy absoluta esperada en
producción.

**Consecuencia declarada**: el MAE 212 reportado es una estimación
optimista de la accuracy esperada en producción, porque incluye
predicciones sobre el régimen alto donde había menos volatilidad
relativa. En operación real sobre régimen actual, la accuracy puede ser
peor. Corresponde reevaluar el MAE después de 8 semanas de operación en
producción.

### Decisión 4: Exploración descartada — descomposición serie base + modelo probabilístico de Cliente G

**Hipótesis inicial**: el cliente Cliente G (único con `pedido_mas_chico >=
300` en toda la cartera, promedio 440 unidades por pedido) generaba los
picos catastróficos que hacían fallar al modelo. Descomponer la serie en
"base sin Cliente G" + "modelo probabilístico de Cliente G" debería mejorar
sustancialmente el forecast, y además serviría como preparación conceptual
para semana 10.

**Implementación**:

- **Modelo Cliente G**: cadencia empírica de sus 5 pedidos históricos (media
  7.2 semanas, desvío 3.1). Probabilidad de reorder modelada con CDF de
  distribución normal centrada en la cadencia media. Contribución
  esperada al forecast = `probabilidad × tamaño_promedio (440)`.
- **Serie base**: unidades semanales excluyendo pedidos de Cliente G, con
  el mismo relleno de gaps (semana del 19/01 con cero por vacaciones).
- **Rebacktesting**: mismos tres modelos sobre la serie base.

**Resultado en backtesting sobre serie base**:

| Modelo | MAE | MAE mediano | Peor error |
|---|---|---|---|
| SMA-4 | 201.3 | 158.8 | 707.0 |
| EWMA (α=0.5) | 226.9 | 166.4 | 728.6 |
| Naive | 298.4 | 256.0 | 900.0 |

**Medición vs hipótesis**: el MAE mejoró solo 5% (212 → 201) y el peor
error no cambió (707 en ambos casos). Análisis de los 3 peores errores
confirmó que **NO coinciden con semanas de pedido de Cliente G**. Los picos
problemáticos (semanas 02/03 con 1172 unidades y 03/08 con 996) son
coincidencias de múltiples clientes B2B medianos concentrados en la
misma semana, no atribuibles a un solo outlier.

**Decisión final**: descartar la descomposición por falta de evidencia
numérica. Se revirtió a SMA-4 directo sobre la serie total. La
implementación se preservó en el notebook como documentación del proceso
analítico, no como código de producción.

**Aprendizaje transferido a semana 10**: el problema de detección de
anomalías B2B debe enfocarse en "semanas de alta concurrencia" más que
en outliers individuales. Un cliente solo (aunque haga pedidos grandes)
no explica los picos; la combinación de varios clientes medianos sí. Esto
cambia el diseño conceptual del detector de reorder que se va a construir
en semana 10.

**Aprendizaje metodológico transferible**: probar hipótesis con
medición explícita y estar dispuesto a descartarlas por evidencia es
más valioso que confirmar una hipótesis que "suena razonable". La
exploración fallida se documenta con el mismo rigor que la exitosa,
porque el aprendizaje sobre el negocio (los picos son multi-cliente, no
mono-cliente) es tan valioso como el modelo final.

### Decisión 5: Banda de confianza empírica, no paramétrica

Cualquier forecast serio comunica incertidumbre con una banda de
confianza. Dos formas de calcularla:

**Alternativa paramétrica**: asumir que los errores del modelo siguen
una distribución normal, calcular la banda como `y_hat ± z * sigma`
donde `z=1.96` para 95%. Es lo que devuelven la mayoría de las
librerías automáticamente. Ventaja: una línea de código. Desventaja:
depende de un supuesto (normalidad de residuos) que casi nunca se
cumple estrictamente en series reales.

**Alternativa empírica (elegida)**: calcular percentiles de los errores
reales del backtesting. La banda al 90% se define como
`y_hat + p5` (límite inferior) y `y_hat + p95` (límite superior). Sin
supuestos distribucionales, refleja exactamente cómo el modelo se
equivocó históricamente.

**Justificación de la elección**:

- Con 25 predicciones en backtesting hay suficiente data para calcular
  percentiles empíricos con estabilidad razonable.
- La distribución de errores del SMA-4 resultó marcadamente asimétrica
  (p5 = -303, p95 = +613), lo que la banda paramétrica hubiera ocultado
  al asumir simetría.
- Alineación con el espíritu del proyecto: decisiones defendibles con
  evidencia, no con supuestos convenientes.
- Vocabulario transferible a IT Audit: "intervalos de predicción
  empíricos" es un concepto real y auditable, no palabrería.

**Resultado**: banda 90% para la próxima semana = predicción ±
asimétrica hacia arriba. Sesgo del modelo casi cero (+8 unidades
promedio), lo que indica ausencia de tendencia sistemática a
sobreestimar o subestimar.

**Interpretación operativa de la asimetría**: la cola positiva (subestimación)
es aproximadamente 2x la negativa (sobreestimación). Traducción: cuando
el modelo se equivoca, es más frecuentemente porque no predice un pico
que porque predice un pico que no ocurre. Para MyM Waffles, que opera
con stock de seguridad como regla explícita del negocio, esto sugiere
que el límite superior de la banda es el número relevante para decisiones
de producción, no el central.

### Decisión 6: No filtrar semana en curso en el notebook, sí en producción

La semana del 17/08/2026 (última en la data) es semana en curso en
sentido estricto (hoy es viernes 21/08). Sin embargo, verificación con
el dueño del negocio confirmó que los tres pedidos B2B grandes de esa
semana ya fueron despachados y no se esperan más pedidos hasta la
semana siguiente. Es semana cerrada "de facto".

Se decidió **incluir esa semana en el notebook exploratorio** para no
perder información real, con verificación explícita del cierre operativo.

Se decidió **filtrar la semana en curso en el asset Dagster de
producción** con `WHERE fecha_emision < DATE_TRUNC('week', CURRENT_DATE)`,
por dos razones: (1) el asset va a correr en momentos donde no
necesariamente el dueño puede verificar el cierre operativo, y (2) es
más conservador matemáticamente asumir semana incompleta cuando hay
duda.

**Documentado como parte del ADR** para dejar claro que la asimetría
entre notebook y producción es intencional, no un descuido.

### Decisión 7: Relleno de gaps con cero, no imputación

La semana del 19/01/2026 no tiene pedidos en la data. Investigación
confirmó que fue cierre por vacaciones. El `GROUP BY` de la query no
genera fila para esa semana, produciendo un gap en la serie temporal
que rompería el walk-forward.

Se decidió rellenar con `unidades = 0`, no con imputación (media,
mediana, interpolación).

**Justificación**: el cero es la verdad del negocio. Imputar con la
media hubiera "mentido" con un valor sintético que ninguna semana real
tuvo. Aunque el 0 hace que el modelo aprenda "las vacaciones existen y
son parte del ruido natural", eso es información honesta que en el
futuro puede repetirse (Semana Santa, feriados largos). Un modelo
entrenado con la realidad va a manejar mejor futuros casos similares
que uno entrenado con datos sintéticos.

## Consecuencias

### Ganancias

- **Forecast funcional end-to-end en notebook exploratorio**: predicción
  central + banda de confianza empírica + backtesting cuantificado. Base
  metodológica lista para extraer a código productivo.
- **Modelo defendible con criterio explícito**: cada decisión (ventana,
  modelo, backtesting, banda) está justificada con alternativas
  consideradas y descartadas por razones explícitas. Auditable línea por
  línea.
- **Aprendizaje transferido a semana 10**: la exploración de Cliente G, aunque
  descartada como componente del forecast, reveló que los picos son
  fenómenos multi-cliente. Semana 10 arranca con el enfoque correcto
  desde el diseño, no descubriéndolo a mitad de camino.
- **Notebook completo como artefacto de portfolio**: incluye la
  exploración fallida (descomposición) documentada como aprendizaje.
  Muestra proceso de trabajo real, no historia editada para verse
  perfecta.
- **Vocabulario técnico consolidado**: walk-forward validation, sliding
  vs expanding window, banda empírica vs paramétrica, sesgo del modelo,
  structural break, concept drift. Todos conceptos aplicados con
  criterio, no citados. Transferibles directamente a preguntas de
  entrevista para IT Audit.
- **Serie limpia y reproducible**: gaps de vacaciones rellenados
  explícitamente, decisión de filtrado documentada, sesgo temporal
  eliminado. Cualquiera que reejecute el notebook obtiene los mismos
  resultados.

### Costos

- **Banda de confianza ancha (~916 unidades) refleja incertidumbre
  real**: la accuracy del forecast está limitada por el volumen y
  volatilidad de la data, no por la elección del modelo. Ningún modelo
  más complejo hubiera producido banda sustancialmente más estrecha con
  este volumen. Es honesto pero puede ser difícil de comunicar a
  stakeholders que esperan predicciones "precisas".
- **MAE reportado (212) es optimista para el régimen actual**: como el
  backtesting usa las 33 semanas, incluye predicciones sobre el régimen
  alto pre-marzo donde había más señal. En operación real sobre régimen
  actual, la accuracy puede ser peor. Requiere reevaluación después de
  8 semanas de operación en producción.
- **Modelo simple no captura picos coincidentes**: la limitación
  estructural del SMA-4 es aplanar picos aislados. Este defecto es
  inherente a la familia de medias móviles y no se puede resolver
  ajustando parámetros. Se acepta como precio de la simplicidad, con la
  banda superior amplia capturando estadísticamente el riesgo.
- **Exploración de descomposición consumió tiempo sin pagar en el
  resultado**: aproximadamente 30-40% del tiempo de trabajo de la
  semana. En retrospectiva, el aprendizaje justifica la inversión
  (aprendizaje sobre negocio + preparación semana 10), pero
  operativamente reduce el tiempo disponible para producción.

### Deuda declarada

- **Extracción del modelo a código productivo**: pendiente para el
  cierre operativo de la semana. Incluye `ingestion/forecast.py` con
  las funciones limpias, asset Dagster que corre el modelo, mart dbt
  `mart_forecast_semanal` y opcionalmente `mart_forecast_backtest`,
  tests dbt básicos.
- **Dashboard Metabase "Forecast vs Actual"**: pendiente. Requiere el
  mart existente. Diseño conceptual: eje temporal, serie real,
  predicción, banda 90% sombreada.
- **Reevaluar MAE después de 8 semanas de operación**: el número
  reportado es optimista por incluir régimen viejo en el backtesting.
  Corresponde recalcular sobre solo las últimas 8-13 semanas cuando la
  data en producción lo permita.
- **Investigar picos multi-cliente**: las semanas 02/03 (1172) y 03/08
  (996) tuvieron alta concurrencia B2B sin Cliente G. Identificar qué
  combinación de clientes las generó → alimenta directamente semana 10.
- **Discrepancia de schema entre Metabase (`serving`) y Python
  (`marts`)**: detectada durante la sesión. No bloqueó el trabajo pero
  sugiere que hay dos archivos `.duckdb` o algún tema de mount de
  Docker. Investigar cuando cierre semana 9.
- **Reevaluar vigencia del régimen actual periódicamente**: la decisión
  de usar sliding window 8 asume que el régimen actual es
  representativo. Si el negocio entra en nuevo régimen (crecimiento por
  cliente nuevo, pérdida importante), el forecast va a arrastrar el
  régimen viejo por 6-8 semanas hasta adaptarse. Corresponde monitorear
  con seguimiento visual en el dashboard.
- **Sesgo asimétrico del modelo**: subestima picos más que sobreestima
  valles (p95 = +613 vs p5 = -303). Si en el futuro se justifica agregar
  complejidad, el foco debe estar en capturar picos, no en refinar
  predicción central.
- **Modelo probabilístico de reorder de Cliente G preservado en notebook,
  NO extraído a producción**: la implementación (CDF normal sobre
  cadencia empírica) quedó en el notebook
  `notebooks/forecast_exploration.ipynb` como código de referencia. Al
  arrancar semana 10 (detección de anomalías B2B), corresponde extraer
  la lógica a `ingestion/b2b_reorder.py` como módulo dedicado, y
  agregar `scipy` como dependencia del container Dagster (hoy no está
  instalada porque `forecast.py` no la usa). No se incluyó en
  `ingestion/forecast.py` de semana 9 para mantener separación de
  concerns entre forecast general y detección de reorder B2B, que son
  problemas conceptualmente distintos aunque compartan matemática.
- **Filtrado de semana en curso solo en producción, no en notebook**:
  intencional, pero requiere que el asset Dagster de producción
  incluya el filtro explícitamente. No confiar en que la lógica del
  notebook sea reutilizable tal cual.
