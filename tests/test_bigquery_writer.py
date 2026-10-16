"""Tests for the BigQuery writer. No network and no google libraries needed."""

import polars as pl
import pytest

from ingestion.bigquery_writer import (
    bq_safe_name,
    prepare_for_bigquery,
    pseudonymize,
    sanitize_columns,
)


def test_bq_safe_name_strips_accents():
    assert bq_safe_name("seña_ars") == "sena_ars"


def test_bq_safe_name_replaces_invalid_chars_and_leading_digit():
    assert bq_safe_name("A FAVOR-ENVIO") == "A_FAVOR_ENVIO"
    assert bq_safe_name("1er_pedido") == "_1er_pedido"


def test_sanitize_columns_raises_on_collision():
    df = pl.DataFrame({"seña": [1], "sena": [2]})
    with pytest.raises(ValueError):
        sanitize_columns(df)


def test_pseudonymize_is_stable_and_hides_name():
    a = pseudonymize("Cliente Ficticio SA")
    assert a == pseudonymize("Cliente Ficticio SA")
    assert "Ficticio" not in a
    assert pseudonymize(None) is None


def test_prepare_casts_and_anonymizes():
    df = pl.DataFrame(
        {
            "cliente_canonico": ["Cliente Ficticio SA", None],
            "seña_ars": [100, 200],
            "u": pl.Series([1, 2], dtype=pl.UInt32),
            "vacia": pl.Series([None, None], dtype=pl.Null),
        }
    )
    out = prepare_for_bigquery(df)
    assert out.columns == ["cliente_canonico", "sena_ars", "u", "vacia"]
    assert out["u"].dtype == pl.Int64
    assert out["vacia"].dtype == pl.Utf8
    assert out["cliente_canonico"][0].startswith("cliente_")
    assert out["cliente_canonico"][1] is None


def test_prepare_without_anonymize_keeps_names():
    df = pl.DataFrame({"cliente_canonico": ["Cliente Ficticio SA"]})
    assert prepare_for_bigquery(df, anonymize=False)["cliente_canonico"][0] == "Cliente Ficticio SA"


def test_write_uses_truncate_load_job_and_returns_rows(monkeypatch):
    pytest.importorskip("google.cloud.bigquery")
    from unittest.mock import MagicMock

    from google.cloud import bigquery

    from ingestion import bigquery_writer

    client = MagicMock()
    client.get_table.return_value.num_rows = 2
    monkeypatch.setattr(bigquery_writer, "_get_client", lambda *a, **k: client)

    df = pl.DataFrame({"seña_ars": [1, 2]})
    rows = bigquery_writer.write_dataframe_to_bigquery(
        df, "ds", "t", project="p", location="US", credentials_path="x.json"
    )

    assert rows == 2
    args, kwargs = client.load_table_from_file.call_args
    assert args[1] == "p.ds.t"
    assert kwargs["job_config"].write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE
    assert kwargs["job_config"].source_format == bigquery.SourceFormat.PARQUET
