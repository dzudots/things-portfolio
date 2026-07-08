"""Telegram account linking (no live Bot API calls)."""

from __future__ import annotations

import os
import unittest
import uuid
from datetime import timedelta

os.environ.pop("THINGS_TELEGRAM_BOT_TOKEN", None)

from app.models import SessionLocal, User, init_db, utcnow  # noqa: E402
from app.telegram.linking import consume_link_token, create_link_token, unlink_telegram  # noqa: E402


class TelegramLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def _make_user(self) -> User:
        user = User(
            email=f"tg-{uuid.uuid4().hex[:8]}@test.local",
            password_hash="x",
            display_name="TG",
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def _chat_id(self) -> str:
        return str(900_000_000 + uuid.uuid4().int % 99_000_000)

    def setUp(self):
        self.db = SessionLocal()
        self.user = self._make_user()

    def tearDown(self):
        try:
            self.db.delete(self.user)
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def test_link_token_binds_chat(self):
        token = create_link_token(self.db, self.user)
        chat_id = self._chat_id()
        linked, err = consume_link_token(self.db, chat_id, token, username="tester")
        self.assertIsNone(err)
        self.assertIsNotNone(linked)
        self.assertEqual(linked.telegram_chat_id, chat_id)
        self.assertEqual(linked.telegram_username, "tester")
        self.assertTrue(linked.telegram_alerts_enabled)
        self.assertIsNone(linked.telegram_link_token)

    def test_expired_token_rejected(self):
        token = create_link_token(self.db, self.user)
        self.user.telegram_link_expires_at = utcnow() - timedelta(minutes=1)
        self.db.commit()
        linked, err = consume_link_token(self.db, self._chat_id(), token)
        self.assertIsNone(linked)
        self.assertIn("истекла", err or "")

    def test_unlink_clears_fields(self):
        token = create_link_token(self.db, self.user)
        consume_link_token(self.db, self._chat_id(), token)
        unlink_telegram(self.db, self.user)
        self.db.refresh(self.user)
        self.assertIsNone(self.user.telegram_chat_id)
        self.assertFalse(self.user.telegram_alerts_enabled)


if __name__ == "__main__":
    unittest.main()
