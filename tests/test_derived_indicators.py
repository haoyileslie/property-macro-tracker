import copy
import json
import unittest
from pathlib import Path

from derived_indicators import annual_growth, build_derived_series, relative_index
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

    def test_repository_derivations_match_raw_inputs(self):
        self.assertEqual(self.data["derived_series"], build_derived_series(self.data))

    def test_changed_derived_value_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["derived_series"]["mortgage_cash_spread"]["data"]["National"][-1]["value"] += 1
        with self.assertRaisesRegex(ValidationError, "does not match its source formula"):
            validate_dataset(data)


if __name__ == "__main__":
    unittest.main()
