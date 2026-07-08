from __future__ import annotations

from datetime import datetime, timezone

import bcrypt
import hmac

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import ADMIN_API_KEY, ADMIN_EMAILS
from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def is_admin_email(email: str | None) -> bool:
    if not email or not ADMIN_EMAILS:
        return False
    return email.strip().lower() in ADMIN_EMAILS


def admin_key_ok(request: Request) -> bool:
    if not ADMIN_API_KEY:
        return False
    header = (request.headers.get("X-Admin-Key") or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    key = header or (auth[7:].strip() if auth.lower().startswith("bearer ") else "")
    if not key:
        return False
    return hmac.compare_digest(key.encode("utf-8"), ADMIN_API_KEY.encode("utf-8"))


def assert_admin(request: Request, user: User | None) -> None:
    """
    Gate for /api/admin/* — needs THINGS_ADMIN_API_KEY and/or allowlisted email.
    Logged-in non-admin users are always rejected.
    """
    if not ADMIN_EMAILS and not ADMIN_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Admin API locked: set THINGS_ADMIN_EMAILS or THINGS_ADMIN_API_KEY",
        )
    if admin_key_ok(request):
        return
    if user is not None and is_admin_email(user.email):
        return
    raise HTTPException(status_code=403, detail="Admin access required")


def create_user(
    db: Session,
    email: str,
    password: str,
    display_name: str = "",
    accept_privacy: bool = True,
) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=hash_password(password),
        privacy_accepted_at=datetime.now(timezone.utc) if accept_privacy else None,
    )
    user.display_name = display_name or email.split("@")[0]
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def delete_user_account(db: Session, user: User) -> None:
    """Hard-delete all private data for the account (GDPR-style erasure)."""
    from app.models import (
        ApiUsage,
        Item,
        Payment,
        PriceAlert,
        ScanJob,
        UserAchievement,
        UserEvent,
        ValuationSnapshot,
        WeeklyDigest,
    )

    item_ids = [i.id for i in db.query(Item.id).filter(Item.owner_id == user.id).all()]
    if item_ids:
        db.query(ValuationSnapshot).filter(ValuationSnapshot.item_id.in_(item_ids)).delete(
            synchronize_session=False
        )
        db.query(PriceAlert).filter(PriceAlert.item_id.in_(item_ids)).delete(
            synchronize_session=False
        )
        db.query(Item).filter(Item.owner_id == user.id).delete(synchronize_session=False)
    db.query(PriceAlert).filter(PriceAlert.user_id == user.id).delete(synchronize_session=False)
    db.query(WeeklyDigest).filter(WeeklyDigest.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(UserAchievement).filter(UserAchievement.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(UserEvent).filter(UserEvent.user_id == user.id).delete(synchronize_session=False)
    db.query(Payment).filter(Payment.user_id == user.id).delete(synchronize_session=False)
    # Clear FK from scans → usage, then both ledgers
    db.query(ScanJob).filter(ScanJob.user_id == user.id).update(
        {ScanJob.usage_id: None}, synchronize_session=False
    )
    db.query(ScanJob).filter(ScanJob.user_id == user.id).delete(synchronize_session=False)
    db.query(ApiUsage).filter(ApiUsage.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()


def export_user_data(db: Session, user: User) -> dict:
    """Portable JSON export of the user's private portfolio (for the user only)."""
    from sqlalchemy.orm import joinedload

    from app.models import Item, PriceAlert, WeeklyDigest
    from app.valuation import latest_snapshot
    from app.achievements import achievement_progress

    items = (
        db.query(Item)
        .options(joinedload(Item.model), joinedload(Item.valuations))
        .filter(Item.owner_id == user.id)
        .all()
    )
    payload_items = []
    for item in items:
        snap = latest_snapshot(item)
        payload_items.append(
            {
                "id": item.id,
                "category": item.category,
                "model": f"{item.model.brand} {item.model.name}",
                "condition": item.condition,
                "defects": item.defect_list(),
                "cost_basis": item.cost_basis,
                "override_mid": item.override_mid,
                "notes": item.notes,
                "location_city": item.location_city,
                "location_region": item.location_region,
                "latest_valuation": None
                if snap is None
                else {
                    "low": snap.low,
                    "mid": snap.mid,
                    "high": snap.high,
                    "confidence": snap.confidence,
                    "ts": snap.ts.isoformat(),
                },
                "history": [
                    {
                        "ts": v.ts.isoformat(),
                        "low": v.low,
                        "mid": v.mid,
                        "high": v.high,
                    }
                    for v in item.valuations
                ],
            }
        )

    alerts = (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user.id)
        .order_by(PriceAlert.created_at.desc())
        .limit(100)
        .all()
    )
    digests = (
        db.query(WeeklyDigest)
        .filter(WeeklyDigest.user_id == user.id)
        .order_by(WeeklyDigest.created_at.desc())
        .limit(52)
        .all()
    )

    return {
        "export_version": 1,
        "purpose": "personal_household_inventory",
        "disclaimer": (
            "Личный учёт имущества. Не является налоговой отчётностью, "
            "декларацией или передачей данных в госорганы."
        ),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "items": payload_items,
        "alerts": [
            {
                "item_id": a.item_id,
                "direction": a.direction,
                "change_pct": a.change_pct,
                "old_mid": a.old_mid,
                "new_mid": a.new_mid,
                "message": a.message,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
        "digests": [
            {
                "week_start": d.week_start,
                "total_mid": d.total_mid,
                "delta_week": d.delta_week,
                "created_at": d.created_at.isoformat(),
            }
            for d in digests
        ],
        "achievements": achievement_progress(db, user.id),
    }
