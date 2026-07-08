"""Manual JSON ingest — admin POST /api/admin/comps/ingest or CLI."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.comps.types import CompIngestRow


class ManualJsonSource:
    source_id = "manual_json"

    def fetch_rows(self, db: Session, *, rows: list[dict[str, Any]] | None = None, **_: Any) -> list[CompIngestRow]:
        del db  # validation uses ingest layer; no DB reads here
        out: list[CompIngestRow] = []
        for raw in rows or []:
            ref = str(raw.get("external_ref") or "").strip()
            if not ref:
                continue
            out.append(
                CompIngestRow(
                    model_id=int(raw["model_id"]),
                    condition_bucket=str(raw["condition_bucket"]).strip().lower(),
                    price=float(raw["price"]),
                    region=str(raw.get("region") or "Москва").strip(),
                    city=str(raw.get("city") or "Москва").strip(),
                    source=self.source_id,
                    external_ref=ref,
                    defects=str(raw.get("defects") or "").strip(),
                    observed_at=raw.get("observed_at"),
                )
            )
        return out
