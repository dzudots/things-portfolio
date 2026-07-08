"""Webhook registration or dev polling loop."""

from __future__ import annotations

import logging
import threading
import time

from app.config import PUBLIC_BASE_URL, TELEGRAM_POLLING, TELEGRAM_WEBHOOK_PATH
from app.models import SessionLocal
from app.telegram.client import delete_webhook, get_updates, set_webhook, telegram_configured
from app.telegram.handlers import handle_update

logger = logging.getLogger(__name__)

_poller: threading.Thread | None = None
_stop = threading.Event()


def _poll_loop() -> None:
    offset: int | None = None
    logger.info("Telegram long-polling started")
    while not _stop.is_set():
        try:
            updates = get_updates(offset=offset, timeout=25)
            for upd in updates:
                upd_id = upd.get("update_id")
                if isinstance(upd_id, int):
                    offset = upd_id + 1
                db = SessionLocal()
                try:
                    handle_update(db, upd)
                finally:
                    db.close()
        except Exception:
            logger.exception("Telegram polling error")
            time.sleep(3)


def setup_telegram() -> None:
    if not telegram_configured():
        return

    if TELEGRAM_POLLING:
        delete_webhook()
        global _poller
        if _poller is None or not _poller.is_alive():
            _stop.clear()
            _poller = threading.Thread(target=_poll_loop, name="telegram-poll", daemon=True)
            _poller.start()
        return

    if PUBLIC_BASE_URL:
        webhook_url = PUBLIC_BASE_URL.rstrip("/") + TELEGRAM_WEBHOOK_PATH
        if set_webhook(webhook_url):
            logger.info("Telegram webhook set: %s", webhook_url)
        else:
            logger.warning("Failed to set Telegram webhook at %s", webhook_url)


def shutdown_telegram() -> None:
    _stop.set()
