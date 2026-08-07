# CLAUDE.md

Instrucciones para Claude Code al trabajar en este repo.

## Contexto del proyecto

Plataforma de datos personal + productiva para **MyM Waffles**, negocio familiar de waffles congelados en AMBA (Argentina). B2C + B2B mayorista con 10-15 clientes B2B activos.

Doble propósito:
1. Aprender data engineering con casos reales.
2. Detectar patrones en B2B que a ojo se pierden.

Objetivo de carrera del dueño del repo: Analista de Sistemas / IT Audit junior. Priorizar decisiones que demuestren trazabilidad, tests, y documentación (relevante para audit).

## Stack (decisiones ya tomadas — no re-litigar)

- Python 3.11+ con `uv` para deps
- Polars (no pandas) para procesamiento
- DuckDB como warehouse local (un archivo `.duckdb`)
- dbt-core con adapter duckdb
- Dagster para orquestación (con `dagster-dbt`)
- Metabase para dashboards
- Docker Compose para todo
- Ruff como linter + formatter

No sugerir alternativas cloud (BigQuery, Snowflake, Airflow gestionado, etc.) sin pedir permiso: el proyecto es explícitamente free tier / local.

No sugerir pandas: la elección de Polars es deliberada (performance + valor de aprendizaje).

No sugerir Great Expectations: los tests nativos de dbt alcanzan para el volumen actual.

## Convenciones

**Naming:** snake_case en todo. Español para conceptos de negocio (cliente, pedido, seña, entrega, masa, sabor, tarifa). Inglés para artefactos técnicos (staging, fact, dim, incremental, bridge). Prefijos dbt: `stg_`, `int_`, `dim_`, `fact_`, `rpt_`, `bridge_`.

**Comentarios de código:** español en modelos SQL (dominio de negocio), inglés en Python (convención de la comunidad).

**Commits:** conventional commits en inglés, mensajes cortos. Ej: `feat(dbt): add dim_fecha with feriados AR`, `fix(ingestion): handle empty tabs in VENTAS 2026`.

**Docs:** enfocadas en decisiones y contexto, no en tutoriales de herramientas. Si algo se explica en el manual oficial, linkearlo, no reescribirlo.

## Modelo de dominio

**Producto físico** (`dim_producto`, grain: 1 fila por SKU vendible):
- 3 masas: Clásica, Integral, Proteica.
- 4 sabores posibles: Dulce, Salado, Neutro, Oreo.
- Solo 8 combinaciones válidas:
  - Clásica × {Dulce, Salado, Neutro, Oreo} = 4
  - Integral × {Dulce, Salado, Neutro} = 3 (no hay Oreo Integral)
  - Proteica × {Dulce} = 1

**Rate card** (`dim_tarifa`, SCD2): el pricing no es por SKU sino por (segmento × tipo_oferta × es_oreo × unidades_pack). Ver `docs/pricing.md`.

- 4 segmentos: Minorista, Promo, Mayorista, Proteico.
- Dentro de Clásicos e Integrales, todos los sabores comparten precio (excepto Oreo, que tiene precio propio).
- Mayorista solo aplica a Clásicos e Integrales (Proteicos negociado; Promos hasta x24).
- Mayorista es siempre por UNA masa y UN sabor (no mezcla).
- Promos son intra-masa (no se mezclan masas).
- Pedidos mayoristas > 96 unidades: precio unitario del pack 96 × cantidad.
- Pedidos mayoristas no-exactos (entre packs): precio unitario del pack **inmediatamente inferior** × cantidad, con ajuste manual "a ojo" cuando se acerca al próximo pack.

## Grain de facts (crítico, no olvidar)

- `fact_pedidos`: 1 fila por pedido.
- `fact_pedido_items`: 1 fila por (pedido × masa × sabor). Sin precio a este nivel.
- `bridge_pedido_tarifa`: 1 fila por (pedido × tarifa aplicada). El precio vive acá.

Un pedido puede aplicar múltiples tarifas (ej: minorista + promo). Los pedidos negociados (proteico mayorista, etc.) tienen `es_pedido_negociado = true` y no reconcilian contra la rate card.

## Fuente de datos

Google Sheets escritas por una app JS/React + Google Apps Script. **Fuente única de verdad, no cargar manualmente en paralelo.**

