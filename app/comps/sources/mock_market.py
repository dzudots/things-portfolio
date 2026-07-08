"""Mock market refresh — ages stale comps forward + small price drift (no scraping)."""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.comps.sources.registry import REFRESHABLE_SOURCES
from app.comps.types import CompIngestRow
from app.models import CompListing, utcnow

logger = logging.getLogger(__name__)


class MockMarketSource:
    source_id = "mock_market"

    def fetch_rows(
        self,
        db: Session,
        *,
        max_age_days: int = 7,
        limit: int = 500,
        rng: random.Random | None = None,
        **_: Any,
    ) -> list[CompIngestRow]:
        """Build upsert rows for comps that fell out of recency window."""
        rng = rng or random.Random()
        cutoff = utcnow() - timedelta(days=max_age_days)
        stale = (
            db.query(CompListing)
            .filter(
                CompListing.source.in_(REFRESHABLE_SOURCES),
                CompListing.observed_at < cutoff,
            )
            .order_by(CompListing.observed_at.asc())
            .limit(limit)
            .all()
        )
        rows: list[CompIngestRow] = []
        now = utcnow()
        for comp in stale:
            drift = rng.uniform(0.97, 1.03)
            new_price = round(comp.price * drift / 100) * 100
            observed = now - timedelta(hours=rng.randint(0, 72))
            rows.append(
                CompIngestRow(
                    model_id=comp.model_id,
                    condition_bucket=comp.condition_bucket,
                    price=max(new_price, 100),
                    region=comp.region,
                    city=comp.city,
                    source=self.source_id,
                    external_ref=f"refresh:{comp.source}:{comp.id}",
                    defects=comp.defects or "",
                    observed_at=observed,
                )
            )
        logger.info("Mock market prepared %s refresh rows (cutoff %s)", len(rows), cutoff.isoformat())
        return rows
