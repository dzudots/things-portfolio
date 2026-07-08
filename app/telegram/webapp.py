"""Telegram Mini App initData validation + session bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from sqlalchemy.orm import Session

from app.config import TELEGRAM_BOT_TOKEN
from app.models import User


def validate_init_data(init_data: str, *, max_age_sec: int = 86400) -> dict | None:
    """
    Validate Telegram WebApp initData (HMAC-SHA256).
    Returns parsed fields dict or None if invalid.
    """
    if not TELEGRAM_BOT_TOKEN or not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(
        b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    calc = hmac.new(secret_key, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None
    try:
        auth_date = int(pairs.get("auth_date") or 0)
    except ValueError:
        return None
    if auth_date and (time.time() - auth_date) > max_age_sec:
        return None
    if "user" in pairs:
        try:
            pairs["user"] = json.loads(pairs["user"])
        except json.JSONDecodeError:
            return None
    return pairs


def user_from_init_data(db: Session, init_data: str) -> User | None:
    """Resolve linked User by Telegram chat/user id from validated initData."""
    parsed = validate_init_data(init_data)
    if not parsed:
        return None
    tg_user = parsed.get("user")
    if not isinstance(tg_user, dict) or "id" not in tg_user:
        return None
    chat_id = str(tg_user["id"])
    return db.query(User).filter(User.telegram_chat_id == chat_id).first()
