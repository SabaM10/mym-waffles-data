"""
Tests unitarios para ingestion/parsers.py.

Cada test cubre un caso concreto del parser:
- Casos válidos (parseo exitoso).
- Casos edge (input vacío, None, chunks vacíos).
- Casos con herencia de masa.
- Casos que van a cuarentena.
"""

from ingestion.parsers import parse_pedido_string


def test_parsea_un_item_simple():
    """Un solo item con formato estándar."""
    resultado = parse_pedido_string("400 Dulces Clásicos")
    assert resultado == {
        "items": [{"sabor": "Dulces", "masa": "Clásicos", "cantidad": 400}],
        "no_parseados": [],
    }


def test_parsea_dos_items():
    """Dos items separados por +."""
    # TODO: implementar
    pass
    resultado = parse_pedido_string("192 Neutros Clásicos + 96 Neutros Integrales")
    assert resultado == {
        "items": [
            {"sabor": "Neutros", "masa": "Clásicos", "cantidad": 192},
            {"sabor": "Neutros", "masa": "Integrales", "cantidad": 96},
        ],
        "no_parseados": [],
    }



def test_hereda_masa_del_item_anterior():
    """Cuando falta la masa, hereda del item previo del mismo pedido."""
    # TODO: implementar (ej: "24 Dulces Clásicos + 32 Oreos" → los Oreos son Clásicos)
    pass
    resultado = parse_pedido_string("24 Dulces Clásicos + 32 Oreos")
    assert resultado == {
        "items": [
            {"sabor": "Dulces", "masa": "Clásicos", "cantidad": 24},
            {"sabor": "Oreos", "masa": "Clásicos", "cantidad": 32},
        ],
        "no_parseados": [],
    }


def test_input_vacio_devuelve_listas_vacias():
    """String vacío no es error, es 'no hay pedido'."""
    # TODO: implementar
    pass
    resultado = parse_pedido_string("")
    assert resultado == {"items": [], "no_parseados": []}

def test_input_none_devuelve_listas_vacias():
    """None tampoco es error."""
    # TODO: implementar
    pass
    resultado = parse_pedido_string(None)
    assert resultado == {"items": [], "no_parseados": []}


def test_chunk_sin_cantidad_va_a_cuarentena():
    """'oreos' (sin número) no parsea."""
    # TODO: implementar
    pass
    resultado = parse_pedido_string("oreos")
    assert resultado == {"items": [], "no_parseados": ["oreos"]}

def test_chunk_con_cantidad_pero_una_sola_palabra_sin_masa_previa():
    """'13 oreos' al inicio (sin masa heredable) va a cuarentena."""
    
    resultado = parse_pedido_string("13 oreos")
    assert resultado == {"items": [], "no_parseados": ["13 oreos"]} 

def test_fallback_cantidad_para_input_sin_numero():
    
    resultado = parse_pedido_string("Neutros Clásicos", cantidad_default=100)
    assert resultado == {
        "items": [{"sabor": "Neutros", "masa": "Clásicos", "cantidad": 100}],
        "no_parseados": [],
    }
def test_masa_por_defecto_cuando_no_hay_masa_anterior():
    
    resultado = parse_pedido_string("13 oreos", masa_por_defecto="Clásicos")
    assert resultado == {
        "items": [{"sabor": "oreos", "masa": "Clásicos", "cantidad": 13}],
        "no_parseados": [],
    }

def test_masa_por_defecto_no_se_usa_si_hay_masa_anterior():  #(para verificar que la herencia gana sobre el default)

    
    resultado = parse_pedido_string("24 Dulces Integrales + 32 oreos", masa_por_defecto="Clásicos")
    assert resultado == {
        "items": [
            {"sabor": "Dulces", "masa": "Integrales", "cantidad": 24},
            {"sabor": "oreos", "masa": "Integrales", "cantidad": 32}
        ],
        "no_parseados": [],
    }
def test_fallback_cantidad_no_se_aplica_si_hay_signo_mas():
    pass
    resultado = parse_pedido_string("Neutros Clásicos + 24 Oreos", cantidad_default=100)
    assert resultado == {
    "items": [],
    "no_parseados": ["Neutros Clásicos", "24 Oreos"],
}