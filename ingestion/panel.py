"""
Publishes pipeline results to the "MyM Pipeline" spreadsheet read by the panel.

The panel (github.com/SabaM10/waffles) never talks to this machine. The
pipeline writes a few small tabs to a spreadsheet of its own, and a tiny Apps
Script (serving/apps_script/lector_panel.gs) serves them as JSON. The
service account is Editor of THAT spreadsheet only and keeps read-only access
to VENTAS 2026, so a pipeline bug can never touch the orders.

The tab layout is a contract with the panel (src/semana.js over there).
Bump CONTRATO_VERSION on any breaking change to column names or meaning.

Decisions in docs/decisions/semana-13.md.
"""

from __future__ import annotations

import os
from datetime import date, datetime

import polars as pl

CONTRATO_VERSION = 1

# Panel stock keys have no freezer prefix: "dulces", "neutros_int", ...
# (see stockFisico / demandaGlobal in the panel's CLAUDE.md).
_SABOR_A_CLAVE = {"Dulce": "dulces", "Salado": "salados", "Neutro": "neutros", "Oreo": "oreos"}
_MASA_A_SUFIJO = {"Clásica": "", "Integral": "_int", "Proteica": "_prot"}


def clave_stock(masa: str, sabor: str) -> str:
    """Maps a (masa, sabor) SKU to the panel's stock key."""
    if masa not in _MASA_A_SUFIJO or sabor not in _SABOR_A_CLAVE:
        raise ValueError(f"SKU desconocido para el panel: {masa} / {sabor}")
    return _SABOR_A_CLAVE[sabor] + _MASA_A_SUFIJO[masa]


def preparar_forecast_sku(forecast: pl.DataFrame) -> pl.DataFrame:
    """Adds clave_stock and rounds to whole units (nobody bakes 0.4 waffles).

    The upper band is rounded UP: it is the "to be safe" number.
    """
    return forecast.select(
        pl.struct(["masa", "sabor"])
        .map_elements(lambda r: clave_stock(r["masa"], r["sabor"]), return_dtype=pl.Utf8)
        .alias("clave_stock"),
        "masa",
        "sabor",
        "semana_predicha",
        pl.col("prediccion_central").round(0).cast(pl.Int64).alias("prediccion"),
        pl.col("banda_inferior").floor().cast(pl.Int64).alias("banda_inferior"),
        pl.col("banda_superior").ceil().cast(pl.Int64).alias("banda_superior"),
        pl.col("mae_backtest").round(1),
        pl.col("mae_naive").round(1),
        "unidades_ultimas_4",
    ).sort("clave_stock")


def preparar_forecast_total(forecast: pl.DataFrame) -> pl.DataFrame:
    """Total forecast (one row), rounded like the per-SKU one."""
    return forecast.select(
        "semana_predicha",
        pl.col("prediccion_central").round(0).cast(pl.Int64).alias("prediccion"),
        pl.col("banda_inferior").clip(lower_bound=0).floor().cast(pl.Int64).alias("banda_inferior"),
        pl.col("banda_superior").clip(lower_bound=0).ceil().cast(pl.Int64).alias("banda_superior"),
        pl.col("mae_backtest").round(1),
        "nivel_confianza",
    )


def preparar_clientes(clientes: pl.DataFrame) -> pl.DataFrame:
    """Customers table for the panel, most urgent first.

    Order: atrasado (by ratio_atraso desc), then le_toca (by expected date),
    then al_dia. cliente_id is dropped: the panel has no use for it.
    """
    orden_estado = {"atrasado": 0, "le_toca": 1, "al_dia": 2}
    return (
        clientes.with_columns(
            pl.col("estado_semana").replace_strict(orden_estado, return_dtype=pl.Int64).alias("_o")
        )
        .with_columns(
            pl.when(pl.col("estado_semana") == "atrasado")
            .then(-pl.col("ratio_atraso"))
            .otherwise(None)
            .alias("_r")
        )
        .sort(["_o", "_r", "fecha_proximo_esperado", "cliente_canonico"], nulls_last=True)
        .select(
            pl.col("cliente_canonico").alias("cliente"),
            "estado_semana",
            "fecha_ultimo_pedido",
            "fecha_proximo_esperado",
            pl.col("intervalo_promedio_dias").round(0).cast(pl.Int64).alias("cada_dias"),
            pl.col("dias_desde_ultimo_pedido").alias("dias_sin_pedir"),
            pl.col("probabilidad_reorder_ya").round(2).alias("probabilidad"),
            "confianza_estimacion",
            pl.col("unidades_promedio").round(0).cast(pl.Int64).alias("unidades_promedio"),
            pl.col("masa_habitual"),
            pl.col("sabor_habitual"),
        )
    )


def preparar_meta(generado: datetime, semana_predicha: date) -> pl.DataFrame:
    """One-row tab the panel reads first: when and for which week."""
    return pl.DataFrame({
        "contrato_version": [CONTRATO_VERSION],
        "generado": [generado.isoformat(timespec="seconds")],
        "semana_predicha": [semana_predicha],
    })


def _celda(valor):
    """A JSON-safe cell for the Sheets API."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:  # NaN
        return ""
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def dataframe_a_filas(df: pl.DataFrame) -> list[list]:
    """Header row plus data rows. Dates go as ISO text, never as Sheets dates,
    so the Apps Script reads exactly what was written."""
    return [df.columns] + [[_celda(v) for v in fila] for fila in df.iter_rows()]


def publicar_pestanas(client, spreadsheet_id: str, pestanas: dict[str, pl.DataFrame]) -> None:
    """Full refresh of each tab: clear and rewrite.

    Tabs are written in dict order; put `meta` last, so a panel that reads
    while this runs sees the previous meta until the data is in place.
    """
    hoja = client.open_by_key(spreadsheet_id)
    existentes = {ws.title: ws for ws in hoja.worksheets()}
    for nombre, df in pestanas.items():
        filas = dataframe_a_filas(df)
        ws = existentes.get(nombre)
        if ws is None:
            ws = hoja.add_worksheet(title=nombre, rows=len(filas) + 10, cols=len(df.columns) + 2)
        ws.clear()
        # RAW: no locale parsing, "2026-10-19" stays text and 0.5 stays 0.5.
        ws.update(filas, "A1", value_input_option="RAW")


def get_panel_spreadsheet_id() -> str:
    """Reads GSHEETS_PANEL_ID. Only the publishing asset needs it."""
    spreadsheet_id = os.getenv("GSHEETS_PANEL_ID")
    if not spreadsheet_id:
        raise ValueError(
            "Falta la variable GSHEETS_PANEL_ID en .env (la planilla 'MyM Pipeline'). "
            "Ver docs/decisions/semana-13.md."
        )
    return spreadsheet_id
