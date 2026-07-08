"""Process Telegram Bot API updates."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, joinedload

from app.config import PRODUCT_NAME, PUBLIC_BASE_URL
from app.models import Item, User
from app.telegram.client import send_message
from app.telegram.linking import LINK_PREFIX, consume_link_token, unlink_telegram
from app.valuation import display_mid, latest_snapshot

logger = logging.getLogger(__name__)


def _portfolio_button() -> dict | None:
    if not PUBLIC_BASE_URL:
        return None
    url = PUBLIC_BASE_URL.rstrip("/") + "/portfolio"
    return {
        "inline_keyboard": [[{"text": f"Открыть {PRODUCT_NAME}", "url": url}]]
    }


def _miniapp_button() -> dict | None:
    if not PUBLIC_BASE_URL:
        return None
    # WebApp button opens Mini App shell inside Telegram
    return {
        "inline_keyboard": [
            [
                {
                    "text": f"Открыть {PRODUCT_NAME}",
                    "web_app": {"url": PUBLIC_BASE_URL.rstrip("/") + "/tg"},
                }
            ],
            [
                {
                    "text": "В браузере",
                    "url": PUBLIC_BASE_URL.rstrip("/") + "/portfolio",
                }
            ],
        ]
    }


def _user_by_chat(db: Session, chat_id: str) -> User | None:
    return db.query(User).filter(User.telegram_chat_id == str(chat_id)).first()


def _status_text(db: Session, user: User) -> str:
    items = (
        db.query(Item)
        .options(joinedload(Item.model), joinedload(Item.valuations))
        .filter(Item.owner_id == user.id)
        .all()
    )
    total = 0.0
    n = 0
    for item in items:
        mid = display_mid(item, latest_snapshot(item))
        if mid is None:
            continue
        total += mid
        n += 1
    plan = "Pro" if (user.plan or "free") == "pro" else "Free"
    return (
        f"{PRODUCT_NAME} · статус\n"
        f"Вещей: {n}\n"
        f"Сумма стака: {int(total):,} ₽\n".replace(",", " ")
        + f"Тариф: {plan}"
    )


def _help_text() -> str:
    return (
        f"Команды {PRODUCT_NAME}:\n"
        "/start — привязка и приветствие\n"
        "/status — сумма стака\n"
        "/unlink — отвязать Telegram\n"
        "/help — эта справка"
    )


def handle_update(db: Session, update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message or "chat" not in message:
        return

    chat = message["chat"]
    chat_id = str(chat["id"])
    username = chat.get("username")
    text = (message.get("text") or "").strip()
    if not text:
        return

    cmd = text.split()[0].split("@")[0].lower()

    if cmd == "/start":
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
                "Буду присылать алерты и еженедельный дайджест стака.\n"
                "Команды: /status · /unlink",
                reply_markup=_miniapp_button() or _portfolio_button(),
            )
            logger.info("Telegram linked user_id=%s chat_id=%s", user.id, chat_id)
            return

        send_message(
            chat_id,
            f"Привет! Это {PRODUCT_NAME} — твой стак имущества.\n\n"
            "Чтобы получать push-алерты и дайджест:\n"
            "1. Зайди на сайт и войди в аккаунт\n"
            "2. Аккаунт → «Подключить Telegram»\n"
            "3. Вернись сюда по ссылке из браузера\n\n"
            + _help_text(),
            reply_markup=_miniapp_button() or _portfolio_button(),
        )
        return

    if cmd == "/help":
        send_message(chat_id, _help_text(), reply_markup=_miniapp_button() or _portfolio_button())
        return

    if cmd == "/status":
        user = _user_by_chat(db, chat_id)
        if not user:
            send_message(
                chat_id,
                "Telegram ещё не привязан. Открой Аккаунт на сайте → Подключить Telegram.",
                reply_markup=_portfolio_button(),
            )
            return
        send_message(
            chat_id,
            _status_text(db, user),
            reply_markup=_miniapp_button() or _portfolio_button(),
        )
        return

    if cmd == "/unlink":
        user = _user_by_chat(db, chat_id)
        if not user:
            send_message(chat_id, "Этот чат и так не привязан.")
            return
        unlink_telegram(db, user)
        send_message(
            chat_id,
            "Telegram отвязан. Алерты в этот чат больше не придут.",
            reply_markup=_portfolio_button(),
        )
        return

    if text.startswith("/"):
        send_message(
            chat_id,
            f"Не знаю команду. {_help_text()}",
            reply_markup=_miniapp_button() or _portfolio_button(),
        )
