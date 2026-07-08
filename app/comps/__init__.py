"""Comps ingestion: whitelist sources, dedupe, regional normalization."""

from app.comps.ingest import IngestResult, ingest_comp_rows

__all__ = ["IngestResult", "ingest_comp_rows"]
