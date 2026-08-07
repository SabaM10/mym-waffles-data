# Roadmap — 12 semanas

Un módulo por semana. La marca "listo" es el estado al cierre de la semana, no el estado en que se arranca.

Estimación: 6-10 horas por semana. Ajustable.

---

## Semana 1 — Setup e infraestructura base

**Entregable:** `docker compose up` levanta el esqueleto sin explotar.

- Repo en GitHub con estructura de carpetas.
- `pyproject.toml` con deps declaradas.
- `Dockerfile` + `docker-compose.yml` funcionales.
- Service account de Google Cloud creado, `credentials.json` descargado y ubicado en `secrets/`.
- Sheet de pedidos compartida con el service account.
- `.env` completo con IDs reales.
- `README.md` y `CLAUDE.md` con contexto del proyecto.
- `.gitignore` protegiendo credenciales y datos.
- Placeholder de Dagster que arranca en `localhost:3000` con workspace vacío.
- Metabase levantando en `localhost:3001`.

## Semana 2 — Ingesta raw

**Entregable:** tabla `raw.pedidos` en DuckDB con datos 2026 completos.

- Cliente de gspread configurado, autenticando OK contra Sheets.
- Función que lista pestañas de "VENTAS 2026" y filtra las que matchean el regex.
- Lector que concatena todas las pestañas mensuales en un solo Polars DataFrame.
- Escritura a `raw.pedidos` en DuckDB (full refresh, no incremental todavía).
- Segunda ingesta análoga para `raw.precios`.
- Primer asset Dagster (`raw_pedidos`, `raw_precios`) materializable desde la UI.
- Test con pytest: dado un mock de gspread, el pipeline devuelve el DataFrame esperado.

## Semana 3 — Parsing y normalización

**Entregable:** notebook o script que muestra data parseada, limpia, y en formato tabular estricto.

- Parser del campo `PEDIDO` ("192 Neutros Clásicos + 96 Neutros Integrales") a lista de tuplas `(masa, sabor, cantidad)`.
- Validación contra el catálogo de 8 SKUs válidos. Combinaciones no válidas van a cuarentena.
- Función de normalización de nombres de cliente (lower, trim, remover puntuación, quitar acentos).
- Suite de tests unitarios (pytest) cubriendo casos borde: pedidos con un solo item, pedidos con typos, cantidades inválidas, pestañas vacías, nombres con y sin acentos.

## Semana 4 — dbt setup + staging

**Entregable:** `dbt run && dbt test` pasa en verde.

- Instalación de dbt-duckdb, `profiles.yml` configurado en el container.
- Modelos `stg_pedidos`, `stg_pedido_items` (con parsing SQL desde `raw`), `stg_precios`.
- Tests dbt básicos: `not_null` en PKs, `unique` en `pedido_id`.
- `dbt_project.yml` con la estructura de carpetas y variables.

## Semana 5 — Dimensiones y seeds

**Entregable:** `dim_cliente`, `dim_producto`, `dim_fecha` y `dim_tarifa` poblados y verificables a ojo.

- Seed `productos_catalogo.csv` con las 8 combinaciones válidas.
- Seed `client_name_mapping.csv` con los 10-15 B2B conocidos (gitignored; version pública anonimizada en `.example.csv`).
- Modelo `dim_fecha` generado con macro o seed.
- Modelo `dim_cliente` con dedup vía mapping.
- Modelo `dim_producto` con flags de masa y sabor.
- Modelo `dim_tarifa` (SCD2) poblado desde el sheet de precios.
- Tests dbt: catálogo válido, `es_oreo` solo con masa Clásica, integridad de SCD2.

## Semana 6 — Facts y primeras métricas

**Entregable:** `SELECT * FROM rpt_ventas_semanales` devuelve data razonable.

- `fact_pedidos` con reconciliación (`precio_total_sheet` vs `precio_total_calculado`).
- `fact_pedido_items` (grain: pedido × masa × sabor).
- `bridge_pedido_tarifa` con lógica de matching pedido → tarifa (esta es la parte compleja).
- Primer mart `rpt_ventas_semanales`.
- Tests dbt críticos: reconciliación de cantidades, integridad de FKs.

## Semana 7 — Dagster orquestación

**Entregable:** UI de Dagster mostrando el DAG completo, "Materialize all" funciona end-to-end.

- Assets Python (`raw_pedidos`, `raw_precios`) definidos como `@asset`.
- Modelos dbt integrados vía `dagster-dbt` como assets automáticos.
- Schedule diario configurado.
- Resources: conexión DuckDB, cliente gspread, config de dbt.
- Sensor opcional: detectar cambios en el sheet y disparar re-materialización.

## Semana 8 — Metabase dashboards

**Entregable:** dashboard "Ventas semanales" con 3-4 gráficos funcionales.

- Driver DuckDB de Metabase instalado y funcionando (o plan B: exportar marts a Postgres).
- Conexión Metabase → `.duckdb` estable.
- Dashboard "Ventas semanales": total por semana, top clientes, mix por masa, tendencia.
- Dashboard "Descuentos implícitos": diferencia entre `precio_sheet` y `precio_calculado` por cliente.

## Semana 9 — Forecast semanal

**Entregable:** dashboard con proyección de la próxima semana + banda de confianza.

- Asset Dagster que corre un modelo estadístico (media móvil o Holt-Winters con `statsmodels`).
- Escribe a `mart_forecast_semanal`.
- Métrica de accuracy calculada contra semanas anteriores (backtesting simple).
- Dashboard "Forecast vs actual".

## Semana 10 — Análisis B2B (caso 3, el dolor real)

**Entregable:** dashboard con clientes B2B ordenados por criticidad de reorder.

- Modelo `int_b2b_cadencia`: por cliente B2B, intervalo promedio entre pedidos, desvío estándar, días desde último pedido.
- Regla simple: `alerta_reorder = dias_desde_ultimo > intervalo_promedio + 1 desvío`.
- Dashboard "Alertas B2B" con tabla ordenada por criticidad.

## Semana 11 — Backfill 2024-2025

**Entregable:** histórico cargado con `data_source_version` marcado, dashboard con toggle histórico.

- Pipeline paralelo con parser lenient para el historial.
- Tabla `raw.pedidos_backfill` separada de `raw.pedidos`.
- Tabla `raw.pedidos_quarantine` para filas que no parsean.
- Reconstrucción de tarifas históricas por regla (inflación ~12.5% trimestral).
- Columna `data_source_version` en marts.
- Reconciliación contra totales conocidos del negocio.

## Semana 12 — Polish + portfolio

**Entregable:** repo público listo para linkear en CV.

- README con screenshots del dashboard.
- `dbt docs generate && dbt docs serve` funcionando.
- CI mínimo con GitHub Actions (opcional): dbt test en cada PR.
- Docs finales: `arquitectura.md`, `modelo.md`, `pricing.md`, `backfill.md` completos.
- Retro breve: qué se aprendió, qué falló, próximos pasos.
- Revisión de todos los commits del historial para asegurar que no hay PII expuesta.
- Repo cambiado a público.
