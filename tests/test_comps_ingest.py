"""Tests for comps ingest pipeline and mock market refresh."""

from __future__ import annotations

import unittest
import uuid
from datetime import timedelta

from app.auth import hash_password
from app.comps.ingest import ingest_comp_rows
from app.comps.sources.mock_market import MockMarketSource
from app.jobs import refresh_market_comps
from app.models import CanonicalModel, CompListing, SessionLocal, User, init_db, utcnow


class CompsIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self._run_id = uuid.uuid4().hex[:8]
        self.user = User(
            email=f"ingest{utcnow().timestamp()}@test.local",
            password_hash=hash_password("x"),
            display_name="ingest",
        )
        self.db.add(self.user)
        self.model = CanonicalModel(
            category="smartphone",
            brand="Test",
            name="Ingest Phone",
            attrs_json="{}",
            search_text="test ingest phone",
        )
        self.db.add(self.model)
        self.db.commit()
        self.db.refresh(self.model)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_manual_ingest_and_dedupe(self):
        ref = f"test:dedupe-{utcnow().timestamp()}"
        rows = [
            {
                "model_id": self.model.id,
                "condition_bucket": "good",
                "price": 50000,
                "city": "Москва",
                "region": "Москва",
                "external_ref": ref,
            }
        ]
        first = ingest_comp_rows(self.db, rows, source="manual_json")
        self.assertEqual(first.ingested, 1)
        self.assertGreaterEqual(first.inserted + first.updated, 1)

        rows[0]["price"] = 51000
        second = ingest_comp_rows(self.db, rows, source="manual_json")
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.updated, 1)

        stored = (
            self.db.query(CompListing)
            .filter(
                CompListing.source == "manual_json",
                CompListing.external_ref == ref,
            )
            .one()
        )
        self.assertEqual(stored.price, 51000)

    def test_rejects_unknown_source(self):
        result = ingest_comp_rows(
            self.db,
            [
                {
                    "model_id": self.model.id,
                    "condition_bucket": "good",
                    "price": 1000,
                    "external_ref": "bad:1",
                }
            ],
            source="scraper_avito",
        )
        self.assertEqual(result.ingested, 0)
        self.assertEqual(result.skipped, 1)

    def test_mock_refresh_creates_fresh_comps(self):
        ref = f"test:stale-seed-{utcnow().timestamp()}"
        stale = CompListing(
            model_id=self.model.id,
            condition_bucket="good",
            price=48000,
            region="Москва",
            city="Москва",
            source="seed",
            external_ref=ref,
            observed_at=utcnow() - timedelta(days=20),
        )
        self.db.add(stale)
        self.db.commit()

        adapter = MockMarketSource()
        rows = adapter.fetch_rows(self.db, max_age_days=7, limit=10)
        self.assertGreaterEqual(len(rows), 1)

        result = ingest_comp_rows(self.db, rows, source="mock_market")
        self.assertGreaterEqual(result.ingested, 1)

    def test_refresh_job_returns_stats(self):
        stale = CompListing(
            model_id=self.model.id,
            condition_bucket="fair",
            price=40000,
            region="Алматы",
            city="Алматы",
            source="partner_feed",
            external_ref=f"test:stale-partner-{self._run_id}",
            observed_at=utcnow() - timedelta(days=15),
        )
        self.db.add(stale)
        self.db.commit()

        stats = refresh_market_comps(self.db)
        self.assertIn("refreshed", stats)
        self.assertGreaterEqual(stats["refreshed"], 1)


if __name__ == "__main__":
    unittest.main()
