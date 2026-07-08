"""Unit tests for valuation percentiles and condition bucketing."""

from __future__ import annotations

import unittest
from datetime import timedelta

from app.models import (
    CanonicalModel,
    CompListing,
    Condition,
    Item,
    SessionLocal,
    User,
    init_db,
    utcnow,
)
from app.auth import hash_password
from app.valuation import compute_valuation, percentile


class PercentileTests(unittest.TestCase):
    def test_median_odd(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 50), 3)

    def test_p25_p75(self):
        vals = [10, 20, 30, 40, 50, 60, 70, 80]
        self.assertAlmostEqual(percentile(vals, 25), 27.5)
        self.assertAlmostEqual(percentile(vals, 75), 62.5)


class ValuationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        # unique email per test
        self.user = User(
            email=f"t{utcnow().timestamp()}@test.local",
            password_hash=hash_password("x"),
            display_name="t",
        )
        self.db.add(self.user)
        self.db.flush()
        self.model = CanonicalModel(
            category="smartphone",
            brand="Test",
            name="Phone X",
            attrs_json="{}",
            search_text="test phone x",
        )
        self.db.add(self.model)
        self.db.flush()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _add_comps(self, condition: str, prices: list[float], defects: str = ""):
        for i, p in enumerate(prices):
            self.db.add(
                CompListing(
                    model_id=self.model.id,
                    condition_bucket=condition,
                    defects=defects,
                    price=p,
                    region="Москва",
                    city="Москва",
                    source="test",
                    observed_at=utcnow() - timedelta(days=i % 10),
                )
            )
        self.db.commit()

    def test_condition_buckets_isolated(self):
        self._add_comps("good", [60000, 61000, 62000, 63000, 64000, 65000])
        self._add_comps("poor", [20000, 21000, 22000, 23000, 24000, 25000])

        good_item = Item(
            owner_id=self.user.id,
            category="smartphone",
            canonical_model_id=self.model.id,
            condition=Condition.GOOD.value,
            location_city="Москва",
            location_region="Москва",
        )
        self.db.add(good_item)
        self.db.flush()
        good_val = compute_valuation(self.db, good_item)

        poor_item = Item(
            owner_id=self.user.id,
            category="smartphone",
            canonical_model_id=self.model.id,
            condition=Condition.POOR.value,
            location_city="Москва",
            location_region="Москва",
        )
        self.db.add(poor_item)
        self.db.flush()
        poor_val = compute_valuation(self.db, poor_item)

        self.assertGreater(good_val.mid, 55000)
        self.assertLess(poor_val.mid, 30000)
        self.assertFalse(good_val.insufficient_data)

    def test_insufficient_data_flag(self):
        self._add_comps("mint", [90000, 91000])  # < 5
        item = Item(
            owner_id=self.user.id,
            category="smartphone",
            canonical_model_id=self.model.id,
            condition=Condition.MINT.value,
            location_city="Москва",
            location_region="Москва",
        )
        self.db.add(item)
        self.db.flush()
        val = compute_valuation(self.db, item)
        self.assertTrue(val.insufficient_data)
        self.assertEqual(val.confidence, "low")


if __name__ == "__main__":
    unittest.main()
