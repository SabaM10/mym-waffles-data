# Precios y reconciliación

Cómo se modelan los precios, cómo se resuelve qué tarifa aplica a cada item, y
cómo se detectan las discrepancias entre lo cobrado y lo que la lista dice.

Es la parte más sutil del proyecto: la que más bugs generó y la que más
aprendizajes dejó.

---

## 1. Estructura de la rate card

Los precios viven en una Google Sheet con formato humano-legible: headers
decorativos, sub-headers de sección, y valores en formato monetario argentino.
`ingestion/precios.py` la lee con un parser tolerante a ese formato.

Cada tarifa combina:

- **`producto_desc`** — la descripción comercial del producto.
- **`segmento`** — `MINORISTA`, `MAYORISTA` o `PROMO`.
- **`unidades_pack`** — el tamaño de pack al que aplica el precio.
- **`precio_unitario`** — el precio por unidad dentro de ese pack.

### Dos reglas de negocio que definen todo

**El cliente no influye en el precio.** B2C y B2B pagan lo mismo. El segmento no
se determina por tipo de cliente sino por qué tarifa matchea, y eso depende de la
cantidad pedida. Esto simplifica enormemente el modelo: no hay listas de precios
por cliente ni descuentos negociados formalizados.

**PROMO se aplica solo cuando el pedido lo indica explícitamente.** No se deduce
de la composición del pedido.

### Los nombres no son uniformes entre segmentos

El mismo producto físico aparece con descripciones distintas según el segmento.
Un sabor no-Oreo se llama de una forma en la rate card minorista y de otra,
agrupada, en la mayorista.

Esto generó un bug real: el matcher construía la descripción minorista sin mirar
la cantidad, y al buscar tarifas mayoristas no encontraba nada. El fallback
tomaba entonces una tarifa minorista de pack chico y calculaba precios erróneos.
El fix fue pasarle la cantidad a la función que arma la descripción, para que
devuelva el nombre correcto según segmento.

**Aprendizaje**: en un rediseño ideal se separaría la representación canónica del
producto (masa, sabor) de su descripción comercial por segmento. Hoy están
acopladas y esa asimetría requiere lógica específica.

---

## 2. Historia de precios: SCD Type 2

`dim_tarifa` implementa Slowly Changing Dimension Type 2. Cada tarifa tiene una
fila por período de vigencia con `valid_from` / `valid_to` y su propio
`tarifa_id`. Durante 2026 hubo tres versiones, correspondientes a dos aumentos.

### Por qué CSV histórico y no snapshots de dbt

Los snapshots de dbt capturan cambios **desde el momento en que empiezan a
correr**. No pueden reconstruir historia previa. Para reconciliar pedidos de enero
contra la tarifa vigente en enero hacía falta la historia completa del año, que
ningún snapshot iniciado en junio podía producir.

El CSV `precios_historicos.csv` se armó manualmente desde las planillas de cada
aumento. Está gitignored por contener costos comerciales; el repo incluye un
`.example.csv` con la estructura anonimizada.

**Deuda asumida**: cada aumento futuro requiere agregar filas a mano. Alternativa
a mediano plazo: migrar a snapshots ahora que la historia base ya está cargada.

**Fragilidad conocida**: los `tarifa_id` son hashes de campos que incluyen
`producto_desc` y `segmento`. Si alguien renombra un producto en el sheet de
precios, las versiones nuevas dejan de matchear con las históricas y se rompe la
trazabilidad SCD Type 2.

### El bug del corte de marzo

El CSV declaraba el fin del período pre-aumento el **31/03**. La verificación
contra el sheet mostró que el aumento se había aplicado desde el **25/03**: todos
los pedidos desde esa fecha ya cobraban precios nuevos.

Consecuencia: seis días de pedidos correctamente cobrados aparecían como
discrepancias, porque se reconciliaban contra la tarifa vieja. Falsos negativos
puros.

El fix fue un script one-off que corrigió las fechas de vigencia en las 26 tarifas
afectadas —52 ediciones— con backup previo del CSV. La coincidencia exacta subió
del 67% al 71,4%.

**Aprendizaje, y probablemente el más transferible del proyecto**: los cortes de
SCD Type 2 declarados a mano tienen que validarse contra la data transaccional
real. El CSV se había armado con una fecha "prolija" de fin de mes para simplificar
la carga. Ningún test automático podía detectar el desfasaje, porque el modelo era
internamente consistente — solo no coincidía con la realidad. Apareció como
discrepancias sin causa aparente en el dashboard, y se encontró auditando caso por
caso.

**Corolario**: puede haber otros cortes con el mismo problema que todavía no se
detectaron. La práctica correcta es reconciliar después de cada aumento, no
confiar en la fecha cargada.

### El corte de julio: excepciones que no se tapan

El corte de julio se verificó y está correcto. Pero se detectaron pedidos
posteriores al aumento facturados con precio viejo, por gentileza operativa.

Se decidió **no ajustar el CSV** para absorberlos. La regla queda establecida así:
las fechas de vigencia reflejan **las fechas oficiales del aumento**, no las de
aplicación efectiva pedido por pedido.

Ajustar el CSV para tapar estos casos eliminaría exactamente la señal que el
dashboard debe exponer. Aparecen como discrepancias chicas documentadas, y esa
información le sirve al negocio para decidir si acepta la práctica o la limita.

---

## 3. Algoritmo de matching

Para cada item del pedido `(masa, sabor, cantidad)`:

