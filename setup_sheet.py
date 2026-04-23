"""
Google Sheet Initializer for OXYGN Sales Bot
=============================================
Run this script ONCE to set up the Google Sheet with headers,
OXYGN branding (green color scheme), and optimized column widths.

WARNING: This will overwrite existing content in the sheet.
Only use on a new or empty Google Sheet.

Usage:
    python setup_sheet.py
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Fecha",            # A
    "Hora",             # B
    "Nombre",           # C
    "Documento",        # D
    "Teléfono",         # E
    "Dirección",        # F
    "Ciudad",           # G
    "Cantidad",         # H
    "Colores",          # I
    "Precio",           # J
    "Envío",            # K
    "Método de Pago",   # L
    "Registrado Por",   # M
]

# OXYGN brand colors
OXYGN_GREEN = {"red": 0.18, "green": 0.54, "blue": 0.34}
OXYGN_GREEN_LIGHT = {"red": 0.85, "green": 0.94, "blue": 0.88}
WHITE = {"red": 1, "green": 1, "blue": 1}


def get_credentials():
    """Support both file-based and env var credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)


def main():
    creds = get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    sheet = spreadsheet.sheet1

    sheet.update_title("Ventas OXYGN")

    # Set headers (A1:M1 — 13 columns)
    sheet.update("A1:M1", [HEADERS], value_input_option="USER_ENTERED")

    # --- FORMAT HEADER ROW ---
    sheet.format("A1:M1", {
        "textFormat": {
            "bold": True, "fontSize": 11,
            "foregroundColor": WHITE, "fontFamily": "Arial",
        },
        "backgroundColor": OXYGN_GREEN,
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
        "borders": {
            "bottom": {"style": "SOLID", "width": 2, "color": {"red": 0, "green": 0, "blue": 0}},
        },
    })

    # --- FORMAT DATA CELLS ---
    sheet.format("A2:M1000", {
        "textFormat": {"fontSize": 10, "fontFamily": "Arial"},
        "verticalAlignment": "MIDDLE",
    })

    # Center-align specific columns
    sheet.format("A2:B1000", {"horizontalAlignment": "CENTER"})   # Fecha, Hora
    sheet.format("D2:E1000", {"horizontalAlignment": "CENTER"})   # Documento, Teléfono
    sheet.format("G2:G1000", {"horizontalAlignment": "CENTER"})   # Ciudad
    sheet.format("H2:H1000", {"horizontalAlignment": "CENTER"})   # Cantidad
    sheet.format("J2:K1000", {"horizontalAlignment": "RIGHT"})    # Precio, Envío
    sheet.format("L2:L1000", {"horizontalAlignment": "CENTER"})   # Método de pago
    sheet.format("M2:M1000", {"horizontalAlignment": "CENTER"})   # Registrado por

    # --- COLUMN WIDTHS ---
    requests = [
        _resize_col(0, 100),   # A: Fecha
        _resize_col(1, 80),    # B: Hora
        _resize_col(2, 180),   # C: Nombre
        _resize_col(3, 120),   # D: Documento
        _resize_col(4, 120),   # E: Teléfono
        _resize_col(5, 250),   # F: Dirección
        _resize_col(6, 140),   # G: Ciudad
        _resize_col(7, 80),    # H: Cantidad
        _resize_col(8, 140),   # I: Colores
        _resize_col(9, 100),   # J: Precio
        _resize_col(10, 80),   # K: Envío
        _resize_col(11, 140),  # L: Método de pago
        _resize_col(12, 130),  # M: Registrado por
    ]

    # Freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet.id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Alternating row colors (banding)
    requests.append({
        "addBanding": {
            "bandedRange": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endColumnIndex": 13,
                },
                "rowProperties": {
                    "headerColor": OXYGN_GREEN,
                    "firstBandColor": WHITE,
                    "secondBandColor": OXYGN_GREEN_LIGHT,
                },
            }
        }
    })

    spreadsheet.batch_update({"requests": requests})

    print("✅ Google Sheet initialized successfully!")
    print(f"   Sheet ID: {GOOGLE_SHEET_ID}")
    print(f"   Tab: Ventas OXYGN")
    print(f"   Columns ({len(HEADERS)}): {', '.join(HEADERS)}")
    print(f"   Format: OXYGN brand colors, alternating rows, frozen header")


def _resize_col(col_index: int, width: int) -> dict:
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": 0, "dimension": "COLUMNS",
                "startIndex": col_index, "endIndex": col_index + 1,
            },
            "properties": {"pixelSize": width},
            "fields": "pixelSize",
        }
    }


if __name__ == "__main__":
    main()
