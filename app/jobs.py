"""Nightly revaluation, alerts, weekly digests + Phase B comps ingest."""

from __future__ import annotations

import logging
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, joinedload

from app.alerts import build_weekly_digests, detect_alerts_for_item
from app.models import CompListing, Item, SessionLocal, User, utcnow
from app.valuation import save_snapshot

logger = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None


def revalue_all_items(db: Session | None = None) -> int:
    own = db is None
    if own:
        db = SessionLocal()
    try:
        items = (
            db.query(Item)
            .options(joinedload(Item.model), joinedload(Item.owner))
            .all()
        )
        count = 0
        for item in items:
            snap = save_snapshot(db, item)
            user = item.owner
            if user:
                detect_alerts_for_item(db, item, user, snap.mid)
            count += 1
        logger.info("Revalued %s items at %s", count, utcnow().isoformat())
        return count
    finally:
        if own:
            db.close()


def ingest_comp_aggregates(
    db: Session,
    rows: Iterable[dict],
) -> int:
    """
    Phase B: accept normalized aggregate comps from a partner/API feed.
    Stores metadata/aggregates only — not tied to any user identity.
    """
    n = 0
    for row in rows:
        db.add(
            CompListing(
                model_id=row["model_id"],
                condition_bucket=row["condition_bucket"],
                defects=row.get("defects", ""),
                price=float(row["price"]),
                region=row.get("region", "Россия"),
                city=row.get("city", "Россия"),
                source=row.get("source", "partner_feed"),
                external_ref=row.get("external_ref"),
                observed_at=row.get("observed_at") or utcnow(),
            )
        )
        n += 1
    db.commit()
    return n


def start_scheduler() -> BackgroundScheduler:
    global scheduler
    if scheduler is not None:
        return scheduler
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        revalue_all_items,
        trigger="cron",
        hour=3,
        minute=0,
        id="nightly_revaluation",
        replace_existing=True,
    )
    scheduler.add_job(
        build_weekly_digests,
        trigger="cron",
        day_of_week="mon",
        hour=7,
        minute=0,
        id="weekly_digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: revaluation 03:00 UTC, digest Mon 07:00 UTC")
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
