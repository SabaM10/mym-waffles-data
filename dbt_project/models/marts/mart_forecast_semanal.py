"""
Forecast semanal de unidades para la semana que viene.

Grain: una fila (la semana a predecir).
Columnas: semana_predicha, prediccion_central, banda_inferior,
banda_superior, nivel_confianza, mae_backtest, sesgo_backtest, modelo,
generated_at.

Depende de mart_forecast_backtest para calcular la banda de confianza
empírica basada en los errores históricos del modelo.

Decisiones metodológicas en `docs/decisions/semana-9.md`. Desde semana 14:
sólo semanas cerradas, y la semana predicha es siempre la que viene (la primera
que todavía no empezó), se corra el día que se corra (`docs/decisions/semana-14.md`).
"""

from datetime import UTC, date, datetime, timedelta

import polars as pl

from ingestion.forecast import (
    HORIZONTE_SEMANAS,
    calcular_banda_empirica,
    corte_semanas_cerradas,
    semana_a_predecir,
    serie_semanal_total,
    sma,
)


def model(dbt, session):
    """Modelo dbt Python: genera el forecast de la semana que viene."""

    dbt.config(
        materialized="table",
        packages=["polars"],
    )

    hoy = date.today()
    fact_pedidos = dbt.ref("fact_pedidos").pl()
    serie = serie_semanal_total(fact_pedidos, corte_semanas_cerradas(hoy))

    # La última semana observada es la última cerrada; la predicha, la que viene.
    # Entre las dos está la semana en curso: dos pasos (HORIZONTE_SEMANAS).
    proxima_semana = semana_a_predecir(hoy)
    assert serie["semana"].max() + timedelta(weeks=HORIZONTE_SEMANAS) == proxima_semana

    # Predicción central con SMA-4 sobre las últimas 4 semanas cerradas
    ultimas_4 = serie["unidades"].tail(4).cast(pl.Float64)
    prediccion_central = sma(ultimas_4, ventana=4)

    # Banda empírica con los errores del backtest, medido al mismo horizonte
    backtest = dbt.ref("mart_forecast_backtest").pl()
    errores_firmados = backtest["y_real"] - backtest["y_hat"]
    banda = calcular_banda_empirica(errores_firmados, nivel_confianza=0.90)

    mae_backtest = float(backtest["error_absoluto"].mean())
    sesgo_backtest = float(errores_firmados.mean())

    return pl.DataFrame({
        "semana_predicha": [proxima_semana],
        "prediccion_central": [prediccion_central],
        "banda_inferior": [prediccion_central + banda["p_inferior"]],
        "banda_superior": [prediccion_central + banda["p_superior"]],
        "nivel_confianza": [banda["nivel_confianza"]],
        "mae_backtest": [mae_backtest],
        "sesgo_backtest": [sesgo_backtest],
        "modelo": ["sma_4_v8_h2"],
        "generated_at": [datetime.now(UTC)],
    })
