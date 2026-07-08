"""Match AI identify result → canonical model + comps valuation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.providers import IdentifyResult
from app.models import CanonicalModel, CompListing, Condition
from app.valuation import ValuationResult, compute_valuation, percentile
from app.config import COMPS_WINDOW_DAYS, MIN_COMPS_FOR_CONFIDENCE
from datetime import timedelta
from app.models import utcnow


@dataclass
class ScanMatch:
    model: Optional[CanonicalModel]
    score: float
    candidates: list[dict]


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("-", " ").split())


def match_canonical(db: Session, identified: IdentifyResult) -> ScanMatch:
    q = db.query(CanonicalModel)
    if identified.category in {"smartphone", "laptop", "car"}:
        q = q.filter(CanonicalModel.category == identified.category)
    models = q.all()
    needle = _norm(f"{identified.brand} {identified.model_hint}")
    scored: list[tuple[float, CanonicalModel]] = []
    for m in models:
        hay = _norm(f"{m.brand} {m.name} {m.search_text}")
        score = 0.0
        if identified.brand and _norm(identified.brand) in hay:
            score += 0.35
        # token overlap
        tokens = [t for t in needle.split() if len(t) > 1]
        if tokens:
            hits = sum(1 for t in tokens if t in hay)
            score += 0.65 * (hits / len(tokens))
        scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    top = scored[:5]
    best = top[0] if top and top[0][0] >= 0.35 else None
    return ScanMatch(
        model=best[1] if best else None,
        score=best[0] if best else 0.0,
        candidates=[
            {
                "id": m.id,
                "label": f"{m.brand} {m.name}",
                "category": m.category,
                "score": round(s, 3),
            }
            for s, m in top
            if s > 0.15
        ],
    )


def comps_preview(
    db: Session,
    model_id: int,
    condition: str,
    city: str = "Москва",
    region: str = "Москва",
) -> ValuationResult:
    """Lightweight valuation without creating an Item."""
    from app.models import Item

    # Temporary in-memory-like object via detached Item pattern
    class _Tmp:
        pass

    tmp = _Tmp()
    tmp.id = 0
    tmp.canonical_model_id = model_id
    tmp.condition = condition if condition in {c.value for c in Condition} else Condition.GOOD.value
    tmp.defects = ""
    tmp.location_city = city
    tmp.location_region = region
    tmp.cost_basis = None
    tmp.defect_list = lambda: []  # type: ignore

    # Reuse fetch via compute_valuation expecting Item — build real ephemeral Item
    item = Item(
        owner_id=0,
        category="smartphone",
        canonical_model_id=model_id,
        condition=tmp.condition,
        location_city=city,
        location_region=region,
    )
    # owner_id 0 may violate FK if flushed — don't add to session
    return _compute_without_persist(db, item)


def _compute_without_persist(db: Session, item) -> ValuationResult:
    since = utcnow() - timedelta(days=COMPS_WINDOW_DAYS)
    rows = (
        db.query(CompListing)
        .filter(
            CompListing.model_id == item.canonical_model_id,
            CompListing.condition_bucket == item.condition,
            CompListing.observed_at >= since,
            CompListing.defects == "",
        )
        .all()
    )
    # geo prefer city
    city_rows = [r for r in rows if r.city == item.location_city]
    use = city_rows if len(city_rows) >= MIN_COMPS_FOR_CONFIDENCE else rows
    prices = sorted(r.price for r in use)
    if not prices:
        return ValuationResult(
            low=0,
            mid=0,
            high=0,
            confidence="low",
            comps_count=0,
            geo_level="country",
            insufficient_data=True,
            method="no_comps",
        )
    mid = percentile(prices, 50)
    low = percentile(prices, 25)
    high = percentile(prices, 75)
    insufficient = len(prices) < MIN_COMPS_FOR_CONFIDENCE
    if insufficient:
        spread = max(mid * 0.12, (high - low) * 0.5)
        low, high = mid - spread, mid + spread
    conf = "low" if insufficient else ("medium" if len(prices) < 12 else "high")
    return ValuationResult(
        low=round(low),
        mid=round(mid),
        high=round(high),
        confidence=conf,
        comps_count=len(prices),
        geo_level="city" if city_rows and len(city_rows) >= MIN_COMPS_FOR_CONFIDENCE else "country",
        insufficient_data=insufficient,
        method="comps_percentile",
    )
