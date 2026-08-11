# ADR — Semana 2: Arquitectura de la capa de ingesta

Fecha: 2026-07 (semana 2 del roadmap)
Estado: Aceptado

## Contexto

Necesito diseñar el módulo de ingesta que va a leer datos desde Google Sheets y escribirlos a DuckDB en el schema `raw`. Las fuentes son dos hojas distintas: pedidos (una pestaña por mes, formato relativamente estándar) y precios (rate card en formato humano-legible con headers decorativos, sub-headers de sección, y valores en formato monetario argentino).

Tengo que decidir tres cosas antes de escribir código:

1. Cómo organizar los archivos dentro de `ingestion/`.
2. En qué momento del pipeline convertir los datos crudos a tipos correctos.
3. Cómo cargar los datos a la tabla cada vez que corre la ingesta.

Las tres decisiones se toman juntas porque afectan la robustez del pipeline y la separación de responsabilidades entre las capas raw/staging/marts.

---

## Decisión 1: Organización por dominio de datos

Cada fuente de datos tiene su propio módulo. Los módulos comparten solo lo que es genuinamente único en el sistema (autenticación, escritura a DuckDB, configuración).

```
ingestion/
├── __init__.py
├── sheets_auth.py      # Autenticación contra Google Sheets API
├── config.py           # Carga de variables de entorno
├── duckdb_writer.py    # Escritura genérica a DuckDB
├── pedidos.py          # Lector completo de pedidos
└── precios.py          # Lector completo de precios
```

### Alternativa considerada: organización por responsabilidad técnica

Un solo archivo `readers.py` con funciones para cada fuente, `writers.py` con las escrituras, `models.py` con los schemas. La lógica de cada fuente queda partida entre varios archivos según qué "hace".

### Por qué la rechacé

Las dos fuentes que tengo hoy (pedidos y precios) son muy distintas entre sí. El sheet de precios es un export humano-legible con headers decorativos y formato monetario ARS que no aplica a pedidos. Meter ambos lectores en un solo archivo hubiera generado un frankenstein con muchos casos especiales. Con organización por dominio, cada archivo cuenta la historia completa de una fuente, es leíble de arriba a abajo, y se puede modificar sin miedo a romper otra fuente.

Cuando en el futuro agregue gastos (fuera de scope inicial), va a ser `gastos.py` siguiendo el mismo patrón, sin tocar los otros dos.

### Consecuencias

- **Pro**: modularidad clara. Un desarrollador nuevo (o yo en 6 meses) sabe dónde buscar el código de cada fuente.
- **Pro**: escalabilidad por fuente. Agregar una nueva fuente es agregar un archivo, no modificar archivos existentes.
- **Contra**: si dos fuentes comparten lógica de parsing muy específica, hay que decidir explícitamente en qué archivo vive (o factorizar a un helper compartido). Todavía no me pasa, pero puede pasar.

---

## Decisión 2: Tipado tardío (todo VARCHAR en raw)

La capa `raw` guarda todos los campos como strings, tal cual llegan de la Sheet. El casting a tipos correctos (int, date, decimal) se hace en la capa dbt staging.

### Alternativa considerada: tipar en la ingesta Python

Convertir cantidades a int, precios a float, fechas a date en el momento de leer desde Sheets, antes de escribir a DuckDB.

### Por qué la rechacé

Mi intuición inicial era tipar temprano, siguiendo el principio general de "detectar errores lo antes posible". Pero en pipelines analíticos ese principio se aplica al revés que en desarrollo de aplicaciones.

La fuente son humanos tipeando en una Sheet. La data sucia no es una excepción, es la norma esperada. Si tipeamos en la ingesta y una celda tiene "48 unidades" en vez de "48", la ingesta entera se rompe y **ninguna fila se carga**, incluso las 199 filas que estaban bien. El warehouse queda desactualizado hasta que alguien corrija la fila mala.

Con tipado tardío, esa fila mala llega a raw sin problema como string. En dbt staging hay un test que valida que sea casteable a int; ese test falla puntualmente para esa fila, las otras 199 fluyen normal hacia los marts, y el dashboard sigue actualizado. La corrección se hace cuando se puede, sin bloquear el resto del pipeline.

También hay una ventaja de auditoría: raw queda como snapshot literal de lo que estaba en la Sheet en el momento de la ingesta. Si en 6 meses un auditor pregunta "¿qué llegó realmente el 15 de agosto?", puedo mostrárselo tal cual. Si hubiera tipado temprano, esa información histórica está perdida.

### Consecuencias

- **Pro**: pipeline resiliente a data sucia. Filas malas no bloquean filas buenas.
- **Pro**: raw es literal, auditable, y reproducible.
- **Pro**: separación clara de responsabilidades. Ingesta = leer y guardar. Staging = tipar y limpiar.
- **Contra**: los tests de calidad de datos viven en dbt, no en Python. Hay que confiar en que dbt corre y sus tests son revisados. En este proyecto es aceptable porque dbt corre en cada Dagster run.

---

## Decisión 3: Full refresh con columna técnica `ingested_at`

Cada corrida de la ingesta borra y recarga completamente las tablas de raw. Se agrega una columna técnica `ingested_at` con el timestamp UTC del momento de la corrida.

### Alternativa considerada: carga incremental

Detectar qué pestañas mensuales cambiaron desde la última corrida (por hash o timestamp) y solo recargar esas.

### Por qué la rechacé

El volumen no lo justifica. Con ~200 pedidos por mes y ~12 meses de datos, hablamos de ~2.400 filas. Google Sheets API las devuelve en 2-3 segundos. La complejidad de implementar detección de cambios (tracking de hashes o versiones, manejo de deletions, testing de edge cases) es órdenes de magnitud mayor al costo de leer todo de nuevo.

Es un caso claro de optimización prematura. Si algún día el volumen crece a niveles donde full refresh empieza a doler (probablemente nunca en este proyecto), se reevalúa.

Full refresh también es idempotente por definición: correr la ingesta dos veces seguidas produce exactamente el mismo estado. No hay que preocuparse por duplicados ni por orden de ejecución.

### Consecuencias

- **Pro**: simplicidad total. La lógica es "borrar todo, cargar todo".
- **Pro**: idempotencia natural. Es imposible ensuciar el warehouse re-corriendo.
- **Pro**: la columna `ingested_at` da trazabilidad de "cuándo se cargó cada snapshot" sin complicar el modelo.
- **Contra**: trabajo redundante en cada corrida. Aceptable dado el volumen.
- **Contra**: pierdo el historial de "cómo era raw ayer" cuando corro hoy. Si algún día importa, se implementa append-only con particiones por fecha. No es hoy.

---

## Cómo se ve el flujo end-to-end resultante

```
Google Sheets (VENTAS 2026, precios)
    ↓ [sheets_auth.py autentica]
    ↓ [pedidos.py lee las pestañas mensuales, concatena]
    ↓ [precios.py lee la rate card con parser tolerante]
    ↓ [duckdb_writer.py escribe con ingested_at]
DuckDB: raw.pedidos, raw.precios (todo VARCHAR)
    ↓ [dbt staging: tipa, limpia, valida]
DuckDB: staging.stg_pedidos, staging.stg_precios (tipos correctos)
    ↓ [dbt intermediate + marts: lógica de negocio]
DuckDB: marts (dims, facts, bridges)
```

## Referencias

- Modelo dimensional detallado: `docs/modelo.md` (pendiente semana 5).
- Rate card y estructura de precios: `docs/pricing.md` (pendiente semana 5).
- Roadmap general: `docs/roadmap.md`.
