"""Nightly revaluation, alerts, weekly digests + Phase B comps ingest."""

from __future__ import annotations

import logging
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, joinedload

from app.alerts import build_weekly_digests
from app.comps.ingest import IngestResult, ingest_comp_rows
from app.comps.sources.mock_market import MockMarketSource
from app.comps.sources.partner_feed import PartnerFeedSource, partner_feed_configured
from app.models import Item, SessionLocal, utcnow
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
                from app.alerts import detect_alerts_for_item

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


def refresh_partner_comps(db: Session | None = None) -> dict:
    """Daily partner_feed ingest; mock_market only as fallback when feed empty/unconfigured."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        out: dict = {
            "refreshed": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "partner": {"refreshed": 0, "inserted": 0, "updated": 0, "skipped": 0},
            "mock_fallback": False,
            "source_used": None,
        }
        partner_rows: list = []
        if partner_feed_configured():
            partner_rows = PartnerFeedSource().fetch_rows(db)
        if partner_rows:
            result = ingest_comp_rows(db, partner_rows, source="partner_feed")
            stats = result.as_dict()
            stats["refreshed"] = result.ingested
            out["partner"] = stats
            out.update(
                {
                    "refreshed": result.ingested,
                    "inserted": result.inserted,
                    "updated": result.updated,
                    "skipped": result.skipped,
                    "source_used": "partner_feed",
                }
            )
            revalue_all_items(db)
            return out

        # Fallback: keep comps fresh via mock drift when no partner data
        adapter = MockMarketSource()
        rows = adapter.fetch_rows(db)
        if not rows:
            out["source_used"] = "none"
            return out
        result = ingest_comp_rows(db, rows, source=adapter.source_id)
        stats = result.as_dict()
        stats["refreshed"] = result.ingested
        out["partner"] = stats
        out["mock_fallback"] = True
        out.update(
            {
                "refreshed": result.ingested,
                "inserted": result.inserted,
                "updated": result.updated,
                "skipped": result.skipped,
                "source_used": "mock_market",
            }
        )
        revalue_all_items(db)
        return out
    finally:
        if own:
            db.close()


def refresh_market_comps(db: Session | None = None) -> dict:
    """
    Scheduled refresh: partner_feed first, mock_market as fallback.
    Admin /api/admin/comps/refresh uses the same path.
    """
    return refresh_partner_comps(db)


def start_scheduler() -> BackgroundScheduler:
    global scheduler
    if scheduler is not None:
        return scheduler
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        refresh_partner_comps,
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
        "Scheduler started: partner/mock comps 02:00 UTC, revaluation 03:00 UTC, digest Mon 07:00 UTC"
    )
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
