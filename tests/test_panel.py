"""
Tests unitarios para ingestion/panel.py (el contrato con el panel).

Fixtures anonimizados: ningún cliente real.
"""

from datetime import UTC, date, datetime

import polars as pl
import pytest

from ingestion.panel import (
    CONTRATO_VERSION,
    clave_stock,
    dataframe_a_filas,
    preparar_clientes,
    preparar_forecast_sku,
    preparar_forecast_total,
    preparar_meta,
    publicar_pestanas,
)


class TestClaveStock:
    """Las claves tienen que ser exactamente las de demandaGlobal del panel."""

    @pytest.mark.parametrize(
        ("masa", "sabor", "esperada"),
        [
            ("Clásica", "Dulce", "dulces"),
            ("Clásica", "Oreo", "oreos"),
            ("Integral", "Neutro", "neutros_int"),
            ("Integral", "Salado", "salados_int"),
            ("Proteica", "Dulce", "dulces_prot"),
        ],
    )
    def test_mapeo(self, masa, sabor, esperada):
        assert clave_stock(masa, sabor) == esperada

    def test_sku_desconocido_falla(self):
        with pytest.raises(ValueError, match="SKU desconocido"):
            clave_stock("Clasica", "Dulce")  # sin tilde: no se adivina


def _forecast_sku():
    return pl.DataFrame({
        "masa": ["Integral", "Clásica"],
        "sabor": ["Neutro", "Dulce"],
        "semana_predicha": [date(2026, 10, 19)] * 2,
        "prediccion_central": [20.4, 87.6],
        "banda_inferior": [0.0, 12.9],
        "banda_superior": [51.2, 136.0],
        "mae_backtest": [16.23, 36.26],
        "mae_naive": [23.41, 58.08],
        "unidades_ultimas_4": [80, 352],
    })


class TestPrepararForecastSku:

    def test_redondeo_banda_superior_hacia_arriba(self):
        df = preparar_forecast_sku(_forecast_sku())
        fila = df.filter(pl.col("clave_stock") == "neutros_int").row(0, named=True)
        assert fila["prediccion"] == 20
        assert fila["banda_superior"] == 52  # 51.2 -> 52: "para estar tranquilos"
        assert fila["banda_inferior"] == 0

    def test_columnas_del_contrato(self):
        df = preparar_forecast_sku(_forecast_sku())
        assert df.columns == [
            "clave_stock", "masa", "sabor", "semana_predicha", "prediccion",
            "banda_inferior", "banda_superior", "mae_backtest", "mae_naive",
            "unidades_ultimas_4",
        ]


class TestPrepararForecastTotal:

    def test_banda_negativa_se_recorta(self):
        df = preparar_forecast_total(pl.DataFrame({
            "semana_predicha": [date(2026, 10, 19)],
            "prediccion_central": [40.0],
            "banda_inferior": [-25.5],
            "banda_superior": [90.2],
            "mae_backtest": [30.0],
            "nivel_confianza": [0.9],
        }))
        fila = df.row(0, named=True)
        assert fila["banda_inferior"] == 0
        assert fila["banda_superior"] == 91


def _clientes():
    return pl.DataFrame({
        "cliente_canonico": ["Cliente C", "Cliente A", "Cliente B", "Cliente D"],
        "estado_semana": ["al_dia", "atrasado", "le_toca", "atrasado"],
        "ratio_atraso": [0.5, 1.4, 0.9, 3.0],
        "fecha_ultimo_pedido": [date(2026, 10, 10)] * 4,
        "fecha_proximo_esperado": [
            date(2026, 10, 25), date(2026, 10, 1), date(2026, 10, 16), date(2026, 9, 20),
        ],
        "intervalo_promedio_dias": [14.6, 12.2, 20.0, 9.0],
        "dias_desde_ultimo_pedido": [4, 19, 4, 46],
        "probabilidad_reorder_ya": [0.21, 0.93, None, float("nan")],
        "confianza_estimacion": ["ALTA", "MEDIA", "BAJA", "ALTA"],
        "unidades_promedio": [48.0, 32.4, 64.0, 96.0],
        "masa_habitual": ["Clásica", "Integral", "Clásica", "Clásica"],
        "sabor_habitual": ["Dulce", "Neutro", "Oreo", "Dulce"],
    })


class TestPrepararClientes:

    def test_orden_por_urgencia(self):
        df = preparar_clientes(_clientes())
        # atrasados por ratio desc, después le_toca, después al_dia
        assert df["cliente"].to_list() == ["Cliente D", "Cliente A", "Cliente B", "Cliente C"]

    def test_no_publica_cliente_id(self):
        assert "cliente_id" not in preparar_clientes(_clientes()).columns


class TestDataframeAFilas:

    def test_fechas_como_texto_iso_y_nulos_vacios(self):
        df = preparar_clientes(_clientes())
        filas = dataframe_a_filas(df)
        assert filas[0] == df.columns
        encabezado = filas[0]
        d = dict(zip(encabezado, filas[1], strict=True))  # Cliente D
        assert d["fecha_proximo_esperado"] == "2026-09-20"
        assert d["probabilidad"] == ""  # NaN no viaja como NaN

    def test_meta(self):
        meta = preparar_meta(datetime(2026, 10, 14, 3, 0, tzinfo=UTC), date(2026, 10, 19))
        filas = dataframe_a_filas(meta)
        assert filas[1] == [CONTRATO_VERSION, "2026-10-14T03:00:00+00:00", "2026-10-19"]


class _HojaFalsa:
    """Minimal stand-in for a gspread worksheet."""

    def __init__(self, title):
        self.title = title
        self.valores = [["basura vieja"]]
        self.eventos = []

    def clear(self):
        self.valores = []
        self.eventos.append("clear")

    def update(self, valores, rango, value_input_option=None):
        self.valores = valores
        self.eventos.append(("update", rango, value_input_option))


class _PlanillaFalsa:
    def __init__(self, existentes):
        self.hojas = {t: _HojaFalsa(t) for t in existentes}
        self.orden = []

    def worksheets(self):
        return list(self.hojas.values())

    def add_worksheet(self, title, rows, cols):
        self.hojas[title] = _HojaFalsa(title)
        return self.hojas[title]


class _ClienteFalso:
    def __init__(self, planilla):
        self.planilla = planilla
        self.abiertas = []

    def open_by_key(self, key):
        self.abiertas.append(key)
        return self.planilla


class TestPublicarPestanas:

    def test_crea_las_que_faltan_y_reescribe_las_que_estan(self):
        planilla = _PlanillaFalsa(["meta"])
        cliente = _ClienteFalso(planilla)
        meta = preparar_meta(datetime(2026, 10, 14, tzinfo=UTC), date(2026, 10, 19))
        publicar_pestanas(cliente, "ID", {
            "forecast_sku": preparar_forecast_sku(_forecast_sku()),
            "meta": meta,
        })
        assert cliente.abiertas == ["ID"]
        assert set(planilla.hojas) == {"meta", "forecast_sku"}
        assert planilla.hojas["meta"].valores[0] == ["contrato_version", "generado", "semana_predicha"]
        assert planilla.hojas["meta"].eventos == ["clear", ("update", "A1", "RAW")]
