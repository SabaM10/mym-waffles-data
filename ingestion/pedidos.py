"""
Ingesta de la Sheet 'VENTAS 2026'.

Lee todas las pestañas mensuales que matchean el patrón definido en .env
(ej: 'AGOSTO 2026', 'JULIO 2026') y las concatena en un solo DataFrame.
"""

import re
from datetime import datetime, timezone

import polars as pl
import gspread

from ingestion.config import get_config
from ingestion.sheets_auth import get_sheets_client

VENTAS_COLUMNS = [
    "CUIT",
    "CLIENTE",
    "CANTIDAD",
    "PEDIDO",
    "PRECIO",
    "A FAVOR ENVIO",
    "PAGO",
    "SEÑA",
    "EMISIÓN",
    "ENTREGA",
    "PAGO COMPLETADO",
    "ENTREGADO",
] 
FILAS_RESUMEN = {"INGRESOS SUBTOTALES DEL MES", "INGRESOS TOTALES DEL MES", "TOTAL WAFFLES"}
#FILAS QUE SE DEBEN IGNORAR: FILAS DE RESUMEN, FILAS VACÍAS, FILAS CON CLIENTE VACÍO PERO QUE SE LEIAN IGUAL POR QUE CLIENTE TENIA UN "VALOR".
def _list_tabs_matching_pattern(spreadsheet, pattern: str) -> list[str]:

    return [worksheet.title for worksheet in spreadsheet.worksheets() if re.match(pattern, worksheet.title)]



def _read_tab_as_dataframe(spreadsheet, tab_name: str) -> pl.DataFrame:
   
    worksheet = spreadsheet.worksheet(tab_name)
    values = worksheet.get_all_values()

    # Necesitamos al menos fila de título + fila de headers + al menos 1 dato.
    # Si hay menos de 3 filas, no hay data útil.
    if len(values) < 3:
        return pl.DataFrame()

    # Descartar fila 0 (título "VENTAS" mergeado).
    # Ahora values[0] son los headers reales, values[1:] son los datos.
    values = values[1:]
    sheet_headers = values[0]
    data_rows = values[1:]

    # Para cada columna canónica, encontrar su índice en el sheet (o None si falta).
    sheet_headers_stripped = [h.strip() for h in sheet_headers]
    column_indices = {}
    for canonical_col in VENTAS_COLUMNS:
        if canonical_col in sheet_headers_stripped:
            column_indices[canonical_col] = sheet_headers_stripped.index(canonical_col)
        else:
            column_indices[canonical_col] = None

    # Construir las filas alineadas al schema canónico.
    aligned_rows = []
    for row in data_rows:
        aligned_row = []
        for canonical_col in VENTAS_COLUMNS:
            idx = column_indices[canonical_col]
            if idx is None or idx >= len(row):
                aligned_row.append(None)
            else:
                aligned_row.append(row[idx])
        aligned_rows.append(aligned_row)

    # Filtrar filas donde CLIENTE esté vacío o solo espacios.
    cliente_idx = VENTAS_COLUMNS.index("CLIENTE")
    aligned_rows = [
        row for row in aligned_rows
        if row[cliente_idx] is not None 
        and row[cliente_idx].strip() != ""
        and row[cliente_idx].strip().upper() not in FILAS_RESUMEN
    ]

    if not aligned_rows:
        return pl.DataFrame()

    schema_dict = {col: pl.Utf8 for col in VENTAS_COLUMNS}
    return pl.DataFrame(aligned_rows, schema=schema_dict, orient="row")


def ingest_pedidos() -> pl.DataFrame:

    config = get_config()
    client = get_sheets_client()
    list_of_dfs = []
    sheet_gspread = client.open_by_key(config["gsheets_pedidos_id"])
    for tab_name in _list_tabs_matching_pattern(sheet_gspread, config["gsheets_pedidos_tab_pattern"]):
        df = _read_tab_as_dataframe(sheet_gspread, tab_name)
        list_of_dfs.append(df)
    list_of_dfs = [df for df in list_of_dfs if not df.is_empty()]
    if list_of_dfs:
        final_df = pl.concat(list_of_dfs)
        final_df = final_df.with_columns(pl.lit(datetime.now(timezone.utc)).alias("ingested_at"))
    else:
        final_df = pl.DataFrame()
    return final_df

