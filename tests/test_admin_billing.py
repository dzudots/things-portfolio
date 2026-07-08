"""Admin API lock + YooKassa webhook activation."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import hash_password
from app.billing import apply_yookassa_payment, is_pro
from app.main import app
from app.models import SessionLocal, User, init_db


class AdminLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def setUp(self):
        self.db = SessionLocal()
        admin_email = f"admin-{uuid.uuid4().hex[:8]}@test.local"
        self.user = User(
            email=f"user-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x"),
            plan="free",
        )
        self.user.display_name = "u"
        self.admin = User(
            email=admin_email,
            password_hash=hash_password("x"),
            plan="free",
        )
        self.admin.display_name = "a"
        self.db.add_all([self.user, self.admin])
        self.db.commit()
        self.db.refresh(self.user)
        self.db.refresh(self.admin)
        self._email_patch = patch("app.auth.ADMIN_EMAILS", {admin_email})
        self._key_patch = patch("app.auth.ADMIN_API_KEY", "test-admin-key")
        self._email_patch.start()
        self._key_patch.start()

    def tearDown(self):
        self._email_patch.stop()
        self._key_patch.stop()
        self.db.rollback()
        self.db.close()

    def test_non_admin_forbidden(self):
        self.client.cookies.set("things_session", str(self.user.id))
        r = self.client.post("/api/admin/revalue")
        self.assertEqual(r.status_code, 403)

    def test_admin_email_allowed(self):
        self.client.cookies.set("things_session", str(self.admin.id))
        with patch("app.main.revalue_all_items", return_value=0):
            r = self.client.post("/api/admin/revalue")
        self.assertEqual(r.status_code, 200)

    def test_admin_api_key_allowed(self):
        self.client.cookies.clear()
        with patch("app.main.revalue_all_items", return_value=0):
            r = self.client.post(
                "/api/admin/revalue",
                headers={"X-Admin-Key": "test-admin-key"},
            )
        self.assertEqual(r.status_code, 200)


class YooKassaWebhookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(
            email=f"pay-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x"),
            plan="free",
        )
        self.user.display_name = "pay"
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_succeeded_activates_pro(self):
        ok = apply_yookassa_payment(
            self.db,
            {
                "id": f"yk-{uuid.uuid4().hex}",
                "status": "succeeded",
                "amount": {"value": "299.00", "currency": "RUB"},
                "description": "Стак Pro",
                "metadata": {"user_id": str(self.user.id), "plan_days": "30"},
            },
        )
        self.assertTrue(ok)
        self.db.refresh(self.user)
        self.assertTrue(is_pro(self.user))
        self.assertIsNotNone(self.user.plan_expires_at)


if __name__ == "__main__":
    unittest.main()
