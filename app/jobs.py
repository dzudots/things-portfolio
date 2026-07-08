"""Nightly revaluation, alerts, weekly digests + Phase B comps ingest."""

from __future__ import annotations

import logging
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, joinedload

from app.alerts import build_weekly_digests, detect_alerts_for_item
from app.comps.ingest import IngestResult, ingest_comp_rows
from app.comps.sources.mock_market import MockMarketSource
from app.models import Item, SessionLocal, User, utcnow
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
    *,
    source: str = "manual_json",
) -> IngestResult:
    """
    Accept normalized aggregate comps from partner/API/manual feed.
    Dedupes on (source, external_ref); stores local RUB prices + geo metadata.
    """
    return ingest_comp_rows(db, rows, source=source)


def refresh_market_comps(db: Session | None = None) -> dict:
    """
    Scheduled stub: refresh stale seed/partner comps via mock_market adapter.
    Production path: swap MockMarketSource for avito_api / kufar_api adapters.
    """
    own = db is None
    if own:
        db = SessionLocal()
    try:
        adapter = MockMarketSource()
        rows = adapter.fetch_rows(db)
        if not rows:
            return {"refreshed": 0, "inserted": 0, "updated": 0, "skipped": 0}
        result = ingest_comp_rows(db, rows, source=adapter.source_id)
        out = result.as_dict()
        out["refreshed"] = result.ingested
        revalue_all_items(db)
        return out
    finally:
        if own:
            db.close()


def start_scheduler() -> BackgroundScheduler:
    global scheduler
    if scheduler is not None:
        return scheduler
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        refresh_market_comps,
        trigger="cron",
        hour=2,
        minute=0,
        id="market_comp_refresh",
        replace_existing=True,
    )
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
    logger.info(
        "Scheduler started: market refresh 02:00 UTC, revaluation 03:00 UTC, digest Mon 07:00 UTC"
    )
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
