"""
Modelos y utilidades para forecasting semanal de unidades vendidas.

Este módulo contiene:
- Modelos simples de forecasting (naive, SMA, EWMA).
- Backtesting walk-forward con sliding window.
- Cálculo de banda de confianza empírica.
- Función de alto nivel para generar forecast completo.

Todas las funciones son puras: reciben datos como argumentos y devuelven
resultados, sin efectos secundarios ni I/O. La conexión con el warehouse
vive en los modelos dbt que consumen este módulo.

Decisiones metodológicas documentadas en `docs/adr/semana-9.md`.
"""

from datetime import date, timedelta
from typing import Callable

import polars as pl


# ============================================================
# MODELOS
# ============================================================

def naive(serie_historica: pl.Series) -> float:
    """Predice el valor de la próxima semana como el último valor observado.
    
    Baseline obligatorio. Cualquier modelo más complejo debe ganarle
    por margen sustancial en MAE para justificar su complejidad.
    
    Args:
        serie_historica: valores históricos ordenados cronológicamente.
    
    Returns:
        Predicción para el próximo período.
    """
    if len(serie_historica) == 0:
        raise ValueError("serie_historica no puede estar vacía")
    return float(serie_historica[-1])


def sma(serie_historica: pl.Series, ventana: int = 4) -> float:
    """Predice como promedio simple de las últimas `ventana` observaciones.
    
    Suaviza el ruido semana a semana. Bueno en régimen estable con alta
    volatilidad. Limitación: aplana picos aislados.
    
    Args:
        serie_historica: valores históricos ordenados cronológicamente.
        ventana: cantidad de observaciones recientes a promediar. Default 4.
    
    Returns:
        Predicción para el próximo período.
    """
    if len(serie_historica) < ventana:
        raise ValueError(
            f"serie_historica tiene {len(serie_historica)} valores, "
            f"se requieren al menos {ventana}"
        )
    return float(serie_historica[-ventana:].mean())


def ewma(serie_historica: pl.Series, alpha: float) -> float:
    """Predice como promedio ponderado exponencial de toda la serie histórica.
    
    Alpha alto (cerca de 1) = memoria corta, se adapta rápido a cambios.
    Alpha bajo (cerca de 0) = memoria larga, similar a promedio simple.
    
    Args:
        serie_historica: valores históricos ordenados cronológicamente.
        alpha: factor de suavizado, en (0, 1].
    
    Returns:
        Predicción para el próximo período.
    """
    if not (0 < alpha <= 1):
        raise ValueError(f"alpha debe estar en (0, 1], recibido: {alpha}")
    if len(serie_historica) == 0:
        raise ValueError("serie_historica no puede estar vacía")
    
    valores = serie_historica.to_list()
    ewma_valor = valores[0]
    for v in valores[1:]:
        ewma_valor = alpha * v + (1 - alpha) * ewma_valor
    return float(ewma_valor)


# ============================================================
# BACKTESTING
# ============================================================

