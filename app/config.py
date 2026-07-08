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
# Poe: https://api.poe.com/v1 + bot name as model (vision: claude-haiku-4.5)
AI_API_KEY = os.getenv("THINGS_AI_API_KEY", "")
AI_BASE_URL = os.getenv("THINGS_AI_BASE_URL", "https://api.poe.com/v1").rstrip("/")
AI_MODEL = os.getenv("THINGS_AI_MODEL", "claude-haiku-4.5")
AI_TIMEOUT_SEC = float(os.getenv("THINGS_AI_TIMEOUT_SEC", "60"))
# Force mock even if key is set (tests / offline)
AI_FORCE_MOCK = os.getenv("THINGS_AI_FORCE_MOCK", "").lower() in {"1", "true", "yes"}

# Cost model (USD) — approximate; Poe bills in points. Haiku-class defaults.
AI_INPUT_USD_PER_1M = float(os.getenv("THINGS_AI_INPUT_USD_PER_1M", "0.80"))
AI_OUTPUT_USD_PER_1M = float(os.getenv("THINGS_AI_OUTPUT_USD_PER_1M", "4.00"))
AI_IMAGE_USD = float(os.getenv("THINGS_AI_IMAGE_USD", "0.003"))

# Markup on AI cost billed to user/product: 10–30% depending on model tier
AI_MARKUP_PCT = float(os.getenv("THINGS_AI_MARKUP_PCT", "20"))
# Optional FX for display (RUB)
USD_RUB = float(os.getenv("THINGS_USD_RUB", "90"))

# Free tier scan limits (stability + cost control)
FREE_SCANS_PER_DAY = int(os.getenv("THINGS_FREE_SCANS_PER_DAY", "5"))
PRO_SCANS_PER_DAY = int(os.getenv("THINGS_PRO_SCANS_PER_DAY", "50"))
PRO_ITEM_LIMIT = int(os.getenv("THINGS_PRO_ITEM_LIMIT", "200"))
# Promo codes: CODE:DAYS,CODE2:DAYS — activates Pro without payment gateway
PRO_PROMO_CODES = os.getenv("THINGS_PRO_PROMO_CODES", "STAKBETA30:30,STAKPRO90:90")
MAX_UPLOAD_BYTES = int(os.getenv("THINGS_MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))

UPLOAD_DIR = Path(os.getenv("THINGS_UPLOAD_DIR", str(BASE_DIR / "uploads" / "scans")))

# --- Admin API (ingest / revalue / digest) ---
# Comma-separated emails allowed to call /api/admin/*
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("THINGS_ADMIN_EMAILS", "").split(",")
    if e.strip()
}
# Optional shared secret: Authorization: Bearer <key> or X-Admin-Key header
ADMIN_API_KEY = os.getenv("THINGS_ADMIN_API_KEY", "").strip()

# --- YooKassa (Pro subscription) ---
YOOKASSA_SHOP_ID = os.getenv("THINGS_YOOKASSA_SHOP_ID", "").strip()
YOOKASSA_SECRET_KEY = os.getenv("THINGS_YOOKASSA_SECRET_KEY", "").strip()
YOOKASSA_RETURN_URL = os.getenv("THINGS_YOOKASSA_RETURN_URL", "").rstrip("/")
# Monthly Pro price in RUB (kopecks internally for API)
PRO_PRICE_RUB = int(os.getenv("THINGS_PRO_PRICE_RUB", "299"))
PRO_DAYS_MONTH = int(os.getenv("THINGS_PRO_DAYS_MONTH", "30"))
PRO_DAYS_YEAR = int(os.getenv("THINGS_PRO_DAYS_YEAR", "365"))
PRO_PRICE_YEAR_RUB = int(os.getenv("THINGS_PRO_PRICE_YEAR_RUB", "2990"))  # ~2 months free

# Partner comps feed (JSON URL or local path); empty = skip, mock fallback only
PARTNER_FEED_URL = os.getenv("THINGS_PARTNER_FEED_URL", "").strip()
PARTNER_FEED_PATH = os.getenv("THINGS_PARTNER_FEED_PATH", "").strip()

# --- Telegram (optional: distribution + alert push) ---
TELEGRAM_BOT_TOKEN = os.getenv("THINGS_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("THINGS_TELEGRAM_BOT_USERNAME", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("THINGS_TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_PATH = os.getenv("THINGS_TELEGRAM_WEBHOOK_PATH", "/api/telegram/webhook")
# Public HTTPS base for webhook + deep links (e.g. https://things-portfolio-production.up.railway.app)
PUBLIC_BASE_URL = os.getenv("THINGS_PUBLIC_BASE_URL", "").rstrip("/")
# Local dev only — long-polling instead of webhook (do not use in prod with multiple workers)
TELEGRAM_POLLING = os.getenv("THINGS_TELEGRAM_POLLING", "").lower() in {"1", "true", "yes"}
# Mini App start path (opened inside Telegram WebApp)
TELEGRAM_MINIAPP_PATH = os.getenv("THINGS_TELEGRAM_MINIAPP_PATH", "/tg")