- **Sheet de pedidos** ("VENTAS 2026"): una pestaña por mes (formato `MES 2026` en mayúsculas). Pipeline itera todas las que matchean regex. La pestaña `HISTORIAL_BALANCES` se ignora.
- **Sheet de precios**: rate card actual en pestaña `VIGENTES`.
- El campo `PRECIO` del pedido lo tipea alguien a mano en la app. La rate card es referencia pero no source of truth transaccional. Las diferencias entre `precio_sheet` y `precio_calculado` son descuentos manuales legítimos.
- Datos 2026: confiables. 2024-2025: requieren backfill separado con parsing tolerante (semana 11).

## Datos sensibles / PII

Nombres de clientes B2B son PII del negocio. **No incluir datos reales en:**
- Tests unitarios
- Seeds públicos
- Ejemplos en docs
- Screenshots o outputs commiteados

Usar fixtures anonimizados. El archivo `dbt_project/seeds/client_name_mapping.csv` está gitignored. Existe `client_name_mapping.example.csv` con datos ficticios que sí va al repo.

Credenciales de Google Service Account: nunca en el repo. Solo en `secrets/credentials.json` local (gitignored).

## Cómo correr localmente

```bash
# Levantar servicios
docker compose up -d

# Correr tests de Python
docker compose exec dagster pytest tests/

# Correr tests de dbt
docker compose exec dagster dbt test --project-dir dbt_project

# Materializar todos los assets
docker compose exec dagster dagster asset materialize --select "*"

# Formatear código
docker compose exec dagster ruff format .
docker compose exec dagster ruff check --fix .
```

## Estilo de colaboración esperado

- Cuando haya trade-offs reales, explicarlos antes de decidir por mí.
- Preguntar antes de agregar dependencias nuevas.
- Preguntar antes de crear archivos que no pedí.
- Si algo del modelo de negocio no está claro, preguntar en vez de inventar.
- Preferir soluciones aburridas y verificables sobre novedosas.
- No usar emojis en código, docs, ni commits salvo pedido explícito.
- No usar bullet points ni bold excesivo cuando la prosa alcanza.
- Español rioplatense (voseo) en explicaciones, sin ser forzado.

## Fuera de scope actual

- Análisis de gastos y márgenes (deuda declarada, alimentada por CSV de costos de proteicos + estructura similar futura).
- Aging de cobranzas.
- ML de forecast (semana 9 usa estadística clásica: media móvil o Holt-Winters).
- Backfill 2024-2025 (semana 11 con estrategia definida en `docs/backfill.md`).

Si aparecen ideas en estas áreas, anotarlas como "future work" en `docs/roadmap.md`, no implementarlas.

## Tests dbt críticos (los que atrapan bugs de negocio)

1. `dim_producto`: combinación (masa, sabor) tiene que estar en el catálogo de 8 SKUs válidos.
2. `dim_tarifa`: si `es_oreo = true` → `'Clásica' IN aplica_a_masas`.
3. `dim_tarifa`: si `segmento = 'Proteico'` → `aplica_a_masas = ['Proteica']`.
4. `dim_tarifa`: para cualquier fecha, cada (segmento, tipo_oferta, es_oreo, unidades_pack) tiene exactamente una tarifa vigente (validación SCD2).
5. `fact_pedidos`: si `es_pedido_negociado = false` → `precio_total_calculado IS NOT NULL`.
6. `bridge_pedido_tarifa`: `Σ (cantidad × unidades_pack)` = `fact_pedido_items.cantidad` total del pedido.

## Rate card inicial (referencia rápida)

Ver `docs/pricing.md` para la seed completa (32 filas). Resumen:

| Segmento | Aplica a | Packs |
|---|---|---|
| Minorista sabor único | Clásicos + Integrales (no-Oreo) | 8, 12, 16, 24 |
| Minorista sabor único Oreo | Clásicos Oreo | 8, 12, 16, 24 |
| Promo 2 sabores | Clásicos + Integrales, intra-masa | 8, 12, 16, 24 |
| Promo 3 sabores | Clásicos + Integrales, intra-masa | 9, 12, 16, 24 |
| Mayorista mix libre | Clásicos + Integrales (no-Oreo), 1 masa 1 sabor | 32, 48, 64, 80, 96 |
| Mayorista Oreo | Clásicos Oreo | 32, 48, 64, 80, 96 |
| Proteico sabor único | Proteica Dulce | 8, 16, 24, 32 |

## Referencias

- `docs/roadmap.md` — plan semanal.
- `docs/modelo.md` — modelo dimensional detallado.
- `docs/pricing.md` — rate card y lógica de aplicación de tarifas.
- `docs/backfill.md` — estrategia para 2024-2025.
- `docs/arquitectura.md` — diagrama y flujos de datos.
