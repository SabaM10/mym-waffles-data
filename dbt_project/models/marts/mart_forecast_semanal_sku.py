"""
Forecast semanal de unidades por SKU (masa x sabor) para la próxima semana.

Grain: una fila por SKU del catálogo (8 filas).
Columnas: masa, sabor, semana_predicha, prediccion_central, banda_inferior,
banda_superior, nivel_confianza, mae_backtest, mae_naive,
n_predicciones_backtest, unidades_ultimas_4, modelo, generated_at.

Complementa mart_forecast_semanal (el total). Cada SKU tiene su propio
backtest walk-forward contra SMA-4 y contra naive: la mejora del 34% se
midió sobre el total y no se traslada sola a series más ralas.

Lo consume el panel (vista "La semana") a través de la planilla del
pipeline. Decisiones en `docs/decisions/semana-13.md`.
"""

from datetime import UTC, date, datetime, timedelta

import polars as pl

from ingestion.forecast import armar_series_semanales_por_sku, forecast_por_sku, sma

NIVEL_CONFIANZA = 0.90


def model(dbt, session):
    """Modelo dbt Python: forecast de la próxima semana por SKU."""

    dbt.config(
        materialized="table",
        packages=["polars"],
    )

    # Items con la fecha del pedido (fact_pedido_items no la trae)
    items = dbt.ref("fact_pedido_items").pl().select(["pedido_id", "masa", "sabor", "cantidad"])
    pedidos = dbt.ref("fact_pedidos").pl().select(["pedido_id", "fecha_emision"])
    items = items.join(pedidos, on="pedido_id", how="inner")

    catalogo = dbt.ref("dim_producto").pl().select(["masa", "sabor"])

    # Mismo corte que mart_forecast_semanal: la semana en curso entra como
    # cerrada (ADR semana 9). Así el total y la suma por SKU usan la misma
    # historia.
    lunes_semana_actual = date.today() - timedelta(days=date.today().weekday())
    lunes_proxima_semana = lunes_semana_actual + timedelta(weeks=1)

    series = armar_series_semanales_por_sku(items, catalogo, lunes_proxima_semana)

    def sma_4(serie):
        return sma(serie, ventana=4)

    resultado = forecast_por_sku(
        series,
        modelo=sma_4,
        ventana_backtest=8,
        nivel_confianza=NIVEL_CONFIANZA,
    )

    return resultado.with_columns(
        pl.lit(NIVEL_CONFIANZA).alias("nivel_confianza"),
        pl.lit("sma_4_v8").alias("modelo"),
        pl.lit(datetime.now(UTC)).alias("generated_at"),
    )
