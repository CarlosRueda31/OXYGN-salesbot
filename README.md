# OXYGN Sales Bot

<p align="center">
  <img src="banner.png" alt="OXYGN Sales Bot — WhatsApp to Telegram to Google Sheets" width="100%" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Telegram-Bot%20API-26A5E4?logo=telegram&logoColor=white" />
  <img src="https://img.shields.io/badge/Google%20Sheets-API%20v4-34A853?logo=google-sheets&logoColor=white" />
  <img src="https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white" />
</p>

A Telegram bot built for **OXYGN**, My own Colombian e-commerce business, to automate sales tracking directly into Google Sheets. The bot replaces manual data entry by parsing unstructured customer data from WhatsApp/Instagram conversations and organizing it into a structured spreadsheet.

---

## The Problem

OXYGN receives customer orders via WhatsApp and Instagram in unstructured text formats. Previously, each sale had to be manually entered into a Google Sheet — a tedious, error-prone process that slowed down operations across a team of 3 partners in different countries.

## The Solution

A Telegram bot that accepts customer data in **three flexible input modes**, automatically parses and classifies the information, and writes it to a shared Google Sheet in real time.

---

## Features

**Three Input Modes:**

- **Free text** — Paste raw customer data (copy-pasted from WhatsApp). The bot uses regex-based NLP to detect names, phone numbers, IDs, addresses, cities, colors, prices, and payment methods automatically.
- **Quick format** (`/venta`) — One-line entry with pipe-separated fields for fast input.
- **Step-by-step** (`/nueva`) — Guided 10-step conversation for complete data entry.

**Smart Data Parsing:**

- Distinguishes Colombian phone numbers (10 digits, starts with `3`) from document/ID numbers
- Detects 45+ Colombian cities and classifies address components using regex patterns
- Recognizes color names in Spanish (with normalization: "rosa" → "rosado", "negra" → "negro")
- Identifies payment methods (Nequi, Daviplata, Transferencia, Efectivo, etc.)
- Asks follow-up questions for any fields not detected

**Google Sheets Integration:**

- Auto-generates 13-column rows: Date, Time, Name, Document, Phone, Address, City, Quantity, Colors, Price, Shipping, Payment Method, Registered By
- Maintains a dynamic TOTALES row with SUM formulas
- OXYGN-branded formatting (green headers, alternating row colors)

**Other:**

- `/resumen` — Daily sales summary with totals
- Cloud-deployed on Railway for 24/7 availability
- Supports both file-based and environment variable credentials

---

## Tech Stack

| Technology | Purpose |
|---|---|
| Python 3.11 | Core language |
| python-telegram-bot 21.6 | Telegram Bot API wrapper |
| gspread 6.1.4 | Google Sheets API client |
| google-auth | Service Account authentication |
| Railway | Cloud hosting (free tier) |

---

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌───────────────┐
│  WhatsApp /  │     │   Telegram Bot   │     │ Google Sheets │
│  Instagram   │────>│   (Python)       │────>│   (gspread)   │
│  customers   │     │                  │     │               │
└─────────────┘     │  • Free text     │     │  13-column    │
                    │    parser        │     │  sales log    │
  User pastes       │  • Step-by-step  │     │  + TOTALES    │
  data into         │  • Quick format  │     │  auto-row     │
  Telegram          │  • Smart field   │     │               │
                    │    detection     │     │  Shared with  │
                    └──────────────────┘     │  3 partners   │
                           │                └───────────────┘
                           │
                    ┌──────────────┐
                    │   Railway    │
                    │  (24/7 host) │
                    └──────────────┘
```

---

## Project Structure

```
oxygn-sales-bot/
├── bot.py              # Main bot logic (900+ lines)
├── setup_sheet.py      # One-time Google Sheet initializer
├── requirements.txt    # Python dependencies
├── Procfile            # Railway process definition
├── runtime.txt         # Python version for Railway
├── .env.example        # Environment variables template
└── .gitignore          # Excluded files
```

---

## Setup

### Prerequisites

- Python 3.11+
- A Telegram Bot (create via [@BotFather](https://t.me/BotFather))
- A Google Cloud project with Sheets API & Drive API enabled
- A Google service account with JSON credentials

### 1. Clone the repository

```bash
git clone https://github.com/CarlosRueda31/oxygn-sales-bot.git
cd oxygn-sales-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
GOOGLE_SHEET_ID=your_google_sheet_id
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
```

### 4. Initialize Google Sheet (first time only)

```bash
python setup_sheet.py
```

This creates the headers, applies OXYGN branding, and sets column widths.

### 5. Run the bot

```bash
python bot.py
```

### 6. Deploy to Railway (optional)

1. Push to GitHub
2. Connect the repo to [Railway](https://railway.app)
3. Add environment variables in Railway dashboard
4. Deploy — the `Procfile` handles the rest

---

## Usage Examples

### Free Text (paste from WhatsApp)

```
Ingrid Becerra
1060655877
3022242533
Cra 23 # 73 - 39 — Apto B6, Plazuela de los Almendros
Manizales, Caldas
1 negro
77000
Nequi
```

The bot will parse all fields, ask for anything missing, show a confirmation summary, and write to the sheet.

### Quick Format

```
/venta Juan Pérez | 1060655877 | 3101234567 | Cra 23 #10 | Bogotá | 2 | azul, negro | 50000 | Nequi | 8000
```

### Step by Step

```
/nueva
```

The bot guides you through 10 steps with keyboard buttons for payment methods and shipping costs.

---

## Google Sheet Output

| Fecha | Hora | Nombre | Documento | Teléfono | Dirección | Ciudad | Cantidad | Colores | Precio | Envío | Método de Pago | Registrado Por |
|-------|------|--------|-----------|----------|-----------|--------|----------|---------|--------|-------|----------------|----------------|
| 2026-04-08 | 16:25:22 | Ingrid Becerra | 1060655877 | 3022242533 | Cra 23 # 73-39 — Apto B6 | Manizales, Caldas | 1 | negro | 77000 | 0 | Nequi | Carlos |
| **TOTALES** | | | | | | | **1** | | **77000** | **0** | | **1 ventas** |

---

## Key Technical Decisions

- **Phone vs. Document detection**: Colombian mobile numbers start with `3` and have exactly 10 digits. Any other numeric sequence is classified as a document/ID number.
- **Address parsing**: Uses a comprehensive regex pattern matching 30+ Colombian address indicators (Cra, Calle, Barrio, Edificio, etc.) with word boundaries to avoid false matches inside names.
- **Color normalization**: Maps Spanish color variations to canonical forms ("negra"/"negros"/"negras" → "negro") to avoid duplicates.
- **TOTALES row management**: Deletes and re-inserts the totals row on each sale to maintain accurate SUM formulas.

---

## Author

**Carlos Rueda** — [GitHub](https://github.com/CarlosRueda31)

Built as a real-world automation tool for OXYGN, a nasal band business operating across Colombia.

---

## License

This project is open source under the [MIT License](LICENSE).
