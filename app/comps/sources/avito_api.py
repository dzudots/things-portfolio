"""Avito Business API adapter stub — official API only, no HTML scrape."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.comps.types import CompIngestRow

logger = logging.getLogger(__name__)


class AvitoApiSource:
    """
    Placeholder for Avito Business / partner API.
    Returns empty until THINGS_AVITO_* credentials + mapping are configured.
    """

    source_id = "avito_api"

    def fetch_rows(self, db: Session, **_: Any) -> list[CompIngestRow]:
        del db
        logger.debug("avito_api adapter not configured — skipping")
        return []
