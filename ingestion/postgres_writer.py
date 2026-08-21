"""
Escritura de DataFrames Polars a Postgres vía ADBC.

Estrategia: full refresh (DROP TABLE IF EXISTS + CREATE + INSERT).
Consistente con la estrategia de raw (ADR semana 2, Decisión 3).

Postgres funciona como capa de serving para Metabase.
El warehouse sigue siendo DuckDB.

Usa ADBC (Arrow Database Connectivity) en vez de SQLAlchemy porque
Polars soporta ADBC nativamente sin depender de pandas.
"""
import os
import polars as pl
import adbc_driver_postgresql.dbapi


def get_postgres_uri() -> str:
    """
    Arma la connection URI de Postgres desde env vars.
    Formato: postgresql://user:password@host:port/db
    """
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ["POSTGRES_HOST"]
    port = os.environ["POSTGRES_PORT"]
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def write_dataframe_to_postgres(
    df: pl.DataFrame,
    schema: str,
    table: str,
) -> None:
    """
    Escribe un DataFrame Polars a Postgres con full refresh.

    Crea el schema si no existe. La tabla se reemplaza en cada corrida
    (equivalente a DROP + CREATE + INSERT).

    Args:
        df: DataFrame a escribir.
        schema: schema de destino en Postgres (ej. 'serving').
        table: nombre de la tabla (ej. 'rpt_reconciliacion_pedidos').
    """
    uri = get_postgres_uri()

    # Asegurar que el schema existe (ADBC lo requiere pre-creado)
    with adbc_driver_postgresql.dbapi.connect(uri) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.commit()

    # Escribir con ADBC nativo de Polars
    df.write_database(
        table_name=f'"{schema}"."{table}"',
        connection=uri,
        if_table_exists="replace",
        engine="adbc",
    )