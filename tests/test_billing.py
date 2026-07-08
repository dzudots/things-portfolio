"""Pro promo redeem tests."""

from __future__ import annotations

import unittest

from app.auth import hash_password
from app.billing import is_pro, redeem_promo
from app.models import SessionLocal, User, init_db, utcnow


class BillingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(
            email=f"pro{utcnow().timestamp()}@test.local",
            password_hash=hash_password("x"),
            plan="free",
        )
        self.user.display_name = "pro"
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_redeem_beta(self):
        self.assertFalse(is_pro(self.user))
        result = redeem_promo(self.db, self.user, "stakbeta30")
        self.assertTrue(result.ok)
        self.db.refresh(self.user)
        self.assertTrue(is_pro(self.user))
        self.assertIsNotNone(self.user.plan_expires_at)

    def test_bad_code(self):
        result = redeem_promo(self.db, self.user, "NOPE")
        self.assertFalse(result.ok)
        self.assertFalse(is_pro(self.user))


if __name__ == "__main__":
    unittest.main()
