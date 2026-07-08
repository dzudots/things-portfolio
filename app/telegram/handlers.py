"""Process Telegram Bot API updates."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import PRODUCT_NAME, PUBLIC_BASE_URL
from app.telegram.client import send_message
from app.telegram.linking import LINK_PREFIX, consume_link_token

logger = logging.getLogger(__name__)


def _portfolio_button() -> dict | None:
    if not PUBLIC_BASE_URL:
        return None
    url = PUBLIC_BASE_URL.rstrip("/") + "/portfolio"
    return {
        "inline_keyboard": [[{"text": f"Открыть {PRODUCT_NAME}", "url": url}]]
    }


def handle_update(db: Session, update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message or "chat" not in message:
        return

    chat = message["chat"]
    chat_id = str(chat["id"])
    username = chat.get("username")
    text = (message.get("text") or "").strip()

    if not text.startswith("/start"):
        if text.startswith("/"):
            send_message(
                chat_id,
                f"Привет! Я бот {PRODUCT_NAME}. Нажми /start или привяжи аккаунт через сайт → Аккаунт.",
                reply_markup=_portfolio_button(),
            )
        return

    parts = text.split(maxsplit=1)
    payload = parts[1] if len(parts) > 1 else ""

    if payload.startswith(LINK_PREFIX):
        token = payload[len(LINK_PREFIX) :]
        user, err = consume_link_token(db, chat_id, token, username)
        if err:
            send_message(chat_id, err, reply_markup=_portfolio_button())
            return
        send_message(
            chat_id,
            f"Готово — Telegram привязан к {user.email}.\n"
            "Буду присылать алерты, когда рыночная оценка вещи сильно сдвинется.",
            reply_markup=_portfolio_button(),
        )
        logger.info("Telegram linked user_id=%s chat_id=%s", user.id, chat_id)
        return

    send_message(
        chat_id,
        f"Привет! Это {PRODUCT_NAME} — твой стак имущества.\n\n"
        "Чтобы получать push-алерты:\n"
        "1. Зайди на сайт и войди в аккаунт\n"
        "2. Аккаунт → «Подключить Telegram»\n"
        "3. Вернись сюда по ссылке из браузера",
        reply_markup=_portfolio_button(),
    )
