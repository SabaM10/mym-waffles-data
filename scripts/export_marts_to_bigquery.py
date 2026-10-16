"""
Export DuckDB marts to a BigQuery dataset (full refresh per table).

Usage:
    python -m scripts.export_marts_to_bigquery --dry-run   # no credentials needed
    python -m scripts.export_marts_to_bigquery             # loads to BigQuery

Environment: DUCKDB_PATH, BQ_PROJECT, BQ_DATASET (default mym_serving),
BQ_LOCATION (default US), BQ_CREDENTIALS_PATH.

dim_tarifa (costs and margins) is deliberately not exported.
"""

from __future__ import annotations

import argparse
import os

import duckdb

from ingestion.bigquery_writer import prepare_for_bigquery, write_dataframe_to_bigquery

MARTS = [
    "rpt_ventas_semanales",
    "rpt_reconciliacion_pedidos",
    "fact_pedidos",
    "fact_pedido_items",
    "mart_forecast_backtest",
    "mart_forecast_semanal",
    "mart_forecast_semanal_sku",
    "rpt_alertas_reorder_b2b",
    "mart_b2b_reorder_probabilistico",
    "rpt_panel_clientes_semana",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="prepare data, do not call BigQuery")
    parser.add_argument(
        "--no-anonymize", action="store_true", help="send real client names (not recommended)"
    )
    args = parser.parse_args()

    duckdb_path = os.environ["DUCKDB_PATH"]
    dataset = os.getenv("BQ_DATASET", "mym_serving")
    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        for mart in MARTS:
            df = con.sql(f"SELECT * FROM marts.{mart}").pl()
            if args.dry_run:
                prepared = prepare_for_bigquery(df, anonymize=not args.no_anonymize)
                print(f"[dry-run] {dataset}.{mart}: {prepared.height} rows, {prepared.width} cols")
                continue
            loaded = write_dataframe_to_bigquery(df, dataset, mart, anonymize=not args.no_anonymize)
            status = "OK" if loaded == df.height else "MISMATCH"
            print(f"[{status}] {dataset}.{mart}: source {df.height} rows, BigQuery {loaded} rows")
    finally:
        con.close()


if __name__ == "__main__":
    main()
