"""
Assets de ingesta raw.

Cada asset representa una tabla en el schema raw de DuckDB.
Se materializa ejecutando la ingesta desde Sheets y escribiendo a DuckDB.
"""

import polars as pl
from dagster import asset

from ingestion.pedidos import ingest_pedidos
from ingestion.precios import ingest_precios
from ingestion.duckdb_writer import write_dataframe_to_duckdb


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