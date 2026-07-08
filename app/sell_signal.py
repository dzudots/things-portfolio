"""Sell-now job: one action + one phrase from mid trend and comps quality."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from app.models import ValuationSnapshot, utcnow


@dataclass(frozen=True)
class SellSignal:
    """Product answer: sell / wait / refresh listing / uncertain."""

    action: str  # sell_now | wait | refresh_listing | uncertain
    action_label: str  # short verb for UI / alerts
    headline: str  # one recommendation sentence
    reason: str  # supporting line
    trend_days: int
    trend_pct: Optional[float]
    money_delta: Optional[float]  # mid_now - mid_then (signed ₽)
    before_mid: Optional[float]
    after_mid: Optional[float]
    before_after_line: Optional[str]
    comps_note: Optional[str]  # honest copy when weak/stale
    confidence: str  # high | medium | low


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def mid_at_or_before(
    valuations: Sequence[ValuationSnapshot],
    *,
    days: int,
) -> Optional[float]:
    """Latest snapshot mid at or before now-days; else earliest available."""
    if not valuations:
        return None
    ordered = sorted(
        (v for v in valuations if _aware(v.ts) is not None),
        key=lambda v: _aware(v.ts) or utcnow(),
    )
    if not ordered:
        return None
    cutoff = utcnow() - timedelta(days=days)
    past = [v for v in ordered if (_aware(v.ts) or cutoff) <= cutoff]
    if past:
        return past[-1].mid
    if len(ordered) >= 2:
        return ordered[0].mid
    return ordered[-1].mid


def _pct(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None or old == 0:
        return None
    return ((new - old) / old) * 100.0


def _fmt_money_rub(value: float) -> str:
    return f"{int(round(value)):,} ₽".replace(",", " ")


def comps_honesty(
    *,
    comps_count: int,
    insufficient_data: bool,
    freshness_days: Optional[int],
    confidence: str,
    band_pct: Optional[float],
) -> Optional[str]:
    """Never imply false precision when comps are weak or stale."""
    if insufficient_data or comps_count < 5 or confidence == "low":
        return (
            "Ориентир, не точная цена: мало похожих объявлений. "
            "Перед сделкой сверь 2–3 свежих лота."
        )
    if freshness_days is not None and freshness_days >= 14:
        return (
            f"Comps старше {freshness_days} дн. — цифра могла устареть. "
            "Перед продажей обнови объявление и перепроверь рынок."
        )
    if band_pct is not None and band_pct >= 25:
        return (
            "Разброс рынка широкий — mid условный. "
            "Смотри диапазон low–high, не одну цифру."
        )
    return None


def build_sell_signal(
    *,
    mid: Optional[float],
    valuations: Sequence[ValuationSnapshot],
    comps_count: int = 0,
    insufficient_data: bool = False,
    freshness_days: Optional[int] = None,
    confidence: str = "low",
    low: Optional[float] = None,
    high: Optional[float] = None,
    trend_days: int = 30,
) -> SellSignal:
    before = mid_at_or_before(valuations, days=trend_days)
    after = mid
    trend_pct = _pct(before, after)
    money_delta = None
    if before is not None and after is not None:
        money_delta = after - before

    band_pct = None
    if mid and mid > 0 and low is not None and high is not None:
        band_pct = ((high - low) / mid) * 100.0

    note = comps_honesty(
        comps_count=comps_count,
        insufficient_data=insufficient_data,
        freshness_days=freshness_days,
        confidence=confidence,
        band_pct=band_pct,
    )

    before_after_line = None
    if money_delta is not None and abs(money_delta) >= 500 and before is not None:
        if money_delta < 0:
            before_after_line = (
                f"За {trend_days} дн. рынок просел на {_fmt_money_rub(abs(money_delta))} "
                f"({_fmt_money_rub(before)} → {_fmt_money_rub(after or 0)}). "
                f"Если бы продал раньше — мог выиграть ~{_fmt_money_rub(abs(money_delta))}."
            )
        else:
            before_after_line = (
                f"За {trend_days} дн. рынок вырос на {_fmt_money_rub(money_delta)} "
                f"({_fmt_money_rub(before)} → {_fmt_money_rub(after or 0)}). "
                f"Если бы продал раньше — мог недополучить ~{_fmt_money_rub(money_delta)}."
            )

    # Weak data → uncertain, never a sharp sell/wait
    weak = insufficient_data or comps_count < 5 or confidence == "low"
    if mid is None or mid <= 0 or weak:
        return SellSignal(
            action="uncertain",
            action_label="уточни рынок",
            headline="Пока рано решать — данных мало для уверенного mid.",
            reason=note
            or "Добавь состояние/город точнее или подожди свежих comps.",
            trend_days=trend_days,
            trend_pct=trend_pct,
            money_delta=money_delta,
            before_mid=before,
            after_mid=after,
            before_after_line=before_after_line,
            comps_note=note,
            confidence="low",
        )

    if freshness_days is not None and freshness_days >= 14:
        return SellSignal(
            action="refresh_listing",
            action_label="обнови объявление",
            headline="Сначала обнови объявление и перепроверь рынок — comps устарели.",
            reason=note or f"Последние comps ~{freshness_days} дн. назад.",
            trend_days=trend_days,
            trend_pct=trend_pct,
            money_delta=money_delta,
            before_mid=before,
            after_mid=after,
            before_after_line=before_after_line,
            comps_note=note,
            confidence=confidence,
        )

    # Trend-based action
    pct = trend_pct if trend_pct is not None else 0.0
    if pct <= -5:
        return SellSignal(
            action="sell_now",
            action_label="продавай",
            headline="Окно продажи: рынок падает — лучше выходить сейчас, чем ждать дальше.",
            reason=(
                f"За {trend_days} дн. mid {pct:.1f}%"
                + (f" (~{_fmt_money_rub(abs(money_delta or 0))})" if money_delta else "")
                + "."
            ),
            trend_days=trend_days,
            trend_pct=trend_pct,
            money_delta=money_delta,
            before_mid=before,
            after_mid=after,
            before_after_line=before_after_line,
            comps_note=note,
            confidence=confidence,
        )

    if pct >= 5:
        return SellSignal(
            action="wait",
            action_label="подожди",
            headline="Подожди: рынок растёт — спешить с продажей не обязательно.",
            reason=(
                f"За {trend_days} дн. mid +{pct:.1f}%"
                + (f" (~{_fmt_money_rub(money_delta or 0)})" if money_delta else "")
                + ". Следи за алертом, если развернётся."
            ),
            trend_days=trend_days,
            trend_pct=trend_pct,
            money_delta=money_delta,
            before_mid=before,
            after_mid=after,
            before_after_line=before_after_line,
            comps_note=note,
            confidence=confidence,
        )

    # Flat market — soft wait / list if you need cash
    return SellSignal(
        action="wait",
        action_label="можно ждать",
        headline="Рынок спокойный — продавай, если нужны деньги; иначе можно подождать.",
        reason=(
            f"За {trend_days} дн. почти без движения"
            + (f" ({pct:+.1f}%)" if trend_pct is not None else "")
            + ". Не продешеви: держись mid, не «срочно»."
        ),
        trend_days=trend_days,
        trend_pct=trend_pct,
        money_delta=money_delta,
        before_mid=before,
        after_mid=after,
        before_after_line=before_after_line,
        comps_note=note,
        confidence=confidence,
    )


def alert_action_message(
    *,
    model_name: str,
    old_mid: float,
    new_mid: float,
    change_pct: float,
    direction: str,
) -> str:
    """Alert copy with a verb — not only raw %."""
    sign = "+" if change_pct > 0 else ""
    money = abs(new_mid - old_mid)
    money_s = _fmt_money_rub(money)
    old_s = _fmt_money_rub(old_mid)
    new_s = _fmt_money_rub(new_mid)

    if direction == "down":
        action = "Продавай или снижай цену в объявлении"
        why = f"рынок просел {sign}{change_pct:.1f}% (−{money_s})"
    else:
        action = "Подожди с продажей или подними ask"
        why = f"рынок вырос {sign}{change_pct:.1f}% (+{money_s})"

    return f"{model_name}: {action} — {why} ({old_s} → {new_s})."


# Friend-loop checklist (ops, not a feature sprawl)
FRIEND_LOOP_STEPS = [
    "Открой одну вещь в стаке (не весь портфель).",
    "За 10 секунд: понятно sell / wait / why?",
    "Есть ли честное предупреждение, если comps слабые?",
    "Алерт (если был) содержит глагол-действие?",
    "Друг сказал бы «понял, что делать» без объяснений?",
]
