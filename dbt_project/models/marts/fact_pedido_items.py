"""
fact_pedido_items: fact table de items de pedidos.

Genera una fila por (pedido × masa × sabor) parseando el string PEDIDO 
de stg_pedidos con el parser Python de ingestion/parsers.py.

Aplica matching contra dim_tarifa según:
- Si cantidad matchea pack exacto y vigencia contiene la fecha → esa tarifa.
- Si no matchea → pack inmediato inferior con precio_unitario × cantidad_real.
- Si cantidad > 96 → precio_unitario del pack 96 × cantidad.
"""

import hashlib
import polars as pl
from ingestion.parsers import parse_pedido_string


MASA_MAP = {
    "Clásicos": "Clásica",
    "Clasicos": "Clásica",
    "Integrales": "Integral",
    "Integrale": "Integral",
    "Proteicos": "Proteica",
    "Proteico": "Proteica",
}

SABOR_MAP = {
    "Dulces": "Dulce",
    "Salados": "Salado",
    "Neutros": "Neutro",
    "Oreos": "Oreo",
}


def normalizar_masa(masa: str) -> str:
    return MASA_MAP.get(masa, masa)


def normalizar_sabor(sabor: str) -> str:
    return SABOR_MAP.get(sabor, sabor)


def hash_md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def masa_sabor_a_producto_desc(masa: str, sabor: str, cantidad: int) -> str:
    """
    Devuelve el producto_desc según las reglas de la rate card, teniendo 
    en cuenta la cantidad para decidir minorista vs mayorista.
    
    - Oreo: siempre 'OREO' (tanto minorista como mayorista).
    - No-oreo con cantidad <= 24: 'CLÁSICA / DULCE - SALADO - NEUTRO' (minorista).
    - No-oreo con cantidad > 24: 'TODOS LOS SABORES' (mayorista).
    """
    if sabor == "Oreo":
        return "OREO"
    if cantidad <= 24:
        return "CLÁSICA / DULCE - SALADO - NEUTRO"
    return "TODOS LOS SABORES"


def buscar_tarifa(
    df_tarifas: pl.DataFrame,
    masa: str,
    sabor: str,
    cantidad: int,
    fecha: str,
) -> dict:
    """
    Busca la tarifa aplicable para un item.
    
    Prioridad:
    1. Oreo minorista/mayorista según cantidad.
    2. CLÁSICA (dulce/salado/neutro) minorista según cantidad.
    3. TODOS LOS SABORES mayorista para cantidades >= 32.
    
    Devuelve dict con tarifa_id, precio_unitario, precio_total del item.
    """
    if masa is None or sabor is None:
        return {"tarifa_id": None, "precio_unitario": None, "precio_total": None}
    if masa == "Proteica":
        return {"tarifa_id": None, "precio_unitario": None, "precio_total": None}
    producto_desc = masa_sabor_a_producto_desc(masa, sabor, cantidad)
    
    # Filtrar tarifas del producto vigentes en la fecha
    tarifas_producto = df_tarifas.filter(
        (pl.col("producto_desc") == producto_desc)
        & (pl.col("valid_from") <= fecha)
        & ((pl.col("valid_to").is_null()) | (pl.col("valid_to") >= fecha))
    )
    
    if tarifas_producto.is_empty():
        return {"tarifa_id": None, "precio_unitario": None, "precio_total": None}
    
    # Determinar segmento por cantidad
    # Minorista/Promo: cantidad <= 24
    # Mayorista: cantidad >= 32
    if cantidad <= 24:
        tarifas_segmento = tarifas_producto.filter(pl.col("segmento") == "MINORISTA")
    else:
        tarifas_segmento = tarifas_producto.filter(pl.col("segmento") == "MAYORISTA")
    
    if tarifas_segmento.is_empty():
        # Si el producto no tiene tarifa mayorista, quedamos con las minoristas
        tarifas_segmento = tarifas_producto
    
    # Buscar pack exacto
    exacto = tarifas_segmento.filter(pl.col("unidades_pack") == cantidad)
    if not exacto.is_empty():
        tarifa = exacto.row(0, named=True)
        return {
            "tarifa_id": tarifa["tarifa_id"],
            "precio_unitario": float(tarifa["precio_unitario_ars"]),
            "precio_total": float(tarifa["precio_venta_ars"]),
        }
    
    # No hay exacto: buscar pack inmediato inferior
    inferiores = tarifas_segmento.filter(pl.col("unidades_pack") < cantidad).sort(
        "unidades_pack", descending=True
    )
    
    if not inferiores.is_empty():
        tarifa = inferiores.row(0, named=True)
        precio_unitario = float(tarifa["precio_unitario_ars"])
        return {
            "tarifa_id": tarifa["tarifa_id"],
            "precio_unitario": precio_unitario,
            "precio_total": precio_unitario * cantidad,
        }
    
    # No hay inferior tampoco (cantidad menor al pack mínimo)
    # Tomamos el pack mínimo disponible
    minimo = tarifas_segmento.sort("unidades_pack").row(0, named=True)
    precio_unitario = float(minimo["precio_unitario_ars"])
    return {
        "tarifa_id": minimo["tarifa_id"],
        "precio_unitario": precio_unitario,
        "precio_total": precio_unitario * cantidad,
    }


