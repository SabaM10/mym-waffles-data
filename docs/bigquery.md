# Export a BigQuery (opcional)

Capa de serving adicional: los marts de DuckDB se copian a un dataset de BigQuery. Es un laboratorio para practicar el equivalente cloud del flujo local; no reemplaza a DuckDB ni a Postgres. Las transformaciones siguen corriendo en dbt sobre DuckDB.

## Decisiones

- Carga por batch load job desde Parquet (`WRITE_TRUNCATE`): gratis, funciona en el sandbox y mantiene el full refresh del resto del proyecto. Sin streaming ni DML.
- Sin pandas: Polars escribe el Parquet directo.
- Los nombres de cliente se pseudonimizan antes de salir de la máquina (sha256 truncado). Es pseudonimización, no anonimización fuerte. `--no-anonymize` la desactiva.
- `dim_tarifa` (costos y márgenes) no se exporta.
- Los nombres de columna se normalizan: `año` pasa a `ano`, `seña_ars` a `sena_ars`.
- Service account propia, separada de la de Sheets, con `roles/bigquery.jobUser` y `roles/bigquery.dataEditor`.

## Cómo correrlo

1. Crear un proyecto en GCP y una service account con los dos roles. Bajar la key a `secrets/bigquery_credentials.json` (gitignored).
2. Completar `BQ_*` en `.env` (ver `.env.example`).
3. `uv pip install -e ".[gcp]"`
4. `python -m scripts.export_marts_to_bigquery --dry-run` (no usa credenciales).
5. `python -m scripts.export_marts_to_bigquery` (imprime filas origen vs. BigQuery por tabla).
6. Probar `docs/bigquery_queries.sql` en la consola de BigQuery.

Sandbox sin facturación: las tablas vencen a los 60 días. Si los load jobs funcionan con service account sin billing no está documentado; hay que probarlo.

## Qué cambia si se porta dbt a BigQuery

`dbt-bigquery` no reemplaza al adapter actual de forma gratuita. Diferencias conocidas del SQL: no existe `CONCAT_WS`; `MD5` devuelve BYTES (usar `TO_HEX`); `FILTER (WHERE ...)` se reescribe con `COUNTIF` o `SUM(IF())`; `DATE_TRUNC(d, WEEK(MONDAY))`; casteo seguro con `SAFE_CAST`. Los modelos Python de dbt (forecast, reorder) requieren Dataproc en BigQuery.

## Estado de verificación

Probado: tests unitarios con cliente mockeado, dry-run sobre un DuckDB de muestra, y las consultas de `bigquery_queries.sql` parseadas como BigQuery y ejecutadas (transpiladas) sobre datos de muestra. No probado: carga contra un proyecto BigQuery real.