def walk_forward_backtest(
    serie: pl.Series,
    fechas: pl.Series,
    modelo: Callable[[pl.Series], float],
    ventana: int = 8,
    horizonte: int = 1,
) -> pl.DataFrame:
    """Backtesting walk-forward con sliding window de tamaño fijo.
    
    Para cada punto i desde `ventana` hasta el final de la serie:
      1. Toma como historia las últimas `ventana` observaciones anteriores a i.
      2. Aplica el modelo a esa historia para predecir el valor en i.
      3. Compara la predicción contra el valor real.
    
    La ventana es fija (sliding), no expandida. Se eligió sliding sobre
    expanding para adaptabilidad ante cambios de régimen. Justificación
    completa en ADR semana 9.
    
    Args:
        serie: valores de la serie temporal.
        fechas: fechas correspondientes a cada valor de la serie (misma longitud).
        modelo: función que recibe una serie y devuelve una predicción.
        ventana: tamaño de la ventana sliding. Default 8.
        horizonte: cuántos pasos adelante se predice. 1 = la semana siguiente a
            la última observada. Con 2, la historia de cada predicción termina
            dos semanas antes del punto evaluado: es lo que pasa en producción,
            donde la semana en curso no se usa (ver ADR semana 14).
    
    Returns:
        DataFrame con columnas: semana (datetime), y_real (f64),
        y_hat (f64), error_absoluto (f64).
    """
    if len(serie) != len(fechas):
        raise ValueError("serie y fechas deben tener la misma longitud")
    if horizonte < 1:
        raise ValueError(f"horizonte debe ser >= 1, recibido: {horizonte}")
    if len(serie) <= ventana + horizonte - 1:
        raise ValueError(
            f"serie tiene {len(serie)} valores, "
            f"se requieren más de {ventana + horizonte - 1} para hacer backtesting"
        )
    
    resultados = []
    for i in range(ventana + horizonte - 1, len(serie)):
        # La historia termina `horizonte` pasos antes de i (con 1, justo antes).
        fin = i - horizonte + 1
        historia = serie[fin - ventana : fin]
        y_real = float(serie[i])
        y_hat = modelo(historia)
        resultados.append({
            "semana": fechas[i],
            "y_real": y_real,
            "y_hat": y_hat,
            "error_absoluto": abs(y_real - y_hat),
        })
    
    return pl.DataFrame(resultados)


# ============================================================
# BANDA DE CONFIANZA EMPÍRICA
# ============================================================

def calcular_banda_empirica(
    errores_firmados: pl.Series,
    nivel_confianza: float = 0.90,
) -> dict:
    """Calcula banda de confianza empírica a partir de errores del backtesting.
    
    La banda se construye con percentiles empíricos de los errores firmados
    (y_real - y_hat), sin asumir distribución. Preserva asimetría natural
    de los errores.
    
    Args:
        errores_firmados: errores firmados del backtesting (y_real - y_hat).
        nivel_confianza: nivel de confianza deseado, en (0, 1). Default 0.90.
    
    Returns:
        Dict con:
        - p_inferior: percentil inferior del error (float).
        - p_mediana: mediana del error (float, sesgo del modelo).
        - p_superior: percentil superior del error (float).
        - nivel_confianza: el nivel usado (float, echo del input).
    """
    if not (0 < nivel_confianza < 1):
        raise ValueError(
            f"nivel_confianza debe estar en (0, 1), recibido: {nivel_confianza}"
        )
    
    alpha_cola = (1 - nivel_confianza) / 2  # e.g. 0.05 para nivel 0.90
    
    return {
        "p_inferior": float(errores_firmados.quantile(alpha_cola)),
        "p_mediana": float(errores_firmados.quantile(0.50)),
        "p_superior": float(errores_firmados.quantile(1 - alpha_cola)),
        "nivel_confianza": nivel_confianza,
    }


# ============================================================
# FORECAST COMPLETO (función de alto nivel)
# ============================================================

def generar_forecast(
    serie: pl.Series,
    fechas: pl.Series,
    modelo: Callable[[pl.Series], float],
    ventana_backtest: int = 8,
    nivel_confianza: float = 0.90,
    horizonte: int = 1,
) -> dict:
    """Genera forecast para el próximo período con banda de confianza empírica.
    
    Orquesta:
      1. Backtesting walk-forward para calcular errores históricos.
      2. Cálculo de banda empírica basada en esos errores.
      3. Predicción central usando la ventana más reciente.
      4. Aplicación de la banda a la predicción central.
    
    Args:
        serie: valores de la serie temporal completa.
        fechas: fechas correspondientes.
        modelo: función de forecasting a usar.
        ventana_backtest: tamaño de ventana para el walk-forward. Default 8.
        nivel_confianza: nivel de confianza para la banda. Default 0.90.
    
    Returns:
        Dict con:
        - prediccion_central: valor predicho (float).
        - banda_inferior: límite inferior de la banda (float).
        - banda_superior: límite superior de la banda (float).
        - mae_backtest: MAE del modelo en backtesting (float).
        - sesgo_backtest: sesgo promedio del modelo (float, ~0 es bueno).
        - n_predicciones_backtest: cantidad de predicciones evaluadas (int).
    """
    # Backtesting
    backtest = walk_forward_backtest(serie, fechas, modelo, ventana_backtest, horizonte)
    errores_firmados = backtest["y_real"] - backtest["y_hat"]
    
    # Banda empírica
    banda = calcular_banda_empirica(errores_firmados, nivel_confianza)
    
    # Predicción central: aplicar modelo a la ventana más reciente
    ventana_reciente = serie[-ventana_backtest:]
    prediccion_central = modelo(ventana_reciente)
    
    return {
        "prediccion_central": prediccion_central,
        "banda_inferior": prediccion_central + banda["p_inferior"],
        "banda_superior": prediccion_central + banda["p_superior"],
        "mae_backtest": float(backtest["error_absoluto"].mean()),
        "sesgo_backtest": float(errores_firmados.mean()),
        "n_predicciones_backtest": len(backtest),
    }

