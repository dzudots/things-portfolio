"""Achievement unlock logic tests."""

from __future__ import annotations

import unittest

from app.achievements import ACHIEVEMENTS, evaluate_achievements, unlocked_ids
from app.auth import create_user, hash_password
from app.models import CanonicalModel, Item, SessionLocal, User, init_db


class AchievementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(
            email=f"ach{id(self)}@test.local",
            password_hash=hash_password("x"),
        )
        self.user.display_name = "ach"
        self.db.add(self.user)
        self.db.flush()
        self.model = CanonicalModel(
            category="smartphone",
            brand="Test",
            name="Phone",
            attrs_json="{}",
            search_text="test phone",
        )
        self.db.add(self.model)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_catalog_size(self):
        self.assertGreaterEqual(len(ACHIEVEMENTS), 10)

    def test_first_thing_unlock(self):
        item = Item(
            owner_id=self.user.id,
            category="smartphone",
            canonical_model_id=self.model.id,
            condition="good",
            location_city="Москва",
            location_region="Москва",
        )
        self.db.add(item)
        self.db.commit()
        fresh = evaluate_achievements(self.db, self.user.id)
        ids = {a.id for a in fresh}
        self.assertIn("first_thing", ids)
        self.assertIn("phone_in", unlocked_ids(self.db, self.user.id))
        # second call — no duplicates
        again = evaluate_achievements(self.db, self.user.id)
        self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
