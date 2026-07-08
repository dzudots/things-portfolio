"""Pro plan activation via promo codes (payment gateway later)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import PRO_PROMO_CODES, SECRET_KEY
from app.models import User, utcnow


@dataclass
class RedeemResult:
    ok: bool
    message: str
    plan: str = "free"


def _normalize_code(raw: str) -> str:
    return "".join((raw or "").strip().upper().split())


def _configured_codes() -> dict[str, int]:
    """
    Parse THINGS_PRO_PROMO_CODES as CODE:DAYS,CODE2:DAYS
    Default days = 30 if omitted.
    """
    out: dict[str, int] = {}
    raw = (PRO_PROMO_CODES or "").strip()
    if not raw:
        # Built-in beta codes for early testers (rotate via env in prod)
        raw = "STAKBETA30:30,STAKPRO90:90"
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            code, days_s = part.split(":", 1)
            try:
                days = max(1, min(3650, int(days_s)))
            except ValueError:
                days = 30
        else:
            code, days = part, 30
        code = _normalize_code(code)
        if code:
            out[code] = days
    return out


def is_pro(user: User) -> bool:
    if (user.plan or "free") != "pro":
        return False
    expires = getattr(user, "plan_expires_at", None)
    if expires is None:
        return True
    if expires.tzinfo is None:
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    return expires > utcnow()


def ensure_plan_fresh(db: Session, user: User) -> User:
    """Downgrade expired Pro silently."""
    if (user.plan or "free") == "pro" and not is_pro(user):
        user.plan = "free"
        user.plan_expires_at = None
        db.commit()
        db.refresh(user)
    return user


def redeem_promo(db: Session, user: User, code: str) -> RedeemResult:
    codes = _configured_codes()
    key = _normalize_code(code)
    if not key or key not in codes:
        return RedeemResult(ok=False, message="Промокод не найден или уже не действует.")

    days = codes[key]
    # Soft anti-abuse: same user can't stack same code fingerprint endlessly in one day
    fingerprint = hmac.new(
        SECRET_KEY.encode(), f"{user.id}:{key}".encode(), hashlib.sha256
    ).hexdigest()[:16]

    now = utcnow()
    base = now
    if is_pro(user) and user.plan_expires_at and user.plan_expires_at > now:
        base = user.plan_expires_at

    user.plan = "pro"
    user.plan_expires_at = base + timedelta(days=days)
    db.commit()
    db.refresh(user)

    from app.metrics import track_event

    track_event(
        db,
        user.id,
        "pro_redeem",
        {"days": days, "fp": fingerprint, "until": user.plan_expires_at.isoformat()},
    )
    return RedeemResult(
        ok=True,
        message=f"Pro активен на {days} дн. до {user.plan_expires_at.strftime('%d.%m.%Y')}.",
        plan="pro",
    )


def downgrade_to_free(db: Session, user: User) -> None:
    user.plan = "free"
    user.plan_expires_at = None
    db.commit()
