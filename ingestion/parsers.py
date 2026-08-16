"""
Parsers para el campo PEDIDO de la Sheet VENTAS.

Convierte strings como "192 Neutros Clásicos + 96 Neutros Integrales"
en estructuras Python parseadas.

Los items que no cumplen el formato esperado se devuelven aparte
para ir a cuarentena, no se descartan silenciosamente.
"""

import re


def parse_pedido_string(
    pedido: str,
    cantidad_default: int | None = None,
    masa_por_defecto: str | None = None,
) -> dict:
    """
    Parsea un string PEDIDO en items estructurados.

    Args:
        pedido: string del campo PEDIDO, ej. "192 Neutros Clásicos + 96 Neutros Integrales".
        cantidad_default: cantidad a usar si no se especifica en el chunk.
        masa_por_defecto: masa a usar cuando el chunk no tiene masa y no hay masa anterior para heredar.

    Returns:
        Dict con dos claves:
        - "items": lista de dicts con {sabor, masa, cantidad}.
        - "no_parseados": lista de strings que no matchearon el formato esperado.
    """
    if pedido is None or pedido.strip() == "":
        return {"items": [], "no_parseados": []}
    # Fallback: si el pedido no tiene número al inicio y no tiene '+',
    # usar cantidad_default como cantidad y todo el string como descripción.
    if cantidad_default is not None and "+" not in pedido:
        stripped = pedido.strip()
        # Chequear si empieza con dígito
        if stripped and not stripped[0].isdigit():
        # Reconstruir como "<cantidad> <descripción>" y seguir el flujo normal
            pedido = f"{cantidad_default} {stripped}"


    chunks = [chunk.strip() for chunk in pedido.split("+") if chunk.strip()] # Split por "+", limpiar espacios y descartar chunks vacíos.
    items = []
    no_parseados = []
    masa_anterior = None
    for chunk in chunks:
        masa_fallback = masa_anterior if masa_anterior is not None else masa_por_defecto
        parsed = _parse_single_item(chunk, masa_fallback)
        if parsed is None:
            no_parseados.append(chunk)
        else:
            items.append(parsed)
            masa_anterior = parsed["masa"]
    return {"items": items, "no_parseados": no_parseados}


def _parse_single_item(chunk: str, masa_default: str | None = None) -> dict | None:
    """
    Parsea un chunk individual como "192 Neutros Clásicos".

    Args:
        chunk: string con formato esperado "<cantidad> <sabor> <masa>".

    Returns:
        Dict con {sabor, masa, cantidad} si parsea bien.
        None si el chunk no matchea el formato esperado.
    """
    match = re.match(r"^(\d+)\s+(.+)$", chunk)
    if match is None:
        return None

    cantidad = int(match.group(1))
    resto = match.group(2)  

    palabras = resto.split()
    if len(palabras) < 2:
        if masa_default is not None:
            # Solo hay una palabra (sabor), inyectar masa_default.
            masa = masa_default
            sabor = palabras[0]
            return {"sabor": sabor, "masa": masa, "cantidad": cantidad}
        return None
    masa = palabras[-1]  
    sabor = " ".join(palabras[:-1])
    return {"sabor": sabor, "masa": masa, "cantidad": cantidad}
