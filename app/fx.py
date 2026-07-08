"""CIS display currencies + regional market indices (RUB base internally)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import FX_REFRESH_HOURS, FX_RATES_JSON

logger = logging.getLogger(__name__)

# Amounts in DB/comps are RUB. Display conversion: amount_rub * rate_to_display
DEFAULT_RATES: dict[str, float] = {
    "RUB": 1.0,
    "KZT": 5.35,
    "BYN": 1.0 / 28.5,
    "UAH": 1.0 / 2.45,
    "USD": 1.0 / 90.0,
}

CURRENCY_META: dict[str, dict] = {
    "RUB": {"symbol": "₽", "label": "Рубль", "locale": "ru-RU", "decimals": 0},
    "KZT": {"symbol": "₸", "label": "Тенге", "locale": "kk-KZ", "decimals": 0},
    "BYN": {"symbol": "Br", "label": "Бел. рубль", "locale": "be-BY", "decimals": 0},
    "UAH": {"symbol": "₴", "label": "Гривна", "locale": "uk-UA", "decimals": 0},
    "USD": {"symbol": "$", "label": "Доллар", "locale": "en-US", "decimals": 0},
}

DISPLAY_CURRENCIES = list(CURRENCY_META.keys())

_rates_cache: dict[str, float] | None = None
_rates_loaded_at: datetime | None = None


def _parse_rates_json(raw: str) -> dict[str, float]:
    data = json.loads(raw)
    out = dict(DEFAULT_RATES)
    for code in DISPLAY_CURRENCIES:
        if code in data:
            out[code] = float(data[code])
    return out


def get_rates() -> dict[str, float]:
    global _rates_cache, _rates_loaded_at
    now = datetime.now(timezone.utc)
    if FX_RATES_JSON:
        return _parse_rates_json(FX_RATES_JSON)
    if _rates_cache and _rates_loaded_at:
        if now - _rates_loaded_at < timedelta(hours=FX_REFRESH_HOURS):
            return _rates_cache
    try:
        fetched = _fetch_live_rates()
        if fetched:
            _rates_cache = fetched
            _rates_loaded_at = now
            return fetched
    except Exception as exc:
        logger.warning("FX fetch failed, using defaults: %s", exc)
    _rates_cache = dict(DEFAULT_RATES)
    _rates_loaded_at = now
    return _rates_cache


def _fetch_live_rates() -> dict[str, float] | None:
    """Free tier: exchangerate.host (USD base) → derive CIS display rates."""
    with httpx.Client(timeout=8.0) as client:
        resp = client.get(
            "https://api.exchangerate.host/latest",
            params={"base": "USD", "symbols": "RUB,KZT,BYN,UAH"},
        )
        resp.raise_for_status()
        rates = resp.json().get("rates") or {}
    usd_rub = float(rates.get("RUB") or 90.0)
    if usd_rub <= 0:
        return None
    return {
        "RUB": 1.0,
        "USD": 1.0 / usd_rub,
        "KZT": float(rates.get("KZT") or 480.0) / usd_rub,
        "BYN": float(rates.get("BYN") or 3.15) / usd_rub,
        "UAH": float(rates.get("UAH") or 37.0) / usd_rub,
    }


def convert_rub(amount_rub: Optional[float], currency: str) -> Optional[float]:
    if amount_rub is None:
        return None
    code = (currency or "RUB").upper()
    if code not in CURRENCY_META:
        code = "RUB"
    rate = get_rates().get(code, 1.0)
    return float(amount_rub) * rate


def format_amount(amount_rub: Optional[float], currency: str = "RUB") -> str:
    if amount_rub is None:
        return "—"
    code = (currency or "RUB").upper()
    meta = CURRENCY_META.get(code, CURRENCY_META["RUB"])
    value = convert_rub(amount_rub, code) or 0.0
    n = int(round(value)) if meta["decimals"] == 0 else round(value, meta["decimals"])
    if code == "USD":
        return f"${n:,}".replace(",", " ")
    if code == "BYN":
        return f"{n:,} Br".replace(",", " ")
    grouped = f"{n:,}".replace(",", " ")
    return f"{grouped} {meta['symbol']}"


def currency_label(code: str) -> str:
    return CURRENCY_META.get((code or "RUB").upper(), CURRENCY_META["RUB"])["label"]
