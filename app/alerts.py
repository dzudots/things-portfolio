"""Price alerts + weekly digest generation."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from app.models import Item, PriceAlert, User, ValuationSnapshot, WeeklyDigest, utcnow
from app.valuation import display_mid, latest_snapshot

logger = logging.getLogger(__name__)


def _pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return ((new - old) / old) * 100.0


def detect_alerts_for_item(
    db: Session,
    item: Item,
    user: User,
    new_mid: float,
) -> PriceAlert | None:
    if not user.alerts_enabled:
        return None
    # Previous snapshot (before the one just written): second-to-last
    snaps = (
        db.query(ValuationSnapshot)
        .filter(ValuationSnapshot.item_id == item.id)
        .order_by(ValuationSnapshot.ts.desc())
        .limit(2)
        .all()
    )
    if len(snaps) < 2:
        return None
    # snaps[0] is newest (just saved), snaps[1] is previous
    old_mid = snaps[1].mid
    change = _pct_change(old_mid, new_mid)
    threshold = user.alert_threshold_pct or 5.0
    if abs(change) < threshold:
        return None

    direction = "up" if change > 0 else "down"
    model_name = f"{item.model.brand} {item.model.name}" if item.model else f"#{item.id}"
    sign = "+" if change > 0 else ""
    message = (
        f"{model_name}: рыночная оценка {sign}{change:.1f}% "
        f"({int(old_mid):,} → {int(new_mid):,} ₽)".replace(",", " ")
    )
    alert = PriceAlert(
        user_id=user.id,
        item_id=item.id,
        direction=direction,
        change_pct=round(change, 2),
        old_mid=old_mid,
        new_mid=new_mid,
        message=message,
        read=False,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def build_weekly_digests(db: Session | None = None) -> int:
    """Create one digest per user with digest_enabled for the current week."""
    from app.models import SessionLocal

    own = db is None
    if own:
        db = SessionLocal()
    try:
        week_start = (utcnow() - timedelta(days=utcnow().weekday())).strftime("%Y-%m-%d")
        users = db.query(User).filter(User.digest_enabled.is_(True)).all()
        created = 0
        for user in users:
            exists = (
                db.query(WeeklyDigest)
                .filter(
                    WeeklyDigest.user_id == user.id,
                    WeeklyDigest.week_start == week_start,
                )
                .first()
            )
            if exists:
                continue

            items = (
                db.query(Item)
                .options(joinedload(Item.model), joinedload(Item.valuations))
                .filter(Item.owner_id == user.id)
                .all()
            )
            total = 0.0
            lines = []
            week_ago = utcnow() - timedelta(days=7)
            old_total = 0.0
            for item in items:
                snap = latest_snapshot(item)
                mid = display_mid(item, snap)
                if mid is None:
                    continue
                total += mid
                # mid ~7 days ago
                past = (
                    db.query(ValuationSnapshot)
                    .filter(
                        ValuationSnapshot.item_id == item.id,
                        ValuationSnapshot.ts <= week_ago,
                    )
                    .order_by(ValuationSnapshot.ts.desc())
                    .first()
                )
                past_mid = past.mid if past else mid
                old_total += past_mid
                lines.append(
                    {
                        "item_id": item.id,
                        "name": f"{item.model.brand} {item.model.name}",
                        "mid": mid,
                        "week_delta": mid - past_mid,
                    }
                )

            delta = total - old_total
            body = {
                "items": lines,
                "item_count": len(lines),
                "headline": f"Ваше имущество: {int(total):,} ₽".replace(",", " ")
                + (f" ({'+' if delta >= 0 else ''}{int(delta):,} ₽ за неделю)".replace(",", " ")),
            }
            db.add(
                WeeklyDigest(
                    user_id=user.id,
                    week_start=week_start,
                    total_mid=total,
                    delta_week=delta,
                    body_json=json.dumps(body, ensure_ascii=False),
                )
            )
            created += 1
        db.commit()
        logger.info("Created %s weekly digests for week %s", created, week_start)
        return created
    finally:
        if own:
            db.close()


def unread_alerts(db: Session, user_id: int, limit: int = 20) -> list[PriceAlert]:
    return (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user_id, PriceAlert.read.is_(False))
        .order_by(PriceAlert.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_alerts_read(db: Session, user_id: int) -> int:
    q = db.query(PriceAlert).filter(
        PriceAlert.user_id == user_id, PriceAlert.read.is_(False)
    )
    n = q.count()
    q.update({"read": True}, synchronize_session=False)
    db.commit()
    return n
