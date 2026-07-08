"""Valuation engine: comps → P25/P50/P75 within condition bucket."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, timezone
from statistics import median
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.config import COMPS_WINDOW_DAYS, COMP_RECENCY_HALF_LIFE_DAYS, MIN_COMPS_FOR_CONFIDENCE
from app.models import CompListing, Item, ValuationSnapshot, utcnow
from app.regions import price_index_for

# Defect multipliers applied when comps for exact defect set are scarce
DEFECT_MULTIPLIERS = {
    "cracked_screen": 0.72,
    "non_original_battery": 0.90,
    "icloud_lock": 0.55,
    "after_repair": 0.88,
    "water_damage": 0.65,
    "accident": 0.82,
    "repainted": 0.92,
    "multiple_owners": 0.95,
}


@dataclass
class ValuationResult:
    low: float
    mid: float
    high: float
    confidence: str
    comps_count: int
    geo_level: str
    insufficient_data: bool
    method: str = "comps_percentile"
    newest_observed_at: Optional[datetime] = None
    freshness_days: Optional[int] = None


def percentile(sorted_vals: Sequence[float], p: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _normalize_defects(defects: Sequence[str]) -> str:
    return ",".join(sorted(d for d in defects if d))


def _confidence(count: int, insufficient: bool) -> str:
    if insufficient or count < MIN_COMPS_FOR_CONFIDENCE:
        return "low"
    if count < 12:
        return "medium"
    return "high"


def _apply_defect_multipliers(base: ValuationResult, defects: Sequence[str]) -> ValuationResult:
    mult = 1.0
    for d in defects:
        mult *= DEFECT_MULTIPLIERS.get(d, 1.0)
    if mult == 1.0:
        return base
    return ValuationResult(
        low=round(base.low * mult),
        mid=round(base.mid * mult),
        high=round(base.high * mult),
        confidence=base.confidence if base.confidence == "low" else "medium",
        comps_count=base.comps_count,
        geo_level=base.geo_level,
        insufficient_data=base.insufficient_data,
        method="comps_percentile_defect_adj",
        newest_observed_at=base.newest_observed_at,
        freshness_days=base.freshness_days,
    )


def _freshness_meta(comps: list[CompListing]) -> tuple[Optional[datetime], Optional[int]]:
    if not comps:
        return None, None
    newest = max(c.observed_at for c in comps if c.observed_at)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    age = max(0, int((utcnow() - newest).total_seconds() // 86400))
    return newest, age


def fetch_comps(
    db: Session,
    model_id: int,
    condition: str,
    defects_key: str,
    city: str,
    region: str,
    window_days: int = COMPS_WINDOW_DAYS,
) -> tuple[list[CompListing], str]:
    since = utcnow() - timedelta(days=window_days)
    base_q = (
        db.query(CompListing)
        .filter(
            CompListing.model_id == model_id,
            CompListing.condition_bucket == condition,
            CompListing.observed_at >= since,
        )
    )

    # Prefer exact defect match, then empty-defect comps
    for defects_filter in (defects_key, ""):
        q = base_q.filter(CompListing.defects == defects_filter)
        city_rows = q.filter(CompListing.city == city).all()
        if len(city_rows) >= MIN_COMPS_FOR_CONFIDENCE:
            return city_rows, "city"
        region_rows = q.filter(CompListing.region == region).all()
        if len(region_rows) >= MIN_COMPS_FOR_CONFIDENCE:
            return region_rows, "region"
        country_rows = q.all()
        if country_rows:
            return country_rows, "country"

    # Fallback: any defects in same condition
    any_rows = base_q.all()
    return any_rows, "country"


def _recency_weight(observed_at: datetime, now: datetime) -> float:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = max(0.0, (now - observed_at).total_seconds() / 86400.0)
    half = max(1.0, COMP_RECENCY_HALF_LIFE_DAYS)
    return max(0.25, 0.5 ** (age / half))


def weighted_percentile(
    weighted_prices: Sequence[tuple[float, float]], p: float
) -> float:
    """Percentile on (price, weight) pairs — fresher comps weigh more."""
    if not weighted_prices:
        raise ValueError("empty")
    pairs = sorted(weighted_prices, key=lambda x: x[0])
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return float(pairs[len(pairs) // 2][0])
    target = (p / 100.0) * total_w
    acc = 0.0
    for price, w in pairs:
        acc += w
        if acc >= target:
            return float(price)
    return float(pairs[-1][0])


def _comps_to_weighted_prices(
    comps: list[CompListing],
    city: str,
    region: str,
) -> list[tuple[float, float]]:
    now = utcnow()
    idx = price_index_for(city, region)
    out: list[tuple[float, float]] = []
    for c in comps:
        w = _recency_weight(c.observed_at, now)
        out.append((round(c.price * idx), w))
    return out


def compute_valuation(db: Session, item: Item) -> ValuationResult:
    defects = item.defect_list()
    defects_key = _normalize_defects(defects)

    comps, geo_level = fetch_comps(
        db,
        model_id=item.canonical_model_id,
        condition=item.condition,
        defects_key=defects_key,
        city=item.location_city,
        region=item.location_region,
    )

    weighted = _comps_to_weighted_prices(comps, item.location_city, item.location_region)
    prices = sorted(p for p, _ in weighted)
    insufficient = len(prices) < MIN_COMPS_FOR_CONFIDENCE
    newest_obs, freshness_days = _freshness_meta(comps)

    if not prices:
        # Honest empty: wide unknown band around cost_basis or zero
        anchor = item.cost_basis or 0.0
        if anchor <= 0:
            return ValuationResult(
                low=0,
                mid=0,
                high=0,
                confidence="low",
                comps_count=0,
                geo_level=geo_level,
                insufficient_data=True,
                method="no_comps",
                newest_observed_at=None,
                freshness_days=None,
            )
        result = ValuationResult(
            low=round(anchor * 0.7),
            mid=round(anchor),
            high=round(anchor * 1.15),
            confidence="low",
            comps_count=0,
            geo_level=geo_level,
            insufficient_data=True,
            method="cost_basis_fallback",
            newest_observed_at=None,
            freshness_days=None,
        )
        return _apply_defect_multipliers(result, defects)

    low = weighted_percentile(weighted, 25)
    mid = weighted_percentile(weighted, 50)
    high = weighted_percentile(weighted, 75)

    # Widen band when data is scarce
    if insufficient:
        spread = max(mid * 0.12, (high - low) * 0.5)
        low = mid - spread
        high = mid + spread

    result = ValuationResult(
        low=round(low),
        mid=round(mid),
        high=round(high),
        confidence=_confidence(len(prices), insufficient),
        comps_count=len(prices),
        geo_level=geo_level,
        insufficient_data=insufficient,
        method="comps_weighted_percentile",
        newest_observed_at=newest_obs,
        freshness_days=freshness_days,
    )

    # If we used comps without matching defects, adjust
    used_exact = any(
        _normalize_defects(c.defects.split(",") if c.defects else []) == defects_key
        for c in comps
    )
    if defects and not used_exact:
        result = _apply_defect_multipliers(result, defects)

    return result


def save_snapshot(db: Session, item: Item, result: Optional[ValuationResult] = None) -> ValuationSnapshot:
    result = result or compute_valuation(db, item)
    snap = ValuationSnapshot(
        item_id=item.id,
        ts=utcnow(),
        low=result.low,
        mid=result.mid,
        high=result.high,
        confidence=result.confidence,
        comps_count=result.comps_count,
        method=result.method,
        geo_level=result.geo_level,
        insufficient_data=result.insufficient_data,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def display_mid(item: Item, snap: Optional[ValuationSnapshot]) -> Optional[float]:
    """Portfolio sum uses override if set, else market mid."""
    if item.override_mid is not None:
        return item.override_mid
    if snap is None:
        return None
    return snap.mid


def latest_snapshot(item: Item) -> Optional[ValuationSnapshot]:
    if not item.valuations:
        return None
    return item.valuations[-1]
