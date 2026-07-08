"""Normalized comp row for ingest pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class CompIngestRow:
    model_id: int
    condition_bucket: str
    price: float
    region: str
    city: str
    source: str
    external_ref: str
    defects: str = ""
    observed_at: Optional[datetime] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "condition_bucket": self.condition_bucket,
            "defects": self.defects,
            "price": self.price,
            "region": self.region,
            "city": self.city,
            "source": self.source,
            "external_ref": self.external_ref,
            "observed_at": self.observed_at,
        }
