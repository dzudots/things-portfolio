"""AI cost ledger: provider cost + 10–30% markup for product stability."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import (
    AI_IMAGE_USD,
    AI_INPUT_USD_PER_1M,
    AI_MARKUP_PCT,
    AI_OUTPUT_USD_PER_1M,
    USD_RUB,
)


@dataclass
class UsageCost:
    provider_cost_usd: float
    markup_pct: float
    billed_usd: float
    billed_rub: float

    @property
    def margin_usd(self) -> float:
        return self.billed_usd - self.provider_cost_usd


def clamp_markup(pct: float) -> float:
    return max(10.0, min(30.0, float(pct)))


def estimate_vision_cost(
    input_tokens: int = 0,
    output_tokens: int = 0,
    images: int = 1,
    markup_pct: float | None = None,
) -> UsageCost:
    """
    Estimate provider cost then apply product markup.

    Markup policy (product):
    - cheap models / high volume → closer to 10–15%
    - mid models → ~20% (default)
    - expensive vision → up to 30%
    """
    markup = clamp_markup(AI_MARKUP_PCT if markup_pct is None else markup_pct)
    provider = (
        (input_tokens / 1_000_000.0) * AI_INPUT_USD_PER_1M
        + (output_tokens / 1_000_000.0) * AI_OUTPUT_USD_PER_1M
        + images * AI_IMAGE_USD
    )
    # Floor so even tiny calls are tracked
    provider = max(provider, 0.0001)
    billed = provider * (1.0 + markup / 100.0)
    return UsageCost(
        provider_cost_usd=round(provider, 6),
        markup_pct=markup,
        billed_usd=round(billed, 6),
        billed_rub=round(billed * USD_RUB, 4),
    )


def markup_for_model(model: str) -> float:
    """Heuristic tier → markup inside 10–30%."""
    m = (model or "").lower()
    if any(x in m for x in ("mini", "flash", "haiku", "small")):
        return clamp_markup(min(AI_MARKUP_PCT, 15))
    if any(x in m for x in ("o1", "o3", "gpt-4", "claude-3-opus", "sonnet", "pro")):
        return clamp_markup(max(AI_MARKUP_PCT, 25))
    return clamp_markup(AI_MARKUP_PCT)
