"""
Escritura de DataFrames a DuckDB.

Provee una función genérica para persistir cualquier DataFrame
como tabla en un schema específico de DuckDB.
Estrategia: full refresh (drop + create) en cada corrida.
"""

from pathlib import Path

import duckdb
import polars as pl

from ingestion.config import get_config


def write_dataframe_to_duckdb(
    df: pl.DataFrame,
    schema: str,
    table_name: str,
) -> None:
    """
    Escribe un DataFrame a DuckDB en el schema y tabla especificados.

    Estrategia full refresh: la tabla se recrea en cada corrida.
    Crea el schema si no existe.

    Args:
        df: DataFrame de Polars a escribir.
        schema: nombre del schema destino, ej. "raw".
        table_name: nombre de la tabla destino, ej. "pedidos".

    Raises:
        ValueError: si el DataFrame está vacío.
    """
    if df.is_empty():
        raise ValueError(
            f"No se puede escribir un DataFrame vacío a {schema}.{table_name}"
        )

    config = get_config()
    duckdb_path = config["duckdb_path"]

    # Asegurar que el directorio del archivo .duckdb exista.
    Path(duckdb_path).parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(duckdb_path) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(
            f"CREATE OR REPLACE TABLE {schema}.{table_name} AS SELECT * FROM df"
        )