{% docs __overview__ %}

# MyM Waffles — Data Platform

Plataforma de datos para un negocio real de waffles congelados (B2C + B2B, AMBA).
Fuente: Google Sheets. Warehouse: DuckDB. Transformaciones: dbt. Orquestación: Dagster.

## Casos de uso

1. **Reporte semanal de ventas** — `rpt_ventas_semanales`
2. **Forecast estadístico** — `mart_forecast_semanal`, validado en `mart_forecast_backtest`
3. **Detección de reorder B2B** — `rpt_alertas_reorder_b2b` (reglas) y
   `mart_b2b_reorder_probabilistico` (Normal CDF sobre cadencia histórica)

## Convención de prefijos

| Prefijo | Capa | Qué es |
|---|---|---|
| `stg_` | staging | Tipado y limpieza 1:1 contra la fuente |
| `int_` | intermediate | Lógica intermedia, no se consume directo |
| `dim_` / `fact_` | marts | Modelo dimensional (Kimball) |
| `rpt_` | marts | Reportes basados en reglas de negocio |
| `mart_` | marts | Modelos Python con lógica estadística |

## Cómo leer el lineage

`raw` (Sheets) → `stg_*` → `int_*` → `dim_*` / `fact_*` → `rpt_*` / `mart_*`

Los marts se exportan a Postgres como capa de serving para Metabase.

{% enddocs %}   