"""
fact_pedido_items: fact table de items de pedidos.

Genera una fila por (pedido × masa × sabor) parseando el string PEDIDO 
de stg_pedidos con el parser Python de ingestion/parsers.py.

Normaliza los nombres plural → singular para matchear con dim_producto.
"""

import polars as pl
from ingestion.parsers import parse_pedido_string


# Mapping plural (como viene del parser) → singular (como está en dim_producto)
MASA_MAP = {
    "Clásicos": "Clásica",
    "Clasicos": "Clásica",      # sin tilde
    "Integrales": "Integral",
    "Integrale": "Integral",     # por si aparece typo
    "Proteicos": "Proteica",
    "Proteico": "Proteica",      # singular común
}

SABOR_MAP = {
    "Dulces": "Dulce",
    "Salados": "Salado",
    "Neutros": "Neutro",
    "Oreos": "Oreo",
}


def normalizar_masa(masa: str) -> str:
    """Convierte masa en plural a singular. Si no está en el map, devuelve tal cual."""
    return MASA_MAP.get(masa, masa)


def normalizar_sabor(sabor: str) -> str:
    """Convierte sabor en plural a singular. Si no está en el map, devuelve tal cual."""
    return SABOR_MAP.get(sabor, sabor)


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
            "sabor": normalizar_sabor(item["sabor"].capitalize()),
            "masa": normalizar_masa(item["masa"].capitalize()),
            "cantidad": item["cantidad"],
            "orden_en_pedido": orden,
        })
    
    return items


def model(dbt, session):
    dbt.config(materialized="table")
    
    # Leer stg_pedidos como Polars DataFrame
    df_pedidos = dbt.ref("stg_pedidos").pl()
    
    # Aplicar parseo a cada fila y explotar los items
    all_items = []
    for row in df_pedidos.iter_rows(named=True):
        all_items.extend(parsear_pedido_a_items(row))
    
    # Convertir a DataFrame Polars
    df_items = pl.DataFrame(all_items)
    
    # Leer dim_producto para obtener producto_id
    df_producto = dbt.ref("dim_producto").pl()
    
    # Join para agregar producto_id
    df_items = df_items.join(
        df_producto.select(["producto_id", "masa", "sabor"]),
        on=["masa", "sabor"],
        how="left",
    )
    
    # Leer stg_pedidos de nuevo para agregar cliente_id y fecha_id (denormalizado)
    # Como todavía no existen dim_cliente / dim_fecha joins, dejamos placeholders
    # Vamos a agregar los FKs cuando tengamos fact_pedidos armado
    
    # Generar surrogate key
    df_items = df_items.with_columns([
        pl.concat_str([
            pl.col("pedido_id"),
            pl.col("producto_id"),
            pl.col("orden_en_pedido").cast(pl.Utf8),
        ], separator="|").map_elements(
            lambda x: __import__("hashlib").md5(x.encode()).hexdigest(),
            return_dtype=pl.Utf8,
        ).alias("pedido_item_id")
    ])
    
    # Seleccionar columnas finales en orden
    return df_items.select([
        "pedido_item_id",
        "pedido_id",
        "producto_id",
        "masa",
        "sabor",
        "cantidad",
        "orden_en_pedido",
    ])