"""Comp source adapter interface."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.comps.types import CompIngestRow


class CompSource(Protocol):
    """Pull normalized comp rows from a marketplace or feed."""

    source_id: str

    def fetch_rows(self, db: Session, **kwargs: Any) -> list[CompIngestRow]:
        """Return rows ready for ingest_comp_rows (no DB writes)."""
        ...
