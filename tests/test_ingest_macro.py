import copy
import unittest
from unittest.mock import MagicMock, patch

from ingest_macro import (
    RBA_ENHANCEMENT_SERIES,
    ensure_rba_enhancement_series,
    fetch,
    monthly_last,
)


class FetchRetryTests(unittest.TestCase):
    @patch("ingest_macro.time.sleep")
    @patch("ingest_macro.urllib.request.urlopen")
    def test_transient_timeout_is_retried(self, urlopen, sleep):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"source data"
        urlopen.side_effect = [TimeoutError("timed out"), response]

        result = fetch("https://example.com/data.csv", attempts=3, timeout=1)

        self.assertEqual(result, "source data")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("ingest_macro.time.sleep")
    @patch("ingest_macro.urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_terminal_timeout_names_the_source(self, urlopen, sleep):
        with self.assertRaisesRegex(
            RuntimeError,
            "fetch failed after 2 attempts: https://example.com/data.csv",
        ):
            fetch("https://example.com/data.csv", attempts=2, timeout=1)

        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)


class EnhancementDatabaseTests(unittest.TestCase):
    def test_monthly_last_keeps_final_observation(self):
        points = [
            {"date": "2026-01", "value": 1.0},
            {"date": "2026-01", "value": 1.2},
            {"date": "2026-02", "value": 1.3},
        ]
        self.assertEqual(
            monthly_last(points),
            [
                {"date": "2026-01", "value": 1.2},
                {"date": "2026-02", "value": 1.3},
            ],
        )

    def test_metadata_shells_are_complete_and_non_destructive(self):
        data = {
            "meta": {},
            "series": {
                "cash_rate": {
                    "data": {"National": [{"date": "2026-06", "value": 4.35}]}
                }
            },
        }
        original = copy.deepcopy(data["series"]["cash_rate"])
        ensure_rba_enhancement_series(data)
        self.assertEqual(data["series"]["cash_rate"], original)
        self.assertEqual(len(RBA_ENHANCEMENT_SERIES), 32)
        for key, spec in RBA_ENHANCEMENT_SERIES.items():
            series = data["series"][key]
            self.assertEqual(series["source_series_id"], spec["series_id"])
            self.assertEqual(series["source_table"], spec["table"])
            self.assertIn("National", series["data"])
            self.assertGreaterEqual(series["release_lag_days"], 0)

    def test_breakeven_and_zero_curve_warnings_are_preserved(self):
        data = {"meta": {}, "series": {}}
        ensure_rba_enhancement_series(data)
        self.assertIn(
            "not be interpreted as a pure inflation forecast",
            data["series"]["breakeven_inflation_10y"]["methodology_note"],
        )
        self.assertIn(
            "not itself an investable bond-return series",
            data["series"]["au_zero_yield_10y"]["methodology_note"],
        )

if __name__ == "__main__":
    unittest.main()