# ============================================================
# QUÉ SEMANAS SE USAN Y CUÁL SE PREDICE (ADR semana 14)
# ============================================================

# Desde la última semana cerrada hasta la que se predice hay siempre dos pasos:
# la semana en curso (que no se usa) y la siguiente (la que se predice).
HORIZONTE_SEMANAS = 2


def lunes_de(dia: date) -> date:
    """Lunes de la semana (ISO) de `dia`."""
    return dia - timedelta(days=dia.weekday())


def corte_semanas_cerradas(hoy: date) -> date:
    """Lunes de la semana en curso: las semanas ANTERIORES a esta fecha están cerradas.

    Se usa como límite exclusivo. La semana en curso no entra nunca, se corra el
    pipeline el día que se corra: con un día de datos (un lunes) o con cinco (un
    viernes) es igual de incompleta, y el SMA-4 la promediaría como si fuera entera.
    """
    return lunes_de(hoy)


def semana_a_predecir(hoy: date) -> date:
    """Lunes de la semana que viene: la primera que todavía no empezó."""
    return corte_semanas_cerradas(hoy) + timedelta(weeks=1)


def serie_semanal_total(pedidos: pl.DataFrame, hasta_exclusive: date) -> pl.DataFrame:
    """Unidades por semana, de la primera semana con pedidos hasta la última cerrada.

    Las semanas sin pedidos valen cero (ADR semana 9, decisión 7), también las del
    FINAL: la grilla termina en la última semana cerrada, no en la última con
    pedidos. Una semana sin ventas justo antes del corte es un dato (cero), no un
    hueco.

    Args:
        pedidos: una fila por pedido, con fecha_emision (date) y cantidad_total.
        hasta_exclusive: lunes de la primera semana que NO entra.

    Returns:
        DataFrame con columnas semana (date) y unidades (i64), ordenado.
    """
    semanal = (
        pedidos
        .filter(pl.col("fecha_emision").is_not_null())
        .with_columns(pl.col("fecha_emision").dt.truncate("1w").alias("semana"))
        .filter(pl.col("semana") < pl.lit(hasta_exclusive))
        .group_by("semana")
        .agg(pl.col("cantidad_total").sum().alias("unidades"))
    )
    if semanal.is_empty():
        raise ValueError("no hay pedidos con fecha anterior al corte")
    semanas = pl.DataFrame({
        "semana": pl.date_range(
            start=semanal["semana"].min(),
            end=hasta_exclusive - timedelta(weeks=1),
            interval="1w",
            eager=True,
        )
    })
    return (
        semanas
        .join(semanal, on="semana", how="left")
        .with_columns(pl.col("unidades").fill_null(0).cast(pl.Int64))
        .sort("semana")
    )


# ============================================================
# FORECAST POR SKU (masa x sabor)
# ============================================================

