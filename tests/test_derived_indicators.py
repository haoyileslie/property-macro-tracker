import copy
import json
import unittest
from pathlib import Path

from derived_indicators import (
    annual_growth,
    build_derived_series,
    expanding_zscore,
    relative_index,
)
from validate_data import ValidationError, validate_dataset


ROOT = Path(__file__).parents[1]


class DerivedIndicatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "property_data.json").read_text())

    def test_annual_growth_uses_matching_month(self):
        points = [
            {"date": "2025-01", "value": 100},
            {"date": "2026-01", "value": 125},
        ]
        self.assertEqual(annual_growth(points), [{"date": "2026-01", "value": 25.0}])

    def test_relative_index_rebases_first_common_period(self):
        numerator = [{"date": "2025-01", "value": 50}, {"date": "2025-02", "value": 60}]
        denominator = [{"date": "2025-01", "value": 100}, {"date": "2025-02", "value": 100}]
        self.assertEqual(relative_index(numerator, denominator), [
            {"date": "2025-01", "value": 100.0},
            {"date": "2025-02", "value": 120.0},
        ])

    def test_expanding_zscore_does_not_use_future_observations(self):
        history = [
            {"date": f"2024-{month:02d}", "value": month}
            for month in range(1, 7)
        ]
        initial = expanding_zscore(history[:5], minimum_observations=3)
        extended = expanding_zscore(history, minimum_observations=3)
        self.assertEqual(initial, extended[:len(initial)])

    def test_hfci_block_contributions_sum_to_each_index(self):
        derived = build_derived_series(self.data)
        for key in ("hfci_core", "hfci_augmented", "hfci_long_history", "hfci_full"):
            series = derived[key]
            contributions = series["block_contributions"]
            by_block = {
                block: {point["date"]: point["value"] for point in points}
                for block, points in contributions.items()
            }
            for point in series["data"]["National"]:
                total = sum(values[point["date"]] for values in by_block.values())
                self.assertAlmostEqual(point["value"], total, places=3)
            self.assertEqual(series["positive_direction"], "tighter")
            self.assertEqual(
                series["latest_source_period"],
                series["historical_percentile"][-1]["date"],
            )

    def test_housing_cycle_derivatives_are_populated(self):
        derived = build_derived_series(self.data)
        expected = {
            "housing_turnover_rate",
            "price_to_rent_ratio_proxy",
            "average_loan_to_income_proxy",
            "mortgage_credit_quality_risk_index",
            "dwelling_completions_per_1000_population",
            "estimated_housing_demand_gap",
            "first_home_buyer_credit_impulse",
            "investor_credit_impulse",
        }
        self.assertTrue(expected.issubset(derived))
        for key in expected:
            self.assertGreater(len(derived[key]["data"]["National"]), 0, key)

    def test_long_history_hfci_is_materially_longer_than_full_hfci(self):
        derived = build_derived_series(self.data)
        long_history = derived["hfci_long_history"]["data"]["National"]
        full = derived["hfci_full"]["data"]["National"]
        self.assertLess(long_history[0]["date"], full[0]["date"])
        self.assertGreater(len(long_history), len(full) * 3)

    def test_repository_derivations_match_raw_inputs(self):
        self.assertEqual(self.data["derived_series"], build_derived_series(self.data))

    def test_changed_derived_value_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["derived_series"]["mortgage_cash_spread"]["data"]["National"][-1]["value"] += 1
        with self.assertRaisesRegex(ValidationError, "does not match its source formula"):
            validate_dataset(data)


if __name__ == "__main__":
    unittest.main()
