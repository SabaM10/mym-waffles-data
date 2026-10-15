"""
Backtesting walk-forward del modelo SMA-4 sobre la serie histórica de
unidades vendidas por semana.

Grain: una fila por semana evaluada en el backtest.
Cada fila tiene: valor real, predicción del modelo, error absoluto.

Este mart alimenta el dashboard "Forecast vs Actual" de Metabase y
sirve como base para calcular la banda de confianza empírica del
forecast semanal.

Decisiones metodológicas en `docs/decisions/semana-9.md`. Desde semana 14 sólo
entran semanas cerradas y el backtest se mide a dos semanas de horizonte, el
mismo salto que hace el forecast en producción (`docs/decisions/semana-14.md`).
"""

from datetime import date

import polars as pl

from ingestion.forecast import (
    HORIZONTE_SEMANAS,
    corte_semanas_cerradas,
    serie_semanal_total,
    sma,
    walk_forward_backtest,
)


def model(dbt, session):
    """Modelo dbt Python: genera el backtesting histórico del SMA-4."""

    dbt.config(
        materialized="table",
        packages=["polars"],
    )

    fact_pedidos = dbt.ref("fact_pedidos").pl()

    # Sólo semanas cerradas: la semana en curso nunca entra (ADR semana 9,
    # decisión 6, que el código no cumplía hasta semana 14).
    serie = serie_semanal_total(fact_pedidos, corte_semanas_cerradas(date.today()))

    def sma_4(historia):
        return sma(historia, ventana=4)

    backtest = walk_forward_backtest(
        serie=serie["unidades"].cast(pl.Float64),
        fechas=serie["semana"],
        modelo=sma_4,
        ventana=8,
        horizonte=HORIZONTE_SEMANAS,
    )

    # Agregar columna modelo para futura extensibilidad
    return backtest.with_columns(pl.lit("sma_4_v8_h2").alias("modelo"))
