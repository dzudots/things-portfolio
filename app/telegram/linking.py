"""One-time deep-link tokens to bind a Telegram chat to a web account."""

from __future__ import annotations

import secrets
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.models import User, utcnow

LINK_PREFIX = "link_"
LINK_TTL_MINUTES = 30


def _as_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def create_link_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(24)
    user.telegram_link_token = token
    user.telegram_link_expires_at = utcnow() + timedelta(minutes=LINK_TTL_MINUTES)
    db.commit()
    return token


def consume_link_token(
    db: Session,
    chat_id: str,
    token: str,
    username: str | None = None,
) -> tuple[User | None, str | None]:
    """Returns (user, error_message). error_message is user-facing Russian copy."""
    token = (token or "").strip()
    if not token:
        return None, "Ссылка устарела или неверная. Открой «Аккаунт» на сайте и нажми «Подключить Telegram»."

    other = (
        db.query(User)
        .filter(User.telegram_chat_id == chat_id, User.telegram_link_token.is_(None))
        .first()
    )
    if other:
        return None, "Этот Telegram уже привязан к другому аккаунту Стак."

    user = db.query(User).filter(User.telegram_link_token == token).first()
    if not user:
        return None, "Ссылка устарела или неверная. Открой «Аккаунт» на сайте и нажми «Подключить Telegram»."

    expires = user.telegram_link_expires_at
    if expires is not None:
        now = utcnow()
        if _as_utc(expires) < now:
            user.telegram_link_token = None
            user.telegram_link_expires_at = None
            db.commit()
            return None, "Ссылка истекла. Сгенерируй новую в аккаунте на сайте."

    taken = (
        db.query(User)
        .filter(User.telegram_chat_id == chat_id, User.id != user.id)
        .first()
    )
    if taken:
        return None, "Этот Telegram уже привязан к другому аккаунту Стак."

    user.telegram_chat_id = chat_id
    user.telegram_username = (username or "").lstrip("@")[:64] or None
    user.telegram_alerts_enabled = True
    user.telegram_link_token = None
    user.telegram_link_expires_at = None
    db.commit()
    db.refresh(user)
    return user, None


def unlink_telegram(db: Session, user: User) -> None:
    user.telegram_chat_id = None
    user.telegram_username = None
    user.telegram_alerts_enabled = False
    user.telegram_link_token = None
    user.telegram_link_expires_at = None
    db.commit()
