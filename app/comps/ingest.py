"""Ingest pipeline: validate, dedupe by (source, external_ref), regional normalize."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.comps.sources.registry import is_ingestable
from app.comps.types import CompIngestRow
from app.config import COMPS_WINDOW_DAYS
from app.models import CanonicalModel, CompListing, Condition, utcnow
from app.regions import city_info

logger = logging.getLogger(__name__)

_VALID_CONDITIONS = {c.value for c in Condition}
_MAX_INGEST_AGE_DAYS = COMPS_WINDOW_DAYS + 7  # grace beyond valuation window


@dataclass
class IngestResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    @property
    def ingested(self) -> int:
        return self.inserted + self.updated

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "ingested": self.ingested,
        }
        if self.errors:
            out["errors"] = self.errors
        return out


def _parse_observed_at(value: Any) -> datetime:
    if value is None:
        return utcnow()
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_geo(city: str, region: str) -> tuple[str, str]:
    info = city_info(city)
    if info:
        return info.city, info.region
    city = (city or "Москва").strip() or "Москва"
    region = (region or city).strip() or city
    return city, region


def _validate_row(
    db: Session,
    row: CompIngestRow,
    *,
    model_cache: dict[int, bool],
) -> str | None:
    if not is_ingestable(row.source):
        return f"source not allowed: {row.source}"
    if not row.external_ref:
        return "external_ref required"
    if row.condition_bucket not in _VALID_CONDITIONS:
        return f"invalid condition_bucket: {row.condition_bucket}"
    if row.price <= 0:
        return "price must be positive"
    if row.model_id not in model_cache:
        model_cache[row.model_id] = (
            db.query(CanonicalModel.id).filter(CanonicalModel.id == row.model_id).first() is not None
        )
    if not model_cache[row.model_id]:
        return f"unknown model_id: {row.model_id}"
    observed = row.observed_at or utcnow()
    if observed < utcnow() - timedelta(days=_MAX_INGEST_AGE_DAYS):
        return f"observed_at too old (>{_MAX_INGEST_AGE_DAYS}d)"
    return None


def _row_to_listing(row: CompIngestRow) -> CompListing:
    city, region = _normalize_geo(row.city, row.region)
    return CompListing(
        model_id=row.model_id,
        condition_bucket=row.condition_bucket,
        defects=row.defects or "",
        price=float(row.price),
        region=region,
        city=city,
        source=row.source,
        external_ref=row.external_ref,
        observed_at=_parse_observed_at(row.observed_at),
    )


def ingest_comp_rows(
    db: Session,
    rows: Iterable[CompIngestRow | dict[str, Any]],
    *,
    source: str | None = None,
) -> IngestResult:
    """
    Upsert comps by (source, external_ref).
    Prices stored as observed local RUB; valuation applies regional index at read time.
    """
    result = IngestResult(errors=[])
    model_cache: dict[int, bool] = {}
    seen_keys: set[tuple[str, str]] = set()

    for raw in rows:
        if isinstance(raw, CompIngestRow):
            row = raw
        else:
            src = str(raw.get("source") or source or "partner_feed").strip()
            ref = str(raw.get("external_ref") or "").strip()
            row = CompIngestRow(
                model_id=int(raw["model_id"]),
                condition_bucket=str(raw["condition_bucket"]).strip().lower(),
                price=float(raw["price"]),
                region=str(raw.get("region") or "Москва"),
                city=str(raw.get("city") or "Москва"),
                source=src,
                external_ref=ref,
                defects=str(raw.get("defects") or ""),
                observed_at=raw.get("observed_at"),
            )

        if source and row.source != source:
            row = CompIngestRow(
                model_id=row.model_id,
                condition_bucket=row.condition_bucket,
                price=row.price,
                region=row.region,
                city=row.city,
                source=source,
                external_ref=row.external_ref,
                defects=row.defects,
                observed_at=row.observed_at,
            )

        dedupe_key = (row.source, row.external_ref)
        if dedupe_key in seen_keys:
            result.skipped += 1
            continue
        seen_keys.add(dedupe_key)

        err = _validate_row(db, row, model_cache=model_cache)
        if err:
            result.skipped += 1
            if result.errors is not None:
                result.errors.append(f"{row.external_ref}: {err}")
            continue

        existing = (
            db.query(CompListing)
            .filter(
                CompListing.source == row.source,
                CompListing.external_ref == row.external_ref,
            )
            .first()
        )
        if existing:
            city, region = _normalize_geo(row.city, row.region)
            existing.model_id = row.model_id
            existing.condition_bucket = row.condition_bucket
            existing.defects = row.defects or ""
            existing.price = float(row.price)
            existing.region = region
            existing.city = city
            existing.observed_at = _parse_observed_at(row.observed_at)
            result.updated += 1
        else:
            db.add(_row_to_listing(row))
            result.inserted += 1

    db.commit()
    if result.errors is not None and len(result.errors) == 0:
        result.errors = None

    logger.info(
        "Comps ingest source=%s inserted=%s updated=%s skipped=%s",
        source,
        result.inserted,
        result.updated,
        result.skipped,
    )
    return result
