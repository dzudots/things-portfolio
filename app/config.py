from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def _database_url() -> str:
    # Railway Postgres injects DATABASE_URL (postgres://...); SQLAlchemy wants postgresql://
    raw = os.getenv("THINGS_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    if raw:
        if raw.startswith("postgres://"):
            raw = "postgresql://" + raw[len("postgres://") :]
        return raw
    return f"sqlite:///{BASE_DIR / 'things.db'}"


DATABASE_URL = _database_url()
SECRET_KEY = os.getenv("THINGS_SECRET_KEY", "things-portfolio-dev-secret-change-me")
DATA_ENCRYPTION_KEY = os.getenv("THINGS_DATA_KEY", "")

SESSION_COOKIE = "things_session"
COMPS_WINDOW_DAYS = 30
MIN_COMPS_FOR_CONFIDENCE = 5
FREE_ITEM_LIMIT = 20
DEFAULT_ALERT_THRESHOLD_PCT = 5.0

PRODUCT_NAME = os.getenv("THINGS_PRODUCT_NAME", "Стак")
PRODUCT_TAGLINE = os.getenv("THINGS_PRODUCT_TAGLINE", "твой стак имущества")

PRODUCT_PURPOSE = "personal_household_inventory"
NO_TAX_REPORTING = True

# CIS FX display (internal amounts stay RUB)
FX_RATES_JSON = os.getenv("THINGS_FX_RATES_JSON", "")
FX_REFRESH_HOURS = float(os.getenv("THINGS_FX_REFRESH_HOURS", "12"))
COMP_RECENCY_HALF_LIFE_DAYS = float(os.getenv("THINGS_COMP_HALF_LIFE_DAYS", "10"))

# --- AI / vision providers (OpenAI-compatible: OpenAI, Poe, OpenRouter, etc.) ---
AI_API_KEY = os.getenv("THINGS_AI_API_KEY", "")
AI_BASE_URL = os.getenv("THINGS_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("THINGS_AI_MODEL", "gpt-4o-mini")
AI_TIMEOUT_SEC = float(os.getenv("THINGS_AI_TIMEOUT_SEC", "45"))
# Force mock even if key is set (tests / offline)
AI_FORCE_MOCK = os.getenv("THINGS_AI_FORCE_MOCK", "").lower() in {"1", "true", "yes"}

# Cost model (USD) — tune per provider invoice; used for pass-through + markup
AI_INPUT_USD_PER_1M = float(os.getenv("THINGS_AI_INPUT_USD_PER_1M", "0.15"))
AI_OUTPUT_USD_PER_1M = float(os.getenv("THINGS_AI_OUTPUT_USD_PER_1M", "0.60"))
AI_IMAGE_USD = float(os.getenv("THINGS_AI_IMAGE_USD", "0.0025"))

# Markup on AI cost billed to user/product: 10–30% depending on model tier
AI_MARKUP_PCT = float(os.getenv("THINGS_AI_MARKUP_PCT", "20"))
# Optional FX for display (RUB)
USD_RUB = float(os.getenv("THINGS_USD_RUB", "90"))

# Free tier scan limits (stability + cost control)
FREE_SCANS_PER_DAY = int(os.getenv("THINGS_FREE_SCANS_PER_DAY", "5"))
PRO_SCANS_PER_DAY = int(os.getenv("THINGS_PRO_SCANS_PER_DAY", "50"))
MAX_UPLOAD_BYTES = int(os.getenv("THINGS_MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))

UPLOAD_DIR = Path(os.getenv("THINGS_UPLOAD_DIR", str(BASE_DIR / "uploads" / "scans")))

# --- Telegram (optional: distribution + alert push) ---
TELEGRAM_BOT_TOKEN = os.getenv("THINGS_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("THINGS_TELEGRAM_BOT_USERNAME", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("THINGS_TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_PATH = os.getenv("THINGS_TELEGRAM_WEBHOOK_PATH", "/api/telegram/webhook")
# Public HTTPS base for webhook + deep links (e.g. https://things-portfolio-production.up.railway.app)
PUBLIC_BASE_URL = os.getenv("THINGS_PUBLIC_BASE_URL", "").rstrip("/")
# Local dev only — long-polling instead of webhook (do not use in prod with multiple workers)
TELEGRAM_POLLING = os.getenv("THINGS_TELEGRAM_POLLING", "").lower() in {"1", "true", "yes"}
