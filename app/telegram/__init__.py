"""Telegram bot: account linking + optional price-alert push."""

from app.telegram.client import telegram_configured
from app.telegram.handlers import handle_update
from app.telegram.notify import notify_price_alert
from app.telegram.setup import setup_telegram, shutdown_telegram

__all__ = [
    "handle_update",
    "notify_price_alert",
    "setup_telegram",
    "shutdown_telegram",
    "telegram_configured",
]
