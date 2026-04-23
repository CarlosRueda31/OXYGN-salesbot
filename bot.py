"""
OXYGN Sales Bot - Telegram Bot for tracking sales to Google Sheets
==================================================================
Supports three input modes:
  1. Free text — paste customer data as-is, the bot auto-detects fields
  2. Quick format — /venta with pipe-separated fields
  3. Step-by-step — /nueva guided conversation
"""

import os
import re
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

TZ = ZoneInfo("America/Bogota")
AUTHORIZED_USERS: set[int] = set()  # Empty = allow all users

# Step-by-step states (/nueva) — 11 steps
(S_NOMBRE, S_DOCUMENTO, S_TELEFONO, S_DIRECCION, S_CIUDAD, S_CANTIDAD,
 S_COLORES, S_PRECIO, S_METODO_PAGO, S_ENVIO, S_CONFIRMAR) = range(11)

# Free-text states (asking missing fields)
(F_DOCUMENTO, F_TELEFONO, F_CIUDAD, F_CANTIDAD, F_COLORES, F_PRECIO, F_METODO_PAGO,
 F_ENVIO, F_CONFIRMAR) = range(20, 29)

# --- Colors (Spanish) ---
COLORES_CONOCIDOS = [
    "negro", "negra", "negros", "negras",
    "blanco", "blanca", "blancos", "blancas",
    "azul", "azules",
    "rojo", "roja", "rojos", "rojas",
    "verde", "verdes",
    "rosado", "rosada", "rosados", "rosadas", "rosa",
    "morado", "morada", "morados", "moradas",
    "gris", "grises",
    "naranja", "naranjas",
    "amarillo", "amarilla", "amarillos", "amarillas",
    "beige", "transparente", "transparentes", "cafe", "café",
]
COLOR_MAP = {
    "negra": "negro", "negros": "negro", "negras": "negro",
    "blanca": "blanco", "blancos": "blanco", "blancas": "blanco",
    "azules": "azul",
    "roja": "rojo", "rojos": "rojo", "rojas": "rojo",
    "verdes": "verde",
    "rosada": "rosado", "rosados": "rosado", "rosadas": "rosado", "rosa": "rosado",
    "morada": "morado", "morados": "morado", "moradas": "morado",
    "grises": "gris", "naranjas": "naranja",
    "amarilla": "amarillo", "amarillos": "amarillo", "amarillas": "amarillo",
    "transparentes": "transparente", "cafe": "café",
}

# --- Colombian cities ---
CIUDADES = [
    "bogota", "bogotá", "medellin", "medellín", "cali",
    "barranquilla", "cartagena", "bucaramanga", "pereira",
    "manizales", "santa marta", "ibague", "ibagué",
    "pasto", "neiva", "villavicencio", "armenia",
    "monteria", "montería", "sincelejo", "popayan", "popayán",
    "valledupar", "tunja", "florencia", "quibdo", "quibdó",
    "riohacha", "mocoa", "leticia", "inirida", "inírida",
    "mitu", "mitú", "puerto carreño", "san jose", "san josé",
    "yopal", "arauca", "sogamoso", "duitama", "zipaquira", "zipaquirá",
    "chia", "chía", "soacha", "envigado", "itagui", "itagüí",
    "bello", "sabaneta", "rionegro", "girardot", "fusagasuga", "fusagasugá",
    "palmira", "buenaventura", "tulua", "tuluá", "buga",
    "dosquebradas", "la virginia", "cartago",
    "soledad", "malambo", "sabanalarga",
    "cundinamarca", "antioquia", "valle", "atlantico", "atlántico",
    "bolivar", "bolívar", "santander", "caldas", "risaralda",
    "tolima", "huila", "nariño", "narino", "boyaca", "boyacá",
    "meta", "cesar", "magdalena", "cordoba", "córdoba",
    "sucre", "norte de santander", "cauca", "quindio", "quindío",
]

