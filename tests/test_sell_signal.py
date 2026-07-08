"""Sell-now signal + action alerts."""

from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace

from app.models import utcnow
from app.sell_signal import (
    FRIEND_LOOP_STEPS,
    alert_action_message,
    build_sell_signal,
    comps_honesty,
)


def _snap(mid: float, days_ago: int):
    return SimpleNamespace(mid=mid, ts=utcnow() - timedelta(days=days_ago))


class SellSignalTests(unittest.TestCase):
    def test_falling_market_sell_now(self):
        vals = [_snap(60000, 35), _snap(52000, 0)]
        sig = build_sell_signal(
            mid=52000,
            valuations=vals,
            comps_count=12,
            insufficient_data=False,
            freshness_days=2,
            confidence="medium",
            low=48000,
            high=56000,
        )
        self.assertEqual(sig.action, "sell_now")
        self.assertIn("продавай", sig.action_label.lower())
        self.assertIsNotNone(sig.before_after_line)
        self.assertIn("выиграть", sig.before_after_line)

    def test_rising_market_wait(self):
        vals = [_snap(40000, 35), _snap(48000, 0)]
        sig = build_sell_signal(
            mid=48000,
            valuations=vals,
            comps_count=12,
            insufficient_data=False,
            freshness_days=1,
            confidence="high",
            low=45000,
            high=51000,
        )
        self.assertEqual(sig.action, "wait")
        self.assertIn("подожд", sig.action_label.lower())

    def test_weak_comps_uncertain(self):
        sig = build_sell_signal(
            mid=50000,
            valuations=[_snap(50000, 0)],
            comps_count=2,
            insufficient_data=True,
            freshness_days=1,
            confidence="low",
            low=30000,
            high=70000,
        )
        self.assertEqual(sig.action, "uncertain")
        self.assertIsNotNone(sig.comps_note)
        self.assertIn("Ориентир", sig.comps_note)

    def test_stale_comps_refresh(self):
        vals = [_snap(50000, 35), _snap(49500, 0)]
        sig = build_sell_signal(
            mid=49500,
            valuations=vals,
            comps_count=10,
            insufficient_data=False,
            freshness_days=20,
            confidence="medium",
            low=47000,
            high=52000,
        )
        self.assertEqual(sig.action, "refresh_listing")
        self.assertIn("обнов", sig.action_label.lower())

    def test_alert_has_verb(self):
        msg = alert_action_message(
            model_name="Apple iPhone 14",
            old_mid=50000,
            new_mid=45000,
            change_pct=-10.0,
            direction="down",
        )
        self.assertIn("Продавай", msg)
        self.assertIn("iPhone", msg)

    def test_honesty_wide_band(self):
        note = comps_honesty(
            comps_count=10,
            insufficient_data=False,
            freshness_days=3,
            confidence="medium",
            band_pct=40,
        )
        self.assertIsNotNone(note)
        self.assertIn("Разброс", note)

    def test_friend_loop_checklist(self):
        self.assertGreaterEqual(len(FRIEND_LOOP_STEPS), 4)


if __name__ == "__main__":
    unittest.main()
