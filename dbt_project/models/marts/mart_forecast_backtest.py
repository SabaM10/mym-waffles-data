"""
Backtesting walk-forward del modelo SMA-4 sobre la serie histórica de
unidades vendidas por semana.

Grain: una fila por semana evaluada en el backtest.
Cada fila tiene: valor real, predicción del modelo, error absoluto.

Este mart alimenta el dashboard "Forecast vs Actual" de Metabase y
sirve como base para calcular la banda de confianza empírica del
forecast semanal.

Decisiones metodológicas en `docs/adr/semana-9.md`.
"""

import polars as pl

from ingestion.forecast import sma, walk_forward_backtest


def model(dbt, session):
    """Modelo dbt Python: genera el backtesting histórico del SMA-4."""

    dbt.config(
        materialized="table",
        packages=["polars"],
    )

    # Leer fact_pedidos (dbt.ref maneja las dependencias automáticamente)
    fact_pedidos = dbt.ref("fact_pedidos").pl()

    # Agregar por semana ISO
    serie_semanal = (
        fact_pedidos
        .with_columns(
            pl.col("fecha_emision")
              .dt.truncate("1w")
              .alias("semana")
        )
        .group_by("semana")
        .agg(pl.col("cantidad_total").sum().alias("unidades"))
        .sort("semana")
    )

        # Rellenar gaps con cero (semanas sin pedidos = ventas cero)
    semanas_completas = pl.DataFrame({
        "semana": pl.date_range(
            start=serie_semanal["semana"].min(),
            end=serie_semanal["semana"].max(),
            interval="1w",
            eager=True,
        )
    })
    serie_completa = (
        semanas_completas
        .join(serie_semanal, on="semana", how="left")
        .with_columns(pl.col("unidades").fill_null(0).cast(pl.Int64))
    )

        # Filtrar hasta la semana en curso inclusive (se considera cerrada
    # porque los pedidos B2B se despachan lunes-viernes; los viernes por la
    # tarde la semana está funcionalmente cerrada). Ver ADR semana 9.
    from datetime import date, timedelta
    lunes_semana_actual = date.today() - timedelta(days=date.today().weekday())
    lunes_proxima_semana = lunes_semana_actual + timedelta(weeks=1)
    serie_completa = serie_completa.filter(
        pl.col("semana") < pl.lit(lunes_proxima_semana)
    )
    # Correr el backtesting: SMA-4 con ventana 8
    def sma_4(serie):
        return sma(serie, ventana=4)

    backtest = walk_forward_backtest(
        serie=serie_completa["unidades"].cast(pl.Float64),
        fechas=serie_completa["semana"],
        modelo=sma_4,
        ventana=8,
    )

    # Agregar columna modelo para futura extensibilidad
    return backtest.with_columns(pl.lit("sma_4_v8").alias("modelo"))