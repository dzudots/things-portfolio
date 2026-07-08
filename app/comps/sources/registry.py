"""Whitelist of comp sources — production-safe, no arbitrary scraper names."""

from __future__ import annotations

# All sources that may appear in comp_listings.source
KNOWN_SOURCES = frozenset(
    {
        "seed",  # bootstrap only
        "manual_json",  # admin JSON ingest
        "mock_market",  # scheduled demo refresh
        "partner_feed",  # B2B aggregate feed
        "avito_api",  # future: official/partner API
        "kufar_api",  # future: official/partner API
    }
)

# Sources allowed via ingest API / adapters (not seed)
INGESTABLE_SOURCES = frozenset(KNOWN_SOURCES - {"seed"})

# Existing rows from these sources may be touched by mock refresh
REFRESHABLE_SOURCES = frozenset({"seed", "manual_json", "partner_feed", "mock_market"})

SOURCE_LABELS: dict[str, str] = {
    "seed": "Seed bootstrap",
    "manual_json": "Manual JSON ingest",
    "mock_market": "Mock market refresh",
    "partner_feed": "Partner aggregate feed",
    "avito_api": "Avito API (planned)",
    "kufar_api": "Kufar API (planned)",
}


def is_ingestable(source: str) -> bool:
    return (source or "").strip() in INGESTABLE_SOURCES
