"""Marketplace comp source adapters (manual JSON, mock refresh, future APIs)."""

from app.comps.sources.base import CompSource
from app.comps.sources.manual_json import ManualJsonSource
from app.comps.sources.mock_market import MockMarketSource
from app.comps.sources.registry import INGESTABLE_SOURCES, SOURCE_LABELS, is_ingestable

__all__ = [
    "CompSource",
    "INGESTABLE_SOURCES",
    "ManualJsonSource",
    "MockMarketSource",
    "SOURCE_LABELS",
    "is_ingestable",
]
