"""Pro plan: promo codes + YooKassa payments."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import (
    PRO_DAYS_MONTH,
    PRO_DAYS_YEAR,
    PRO_PRICE_RUB,
    PRO_PRICE_YEAR_RUB,
    PRO_PROMO_CODES,
    PUBLIC_BASE_URL,
    SECRET_KEY,
    YOOKASSA_RETURN_URL,
    YOOKASSA_SECRET_KEY,
    YOOKASSA_SHOP_ID,
)
from app.models import Payment, User, utcnow

logger = logging.getLogger(__name__)
_YK_API = "https://api.yookassa.ru/v3"


@dataclass
class RedeemResult:
    ok: bool
    message: str
    plan: str = "free"


@dataclass
class CheckoutResult:
    ok: bool
    message: str
    confirmation_url: str | None = None
    payment_id: str | None = None


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


def activate_pro(db: Session, user: User, days: int, *, source: str = "promo") -> User:
    """Extend or start Pro from now (or from current expiry if still Pro)."""
    now = utcnow()
    base = now
    if is_pro(user) and user.plan_expires_at and user.plan_expires_at > now:
        base = user.plan_expires_at
    user.plan = "pro"
    user.plan_expires_at = base + timedelta(days=max(1, days))
    db.commit()
    db.refresh(user)
    from app.metrics import track_event

    track_event(
        db,
        user.id,
        "pro_activate",
        {
            "days": days,
            "source": source,
            "until": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
        },
    )
    return user


def redeem_promo(db: Session, user: User, code: str) -> RedeemResult:
    codes = _configured_codes()
    key = _normalize_code(code)
    if not key or key not in codes:
        return RedeemResult(ok=False, message="Промокод не найден или уже не действует.")

    days = codes[key]
    fingerprint = hmac.new(
        SECRET_KEY.encode(), f"{user.id}:{key}".encode(), hashlib.sha256
    ).hexdigest()[:16]

    activate_pro(db, user, days, source=f"promo:{fingerprint}")
    return RedeemResult(
        ok=True,
        message=f"Pro активен на {days} дн. до {user.plan_expires_at.strftime('%d.%m.%Y')}.",
        plan="pro",
    )


def downgrade_to_free(db: Session, user: User) -> None:
    user.plan = "free"
    user.plan_expires_at = None
    db.commit()


def yookassa_configured() -> bool:
    return bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)


def _return_url() -> str:
    if YOOKASSA_RETURN_URL:
        return YOOKASSA_RETURN_URL
    base = PUBLIC_BASE_URL or "http://127.0.0.1:8000"
    return base.rstrip("/") + "/account?paid=1"


def _yk_request(method: str, path: str, payload: dict | None = None) -> dict[str, Any] | None:
    if not yookassa_configured():
        return None
    url = f"{_YK_API}{path}"
    headers = {
        "Idempotence-Key": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(
                method,
                url,
                json=payload,
                headers=headers,
                auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
            )
            if resp.status_code >= 400:
                logger.warning("YooKassa %s %s → %s %s", method, path, resp.status_code, resp.text[:300])
                return None
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("YooKassa request failed: %s", exc)
        return None


def create_pro_checkout(
    db: Session,
    user: User,
    *,
    period: str = "month",
) -> CheckoutResult:
    """Create YooKassa payment; returns confirmation_url for redirect."""
    if not yookassa_configured():
        return CheckoutResult(
            ok=False,
            message="Оплата картой пока недоступна. Используй промокод или подожди настройки ЮKassa.",
        )

    if period == "year":
        amount = float(PRO_PRICE_YEAR_RUB)
        days = PRO_DAYS_YEAR
        label = f"Стак Pro — 12 месяцев"
    else:
        amount = float(PRO_PRICE_RUB)
        days = PRO_DAYS_MONTH
        label = f"Стак Pro — 1 месяц"
        period = "month"

    body = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": _return_url()},
        "capture": True,
        "description": label[:128],
        "metadata": {
            "user_id": str(user.id),
            "plan_days": str(days),
            "period": period,
            "product": "stak_pro",
        },
    }
    data = _yk_request("POST", "/payments", body)
    if not data or not data.get("id"):
        return CheckoutResult(ok=False, message="Не удалось создать платёж. Попробуй позже.")

    conf = (data.get("confirmation") or {}).get("confirmation_url")
    payment = Payment(
        user_id=user.id,
        provider="yookassa",
        provider_payment_id=str(data["id"]),
        status=str(data.get("status") or "pending"),
        amount_rub=amount,
        currency="RUB",
        plan_days=days,
        description=label,
        confirmation_url=conf,
        meta_json=json.dumps({"period": period, "raw_status": data.get("status")}, ensure_ascii=False),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    from app.metrics import track_event

    track_event(
        db,
        user.id,
        "pay_start",
        {"payment_id": payment.provider_payment_id, "amount": amount, "period": period},
    )
    if not conf:
        return CheckoutResult(ok=False, message="Платёж создан, но нет ссылки на оплату.")
    return CheckoutResult(
        ok=True,
        message="Перенаправляем на оплату…",
        confirmation_url=conf,
        payment_id=payment.provider_payment_id,
    )


def apply_yookassa_payment(db: Session, payment_obj: dict[str, Any]) -> bool:
    """
    Activate Pro from a YooKassa payment object (webhook or poll).
    Idempotent on provider_payment_id.
    """
    pid = str(payment_obj.get("id") or "")
    status = str(payment_obj.get("status") or "")
    if not pid:
        return False

    row = db.query(Payment).filter(Payment.provider_payment_id == pid).first()
    meta = payment_obj.get("metadata") or {}
    user_id = None
    plan_days = PRO_DAYS_MONTH
    if row:
        user_id = row.user_id
        plan_days = row.plan_days or PRO_DAYS_MONTH
    else:
        try:
            user_id = int(meta.get("user_id") or 0) or None
            plan_days = int(meta.get("plan_days") or PRO_DAYS_MONTH)
        except (TypeError, ValueError):
            user_id = None

    if not user_id:
        logger.warning("YooKassa payment %s: no user_id", pid)
        return False

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False

    amount_value = 0.0
    try:
        amount_value = float((payment_obj.get("amount") or {}).get("value") or 0)
    except (TypeError, ValueError):
        amount_value = row.amount_rub if row else 0.0

    if row is None:
        row = Payment(
            user_id=user.id,
            provider="yookassa",
            provider_payment_id=pid,
            status=status,
            amount_rub=amount_value,
            currency="RUB",
            plan_days=plan_days,
            description=str(payment_obj.get("description") or "Стак Pro")[:200],
            meta_json=json.dumps({"metadata": meta}, ensure_ascii=False),
        )
        db.add(row)
        db.flush()

    row.status = status
    if status == "succeeded":
        if row.paid_at is None:
            row.paid_at = utcnow()
            activate_pro(db, user, plan_days, source="yookassa")
            from app.metrics import track_event

            track_event(
                db,
                user.id,
                "pay_success",
                {"payment_id": pid, "days": plan_days, "amount": amount_value},
            )
            logger.info("Pro activated via YooKassa user_id=%s payment=%s", user.id, pid)
        else:
            db.commit()
        return True

    db.commit()
    return False


def handle_yookassa_webhook(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    event = str(payload.get("event") or "")
    obj = payload.get("object") or {}
    if event in {"payment.succeeded", "payment.waiting_for_capture"} or (
        isinstance(obj, dict) and obj.get("status") == "succeeded"
    ):
        ok = apply_yookassa_payment(db, obj if isinstance(obj, dict) else {})
        return {"ok": ok, "event": event}
    # Still sync status for canceled etc.
    if isinstance(obj, dict) and obj.get("id"):
        apply_yookassa_payment(db, obj)
    return {"ok": True, "event": event, "ignored": True}
