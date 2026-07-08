"""Push in-app price alerts and weekly digests to linked Telegram chats."""

from __future__ import annotations

import logging

from app.config import PRODUCT_NAME, PUBLIC_BASE_URL
from app.models import PriceAlert, User, WeeklyDigest
from app.telegram.client import send_message, telegram_configured

logger = logging.getLogger(__name__)


def _markup(path: str = "/portfolio") -> dict | None:
    if not PUBLIC_BASE_URL:
        return None
    base = PUBLIC_BASE_URL.rstrip("/")
    return {
        "inline_keyboard": [
            [{"text": "Открыть портфель", "url": base + path}],
            [{"text": "Mini App", "web_app": {"url": base + "/tg"}}],
        ]
    }


def notify_price_alert(alert: PriceAlert, user: User) -> bool:
    if not telegram_configured():
        return False
    if not user.telegram_chat_id or not user.telegram_alerts_enabled:
        return False
    if not user.alerts_enabled:
        return False

    arrow = "📉" if alert.direction == "down" else "📈"
    text = f"{arrow} {PRODUCT_NAME}\n{alert.message}"
    item_path = f"/items/{alert.item_id}" if alert.item_id else "/alerts"
    ok = send_message(user.telegram_chat_id, text, reply_markup=_markup(item_path))
    if ok:
        logger.info("Telegram alert sent user_id=%s alert_id=%s", user.id, alert.id)
    return ok


def notify_weekly_digest(digest: WeeklyDigest, user: User) -> bool:
    if not telegram_configured():
        return False
    if not user.telegram_chat_id or not user.telegram_alerts_enabled:
        return False
    if not user.digest_enabled:
        return False

    sign = "+" if digest.delta_week >= 0 else ""
    text = (
        f"📊 {PRODUCT_NAME} · дайджест недели\n"
        f"Стак: {int(digest.total_mid):,} ₽\n"
        f"За неделю: {sign}{int(digest.delta_week):,} ₽\n"
        f"Неделя с {digest.week_start}"
    ).replace(",", " ")
    ok = send_message(user.telegram_chat_id, text, reply_markup=_markup("/portfolio"))
    if ok:
        logger.info("Telegram digest sent user_id=%s digest_id=%s", user.id, digest.id)
    return ok
