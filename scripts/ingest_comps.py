"""CLI: ingest comps from JSON file (manual_json source)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.comps.ingest import ingest_comp_rows
from app.models import SessionLocal, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest comps from JSON file")
    parser.add_argument("path", type=Path, help="JSON file with source + rows")
    parser.add_argument(
        "--source",
        default=None,
        help="Override source id (default: from file or manual_json)",
    )
    args = parser.parse_args()

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    source = args.source or payload.get("source") or "manual_json"
    rows = payload.get("rows") or []

    init_db()
    db = SessionLocal()
    try:
        result = ingest_comp_rows(db, rows, source=source)
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ingested else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
