"""
Assets de ingesta raw.

Cada asset representa una tabla en el schema raw de DuckDB.
Se materializa ejecutando la ingesta desde Sheets y escribiendo a DuckDB.
"""
import os

import polars as pl
import duckdb
from dagster import asset, AssetKey

from ingestion.pedidos import ingest_pedidos
from ingestion.precios import ingest_precios
from ingestion.duckdb_writer import write_dataframe_to_duckdb
from ingestion.postgres_writer import write_dataframe_to_postgres


@asset(key_prefix=["raw"], name="pedidos")
def raw_pedidos() -> pl.DataFrame:
    """
    Ingesta cruda de la Sheet 'VENTAS 2026'.
    Full refresh en cada corrida.
    """
    df = ingest_pedidos()
    write_dataframe_to_duckdb(df, "raw", "pedidos")
    return df


@asset(key_prefix=["raw"], name="precios")
def raw_precios() -> pl.DataFrame:
    """
    Ingesta cruda de la rate card (pestaña VIGENTES).
    Full refresh en cada corrida.
    """
    df = ingest_precios()
    write_dataframe_to_duckdb(df, "raw", "precios")
    return df                      

@asset(
    key_prefix=["serving"],
    name="marts_a_postgres",
    deps=[
        AssetKey(["marts", "rpt_reconciliacion_pedidos"]),
        AssetKey(["marts", "rpt_ventas_semanales"]),
        AssetKey(["marts", "mart_forecast_backtest"]),
        AssetKey(["marts", "mart_forecast_semanal"]),
    ],
)
def export_marts_a_postgres() -> None:
    """
    Exporta los marts rpt_* y mart_forecast_* de DuckDB al Postgres de serving.
    Full refresh de cada tabla en cada corrida.

    Metabase se conecta a este Postgres, no directo a DuckDB,
    para evitar problemas de locks y usar el driver oficial.
    Ver ADR semana 8, Decisión sobre plan B.
    """
    duckdb_path = os.environ["DUCKDB_PATH"]
    marts_a_exportar = [
        "rpt_reconciliacion_pedidos",
        "rpt_ventas_semanales",
        "fact_pedidos",
        "fact_pedido_items",
        "mart_forecast_backtest",
        "mart_forecast_semanal",
    ]

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        for mart in marts_a_exportar:
            df = con.sql(f"SELECT * FROM marts.{mart}").pl()
            write_dataframe_to_postgres(df, schema="serving", table=mart)
    finally:
        con.close()