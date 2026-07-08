"""Thin Telegram Bot API client (httpx, sync)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_WEBHOOK_SECRET,
)

logger = logging.getLogger(__name__)
_API = "https://api.telegram.org"


def telegram_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def _api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"{_API}/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload or {})
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Telegram API %s failed: %s", method, exc)
        return None
    if not body.get("ok"):
        logger.warning("Telegram API %s error: %s", method, body.get("description"))
        return None
    return body.get("result")


def get_bot_username() -> str | None:
    if TELEGRAM_BOT_USERNAME:
        return TELEGRAM_BOT_USERNAME.lstrip("@")
    me = _api("getMe")
    if me and me.get("username"):
        return str(me["username"])
    return None


def send_message(
    chat_id: str,
    text: str,
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _api("sendMessage", payload) is not None


def set_webhook(url: str) -> bool:
    payload: dict[str, Any] = {"url": url, "drop_pending_updates": False}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET
    return _api("setWebhook", payload) is not None


def delete_webhook() -> bool:
    return _api("deleteWebhook", {"drop_pending_updates": False}) is not None


def get_updates(offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    result = _api("getUpdates", payload)
    return result if isinstance(result, list) else []
