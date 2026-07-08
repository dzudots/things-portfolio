"""AI billing + mock vision scan."""

from __future__ import annotations

import asyncio
import unittest

from app.ai.billing import clamp_markup, estimate_vision_cost, markup_for_model
from app.ai.providers import identify_from_image
from app.ai.scan import match_canonical
from app.ai.service import can_scan, run_photo_scan, scan_limit_for
from app.auth import hash_password
from app.models import CanonicalModel, SessionLocal, User, init_db, utcnow
from app.seed import run_seed


class BillingTests(unittest.TestCase):
    def test_markup_clamped(self):
        self.assertEqual(clamp_markup(5), 10.0)
        self.assertEqual(clamp_markup(50), 30.0)
        self.assertEqual(clamp_markup(20), 20.0)

    def test_estimate_applies_markup(self):
        c = estimate_vision_cost(1000, 200, 1, markup_pct=20)
        self.assertGreater(c.billed_usd, c.provider_cost_usd)
        self.assertAlmostEqual(c.billed_usd, c.provider_cost_usd * 1.2, places=5)
        self.assertEqual(c.markup_pct, 20.0)

    def test_model_tier_markup(self):
        self.assertLessEqual(markup_for_model("gpt-4o-mini"), 15)
        self.assertGreaterEqual(markup_for_model("gpt-4o"), 25)


class MockScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        run_seed(reset=False)

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(
            email=f"scan{utcnow().timestamp()}@test.local",
            password_hash=hash_password("x"),
            plan="free",
        )
        self.user.display_name = "scan"
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_mock_identify_iphone(self):
        result = asyncio.run(
            identify_from_image(b"fake", mime="image/jpeg", filename_hint="iphone.jpg")
        )
        self.assertTrue(result.mock)
        self.assertEqual(result.category, "smartphone")
        self.assertIn("iPhone", result.model_hint)

    def test_match_and_scan_job(self):
        async def _run():
            return await run_photo_scan(
                self.db,
                self.user,
                b"\xff\xd8\xfffakejpeg",
                mime="image/jpeg",
                filename="iphone14.jpg",
            )

        job = asyncio.run(_run())
        self.assertEqual(job.status, "done")
        self.assertGreater(job.identify_confidence, 0)
        self.assertTrue(job.brand)

    def test_daily_limit(self):
        self.user.plan = "free"
        ok, _ = can_scan(self.db, self.user)
        self.assertTrue(ok)
        self.assertEqual(scan_limit_for(self.user), 5)


if __name__ == "__main__":
    unittest.main()
