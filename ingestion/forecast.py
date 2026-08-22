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
    
    Returns:
        DataFrame con columnas: semana (datetime), y_real (f64),
        y_hat (f64), error_absoluto (f64).
    """
    if len(serie) != len(fechas):
        raise ValueError("serie y fechas deben tener la misma longitud")
    if len(serie) <= ventana:
        raise ValueError(
            f"serie tiene {len(serie)} valores, "
            f"se requieren más de {ventana} para hacer backtesting"
        )
    
    resultados = []
    for i in range(ventana, len(serie)):
        historia = serie[i - ventana : i]
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
    backtest = walk_forward_backtest(serie, fechas, modelo, ventana_backtest)
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