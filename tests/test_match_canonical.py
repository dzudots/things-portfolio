"""match_canonical improvements for Gen Z catalog."""

from __future__ import annotations

import unittest

from app.ai.billing import UsageCost
from app.ai.providers import IdentifyResult
from app.ai.scan import match_canonical
from app.models import SessionLocal, init_db
from app.seed import ensure_catalog, run_seed


def _id(brand: str, model_hint: str, category: str = "smartphone") -> IdentifyResult:
    return IdentifyResult(
        brand=brand,
        model_hint=model_hint,
        category=category,
        condition_guess="good",
        confidence=0.9,
        raw_text="{}",
        provider="mock",
        model="mock",
        input_tokens=0,
        output_tokens=0,
        cost=UsageCost(0.0, 20.0, 0.0, 0.0),
        mock=True,
    )


class MatchCanonicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        run_seed(reset=False)
        db = SessionLocal()
        try:
            ensure_catalog(db)
        finally:
            db.close()

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_iphone_generation(self):
        match = match_canonical(self.db, _id("Apple", "iPhone 14 128GB"))
        self.assertIsNotNone(match.model)
        self.assertIn("14", match.model.name)
        self.assertNotIn("15 Pro", match.model.name)

    def test_galaxy_alias(self):
        match = match_canonical(self.db, _id("Samsung", "Galaxy S24 Ultra"))
        self.assertIsNotNone(match.model)
        self.assertIn("S24", match.model.name)
        self.assertIn("Ultra", match.model.name)

    def test_pixel(self):
        match = match_canonical(self.db, _id("Google", "Pixel 8a"))
        self.assertIsNotNone(match.model)
        self.assertIn("Pixel", match.model.name)
        self.assertIn("8a", match.model.name)


if __name__ == "__main__":
    unittest.main()
