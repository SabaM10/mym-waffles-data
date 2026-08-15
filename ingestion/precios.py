"""
Ingesta de la Sheet de precios (rate card).

Lee la pestaña 'VIGENTES' con schema canónico definido en PRECIOS_COLUMNS.
Filtra sub-headers decorativos y filas vacías.
"""

from datetime import datetime, timezone

import polars as pl

from ingestion.config import get_config
from ingestion.sheets_auth import get_sheets_client


# Fila donde están los headers reales dentro de la pestaña VIGENTES.
# Filas 0, 1, 2 son título/metadata/objetivo decorativos.
HEADERS_ROW_INDEX = 3

# Fila desde donde empiezan los datos (después de sub-header decorativo).
DATA_START_ROW_INDEX = 5

# Columnas canónicas de la rate card.
PRECIOS_COLUMNS = [
    "SEGMENTO",
    "PRODUCTO",
    "PACK",
    "PRECIO VENTA ($)",
    "COSTO PACK ($)",
    "MARGEN REAL",
    "vs OBJETIVO",
    "ALERTA",
]


def _read_precios_tab(spreadsheet, tab_name: str) -> pl.DataFrame:
    """
    Lee la pestaña de precios y devuelve un DataFrame con schema canónico.

    Descarta filas decorativas (título, metadata, sub-headers) y filas
    donde la columna PRODUCTO esté vacía.

    Args:
        spreadsheet: objeto Spreadsheet de gspread.
        tab_name: nombre de la pestaña, ej. "VIGENTES".

    Returns:
        DataFrame con las 8 columnas canónicas, todas como String.
    """

    worksheet = spreadsheet.worksheet(tab_name)
    values = worksheet.get_all_values()

    if len(values) < DATA_START_ROW_INDEX + 1:
        return pl.DataFrame()
    sheet_headers = values[HEADERS_ROW_INDEX]
    data_rows = values[DATA_START_ROW_INDEX:]
    column_indices = {}
    for canonical_col in PRECIOS_COLUMNS:
        if canonical_col in sheet_headers:
            column_indices[canonical_col] = sheet_headers.index(canonical_col)
        else:
            column_indices[canonical_col] = None

    aligned_rows = []
    for row in data_rows:
        aligned_row = []
        for canonical_col in PRECIOS_COLUMNS:
            idx = column_indices[canonical_col]
            if idx is None or idx >= len(row):
                aligned_row.append(None)
            else:
                aligned_row.append(row[idx])
        aligned_rows.append(aligned_row)
    producto_idx = PRECIOS_COLUMNS.index("PRODUCTO")
    aligned_rows = [
        row for row in aligned_rows
        if row[producto_idx] is not None and row[producto_idx].strip() != ""
    ]
    if not aligned_rows:
        return pl.DataFrame()

    schema_dict = {col: pl.Utf8 for col in PRECIOS_COLUMNS}
    return pl.DataFrame(aligned_rows, schema=schema_dict, orient="row")
def ingest_precios() -> pl.DataFrame:
    """
    Función principal: lee la rate card vigente.

    Returns:
        DataFrame con la rate card + columna `ingested_at` con timestamp UTC.
    """

    config = get_config()
    client = get_sheets_client()

    sheet_gspread = client.open_by_key(config["gsheets_precios_id"])
    df = _read_precios_tab(sheet_gspread, config["gsheets_precios_tab"])

    if df.is_empty():
        raise ValueError("La pestaña de precios está vacía o no tiene datos válidos.")
    
    df = df.with_columns(pl.lit(datetime.now(timezone.utc)).alias("ingested_at"))
    return df
