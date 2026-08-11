"""
Autenticación contra Google Sheets API.
Provee un cliente gspread listo para usar.
"""

import gspread

from ingestion.config import get_config


def get_sheets_client():
    """
    Autentica contra Google Sheets usando el service account.

    Returns:
        gspread.Client: cliente autenticado listo para abrir Sheets.

    Raises:
        FileNotFoundError: si el archivo de credenciales no existe.
    """
    config = get_config()
    credentials_path = config["google_credentials_path"]
    return gspread.service_account(filename=credentials_path)