import copy
import json
import unittest
from pathlib import Path

from validate_data import ValidationError, validate_dataset, validate_vintage_archive


ROOT = Path(__file__).parents[1]


class DataValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "property_data.json").read_text())
        cls.archive = json.loads((ROOT / "data_vintages.json").read_text())

    def test_repository_data_and_vintages_are_valid(self):
        report = validate_dataset(self.data)
        vintage_report = validate_vintage_archive(self.archive, self.data)
        self.assertEqual(report["series"], len(self.data["series"]))
        self.assertEqual(vintage_report["vintages"], len(self.archive["refreshes"]))

    def test_duplicate_dates_are_rejected(self):
        data = copy.deepcopy(self.data)
        points = data["series"]["cash_rate"]["data"]["National"]
        points.append(copy.deepcopy(points[-1]))
        with self.assertRaisesRegex(ValidationError, "duplicate date"):
            validate_dataset(data)

    def test_out_of_order_dates_are_rejected(self):
        data = copy.deepcopy(self.data)
        points = data["series"]["cash_rate"]["data"]["National"]
        points[-1], points[-2] = points[-2], points[-1]
        with self.assertRaisesRegex(ValidationError, "not strictly chronological"):
            validate_dataset(data)

    def test_implausible_values_are_rejected(self):
        data = copy.deepcopy(self.data)
        data["series"]["unemployment_rate"]["data"]["National"][-1]["value"] = 120
        with self.assertRaisesRegex(ValidationError, "outside plausible range"):
            validate_dataset(data)

    def test_missing_source_metadata_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["series"]["cpi_headline_yoy"]["source_url"] = ""
        with self.assertRaisesRegex(ValidationError, "source_url is required"):
            validate_dataset(data)

    def test_stale_freshness_label_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["series"]["cash_rate"]["last_source_check"] = "2020-01-01"
        with self.assertRaisesRegex(ValidationError, "marked fresh"):
            validate_dataset(data)

    def test_latest_vintage_must_match_dashboard_data(self):
        archive = copy.deepcopy(self.archive)
        archive["refreshes"][-1]["series"]["cash_rate"]["data"]["National"][-1]["value"] = 99
        with self.assertRaisesRegex(ValidationError, "does not match dataset"):
            validate_vintage_archive(archive, self.data)


if __name__ == "__main__":
    unittest.main()