def parsear_pedido_a_items(row: dict) -> list[dict]:
    resultado = parse_pedido_string(
        row["pedido_string"],
        cantidad_default=row["cantidad_total"],
        masa_por_defecto="Clásicos",
    )
    
    items = []
    for orden, item in enumerate(resultado["items"], start=1):
        items.append({
            "pedido_id": row["pedido_id"],
            "fecha_emision": row["fecha_emision"],
            "sabor": normalizar_sabor(item["sabor"].capitalize()),
            "masa": normalizar_masa(item["masa"].capitalize()),
            "cantidad": item["cantidad"],
            "orden_en_pedido": orden,
        })
    
    return items


def model(dbt, session):
    dbt.config(materialized="table")
    
    # Leer stg_pedidos
    df_pedidos = dbt.ref("stg_pedidos").pl()
    
    # Parsear todos los items
    all_items = []
    for row in df_pedidos.iter_rows(named=True):
        all_items.extend(parsear_pedido_a_items(row))
    
    df_items = pl.DataFrame(all_items)
    
    # Leer dim_producto para producto_id
    df_producto = dbt.ref("dim_producto").pl()
    df_items = df_items.join(
        df_producto.select(["producto_id", "masa", "sabor"]),
        on=["masa", "sabor"],
        how="left",
    )
    
    # Leer dim_tarifa para matching
    df_tarifas = dbt.ref("dim_tarifa").pl()
    
    # Aplicar matching de tarifa por item
    tarifa_ids = []
    precio_unitarios = []
    precio_totales = []
    
    for row in df_items.iter_rows(named=True):
        resultado = buscar_tarifa(
            df_tarifas,
            row["masa"],
            row["sabor"],
            row["cantidad"],
            row["fecha_emision"],
        )
        tarifa_ids.append(resultado["tarifa_id"])
        precio_unitarios.append(resultado["precio_unitario"])
        precio_totales.append(resultado["precio_total"])
    
    df_items = df_items.with_columns([
        pl.Series("tarifa_id", tarifa_ids),
        pl.Series("precio_unitario_aplicado_ars", precio_unitarios),
        pl.Series("precio_item_ars", precio_totales),
    ])
    
    # Generar surrogate key
    df_items = df_items.with_columns([
        pl.concat_str([
            pl.col("pedido_id"),
            pl.col("producto_id").fill_null("NULL"),
            pl.col("orden_en_pedido").cast(pl.Utf8),
        ], separator="|").map_elements(hash_md5, return_dtype=pl.Utf8).alias("pedido_item_id")
    ])
    
    # Seleccionar columnas finales
    return df_items.select([
        "pedido_item_id",
        "pedido_id",
        "producto_id",
        "tarifa_id",
        "masa",
        "sabor",
        "cantidad",
        "orden_en_pedido",
        "precio_unitario_aplicado_ars",
        "precio_item_ars",
    ])