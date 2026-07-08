"""Vision/LLM providers — OpenAI-compatible (OpenAI, Poe gateway, OpenRouter)."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.ai.billing import UsageCost, estimate_vision_cost, markup_for_model
from app.config import (
    AI_API_KEY,
    AI_BASE_URL,
    AI_FORCE_MOCK,
    AI_MODEL,
    AI_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)


@dataclass
class IdentifyResult:
    brand: str
    model_hint: str
    category: str  # smartphone | laptop | car | unknown
    condition_guess: str
    confidence: float
    raw_text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: UsageCost
    mock: bool = False


SYSTEM_PROMPT = """Ты помощник сервиса оценки б/у вещей в СНГ.
По фото определи товар. Ответь ТОЛЬКО JSON без markdown:
{
  "brand": "Apple",
  "model_hint": "iPhone 14 Pro 256GB",
  "category": "smartphone|laptop|car|unknown",
  "condition_guess": "mint|good|fair|poor|parts",
  "confidence": 0.0
}
Если не уверен — category=unknown, confidence низкий. Не выдумывай VIN/серийники."""


def provider_ready() -> bool:
    return bool(AI_API_KEY) and not AI_FORCE_MOCK


def _parse_json_loose(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


def _mock_identify(filename_hint: str = "") -> IdentifyResult:
    """Offline/dev fallback — keeps product stable without API keys."""
    hint = (filename_hint or "").lower()
    brand, model_hint, category = "Apple", "iPhone 14 Pro 256GB", "smartphone"
    if "mac" in hint or "laptop" in hint or "notebook" in hint:
        brand, model_hint, category = "Apple", "MacBook Air M2 8/256", "laptop"
    elif "camry" in hint or "car" in hint or "auto" in hint:
        brand, model_hint, category = "Toyota", "Toyota Camry 2.5 2019", "car"
    elif "samsung" in hint or "galaxy" in hint:
        brand, model_hint, category = "Samsung", "Galaxy S23 Ultra 256GB", "smartphone"
    cost = estimate_vision_cost(800, 120, 1, markup_pct=15)
    return IdentifyResult(
        brand=brand,
        model_hint=model_hint,
        category=category,
        condition_guess="good",
        confidence=0.55,
        raw_text="mock",
        provider="mock",
        model="mock-local",
        input_tokens=800,
        output_tokens=120,
        cost=cost,
        mock=True,
    )


async def identify_from_image(
    image_bytes: bytes,
    mime: str = "image/jpeg",
    filename_hint: str = "",
) -> IdentifyResult:
    if not provider_ready():
        return _mock_identify(filename_hint)

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    model = AI_MODEL
    markup = markup_for_model(model)

    payload = {
        "model": model,
        "temperature": 0.1,
        # Poe ignores response_format; keep for OpenAI-compatible hosts that support it
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Определи вещь на фото для оценки на вторичном рынке СНГ. Ответ — только JSON.",
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    if "poe.com" not in AI_BASE_URL.lower():
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT_SEC) as client:
            resp = await client.post(
                f"{AI_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.exception("AI provider failed, falling back to mock: %s", exc)
        result = _mock_identify(filename_hint)
        result.raw_text = f"fallback_after_error:{type(exc).__name__}"
        return result

    choice = (data.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content")) or "{}"
    usage = data.get("usage") or {}
    in_tok = int(usage.get("prompt_tokens") or 900)
    out_tok = int(usage.get("completion_tokens") or 150)

    try:
        parsed = _parse_json_loose(content)
    except Exception:
        parsed = {
            "brand": "",
            "model_hint": "",
            "category": "unknown",
            "condition_guess": "good",
            "confidence": 0.2,
        }

    cost = estimate_vision_cost(in_tok, out_tok, 1, markup_pct=markup)
    return IdentifyResult(
        brand=str(parsed.get("brand") or "").strip() or "Unknown",
        model_hint=str(parsed.get("model_hint") or "").strip(),
        category=str(parsed.get("category") or "unknown").strip().lower(),
        condition_guess=str(parsed.get("condition_guess") or "good").strip().lower(),
        confidence=float(parsed.get("confidence") or 0.3),
        raw_text=content[:2000],
        provider="openai_compatible",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost=cost,
        mock=False,
    )
