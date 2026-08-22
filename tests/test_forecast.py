"""
Tests unitarios para ingestion/forecast.py.

Cobertura:
- Modelos: naive, sma, ewma.
- Backtesting: walk_forward_backtest.
- Banda: calcular_banda_empirica.
- End-to-end: generar_forecast.
"""

import polars as pl
import pytest

from ingestion.forecast import (
    naive,
    sma,
    ewma,
    walk_forward_backtest,
    calcular_banda_empirica,
    generar_forecast,
)


# ============================================================
# Tests de modelos
# ============================================================

class TestNaive:
    """Tests del modelo naive."""

    def test_devuelve_ultimo_valor(self):
        serie = pl.Series([100, 200, 300, 400])
        assert naive(serie) == 400.0

    def test_serie_vacia_falla(self):
        with pytest.raises(ValueError, match="no puede estar vacía"):
            naive(pl.Series([], dtype=pl.Float64))


class TestSMA:
    """Tests del modelo SMA (media móvil simple)."""

    def test_ventana_exacta(self):
        # Ventana 4 sobre exactamente 4 valores → promedio de los 4
        serie = pl.Series([100, 200, 300, 400])
        assert sma(serie, ventana=4) == 250.0

    def test_ventana_menor_que_serie(self):
        # Ventana 3 sobre 5 valores → promedio de los últimos 3
        serie = pl.Series([100, 200, 300, 400, 500])
        assert sma(serie, ventana=3) == 400.0  # (300+400+500)/3

    def test_ventana_default(self):
        # Sin especificar ventana, usa default 4
        serie = pl.Series([100, 200, 300, 400, 500])
        assert sma(serie) == 350.0  # (200+300+400+500)/4

    def test_ventana_insuficiente_falla(self):
        # Serie más corta que la ventana → error
        serie = pl.Series([100, 200])
        with pytest.raises(ValueError, match="se requieren al menos"):
            sma(serie, ventana=4)


class TestEWMA:
    """Tests del modelo EWMA (media móvil exponencial)."""

    def test_alpha_1_devuelve_ultimo_valor(self):
        # Con alpha=1, EWMA colapsa al último valor (memoria cero)
        serie = pl.Series([100, 200, 300, 400])
        assert ewma(serie, alpha=1.0) == 400.0

    def test_calculo_con_alpha_conocido(self):
        # Con alpha=0.5 y serie [100, 200, 300]:
        # inicial = 100
        # después de 200: 0.5*200 + 0.5*100 = 150
        # después de 300: 0.5*300 + 0.5*150 = 225
        serie = pl.Series([100, 200, 300])
        assert ewma(serie, alpha=0.5) == 225.0

    def test_alpha_fuera_de_rango_falla(self):
        serie = pl.Series([100, 200])
        with pytest.raises(ValueError, match="alpha debe estar"):
            ewma(serie, alpha=1.5)
        with pytest.raises(ValueError, match="alpha debe estar"):
            ewma(serie, alpha=0.0)


# ============================================================
# Tests de backtesting
# ============================================================

class TestWalkForwardBacktest:
    """Tests del backtesting walk-forward."""

    def test_cantidad_de_predicciones(self):
        # Serie de 10 valores, ventana 3 → 10-3 = 7 predicciones
        serie = pl.Series(range(10), dtype=pl.Float64)
        fechas = pl.Series([f"2026-01-{i+1:02d}" for i in range(10)]).str.to_date()
        resultado = walk_forward_backtest(serie, fechas, naive, ventana=3)
        assert resultado.shape[0] == 7

    def test_no_data_leakage_con_naive(self):
        # Con naive, la predicción en i debe ser exactamente serie[i-1].
        # Si hay leakage, la predicción usaría serie[i] o posteriores.
        serie = pl.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        fechas = pl.Series(["2026-01-01", "2026-01-08", "2026-01-15",
                            "2026-01-22", "2026-01-29"]).str.to_date()
        resultado = walk_forward_backtest(serie, fechas, naive, ventana=2)
        # ventana=2 → predice desde índice 2. En i=2, historia=[10,20], naive=20.
        # En i=3, historia=[20,30], naive=30. En i=4, historia=[30,40], naive=40.
        assert resultado["y_hat"].to_list() == [20.0, 30.0, 40.0]
        assert resultado["y_real"].to_list() == [30.0, 40.0, 50.0]

    def test_columnas_del_resultado(self):
        serie = pl.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        fechas = pl.Series(["2026-01-01", "2026-01-08", "2026-01-15",
                            "2026-01-22", "2026-01-29"]).str.to_date()
        resultado = walk_forward_backtest(serie, fechas, naive, ventana=2)
        assert set(resultado.columns) == {"semana", "y_real", "y_hat", "error_absoluto"}

    def test_longitudes_distintas_fallan(self):
        with pytest.raises(ValueError, match="misma longitud"):
            walk_forward_backtest(
                pl.Series([1.0, 2.0, 3.0]),
                pl.Series(["2026-01-01"]).str.to_date(),
                naive,
                ventana=1,
            )


# ============================================================
# Tests de banda empírica
# ============================================================

class TestCalcularBandaEmpirica:
    """Tests del cálculo de banda de confianza empírica."""

    def test_percentiles_de_distribucion_conocida(self):
        # Serie 0..99 (100 valores). p5=5, p50=50, p95=95 aproximadamente.
        errores = pl.Series(range(100), dtype=pl.Float64)
        banda = calcular_banda_empirica(errores, nivel_confianza=0.90)
        # Tolerancia porque el cálculo exacto de percentiles puede variar
        assert 4 <= banda["p_inferior"] <= 6
        assert 49 <= banda["p_mediana"] <= 51
        assert 93 <= banda["p_superior"] <= 96
        assert banda["nivel_confianza"] == 0.90

    def test_nivel_confianza_fuera_de_rango_falla(self):
        errores = pl.Series([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="nivel_confianza"):
            calcular_banda_empirica(errores, nivel_confianza=1.5)


# ============================================================
# Test end-to-end
# ============================================================

class TestGenerarForecast:
    """Tests de la función de alto nivel generar_forecast."""

    def test_devuelve_todas_las_keys(self):
        serie = pl.Series([100.0 + i * 10 for i in range(15)])
        fechas = pl.Series([f"2026-01-{i+1:02d}" for i in range(15)]).str.to_date()
        resultado = generar_forecast(serie, fechas, naive, ventana_backtest=4)
        keys_esperadas = {
            "prediccion_central",
            "banda_inferior",
            "banda_superior",
            "mae_backtest",
            "sesgo_backtest",
            "n_predicciones_backtest",
        }
        assert set(resultado.keys()) == keys_esperadas

    def test_banda_inferior_menor_que_superior(self):
        serie = pl.Series([100.0 + i * 10 for i in range(15)])
        fechas = pl.Series([f"2026-01-{i+1:02d}" for i in range(15)]).str.to_date()
        resultado = generar_forecast(serie, fechas, naive, ventana_backtest=4)
    # La banda inferior siempre debe ser menor o igual a la superior
    # (los percentiles están ordenados). NO se testea que la predicción
    # central esté "en el medio" porque un modelo sesgado puede tener
    # ambos percentiles del mismo signo, desplazando la banda.
        assert resultado["banda_inferior"] <= resultado["banda_superior"]