# --- Address pattern (Colombian address indicators) ---
ADDRESS_PATTERN = re.compile(
    r"|".join([
        r"\bcra\.?\b", r"\bcarrera\b", r"\bcalle\b", r"\bcl\.?\s", r"\bcll\.?\b",
        r"\bav\.?\b", r"\bavenida\b", r"\btransversal\b", r"\btv\.?\b",
        r"\bdiagonal\b", r"\bdg\.?\b", r"\bdiag\.?\b",
        r"#", r"\bno\.\s", r"\bn°",
        r"\bapto\.?\b", r"\bapartamento\b", r"\bapt\.?\b",
        r"\bbarrio\b", r"\bbr\.\s", r"\bconjunto\b", r"\bconj\.?\b",
        r"\bedificio\b", r"\btorre\b", r"\bbloque\b",
        r"\bpiso\b", r"\bmanzana\b", r"\bmz\.?\b",
        r"\bvereda\b", r"\bsector\b",
        r"\bplazuela\b", r"\bparque\b", r"\burbanización\b", r"\burbanizacion\b",
    ]),
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheet():
    """Connect to Google Sheet. Supports both file-based and env var credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID).sheet1


def append_sale(data: dict):
    """Append a sale row to the Google Sheet and update totals."""
    logger.info("append_sale() called with: %s", data.get("nombre", "?"))
    sheet = get_sheet()
    logger.info("Google Sheet connected OK")
    now = datetime.now(TZ)
    row = [
        now.strftime("%Y-%m-%d"),           # A: Fecha
        now.strftime("%H:%M:%S"),           # B: Hora
        data["nombre"],                      # C: Nombre
        data["documento"],                   # D: Documento
        data["telefono"],                    # E: Teléfono
        data["direccion"],                   # F: Dirección
        data["ciudad"],                      # G: Ciudad
        data["cantidad"],                    # H: Cantidad
        data["colores"],                     # I: Colores
        data["precio"],                      # J: Precio
        data["envio"],                       # K: Envío
        data["metodo_pago"],                 # L: Método de pago
        data.get("registrado_por", "Bot"),   # M: Registrado por
    ]

    # 1) Read all current values
    all_vals = sheet.get_all_values()
    logger.info("Sheet has %d rows currently", len(all_vals))

    # 2) Find and delete TOTALES row if it exists
    totales_idx = None
    for i, r in enumerate(all_vals):
        if r and r[0] == "TOTALES":
            totales_idx = i + 1  # 1-based
            break

    if totales_idx:
        sheet.delete_rows(totales_idx)
        logger.info("Deleted TOTALES row at %d", totales_idx)
        all_vals = sheet.get_all_values()

    # 3) Insert new sale at the next row
    insert_at = len(all_vals) + 1
    logger.info("Inserting sale at row %d", insert_at)
    sheet.insert_row(row, insert_at, value_input_option="USER_ENTERED")
    logger.info("Sale inserted OK: %s", data.get("nombre", "?"))

    # 4) Re-add TOTALES row
    _update_totals(sheet)
    logger.info("Totals updated OK")


def _update_totals(sheet):
    """Maintain a dynamic TOTALES row with SUM formulas."""
    all_values = sheet.get_all_values()
    data_rows = []
    for i, row in enumerate(all_values):
        if i == 0:
            continue
        if row[0] in ("TOTALES", ""):
            continue
        data_rows.append(i + 1)

    if not data_rows:
        return

    first_data = data_rows[0]
    last_data = data_rows[-1]
    totals_row = last_data + 1

    totals = [
        "TOTALES", "", "", "", "", "", "",
        f"=SUM(H{first_data}:H{last_data})",
        "",
        f"=SUM(J{first_data}:J{last_data})",
        f"=SUM(K{first_data}:K{last_data})",
        "",
        f'=COUNTA(A{first_data}:A{last_data})&" ventas"',
    ]

    sheet.insert_row(totals, totals_row, value_input_option="USER_ENTERED")

    try:
        sheet.format(f"A{totals_row}:M{totals_row}", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95},
        })
    except Exception as e:
        logger.warning("Could not format totals row: %s", e)


# ---------------------------------------------------------------------------
# Phone vs Document detection (Colombian logic)
# ---------------------------------------------------------------------------
def _is_colombian_phone(digits: str) -> bool:
    """Colombian mobile: starts with 3, exactly 10 digits."""
    return len(digits) == 10 and digits.startswith("3")


def _is_numeric_line(line: str) -> tuple[bool, str]:
    """Check if a line is mostly numeric. Returns (is_numeric, digits_only)."""
    digits_only = re.sub(r"[^\d]", "", line)
    non_digit_chars = len(re.sub(r"[\d\s\+\-\(\)\.]", "", line))
    if 6 <= len(digits_only) <= 15 and non_digit_chars <= 2:
        return True, digits_only
    return False, ""


# ---------------------------------------------------------------------------
# Smart parser — multi-pass regex-based field detection
# ---------------------------------------------------------------------------
def parse_free_text(text: str) -> dict:
    """Parse unstructured customer data into structured fields.

    Uses a 6-pass approach:
      1. Classify numeric lines as phone or document
      2. Detect quantity + colors
      3. Detect price (>= 1000 or with $)
      4. Detect payment method
      5. Separate address from city
      6. Remaining text = customer name
    """
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    result = {}

    used_indices: set[int] = set()
    paquete_line_idx = None
    precio_line_idx = None
    metodo_line_idx = None

    # --- Pass 1: Find ALL numeric lines and classify as phone or document ---
    numeric_lines = []
    for i, line in enumerate(lines):
        is_num, digits = _is_numeric_line(line)
        if is_num:
            numeric_lines.append((i, digits))

    if len(numeric_lines) >= 2:
        for idx, digits in numeric_lines:
            if _is_colombian_phone(digits) and "telefono" not in result:
                result["telefono"] = digits
            elif "documento" not in result:
                result["documento"] = digits
            used_indices.add(idx)
        if "telefono" not in result and "documento" in result:
            pass  # Bot will ask for phone
    elif len(numeric_lines) == 1:
        idx, digits = numeric_lines[0]
        if _is_colombian_phone(digits):
            result["telefono"] = digits
        else:
            result["documento"] = digits
        used_indices.add(idx)

    # --- Pass 2: Identify quantity + colors ---
    for i, line in enumerate(lines):
        if i in used_indices:
            continue
        lower = line.lower()
        paquete_match = re.search(
            r"(\d+)\s*(?:paquetes?|paq\.?|unidades?|und\.?|cajas?)?\s+(.+)",
            lower,
        )
        if paquete_match:
            cantidad_str = paquete_match.group(1)
            rest = paquete_match.group(2).strip()
            found_colors = [c for c in COLORES_CONOCIDOS if re.search(r"\b" + c + r"\b", rest)]
            if found_colors:
                result["cantidad"] = cantidad_str
                normalized = set()
                for color in found_colors:
                    normalized.add(COLOR_MAP.get(color, color))
                result["colores"] = ", ".join(sorted(normalized))
                paquete_line_idx = i
                used_indices.add(i)
                break

    if "colores" not in result:
        for i, line in enumerate(lines):
            if i in used_indices:
                continue
            lower = line.lower()
            found_colors = [c for c in COLORES_CONOCIDOS if re.search(r"\b" + c + r"\b", lower)]
            num_match = re.match(r"(\d+)\s+", lower)
            if num_match and found_colors:
                result["cantidad"] = num_match.group(1)
                normalized = set()
                for color in found_colors:
                    normalized.add(COLOR_MAP.get(color, color))
                result["colores"] = ", ".join(sorted(normalized))
                paquete_line_idx = i
                used_indices.add(i)
                break

    # --- Pass 3: Identify price (>= 1000 or with $) ---
    for i, line in enumerate(lines):
        if i in used_indices:
            continue
        precio_match = re.search(r"\$?\s*([\d]{1,3}(?:[.\,]\d{3})*(?:\d+)?)", line)
        if precio_match:
            precio_str = precio_match.group(1).replace(".", "").replace(",", "")
            if precio_str.isdigit() and int(precio_str) >= 1000:
                result["precio"] = precio_str
                precio_line_idx = i
                used_indices.add(i)
                break

    # --- Pass 4: Identify payment method ---
    metodos = {
        "nequi": "Nequi", "daviplata": "Daviplata",
        "transferencia": "Transferencia", "efectivo": "Efectivo",
        "bancolombia": "Transferencia Bancolombia", "pse": "PSE",
        "tarjeta": "Tarjeta", "contraentrega": "Contraentrega",
    }
    for i, line in enumerate(lines):
        if i in used_indices:
            continue
        lower = line.lower()
        for key, value in metodos.items():
            if key in lower:
                result["metodo_pago"] = value
                metodo_line_idx = i
                used_indices.add(i)
                break
        if "metodo_pago" in result:
            break

    # --- Pass 5: Separate address lines from city lines ---
    address_lines = []
    city_parts = []

    for i, line in enumerate(lines):
        if i in used_indices:
            continue
        lower = line.lower()
        if ADDRESS_PATTERN.search(line):
            address_lines.append(line)
            used_indices.add(i)
            continue
        for ciudad in CIUDADES:
            if ciudad in lower:
                city_parts.append(line)
                used_indices.add(i)
                break

    if address_lines:
        result["direccion"] = " — ".join(address_lines)
    if city_parts:
        result["ciudad"] = ", ".join(city_parts)

    # --- Pass 6: Name = first unidentified line that looks like a name ---
    for i, line in enumerate(lines):
        if i not in used_indices:
            if re.match(r"^[A-Za-záéíóúñÁÉÍÓÚÑüÜ\s\.]{2,}$", line):
                result["nombre"] = line
                used_indices.add(i)
                break

    if "nombre" not in result:
        for i, line in enumerate(lines):
            if i not in used_indices:
                result["nombre"] = line
                break

    return result


def format_parsed_data(data: dict) -> str:
    """Format parsed data into a readable summary."""
    fields = [
        ("🧑 Nombre", data.get("nombre", "❓ No detectado")),
        ("🪪 Documento", data.get("documento", "❓ No detectado")),
        ("📱 Teléfono", data.get("telefono", "❓ No detectado")),
        ("📍 Dirección", data.get("direccion", "❓ No detectada")),
        ("🏙 Ciudad", data.get("ciudad", "❓ No detectada")),
        ("📦 Cantidad", f"{data.get('cantidad', '❓')} paquete(s)"),
        ("🎨 Colores", data.get("colores", "❓ No detectados")),
        ("💰 Precio", f"${data['precio']}" if "precio" in data else "❓ No detectado"),
        ("🚚 Envío", data.get("envio", "❓ No especificado")),
        ("💳 Método pago", data.get("metodo_pago", "❓ No detectado")),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def is_authorized(user_id: int) -> bool:
    if not AUTHORIZED_USERS:
        return True
    return user_id in AUTHORIZED_USERS


# ---------------------------------------------------------------------------
# Helper: ask the next missing field in free-text flow
# ---------------------------------------------------------------------------
async def _ask_next_missing(update, context):
    d = context.user_data

    if "documento" not in d:
        await update.message.reply_text(
            "🪪 ¿Cuál es el *número de documento* (cédula) del comprador?",
            parse_mode="Markdown",
        )
        return F_DOCUMENTO

    if "telefono" not in d:
        await update.message.reply_text(
            "📱 ¿Cuál es el *número de teléfono* del comprador?",
            parse_mode="Markdown",
        )
        return F_TELEFONO

    if "ciudad" not in d:
        await update.message.reply_text(
            "🏙 ¿De qué *ciudad* es el comprador?",
            parse_mode="Markdown",
        )
        return F_CIUDAD

    if "cantidad" not in d:
        await update.message.reply_text(
            "📦 ¿*Cuántos paquetes*? (escribe el número)",
            parse_mode="Markdown",
        )
        return F_CANTIDAD

    if "colores" not in d:
        await update.message.reply_text(
            "🎨 ¿*Qué colores*? (separados por coma, ej: rosa, negro)",
            parse_mode="Markdown",
        )
        return F_COLORES

    if "precio" not in d:
        await update.message.reply_text(
            "💰 ¿Cuál es el *precio total* de la venta?",
            parse_mode="Markdown",
        )
        return F_PRECIO

    if "metodo_pago" not in d:
        keyboard = [["Nequi", "Daviplata"], ["Transferencia", "Efectivo"], ["Otro"]]
        await update.message.reply_text(
            "💳 ¿*Método de pago*?",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        )
        return F_METODO_PAGO

    if "envio" not in d:
        keyboard = [["Gratis", "$5.000"], ["$8.000", "$10.000"], ["$12.000", "$15.000"]]
        await update.message.reply_text(
            "🚚 ¿Cuánto costó el *envío*? (o escribe el valor)",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        )
        return F_ENVIO

    summary = format_parsed_data(d)
    await update.message.reply_text(
        f"📝 *Resumen final:*\n\n{summary}\n\n¿Todo correcto? *Sí* o *No*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["Sí ✅", "No ❌"]], one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return F_CONFIRMAR


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👃 *¡Bienvenido al Bot de Ventas OXYGN!*\n\n"
        "Tienes tres formas de registrar una venta:\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📝 *Opción 1 — Texto libre*\n"
        "Pega los datos tal como te los mandan.\n"
        "El bot detecta automáticamente cada campo.\n"
        "Si falta algo, te lo pregunta.\n\n"
        "Ejemplo:\n"
        "`Ingrid Becerra`\n"
        "`1060655877`\n"
        "`3101234567`\n"
        "`Cra 23 # 73-39`\n"
        "`Manizales, Caldas`\n"
        "`1 paquete negro`\n\n"
        "📱 Teléfono = empieza con 3, 10 dígitos\n"
        "🪪 Documento = cualquier otro número\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *Opción 2 — Formato rápido*\n"
        "Usa /venta con 10 campos separados por `|`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💬 *Opción 3 — Paso a paso*\n"
        "Envía /nueva y el bot te guía.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 Otros comandos:\n"
        "  /resumen — Resumen de ventas de hoy\n"
        "  /myid — Ver tu ID de Telegram\n"
        "  /ayuda — Mostrar este mensaje\n"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.full_name
    await update.message.reply_text(f"Tu ID de Telegram es: `{uid}`\nNombre: {name}", parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Quick sale: /venta
# ---------------------------------------------------------------------------
async def venta_rapida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    text = update.message.text.replace("/venta", "", 1).strip()
    parts = [p.strip() for p in text.split("|")]

    if len(parts) != 10:
        await update.message.reply_text(
            "⚠️ Necesitas 10 campos separados por `|`\n\n"
            "Ejemplo:\n"
            "`/venta Juan Pérez | 1060655877 | 3101234567 | Cra 23 #10 | Bogotá | 2 | azul, negro | 50000 | Nequi | 8000`\n\n"
            "Orden: Nombre | Doc | Tel | Dir | Ciudad | Cant | Colores | Precio | Pago | Envío",
            parse_mode="Markdown",
        )
        return

    envio_val = parts[9]
    if envio_val.lower() in ("gratis", "0", "free", "no"):
        envio_val = "0"

    data = {
        "nombre": parts[0], "documento": parts[1], "telefono": parts[2],
        "direccion": parts[3], "ciudad": parts[4],
        "cantidad": parts[5], "colores": parts[6],
        "precio": parts[7], "metodo_pago": parts[8], "envio": envio_val,
        "registrado_por": update.effective_user.full_name,
    }

    try:
        append_sale(data)
        envio_display = "Gratis" if data["envio"] == "0" else f"${data['envio']}"
        await update.message.reply_text(
            f"✅ *Venta registrada*\n\n"
            f"🧑 {data['nombre']}\n"
            f"🪪 Doc: {data['documento']}\n"
            f"📱 Tel: {data['telefono']}\n"
            f"📍 {data['direccion']}\n"
            f"🏙 {data['ciudad']}\n"
            f"📦 {data['cantidad']} paquete(s)\n"
            f"🎨 {data['colores']}\n"
            f"💰 ${data['precio']}\n"
            f"🚚 Envío: {envio_display}\n"
            f"💳 {data['metodo_pago']}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Error appending sale: %s", e)
        await update.message.reply_text("❌ Error al registrar. Intenta de nuevo.")


# ---------------------------------------------------------------------------
# Free-text conversation
# ---------------------------------------------------------------------------
async def free_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    text = update.message.text.strip()
    if len(text) < 8 or "\n" not in text:
        return

    parsed = parse_free_text(text)

    recognized = sum(1 for k in ["nombre", "telefono", "documento", "direccion", "ciudad", "cantidad", "colores"] if k in parsed)
    if recognized < 2:
        return

    context.user_data.update(parsed)
    context.user_data["registrado_por"] = update.effective_user.full_name

    summary = format_parsed_data(parsed)
    await update.message.reply_text(f"🔍 *Datos detectados:*\n\n{summary}", parse_mode="Markdown")

    return await _ask_next_missing(update, context)


async def free_documento_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["documento"] = update.message.text.strip()
    return await _ask_next_missing(update, context)


async def free_telefono_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["telefono"] = update.message.text.strip()
    return await _ask_next_missing(update, context)


async def free_ciudad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ciudad"] = update.message.text.strip()
    return await _ask_next_missing(update, context)


async def free_cantidad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cantidad"] = update.message.text.strip()
    return await _ask_next_missing(update, context)


async def free_colores_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["colores"] = update.message.text.strip()
    return await _ask_next_missing(update, context)


async def free_precio_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["precio"] = update.message.text.strip().replace("$", "").replace(".", "").replace(",", "")
    return await _ask_next_missing(update, context)


async def free_metodo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["metodo_pago"] = update.message.text.strip()
    return await _ask_next_missing(update, context)


async def free_envio_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("gratis", "0", "free", "no", "sin costo"):
        context.user_data["envio"] = "0"
    else:
        context.user_data["envio"] = text.replace("$", "").replace(".", "").replace(",", "")
    return await _ask_next_missing(update, context)


async def free_confirmar_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text.startswith("sí") or text.startswith("si") or text == "s":
        data = dict(context.user_data)
        data.setdefault("nombre", "Sin nombre")
        data.setdefault("documento", "Sin documento")
        data.setdefault("telefono", "Sin teléfono")
        data.setdefault("direccion", "Sin dirección")
        data.setdefault("ciudad", "Sin ciudad")
        data.setdefault("cantidad", "1")
        data.setdefault("colores", "Sin especificar")
        data.setdefault("precio", "0")
        data.setdefault("envio", "0")
        data.setdefault("metodo_pago", "Sin especificar")
        try:
            append_sale(data)
            await update.message.reply_text("✅ *¡Venta registrada en Google Sheets!*", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            logger.error("Error writing to sheet: %s", e, exc_info=True)
            await update.message.reply_text(f"❌ Error al registrar: {e}", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("🔄 Cancelada. Puedes enviar los datos de nuevo.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Step-by-step: /nueva
# ---------------------------------------------------------------------------
async def nueva_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return ConversationHandler.END
    await update.message.reply_text("📋 *Paso 1/10* — ¿*Nombre completo* del comprador?", parse_mode="Markdown")
    return S_NOMBRE

async def s_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre"] = update.message.text.strip()
    await update.message.reply_text("🪪 *Paso 2/10* — ¿*Número de documento* (cédula)?", parse_mode="Markdown")
    return S_DOCUMENTO

async def s_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["documento"] = update.message.text.strip()
    await update.message.reply_text("📱 *Paso 3/10* — ¿*Número de teléfono*?", parse_mode="Markdown")
    return S_TELEFONO

async def s_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["telefono"] = update.message.text.strip()
    await update.message.reply_text("📍 *Paso 4/10* — ¿*Dirección* de envío?", parse_mode="Markdown")
    return S_DIRECCION

async def s_direccion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["direccion"] = update.message.text.strip()
    await update.message.reply_text("🏙 *Paso 5/10* — ¿*Ciudad*?", parse_mode="Markdown")
    return S_CIUDAD

async def s_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ciudad"] = update.message.text.strip()
    await update.message.reply_text("📦 *Paso 6/10* — ¿*Cuántos paquetes*?", parse_mode="Markdown")
    return S_CANTIDAD

async def s_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cantidad"] = update.message.text.strip()
    await update.message.reply_text("🎨 *Paso 7/10* — ¿*Qué colores*? (separados por coma)", parse_mode="Markdown")
    return S_COLORES

async def s_colores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["colores"] = update.message.text.strip()
    await update.message.reply_text("💰 *Paso 8/10* — ¿*Precio total*?", parse_mode="Markdown")
    return S_PRECIO

async def s_precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["precio"] = update.message.text.strip()
    keyboard = [["Nequi", "Daviplata"], ["Transferencia", "Efectivo"], ["Otro"]]
    await update.message.reply_text("💳 *Paso 9/10* — ¿*Método de pago*?", parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return S_METODO_PAGO

async def s_metodo_pago(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["metodo_pago"] = update.message.text.strip()
    keyboard = [["Gratis", "$5.000"], ["$8.000", "$10.000"], ["$12.000", "$15.000"]]
    await update.message.reply_text("🚚 *Paso 10/10* — ¿Cuánto costó el *envío*?", parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))
    return S_ENVIO

async def s_envio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text in ("gratis", "0", "free", "no", "sin costo"):
        context.user_data["envio"] = "0"
    else:
        context.user_data["envio"] = text.replace("$", "").replace(".", "").replace(",", "")
    d = context.user_data
    envio_display = "Gratis" if d["envio"] == "0" else f"${d['envio']}"
    await update.message.reply_text(
        f"📝 *Confirma los datos:*\n\n"
        f"🧑 {d['nombre']}\n🪪 Doc: {d['documento']}\n📱 Tel: {d['telefono']}\n"
        f"📍 {d['direccion']}\n🏙 {d['ciudad']}\n"
        f"📦 {d['cantidad']} paquete(s)\n🎨 {d['colores']}\n"
        f"💰 ${d['precio']}\n🚚 Envío: {envio_display}\n💳 {d['metodo_pago']}\n\n"
        f"¿Todo correcto? *Sí* o *No*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["Sí ✅", "No ❌"]], one_time_keyboard=True, resize_keyboard=True))
    return S_CONFIRMAR

async def s_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text.startswith("sí") or text.startswith("si") or text == "s":
        data = {**context.user_data, "registrado_por": update.effective_user.full_name}
        try:
            append_sale(data)
            await update.message.reply_text("✅ *¡Venta registrada en Google Sheets!*", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            logger.error("Error writing to sheet: %s", e, exc_info=True)
            await update.message.reply_text(f"❌ Error al registrar: {e}", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("🔄 Cancelado. Envía /nueva de nuevo.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🔄 Registro cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /resumen — Daily sales summary
# ---------------------------------------------------------------------------
async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso.")
        return
    try:
        sheet = get_sheet()
        records = sheet.get_all_values()
        today = datetime.now(TZ).strftime("%Y-%m-%d")

        today_sales = [r for r in records[1:] if r[0] == today]
        total_sales = len(today_sales)
        if total_sales == 0:
            await update.message.reply_text("📊 No hay ventas registradas hoy aún.")
            return

        total_paquetes = sum(int(r[7]) for r in today_sales if r[7].isdigit())
        total_dinero = total_envio = 0
        for r in today_sales:
            try:
                total_dinero += float(r[9].replace(",", "").replace(".", "").replace("$", ""))
            except (ValueError, IndexError):
                pass
            try:
                total_envio += float(r[10].replace(",", "").replace(".", "").replace("$", ""))
            except (ValueError, IndexError):
                pass

        await update.message.reply_text(
            f"📊 *Resumen de hoy ({today})*\n\n"
            f"🛒 Ventas: {total_sales}\n"
            f"📦 Paquetes: {total_paquetes}\n"
            f"💰 Total ventas: ${total_dinero:,.0f}\n"
            f"🚚 Total envíos: ${total_envio:,.0f}\n"
            f"💵 Gran total: ${total_dinero + total_envio:,.0f}",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Error: %s", e)
        await update.message.reply_text("❌ Error al obtener el resumen.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    step_conv = ConversationHandler(
        entry_points=[CommandHandler("nueva", nueva_start)],
        states={
            S_NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_nombre)],
            S_DOCUMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_documento)],
            S_TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_telefono)],
            S_DIRECCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_direccion)],
            S_CIUDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_ciudad)],
            S_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_cantidad)],
            S_COLORES: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_colores)],
            S_PRECIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_precio)],
            S_METODO_PAGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_metodo_pago)],
            S_ENVIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_envio)],
            S_CONFIRMAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, s_confirmar)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    free_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, free_text_entry)],
        states={
            F_DOCUMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_documento_received)],
            F_TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_telefono_received)],
            F_CIUDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_ciudad_received)],
            F_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_cantidad_received)],
            F_COLORES: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_colores_received)],
            F_PRECIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_precio_received)],
            F_METODO_PAGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_metodo_received)],
            F_ENVIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_envio_received)],
            F_CONFIRMAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, free_confirmar_received)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("venta", venta_rapida))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(step_conv)
    app.add_handler(free_conv)

    logger.info("OXYGN Sales Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
