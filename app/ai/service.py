"""Scan orchestration: rate limits, usage ledger, identify + comps."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.providers import identify_from_image, provider_ready
from app.ai.scan import comps_preview, match_canonical
from app.config import FREE_SCANS_PER_DAY, PRO_SCANS_PER_DAY
from app.models import ApiUsage, ScanJob, User, utcnow


def scans_today(db: Session, user_id: int) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(ScanJob.id))
        .filter(ScanJob.user_id == user_id, ScanJob.created_at >= start)
        .scalar()
        or 0
    )


def scan_limit_for(user: User) -> int:
    return PRO_SCANS_PER_DAY if (user.plan or "free") == "pro" else FREE_SCANS_PER_DAY


def can_scan(db: Session, user: User) -> tuple[bool, str]:
    used = scans_today(db, user.id)
    limit = scan_limit_for(user)
    if used >= limit:
        return False, f"Лимит сканов на сегодня: {limit}. Завтра снова или Pro."
    return True, ""


async def run_photo_scan(
    db: Session,
    user: User,
    image_bytes: bytes,
    mime: str,
    filename: str = "",
) -> ScanJob:
    ok, reason = can_scan(db, user)
    if not ok:
        raise PermissionError(reason)

    identified = await identify_from_image(image_bytes, mime=mime, filename_hint=filename)
    match = match_canonical(db, identified)

    usage = ApiUsage(
        user_id=user.id,
        feature="vision_scan",
        provider=identified.provider,
        model=identified.model,
        input_tokens=identified.input_tokens,
        output_tokens=identified.output_tokens,
        provider_cost_usd=identified.cost.provider_cost_usd,
        markup_pct=identified.cost.markup_pct,
        billed_usd=identified.cost.billed_usd,
        billed_rub=identified.cost.billed_rub,
        mock=identified.mock,
        meta_json=json.dumps(
            {"filename": filename, "mime": mime, "ready": provider_ready()},
            ensure_ascii=False,
        ),
    )
    db.add(usage)
    db.flush()

    low = mid = high = None
    comps_count = 0
    val_conf = "low"
    condition = identified.condition_guess or "good"
    if match.model:
        val = comps_preview(db, match.model.id, condition)
        low, mid, high = val.low, val.mid, val.high
        comps_count = val.comps_count
        val_conf = val.confidence

    payload = {
        "identify": {
            "brand": identified.brand,
            "model_hint": identified.model_hint,
            "category": identified.category,
            "condition_guess": condition,
            "confidence": identified.confidence,
            "mock": identified.mock,
        },
        "match": {
            "model_id": match.model.id if match.model else None,
            "label": f"{match.model.brand} {match.model.name}" if match.model else None,
            "score": match.score,
            "candidates": match.candidates,
        },
        "valuation": {
            "low": low,
            "mid": mid,
            "high": high,
            "comps_count": comps_count,
            "confidence": val_conf,
        },
        "billing": {
            "provider_cost_usd": identified.cost.provider_cost_usd,
            "markup_pct": identified.cost.markup_pct,
            "billed_usd": identified.cost.billed_usd,
            "billed_rub": identified.cost.billed_rub,
            "mock": identified.mock,
        },
    }

    job = ScanJob(
        user_id=user.id,
        status="done",
        category=identified.category,
        brand=identified.brand,
        model_hint=identified.model_hint,
        condition_guess=condition,
        identify_confidence=identified.confidence,
        matched_model_id=match.model.id if match.model else None,
        match_score=match.score,
        low=low,
        mid=mid,
        high=high,
        comps_count=comps_count,
        valuation_confidence=val_conf,
        usage_id=usage.id,
        result_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def usage_summary(db: Session, user_id: Optional[int] = None, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    q = db.query(ApiUsage).filter(ApiUsage.created_at >= since)
    if user_id is not None:
        q = q.filter(ApiUsage.user_id == user_id)
    rows = q.all()
    return {
        "calls": len(rows),
        "provider_cost_usd": round(sum(r.provider_cost_usd for r in rows), 6),
        "billed_usd": round(sum(r.billed_usd for r in rows), 6),
        "billed_rub": round(sum(r.billed_rub for r in rows), 2),
        "margin_usd": round(sum(r.billed_usd - r.provider_cost_usd for r in rows), 6),
        "mock_calls": sum(1 for r in rows if r.mock),
        "days": days,
    }
