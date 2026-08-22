"""
Tests unitarios para el módulo probabilístico de reorder B2B.

Cobertura:
  - Primitivas (calcular_probabilidad_reorder, calcular_z_score, clasificar_confianza)
    con casos analíticamente conocidos.
  - Orquestador (generar_reorder_probabilistico) con un DataFrame chico
    armado a mano.
  - Casos borde (sigma=0, sigma negativo).
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from ingestion.b2b_reorder import (
    calcular_probabilidad_reorder,
    calcular_z_score,
    clasificar_confianza,
    generar_reorder_probabilistico,
)


# ============================================================================
# calcular_probabilidad_reorder
# ============================================================================

class TestCalcularProbabilidadReorder:
    """Casos analíticos donde la CDF de una Normal tiene valor conocido."""

    def test_dias_igual_mu_devuelve_medio(self):
        """CDF(mu) = 0.5 por simetría de la distribución Normal."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=50,
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado == pytest.approx(0.5, abs=1e-6)

    def test_dias_igual_mu_mas_un_sigma(self):
        """CDF(mu + 1σ) ≈ 0.8413 (regla 68-95-99.7)."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=70,
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado == pytest.approx(0.8413, abs=1e-3)

    def test_dias_igual_mu_menos_un_sigma(self):
        """CDF(mu - 1σ) ≈ 0.1587 (complemento de mu + 1σ)."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=30,
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado == pytest.approx(0.1587, abs=1e-3)

    def test_dias_muy_lejano_arriba_devuelve_cerca_de_uno(self):
        """CDF a 5σ del promedio: prácticamente 1."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=150,  # mu + 5σ
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado > 0.999

    def test_dias_muy_lejano_abajo_devuelve_cerca_de_cero(self):
        """CDF a -5σ del promedio: prácticamente 0."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=-50,  # mu - 5σ
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado < 0.001

    def test_sigma_cero_devuelve_nan(self):
        """Caso patológico: intervalos idénticos. La normal degenera."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=50,
            mu_intervalo=50,
            sigma_intervalo=0,
        )
        assert math.isnan(resultado)

    def test_sigma_negativo_devuelve_nan(self):
        """Sigma negativo no tiene sentido físico; blindaje defensivo."""
        resultado = calcular_probabilidad_reorder(
            dias_desde_ultimo=50,
            mu_intervalo=50,
            sigma_intervalo=-5,
        )
        assert math.isnan(resultado)


# ============================================================================
# calcular_z_score
# ============================================================================

class TestCalcularZScore:

    def test_z_score_en_mu_es_cero(self):
        """dias == mu → z = 0."""
        resultado = calcular_z_score(
            dias_desde_ultimo=50,
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado == pytest.approx(0.0, abs=1e-9)

    def test_z_score_mas_un_sigma_es_uno(self):
        """dias == mu + σ → z = 1."""
        resultado = calcular_z_score(
            dias_desde_ultimo=70,
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado == pytest.approx(1.0, abs=1e-9)

    def test_z_score_menos_un_sigma_es_menos_uno(self):
        """dias == mu - σ → z = -1."""
        resultado = calcular_z_score(
            dias_desde_ultimo=30,
            mu_intervalo=50,
            sigma_intervalo=20,
        )
        assert resultado == pytest.approx(-1.0, abs=1e-9)

    def test_z_score_sigma_cero_devuelve_nan(self):
        """División por cero degenerada; devolvemos NaN explícito."""
        resultado = calcular_z_score(
            dias_desde_ultimo=50,
            mu_intervalo=50,
            sigma_intervalo=0,
        )
        assert math.isnan(resultado)


# ============================================================================
# clasificar_confianza
# ============================================================================

class TestClasificarConfianza:
    """Tests parametrizados sobre los cortes del clasificador."""

    @pytest.mark.parametrize(
        "total_pedidos,esperado",
        [
            (0, "BAJA"),
            (3, "BAJA"),
            (5, "BAJA"),   # justo debajo del corte
            (6, "MEDIA"),  # corte inferior de MEDIA
            (7, "MEDIA"),
            (9, "MEDIA"),  # justo debajo del corte a ALTA
            (10, "ALTA"),  # corte inferior de ALTA
            (50, "ALTA"),
        ],
    )
    def test_clasificacion_por_umbral(self, total_pedidos, esperado):
        assert clasificar_confianza(total_pedidos) == esperado


# ============================================================================
# generar_reorder_probabilistico (orquestador)
# ============================================================================

class TestGenerarReorderProbabilistico:

    @pytest.fixture
    def cadencia_df_minimo(self) -> pl.DataFrame:
        """
        DataFrame chico con 3 clientes que cubren los tres niveles de confianza
        y valores analíticamente predecibles.
        """
        return pl.DataFrame({
            "cliente_id": ["c1", "c2", "c3"],
            "cliente_canonico": ["Cliente ALTA", "Cliente MEDIA", "Cliente BAJA"],
            "total_pedidos": [12, 7, 4],
            "fecha_ultimo_pedido": ["2026-08-01", "2026-08-10", "2026-08-15"],
            "intervalo_promedio_dias": [50.0, 30.0, 20.0],
            "intervalo_desvio_dias": [20.0, 10.0, 5.0],
            "dias_desde_ultimo_pedido": [50, 30, 20],  # cada uno en su mu
        })

    def test_output_tiene_las_columnas_nuevas(self, cadencia_df_minimo):
        resultado = generar_reorder_probabilistico(cadencia_df_minimo)
        columnas = set(resultado.columns)
        assert "probabilidad_reorder_ya" in columnas
        assert "z_score" in columnas
        assert "confianza_estimacion" in columnas

    def test_output_preserva_columnas_originales(self, cadencia_df_minimo):
        resultado = generar_reorder_probabilistico(cadencia_df_minimo)
        columnas = set(resultado.columns)
        for col in [
            "cliente_id",
            "cliente_canonico",
            "total_pedidos",
            "fecha_ultimo_pedido",
            "intervalo_promedio_dias",
            "intervalo_desvio_dias",
            "dias_desde_ultimo_pedido",
        ]:
            assert col in columnas

    def test_output_conserva_grain(self, cadencia_df_minimo):
        """Una fila por cliente, sin duplicados ni pérdidas."""
        resultado = generar_reorder_probabilistico(cadencia_df_minimo)
        assert resultado.height == cadencia_df_minimo.height

    def test_probabilidades_en_mu_son_medio(self, cadencia_df_minimo):
        """Los 3 clientes tienen dias == mu, entonces probabilidad = 0.5."""
        resultado = generar_reorder_probabilistico(cadencia_df_minimo)
        probs = resultado["probabilidad_reorder_ya"].to_list()
        for prob in probs:
            assert prob == pytest.approx(0.5, abs=1e-6)

    def test_z_scores_en_mu_son_cero(self, cadencia_df_minimo):
        """Los 3 clientes tienen dias == mu, entonces z = 0."""
        resultado = generar_reorder_probabilistico(cadencia_df_minimo)
        z_scores = resultado["z_score"].to_list()
        for z in z_scores:
            assert z == pytest.approx(0.0, abs=1e-9)

    def test_confianza_asignada_correctamente(self, cadencia_df_minimo):
        """Cliente c1 (12 pedidos) → ALTA, c2 (7) → MEDIA, c3 (4) → BAJA."""
        resultado = generar_reorder_probabilistico(cadencia_df_minimo)
        confianzas = dict(zip(
            resultado["cliente_id"].to_list(),
            resultado["confianza_estimacion"].to_list(),
        ))
        assert confianzas["c1"] == "ALTA"
        assert confianzas["c2"] == "MEDIA"
        assert confianzas["c3"] == "BAJA"

    def test_no_muta_input(self, cadencia_df_minimo):
        """Verificar que el input original no cambia."""
        columnas_originales = set(cadencia_df_minimo.columns)
        _ = generar_reorder_probabilistico(cadencia_df_minimo)
        columnas_despues = set(cadencia_df_minimo.columns)
        assert columnas_originales == columnas_despues

    def test_descarta_columnas_del_rule_based(self):
        """Si el input trae columnas del rule-based, no deben pasar al output."""
        df_con_rule_based = pl.DataFrame({
            "cliente_id": ["c1"],
            "cliente_canonico": ["Cliente X"],
            "total_pedidos": [12],
            "fecha_ultimo_pedido": ["2026-08-01"],
            "intervalo_promedio_dias": [50.0],
            "intervalo_desvio_dias": [20.0],
            "dias_desde_ultimo_pedido": [50],
            "umbral_alerta_dias": [70.0],           # rule-based, no debe pasar
            "alerta_reorder": [False],              # rule-based, no debe pasar
        })
        resultado = generar_reorder_probabilistico(df_con_rule_based)
        assert "umbral_alerta_dias" not in resultado.columns
        assert "alerta_reorder" not in resultado.columns