1. Buscar en `dim_tarifa` la fila donde el producto matchea, `unidades_pack`
   iguala la cantidad, y la vigencia contiene la fecha del pedido.
2. Si hay match exacto → esa tarifa.
3. Si no → tomar el pack inmediatamente inferior del mismo producto y vigencia.
   Precio = `precio_unitario × cantidad_real`.
4. Si la cantidad supera el pack máximo modelado → usar el precio unitario del
   pack mayor multiplicado por la cantidad.

### Por qué no hay tabla puente

Inicialmente se planeó un `bridge_pedido_tarifa` asumiendo una relación
muchos-a-muchos entre pedidos y tarifas. Al aclarar las reglas reales con el
dueño del negocio, la premisa se cayó: **cada item se resuelve independientemente
contra una única tarifa**. La relación es 1:1, no N:M.

Sin N:M no hace falta bridge: alcanza con una FK directa `tarifa_id` en
`fact_pedido_items`.

Es un caso donde la solución técnica se diseñó antes de entender bien la regla de
negocio. La conversación con el dueño simplificó el modelo, no lo complicó.

### Limitación del paso 4

La extrapolación del pack mayor es matemáticamente razonable pero comercialmente
falsa: un pedido muy por encima del pack máximo tiene precio negociado, no
`precio_unitario_del_pack_mayor × cantidad`. Esos pedidos quedan como no
reconciliables. Requiere decidir si se modelan packs jumbo o si se acepta la
limitación.

---

## 4. Reconciliación

### El reencuadre: no existen los descuentos implícitos

El roadmap original planteaba un dashboard de "descuentos implícitos": la
diferencia entre el precio del sheet y el calculado, interpretada como descuento.

**La premisa era incorrecta.** El negocio nunca cobra por debajo de la lista. Toda
discrepancia es, por definición, un error o data no modelada. No hay descuentos
que descubrir.

El entregable cambió de reporte comercial a **herramienta de detección de errores
de calidad de datos**. Las causas posibles de una discrepancia son:

- Error de carga humana en el sheet.
- Producto fuera del scope del modelo de pricing.
- Bug del pipeline (matching, SCD Type 2 con fechas incorrectas).
- Data histórica legítima pero mal estructurada.
- Descuento operativo por gentileza post-aumento.

El reencuadre fue más valioso que el dashboard original: una herramienta de
auditoría de datos es más útil para el negocio, y más pertinente para un perfil
de IT Audit, que un reporte de descuentos que no existen.

### Categorías de `rpt_reconciliacion_pedidos`

Una fila por pedido, clasificada en cuatro categorías:

| Categoría | Criterio |
|---|---|
| `COINCIDE` | Diferencia por debajo del umbral de coincidencia |
| `DISCREPANCIA_CHICA` | Entre ambos umbrales. Revisable, no crítica |
| `DISCREPANCIA_GRANDE` | Sobre el umbral alto. Requiere auditoría manual |
| `SIN_TARIFA_MODELADA` | Al menos un item sin `tarifa_id` |

**`SIN_TARIFA_MODELADA` tiene precedencia sobre las demás.** Si un pedido incluye
un producto fuera del modelo, cae en esa categoría aunque el resto cuadre: la
contaminación por items faltantes hace engañosa cualquier comparación numérica.

La distinción clave que aporta esta categoría es entre **"no puedo comparar"** y
**"puedo comparar y no coincide"**. Son problemas distintos y mezclarlos hace
ilegible el dashboard.

### Umbrales como variables dbt

`umbral_coincide_ars` y `umbral_discrepancia_grande_ars` se declaran en
`dbt_project.yml`, no hardcodeados en el SQL.

Son convenciones tentativas, no reglas del negocio: es esperable ajustarlos según
cómo se distribuya la data. Con variables se cambian editando el YAML o pasando
`--vars`, sin tocar SQL. Y al vivir en el proyecto quedan versionados y
auditables.

### Resultado

Al cierre del trabajo de reconciliación, la mayoría de los pedidos concilia exacto
y el resto está clasificado por causa. El salto más importante no vino de refinar
el algoritmo sino de **corregir el bug del corte de marzo**: nueve pedidos pasaron
de discrepancia grande a coincidencia con una corrección de fechas.

---

## 5. Deuda declarada

- **Flag de gentileza en el sheet.** Una columna que marque los descuentos
  operativos deliberados permitiría distinguirlos de los errores. Requiere cambiar
  la fuente y el pipeline de ingesta.
- **Auditoría sistemática de cortes.** Reconciliar después de cada aumento en
  lugar de confiar en la fecha cargada al CSV.
- **Packs jumbo.** Decidir si se modelan o si los pedidos que superan el pack
  máximo quedan formalmente como no reconciliables.
- **Test `not_null_where`.** Los campos de precio calculado son null por diseño en
  `SIN_TARIFA_MODELADA`, así que no pueden validarse con un `not_null` simple.
  Falta un test que los valide condicionalmente.
- **Migrar a snapshots.** Ahora que la historia base está cargada, los aumentos
  futuros podrían capturarse automáticamente en lugar de a mano.
- **Backfill histórico.** Si el CSV de tarifas para años anteriores se arma con
  fechas prolijas, va a repetir exactamente el bug de marzo. Cada corte tiene que
  validarse contra la data real antes de darlo por bueno.

---

## Referencias

- Modelo dimensional: `modelo.md`
- Stack y capas: `arquitectura.md`
- Decisiones semana a semana: `docs/decisions/`
