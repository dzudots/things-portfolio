"""Push in-app price alerts to linked Telegram chats."""

from __future__ import annotations

import logging

from app.config import PRODUCT_NAME, PUBLIC_BASE_URL
from app.models import PriceAlert, User
from app.telegram.client import send_message, telegram_configured

logger = logging.getLogger(__name__)


def notify_price_alert(alert: PriceAlert, user: User) -> bool:
    if not telegram_configured():
        return False
    if not user.telegram_chat_id or not user.telegram_alerts_enabled:
        return False
    if not user.alerts_enabled:
        return False

    arrow = "📈" if alert.direction == "up" else "📉"
    text = f"{arrow} {PRODUCT_NAME}\n{alert.message}"
    markup = None
    if PUBLIC_BASE_URL:
        markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "Открыть портфель",
                        "url": PUBLIC_BASE_URL.rstrip("/") + "/alerts",
                    }
                ]
            ]
        }
    ok = send_message(user.telegram_chat_id, text, reply_markup=markup)
    if ok:
        logger.info("Telegram alert sent user_id=%s alert_id=%s", user.id, alert.id)
    return ok
