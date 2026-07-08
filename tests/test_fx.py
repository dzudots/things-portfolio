"""FX + CIS region tests."""

from __future__ import annotations

import unittest

from app.fx import convert_rub, format_amount, get_rates
from app.regions import city_info, price_index_for
from app.valuation import weighted_percentile


class FxTests(unittest.TestCase):
    def test_rub_identity(self):
        self.assertEqual(format_amount(1000, "RUB"), "1 000 ₽")

    def test_convert_kzt(self):
        rates = get_rates()
        kzt = convert_rub(1000, "KZT")
        self.assertGreater(kzt or 0, 1000)

    def test_region_index(self):
        self.assertEqual(price_index_for("Москва"), 1.0)
        self.assertLess(price_index_for("Минск"), 1.0)
        self.assertIsNotNone(city_info("Алматы"))


class WeightedPercentileTests(unittest.TestCase):
    def test_fresh_weight_wins(self):
        # older high price vs fresh low price — median should lean fresh
        pairs = [(100000, 0.3), (50000, 1.0), (52000, 0.9)]
        mid = weighted_percentile(pairs, 50)
        self.assertLess(mid, 80000)


if __name__ == "__main__":
    unittest.main()