def armar_series_semanales_por_sku(
    items: pl.DataFrame,
    catalogo: pl.DataFrame,
    hasta_exclusive,
) -> pl.DataFrame:
    """Builds one zero-filled weekly series per catalog SKU.

    Every SKU gets the same week grid (from the first observed week of ANY
    SKU up to the last week before `hasta_exclusive`, sales or not), so a SKU that sold
    nothing in a week counts as a real zero and not as a missing point.
    Without the shared grid, a rarely ordered SKU would be forecast only
    from the weeks where it did sell, which overstates its demand.

    Args:
        items: one row per order item, with columns fecha_emision (date),
            masa (str), sabor (str), cantidad (int).
        catalogo: one row per valid SKU, with columns masa, sabor.
        hasta_exclusive: Monday of the first week NOT to include.

    Returns:
        DataFrame with columns semana (date), masa, sabor, unidades (i64),
        sorted by masa, sabor, semana.
    """
    semanal = (
        items
        .filter(pl.col("fecha_emision").is_not_null())
        .with_columns(pl.col("fecha_emision").dt.truncate("1w").alias("semana"))
        .filter(pl.col("semana") < pl.lit(hasta_exclusive))
        .group_by(["semana", "masa", "sabor"])
        .agg(pl.col("cantidad").sum().alias("unidades"))
    )
    if semanal.is_empty():
        raise ValueError("no hay items con fecha anterior al corte")

    # La grilla termina en la última semana cerrada, no en la última con ventas:
    # una semana final sin pedidos es un cero (ver serie_semanal_total).
    semanas = pl.DataFrame({
        "semana": pl.date_range(
            start=semanal["semana"].min(),
            end=hasta_exclusive - timedelta(weeks=1),
            interval="1w",
            eager=True,
        )
    })
    grilla = semanas.join(catalogo.select(["masa", "sabor"]), how="cross")
    return (
        grilla
        .join(semanal, on=["semana", "masa", "sabor"], how="left")
        .with_columns(pl.col("unidades").fill_null(0).cast(pl.Int64))
        .sort(["masa", "sabor", "semana"])
    )


def forecast_por_sku(
    series: pl.DataFrame,
    modelo: Callable[[pl.Series], float],
    ventana_backtest: int = 8,
    nivel_confianza: float = 0.90,
    horizonte: int = 1,
) -> pl.DataFrame:
    """Forecasts the week `horizonte` steps after the last observed one, per SKU,
    each one with its own backtest at that same horizon.

    The 34% MAE improvement of SMA-4 over naive was measured on the TOTAL
    series. Per-SKU series are sparser and noisier, so the claim does not
    carry over: each SKU gets its own walk-forward backtest against SMA-4
    AND against naive, and both MAEs are published side by side.

    Units cannot be negative, so the band is clipped at zero. The upper
    band is what the panel uses as "produce this much to be safe".

    Args:
        series: output of armar_series_semanales_por_sku.
        modelo: forecasting function (e.g. SMA-4).
        ventana_backtest: sliding window for walk-forward. Default 8.
        nivel_confianza: band confidence level. Default 0.90.

    Returns:
        DataFrame, one row per SKU: masa, sabor, semana_predicha,
        prediccion_central, banda_inferior, banda_superior, mae_backtest,
        mae_naive, n_predicciones_backtest, unidades_ultimas_4.
    """
    filas = []
    for (masa, sabor), grupo in series.group_by(["masa", "sabor"], maintain_order=True):
        grupo = grupo.sort("semana")
        serie = grupo["unidades"].cast(pl.Float64)
        fechas = grupo["semana"]

        resultado = generar_forecast(
            serie, fechas, modelo,
            ventana_backtest=ventana_backtest,
            nivel_confianza=nivel_confianza,
            horizonte=horizonte,
        )
        backtest_naive = walk_forward_backtest(serie, fechas, naive, ventana_backtest, horizonte)

        filas.append({
            "masa": masa,
            "sabor": sabor,
            "semana_predicha": fechas.max() + timedelta(weeks=horizonte),
            "prediccion_central": max(0.0, resultado["prediccion_central"]),
            "banda_inferior": max(0.0, resultado["banda_inferior"]),
            "banda_superior": max(0.0, resultado["banda_superior"]),
            "mae_backtest": resultado["mae_backtest"],
            "mae_naive": float(backtest_naive["error_absoluto"].mean()),
            "n_predicciones_backtest": resultado["n_predicciones_backtest"],
            "unidades_ultimas_4": int(grupo["unidades"].tail(4).sum()),
        })

    return pl.DataFrame(filas)
