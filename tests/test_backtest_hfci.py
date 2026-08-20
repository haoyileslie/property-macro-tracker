import copy
import json
import math
import unittest
from pathlib import Path

from backtest_hfci import build_rows, run_backtests


ROOT = Path(__file__).resolve().parents[1]


class HfciBacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "property_data.json").read_text())
        cls.result = run_backtests(cls.data)

    def test_published_backtest_matches_recalculation(self):
        published = json.loads((ROOT / "hfci_backtest.json").read_text())
        self.assertEqual(published, self.result)

    def test_results_are_finite_and_out_of_sample(self):
        self.assertGreater(len(self.result["performance"]), 0)
        for row in self.result["performance"]:
            self.assertGreaterEqual(row["oos_observations"], 6)
            for key in ("rmse", "mae", "direction_accuracy", "rmse_improvement_vs_cash"):
                self.assertTrue(math.isfinite(row[key]))

    def test_future_hfci_observation_does_not_change_existing_rows(self):
        target = self.data["series"]["house_price_nominal_index"]["data"]["National"]
        hfci = self.data["derived_series"]["hfci_long_history"]["data"]["National"]
        cash = self.data["series"]["cash_rate"]["data"]["National"]
        before = build_rows(target, hfci, cash, 12, "pct_change")
        extended = copy.deepcopy(hfci)
        extended.append({"date": "2099-12", "value": 999})
        self.assertEqual(before, build_rows(target, extended, cash, 12, "pct_change"))

    def test_pairwise_self_correlations_equal_one(self):
        diagonal = [row for row in self.result["hfci_pairwise_correlations"] if row["left"] == row["right"]]
        self.assertEqual(len(diagonal), 4)
        self.assertTrue(all(row["correlation"] == 1.0 for row in diagonal))


if __name__ == "__main__":
    unittest.main()
