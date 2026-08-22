"""
Forecast semanal de unidades para la próxima semana no observada.

Grain: una fila (la próxima semana a predecir).
Columnas: semana_predicha, prediccion_central, banda_inferior,
banda_superior, mae_backtest, sesgo_backtest, modelo, generated_at.

Depende de mart_forecast_backtest para calcular la banda de confianza
empírica basada en los errores históricos del modelo.

Decisiones metodológicas en `docs/adr/semana-9.md`.
"""

from datetime import date, datetime, timedelta, timezone

import polars as pl

from ingestion.forecast import sma, calcular_banda_empirica


def model(dbt, session):
    """Modelo dbt Python: genera el forecast de la próxima semana."""

    dbt.config(
        materialized="table",
        packages=["polars"],
    )

    # Leer serie histórica de unidades por semana desde fact_pedidos
    fact_pedidos = dbt.ref("fact_pedidos").pl()

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

    # Rellenar gaps con cero
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

    # Última semana observada y próxima a predecir
    ultima_semana_observada = serie_completa["semana"].max()
    proxima_semana = ultima_semana_observada + timedelta(weeks=1)

    # Predicción central con SMA-4 sobre las últimas 4 semanas
    ultimas_4 = serie_completa["unidades"].tail(4).cast(pl.Float64)
    prediccion_central = sma(ultimas_4, ventana=4)

    # Leer errores del backtest para calcular banda empírica
    backtest = dbt.ref("mart_forecast_backtest").pl()
    errores_firmados = backtest["y_real"] - backtest["y_hat"]
    banda = calcular_banda_empirica(errores_firmados, nivel_confianza=0.90)

    # Estadísticas del backtest para incluir en el mart
    mae_backtest = float(backtest["error_absoluto"].mean())
    sesgo_backtest = float(errores_firmados.mean())

    # Construir la fila del forecast
    resultado = pl.DataFrame({
        "semana_predicha": [proxima_semana],
        "prediccion_central": [prediccion_central],
        "banda_inferior": [prediccion_central + banda["p_inferior"]],
        "banda_superior": [prediccion_central + banda["p_superior"]],
        "nivel_confianza": [banda["nivel_confianza"]],
        "mae_backtest": [mae_backtest],
        "sesgo_backtest": [sesgo_backtest],
        "modelo": ["sma_4_v8"],
        "generated_at": [datetime.now(timezone.utc)],
    })

    return resultado