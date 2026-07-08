"""Match AI identify result → canonical model + comps valuation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.providers import IdentifyResult
from app.config import COMPS_WINDOW_DAYS, MIN_COMPS_FOR_CONFIDENCE
from app.models import CanonicalModel, CompListing, Condition, utcnow
from app.valuation import ValuationResult, percentile

# Brand / product aliases → canonical brand tokens used in catalog
_BRAND_ALIASES: dict[str, str] = {
    "apple": "apple",
    "iphone": "apple",
    "айфон": "apple",
    "macbook": "apple",
    "макбук": "apple",
    "samsung": "samsung",
    "galaxy": "samsung",
    "самсунг": "samsung",
    "xiaomi": "xiaomi",
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "mi": "xiaomi",
    "сяоми": "xiaomi",
    "google": "google",
    "pixel": "google",
    "гугл": "google",
    "nothing": "nothing",
    "oneplus": "oneplus",
    "realme": "realme",
    "honor": "honor",
    "huawei": "huawei",
    "asus": "asus",
    "lenovo": "lenovo",
    "thinkpad": "lenovo",
    "toyota": "toyota",
    "hyundai": "hyundai",
    "kia": "kia",
    "volkswagen": "volkswagen",
    "vw": "volkswagen",
    "lada": "lada",
    "ваз": "lada",
    "geely": "geely",
    "haval": "haval",
    "chery": "chery",
}


@dataclass
class ScanMatch:
    model: Optional[CanonicalModel]
    score: float
    candidates: list[dict]


def _norm(s: str) -> str:
    s = (s or "").lower().replace("-", " ").replace("_", " ")
    s = s.replace("(", " ").replace(")", " ")
    s = re.sub(r"[^\w\s+/]", " ", s, flags=re.UNICODE)
    return " ".join(s.split())


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).split() if len(t) > 1]


def _canonical_brand(text: str) -> str | None:
    for tok in _tokens(text):
        if tok in _BRAND_ALIASES:
            return _BRAND_ALIASES[tok]
    return None


def _storage_tokens(text: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(r"\b(\d+)\s*(gb|гб|tb|тб)\b", text.lower()):
        found.add(f"{m.group(1)}{m.group(2)[:2].replace('гб', 'gb').replace('тб', 'tb')}")
        found.add(m.group(1))
    # bare 128/256/512 near phone context
    for m in re.finditer(r"\b(64|128|256|512|1024)\b", text):
        found.add(m.group(1))
    return found


def _generation_boost(needle: str, hay: str) -> float:
    """Prefer exact generation (iphone 14 vs 15, s24 vs s23)."""
    boost = 0.0
    # iPhone N / Galaxy SNN / Pixel N / Xiaomi N
    for pattern in (
        r"iphone\s*(\d{1,2})",
        r"galaxy\s*s(\d{1,2})",
        r"pixel\s*(\d{1,2})",
        r"xiaomi\s*(\d{1,2})",
        r"\bs(\d{2})\b",
    ):
        n_m = re.search(pattern, needle)
        h_m = re.search(pattern, hay)
        if n_m and h_m and n_m.group(1) == h_m.group(1):
            boost += 0.18
        elif n_m and h_m and n_m.group(1) != h_m.group(1):
            boost -= 0.12
    # Pro / Max / Ultra / Plus / mini / Flip / Fold
    for tag in ("pro max", "pro", "ultra", "plus", "mini", "flip", "fold", "air"):
        in_n = tag in needle
        in_h = tag in hay
        if in_n and in_h:
            boost += 0.08
        elif in_n and not in_h:
            boost -= 0.04
    return boost


def match_canonical(db: Session, identified: IdentifyResult) -> ScanMatch:
    q = db.query(CanonicalModel)
    if identified.category in {"smartphone", "laptop", "car"}:
        q = q.filter(CanonicalModel.category == identified.category)
    models = q.all()
    brand_hint = _norm(identified.brand or "")
    model_hint = _norm(identified.model_hint or "")
    needle = _norm(f"{identified.brand} {identified.model_hint}")
    needle_brand = _canonical_brand(f"{brand_hint} {model_hint}")
    needle_storage = _storage_tokens(f"{identified.brand} {identified.model_hint}")
    tokens = _tokens(needle)

    scored: list[tuple[float, CanonicalModel]] = []
    for m in models:
        hay = _norm(f"{m.brand} {m.name} {m.search_text}")
        model_brand = _canonical_brand(f"{m.brand} {m.name}")
        score = 0.0

        # Brand alignment
        if needle_brand and model_brand and needle_brand == model_brand:
            score += 0.40
        elif identified.brand and _norm(identified.brand) in hay:
            score += 0.30
        elif needle_brand and needle_brand in hay:
            score += 0.28

        # Token overlap (ignore ultra-generic tokens)
        skip = {"gb", "гб", "phone", "galaxy", "the"}
        useful = [t for t in tokens if t not in skip]
        if useful:
            hits = sum(1 for t in useful if t in hay)
            score += 0.45 * (hits / len(useful))

        # Substring of model hint inside catalog name
        if model_hint and len(model_hint) >= 4 and model_hint in hay:
            score += 0.15

        score += _generation_boost(needle, hay)

        # Storage match
        hay_storage = _storage_tokens(f"{m.name} {m.attrs_json or ''}")
        if needle_storage and hay_storage:
            if needle_storage & hay_storage:
                score += 0.08
            else:
                score -= 0.03

        scored.append((min(score, 1.0), m))

    scored.sort(key=lambda x: -x[0])
    top = scored[:5]
    best = top[0] if top and top[0][0] >= 0.32 else None
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
    cond = condition if condition in {c.value for c in Condition} else Condition.GOOD.value
    since = utcnow() - timedelta(days=COMPS_WINDOW_DAYS)
    rows = (
        db.query(CompListing)
        .filter(
            CompListing.model_id == model_id,
            CompListing.condition_bucket == cond,
            CompListing.observed_at >= since,
        )
        .all()
    )
    city_rows = [c for c in rows if c.city == city]
    use = city_rows if len(city_rows) >= MIN_COMPS_FOR_CONFIDENCE else rows
    prices = sorted(c.price for c in use)
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
    return ValuationResult(
        low=round(percentile(prices, 25)),
        mid=round(percentile(prices, 50)),
        high=round(percentile(prices, 75)),
        confidence="medium" if len(prices) >= MIN_COMPS_FOR_CONFIDENCE else "low",
        comps_count=len(prices),
        geo_level="city"
        if city_rows and len(city_rows) >= MIN_COMPS_FOR_CONFIDENCE
        else "country",
        insufficient_data=len(prices) < MIN_COMPS_FOR_CONFIDENCE,
        method="comps_preview",
    )
