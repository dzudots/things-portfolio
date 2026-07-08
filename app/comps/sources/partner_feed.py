"""Partner aggregate feed — JSON URL or local file (no HTML scraping)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.comps.types import CompIngestRow
from app.config import PARTNER_FEED_PATH, PARTNER_FEED_URL

logger = logging.getLogger(__name__)


class PartnerFeedSource:
    source_id = "partner_feed"

    def fetch_rows(self, db: Session, **_: Any) -> list[CompIngestRow]:
        del db
        payload = self._load_payload()
        if not payload:
            return []
        raw_rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(raw_rows, list):
            logger.warning("Partner feed: expected list or {rows: [...]}")
            return []
        out: list[CompIngestRow] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            ref = str(raw.get("external_ref") or "").strip()
            if not ref or "model_id" not in raw or "price" not in raw:
                continue
            out.append(
                CompIngestRow(
                    model_id=int(raw["model_id"]),
                    condition_bucket=str(
                        raw.get("condition_bucket") or raw.get("condition") or "good"
                    )
                    .strip()
                    .lower(),
                    price=float(raw["price"]),
                    region=str(raw.get("region") or "Москва").strip(),
                    city=str(raw.get("city") or "Москва").strip(),
                    source=self.source_id,
                    external_ref=ref,
                    defects=str(raw.get("defects") or "").strip(),
                    observed_at=raw.get("observed_at"),
                )
            )
        logger.info("Partner feed prepared %s rows", len(out))
        return out

    def _load_payload(self) -> Any:
        if PARTNER_FEED_URL:
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(PARTNER_FEED_URL)
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                logger.warning("Partner feed URL failed: %s", exc)
                return None
        path = (PARTNER_FEED_PATH or "").strip()
        if path:
            p = Path(path)
            if not p.is_file():
                logger.warning("Partner feed path missing: %s", path)
                return None
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Partner feed file failed: %s", exc)
                return None
        return None


def partner_feed_configured() -> bool:
    return bool(PARTNER_FEED_URL or PARTNER_FEED_PATH)
