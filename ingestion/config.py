"""
Configuración del proyecto.
Lee variables de entorno desde .env y las valida.
"""

import os
from dotenv import load_dotenv


# Cargar .env si existe (útil para correr scripts fuera de Docker).
load_dotenv()


def get_config():
    """
    Devuelve un diccionario con toda la configuración del proyecto.
    Si alguna variable requerida falta, lanza un error explicando cuál.
    """
    # Leer las variables requeridas
    pedidos_id = os.getenv("GSHEETS_PEDIDOS_ID")
    pedidos_tab_pattern = os.getenv("GSHEETS_PEDIDOS_TAB_PATTERN")
    precios_id = os.getenv("GSHEETS_PRECIOS_ID")
    precios_tab = os.getenv("GSHEETS_PRECIOS_TAB")
    duckdb_path = os.getenv("DUCKDB_PATH")
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # Validar que todas las requeridas estén definidas
    if pedidos_id is None:
        raise ValueError("Falta la variable GSHEETS_PEDIDOS_ID en .env")
    if pedidos_tab_pattern is None:
        raise ValueError("Falta la variable GSHEETS_PEDIDOS_TAB_PATTERN en .env")
    if precios_id is None:
        raise ValueError("Falta la variable GSHEETS_PRECIOS_ID en .env")
    if precios_tab is None:
        raise ValueError("Falta la variable GSHEETS_PRECIOS_TAB en .env")
    if duckdb_path is None:
        raise ValueError("Falta la variable DUCKDB_PATH en .env")
    if credentials_path is None:
        raise ValueError("Falta la variable GOOGLE_APPLICATION_CREDENTIALS en .env")

    # Leer environment con default
    environment = os.getenv("ENVIRONMENT", "dev")

    # Devolver el dict
    return {
        "gsheets_pedidos_id": pedidos_id,
        "gsheets_pedidos_tab_pattern": pedidos_tab_pattern,
        "gsheets_precios_id": precios_id,
        "gsheets_precios_tab": precios_tab,
        "duckdb_path": duckdb_path,
        "google_credentials_path": credentials_path,
        "environment": environment,
    }