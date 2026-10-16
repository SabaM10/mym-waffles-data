"""
Write Polars DataFrames to BigQuery.

Strategy: full refresh per table (WRITE_TRUNCATE) through a batch load job from a
Parquet file. It does not use pandas and it does not use streaming inserts: load
jobs are free, and they are the only write path that also works in the BigQuery
sandbox (which supports neither streaming nor DML).

google-cloud-bigquery is an optional dependency (extra "gcp" in pyproject.toml).
It is imported only when a write happens, so the rest of the project never needs it.

Client names are pseudonymized by default before leaving the machine
(see PII_COLUMNS). This hides names from screens and queries; it is not
cryptographic anonymization.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path

import polars as pl

# Columns that hold client names. Replaced by a stable pseudonym unless disabled.
PII_COLUMNS = ("cliente_canonico", "cliente_raw")

_UNSIGNED_INTS = (pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)

_BQ_SCOPE = "https://www.googleapis.com/auth/bigquery"


def bq_safe_name(name: str) -> str:
    """
    Return a column name that BigQuery accepts without flexible-name mode.

    Strips accents (seña_ars -> sena_ars), replaces any other character outside
    [A-Za-z0-9_] with an underscore, and prefixes an underscore if the name would
    start with a digit.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9_]", "_", ascii_name)
    if safe == "":
        return "_col"
    if safe[0].isdigit():
        safe = f"_{safe}"
    return safe[:300]


def sanitize_columns(df: pl.DataFrame) -> pl.DataFrame:
    """
    Rename every column with bq_safe_name.

    BigQuery column names are case-insensitive, so two columns that differ only in
    case (or that collapse to the same safe name) would collide. That is an error,
    not something to resolve silently.
    """
    mapping = {col: bq_safe_name(col) for col in df.columns}
    lowered = [new.lower() for new in mapping.values()]
    if len(set(lowered)) != len(lowered):
        clashes = sorted({n for n in lowered if lowered.count(n) > 1})
        raise ValueError(f"Column names collide after sanitizing for BigQuery: {clashes}")
    return df.rename(mapping)


def pseudonymize(value: str | None) -> str | None:
    """Stable pseudonym for a client name: the same name always maps to the same value."""
    if value is None:
        return None
    return "cliente_" + hashlib.sha256(value.encode()).hexdigest()[:8]


def prepare_for_bigquery(df: pl.DataFrame, *, anonymize: bool = True) -> pl.DataFrame:
    """
    Make a DataFrame loadable into BigQuery from Parquet.

    - Pseudonymizes the PII_COLUMNS that are present (if anonymize).
    - Casts unsigned integers to Int64 (BigQuery rejects UINT_64 in Parquet).
    - Casts all-null columns to Utf8 (a Parquet null type has no BigQuery equivalent).
    - Renames columns to BigQuery-safe names.
    """
    out = df
    if anonymize:
        out = out.with_columns(
            [
                pl.col(col).map_elements(pseudonymize, return_dtype=pl.Utf8)
                for col in PII_COLUMNS
                if col in out.columns
            ]
        )
    out = out.with_columns(
        [pl.col(col).cast(pl.Int64) for col, dtype in out.schema.items() if dtype in _UNSIGNED_INTS]
    )
    out = out.with_columns(
        [pl.col(col).cast(pl.Utf8) for col, dtype in out.schema.items() if dtype == pl.Null]
    )
    return sanitize_columns(out)


def _get_client(project: str, location: str, credentials_path: str):
    """Build an authenticated BigQuery client from a service account key file."""
    from google.cloud import bigquery  # optional dependency, imported lazily
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=[_BQ_SCOPE]
    )
    return bigquery.Client(project=project, credentials=credentials, location=location)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Falta la variable {name}")
    return value


def write_dataframe_to_bigquery(
    df: pl.DataFrame,
    dataset: str,
    table: str,
    *,
    project: str | None = None,
    location: str | None = None,
    credentials_path: str | None = None,
    anonymize: bool = True,
) -> int:
    """
    Replace `dataset.table` in BigQuery with the contents of `df`.

    Project, location and credentials fall back to the environment variables
    BQ_PROJECT, BQ_LOCATION (default "US") and BQ_CREDENTIALS_PATH (then
    GOOGLE_APPLICATION_CREDENTIALS).

    Creates the dataset if it does not exist. Returns the row count BigQuery
    reports for the table after the load, so the caller can compare it with the
    source.
    """
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery  # optional dependency, imported lazily

    project = project or _require_env("BQ_PROJECT")
    location = location or os.getenv("BQ_LOCATION", "US")
    credentials_path = (
        credentials_path
        or os.getenv("BQ_CREDENTIALS_PATH")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if not credentials_path:
        raise ValueError("Falta BQ_CREDENTIALS_PATH (o GOOGLE_APPLICATION_CREDENTIALS)")

    client = _get_client(project, location, credentials_path)

    # get-then-create instead of create(exists_ok=True): a service account that only
    # has rights on the dataset can read it but cannot call datasets.create.
    dataset_id = f"{project}.{dataset}"
    try:
        client.get_dataset(dataset_id)
    except NotFound:
        new_dataset = bigquery.Dataset(dataset_id)
        new_dataset.location = location
        client.create_dataset(new_dataset)

    prepared = prepare_for_bigquery(df, anonymize=anonymize)
    table_id = f"{dataset_id}.{table}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{table}.parquet"
        prepared.write_parquet(path)
        with path.open("rb") as handle:
            job = client.load_table_from_file(handle, table_id, job_config=job_config)
        job.result()  # blocks; raises if the load failed

    return int(client.get_table(table_id).num_rows)
