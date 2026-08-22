"""
Mart probabilístico de reorder B2B.

Complementa rpt_alertas_reorder_b2b (rule-based) con probabilidad continua
de reorder basada en Normal(mu, sigma) ajustada a los intervalos históricos
de cada cliente.

Consumido por: dashboard "Alertas B2B" de Metabase (W10).
"""

import polars as pl

from ingestion.b2b_reorder import generar_reorder_probabilistico


def model(dbt, session):
    dbt.config(
        materialized="table",
        schema="marts",
    )

    # Leer int_b2b_cadencia usando dbt.ref (mantiene el lineage).
    cadencia = dbt.ref("int_b2b_cadencia").pl()

    # Aplicar la lógica probabilística (funciones puras del módulo ingestion).
    resultado = generar_reorder_probabilistico(cadencia)

    return resultado