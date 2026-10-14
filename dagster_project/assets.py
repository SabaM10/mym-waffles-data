"""
Assets de ingesta raw.

Cada asset representa una tabla en el schema raw de DuckDB.
Se materializa ejecutando la ingesta desde Sheets y escribiendo a DuckDB.
"""
import os

import duckdb
import polars as pl
from dagster import AssetKey, asset

from ingestion.duckdb_writer import write_dataframe_to_duckdb
from ingestion.panel import (
    get_panel_spreadsheet_id,
    preparar_clientes,
    preparar_forecast_sku,
    preparar_forecast_total,
    preparar_meta,
    publicar_pestanas,
)
from ingestion.pedidos import ingest_pedidos
from ingestion.postgres_writer import write_dataframe_to_postgres
from ingestion.precios import ingest_precios
from ingestion.sheets_auth import get_sheets_client


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
        AssetKey(["marts", "mart_forecast_semanal_sku"]),
        AssetKey(["marts", "rpt_panel_clientes_semana"]),
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
        "rpt_alertas_reorder_b2b",              # ← nuevo, W10
        "mart_b2b_reorder_probabilistico",      # ← nuevo, W10
        "mart_forecast_semanal_sku",            # W13
        "rpt_panel_clientes_semana",            # W13
        ]

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        for mart in marts_a_exportar:
            df = con.sql(f"SELECT * FROM marts.{mart}").pl()
            write_dataframe_to_postgres(df, schema="serving", table=mart)
    finally:
        con.close()


@asset(
    key_prefix=["serving"],
    name="publicar_panel",
    deps=[
        AssetKey(["marts", "mart_forecast_semanal"]),
        AssetKey(["marts", "mart_forecast_semanal_sku"]),
        AssetKey(["marts", "rpt_panel_clientes_semana"]),
    ],
)
def publicar_panel() -> None:
    """
    Publica el forecast y los clientes de la semana en la planilla
    'MyM Pipeline', que el panel lee a través de un Apps Script.

    Es una planilla aparte de VENTAS 2026: el service account es Editor sólo
    de esta. Full refresh de cada pestaña; `meta` se escribe al final.
    Ver ADR semana 13.
    """
    spreadsheet_id = get_panel_spreadsheet_id()
    duckdb_path = os.environ["DUCKDB_PATH"]

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        forecast_total = con.sql("SELECT * FROM marts.mart_forecast_semanal").pl()
        forecast_sku = con.sql("SELECT * FROM marts.mart_forecast_semanal_sku").pl()
        clientes = con.sql("SELECT * FROM marts.rpt_panel_clientes_semana").pl()
    finally:
        con.close()

    meta = preparar_meta(
        generado=forecast_sku["generated_at"].max(),
        semana_predicha=forecast_sku["semana_predicha"].max(),
    )

    publicar_pestanas(
        get_sheets_client(),
        spreadsheet_id,
        {
            "forecast_sku": preparar_forecast_sku(forecast_sku),
            "forecast_total": preparar_forecast_total(forecast_total),
            "clientes_semana": preparar_clientes(clientes),
            "meta": meta,
        },
    )
