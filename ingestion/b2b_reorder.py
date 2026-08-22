"""
Modelo probabilístico de reorder para clientes B2B.

Complementa el enfoque rule-based (rpt_alertas_reorder_b2b) con una medida
continua de "cuán atípico es el silencio actual" basada en la distribución
Normal ajustada a los intervalos históricos entre pedidos de cada cliente.

Extraído a producción desde notebooks/forecast_exploration.ipynb (W9),
generalizado para todos los clientes B2B con >= 4 pedidos históricos.
"""

from __future__ import annotations

import polars as pl
from scipy.stats import norm


# --- Umbrales de confianza de la estimación ---
# Base: cantidad de pedidos históricos. Con más pedidos, más intervalos
# observados, mejor estimación de mu y sigma.

CONFIANZA_ALTA_MIN = 10
CONFIANZA_MEDIA_MIN = 6


def calcular_probabilidad_reorder(
    dias_desde_ultimo: int,
    mu_intervalo: float,
    sigma_intervalo: float,
) -> float:
    """
    Probabilidad (0..1) de que el cliente ya hubiera pedido a esta altura,
    asumiendo intervalos ~ Normal(mu, sigma).

    Equivale a CDF(dias_desde_ultimo) de la distribución ajustada.

    Interpretación operativa:
      0.5   → dias_desde_ultimo == mu (justo en el promedio histórico).
      0.84  → dias_desde_ultimo == mu + 1σ.
      0.975 → dias_desde_ultimo == mu + 2σ.
    """
    if sigma_intervalo <= 0:
        # Caso patológico: intervalos idénticos. La normal degenera.
        # Devolvemos NaN para señalar "no calculable" en vez de mentir.
        return float("nan")

    return float(norm.cdf(dias_desde_ultimo, loc=mu_intervalo, scale=sigma_intervalo))


def calcular_z_score(
    dias_desde_ultimo: int,
    mu_intervalo: float,
    sigma_intervalo: float,
) -> float:
    """
    Cantidad de desvíos estándar que separan el silencio actual del promedio.

    Positivo = por encima del promedio (atraso).
    Negativo = por debajo del promedio (aún pronto para pedir).
    """
    if sigma_intervalo <= 0:
        return float("nan")

    return float((dias_desde_ultimo - mu_intervalo) / sigma_intervalo)


def clasificar_confianza(total_pedidos: int) -> str:
    """
    Clasifica la confianza de la estimación estadística según la cantidad
    de pedidos históricos disponibles.

      total_pedidos >= 10 → 'ALTA'
      total_pedidos entre 6 y 9 → 'MEDIA'
      total_pedidos < 6 → 'BAJA'
    """
    if total_pedidos >= CONFIANZA_ALTA_MIN:
        return "ALTA"
    if total_pedidos >= CONFIANZA_MEDIA_MIN:
        return "MEDIA"
    return "BAJA"


def generar_reorder_probabilistico(cadencia_df: pl.DataFrame) -> pl.DataFrame:
    """
    Función orquestadora. Toma un DataFrame con las columnas de int_b2b_cadencia
    y agrega tres columnas nuevas:
      - probabilidad_reorder_ya (float, 0..1)
      - z_score (float)
      - confianza_estimacion (str: 'BAJA' | 'MEDIA' | 'ALTA')

    Columnas requeridas en cadencia_df:
      cliente_id, cliente_canonico, total_pedidos, fecha_ultimo_pedido,
      intervalo_promedio_dias, intervalo_desvio_dias, dias_desde_ultimo_pedido.

    Columnas descartadas de cadencia_df (pertenecen al enfoque rule-based):
      umbral_alerta_dias, dias_de_atraso, ratio_atraso, alerta_reorder.

    Retorna un DataFrame nuevo, no muta el input.
    """
    columnas_a_conservar = [
        "cliente_id",
        "cliente_canonico",
        "total_pedidos",
        "fecha_ultimo_pedido",
        "intervalo_promedio_dias",
        "intervalo_desvio_dias",
        "dias_desde_ultimo_pedido",
    ]

    base = cadencia_df.select(columnas_a_conservar)

    resultado = base.with_columns(
        # Aplicar las funciones escalares por fila usando map_elements.
        # Con ~13 clientes, la sobrecarga es despreciable y el código queda claro.
        probabilidad_reorder_ya=pl.struct(
            ["dias_desde_ultimo_pedido", "intervalo_promedio_dias", "intervalo_desvio_dias"]
        ).map_elements(
            lambda row: calcular_probabilidad_reorder(
                row["dias_desde_ultimo_pedido"],
                row["intervalo_promedio_dias"],
                row["intervalo_desvio_dias"],
            ),
            return_dtype=pl.Float64,
        ),
        z_score=pl.struct(
            ["dias_desde_ultimo_pedido", "intervalo_promedio_dias", "intervalo_desvio_dias"]
        ).map_elements(
            lambda row: calcular_z_score(
                row["dias_desde_ultimo_pedido"],
                row["intervalo_promedio_dias"],
                row["intervalo_desvio_dias"],
            ),
            return_dtype=pl.Float64,
        ),
        confianza_estimacion=pl.col("total_pedidos").map_elements(
            clasificar_confianza,
            return_dtype=pl.Utf8,
        ),
    )

    return resultado