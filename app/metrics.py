"""Product success metrics: weekly retention, items/user, override rate."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Item, User, UserEvent, utcnow


def track_event(db: Session, user_id: int, event_type: str, meta: dict | None = None) -> list:
    """Record analytics event and evaluate achievements. Returns newly unlocked defs."""
    from app.achievements import evaluate_achievements

    db.add(
        UserEvent(
            user_id=user_id,
            event_type=event_type,
            meta_json=json.dumps(meta or {}, ensure_ascii=False),
        )
    )
    db.commit()
    return evaluate_achievements(db, user_id)


def compute_metrics(db: Session) -> dict[str, Any]:
    now = utcnow()
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_items = db.query(func.count(Item.id)).scalar() or 0

    users_with_items = (
        db.query(func.count(func.distinct(Item.owner_id))).scalar() or 0
    )
    avg_items = round(total_items / users_with_items, 2) if users_with_items else 0.0

    # Weekly active: portfolio_view in last 7 days
    wau = (
        db.query(func.count(func.distinct(UserEvent.user_id)))
        .filter(
            UserEvent.event_type == "portfolio_view",
            UserEvent.created_at >= week_ago,
        )
        .scalar()
        or 0
    )

    # Users who viewed portfolio in previous week (retention cohort)
    prev_wau_ids = {
        r[0]
        for r in db.query(UserEvent.user_id)
        .filter(
            UserEvent.event_type == "portfolio_view",
            UserEvent.created_at >= two_weeks_ago,
            UserEvent.created_at < week_ago,
        )
        .distinct()
        .all()
    }
    retained = 0
    if prev_wau_ids:
        retained = (
            db.query(func.count(func.distinct(UserEvent.user_id)))
            .filter(
                UserEvent.event_type == "portfolio_view",
                UserEvent.created_at >= week_ago,
                UserEvent.user_id.in_(prev_wau_ids),
            )
            .scalar()
            or 0
        )
    weekly_retention = round(retained / len(prev_wau_ids), 3) if prev_wau_ids else None

    overrides = (
        db.query(func.count(Item.id))
        .filter(Item.override_mid_enc != "", Item.override_mid_enc.isnot(None))
        .scalar()
        or 0
    )
    override_rate = round(overrides / total_items, 3) if total_items else 0.0

    item_adds_week = (
        db.query(func.count(UserEvent.id))
        .filter(UserEvent.event_type == "item_add", UserEvent.created_at >= week_ago)
        .scalar()
        or 0
    )
    condition_updates_week = (
        db.query(func.count(UserEvent.id))
        .filter(
            UserEvent.event_type == "condition_update",
            UserEvent.created_at >= week_ago,
        )
        .scalar()
        or 0
    )

    def _count_event(name: str) -> int:
        return (
            db.query(func.count(UserEvent.id))
            .filter(UserEvent.event_type == name, UserEvent.created_at >= week_ago)
            .scalar()
            or 0
        )

    funnel = {
        "register_7d": _count_event("register"),
        "item_add_7d": item_adds_week,
        "hit_limit_7d": _count_event("hit_limit"),
        "pay_cta_7d": _count_event("pay_cta"),
        "pay_start_7d": _count_event("pay_start"),
        "pay_success_7d": _count_event("pay_success"),
        "pro_activate_7d": _count_event("pro_activate"),
    }

    return {
        "total_users": total_users,
        "total_items": total_items,
        "avg_items_per_user": avg_items,
        "weekly_active_users": wau,
        "weekly_retention": weekly_retention,
        "override_count": overrides,
        "override_rate": override_rate,
        "item_adds_last_7d": item_adds_week,
        "condition_updates_last_7d": condition_updates_week,
        "funnel": funnel,
        "success_signals": {
            "retention_ok": weekly_retention is not None and weekly_retention >= 0.3,
            "engagement_ok": (item_adds_week + condition_updates_week) > 0,
            "trust_ok": override_rate < 0.35,
        },
    }
