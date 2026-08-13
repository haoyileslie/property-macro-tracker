import copy
import io
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from ingest_macro import (
    RBA_ENHANCEMENT_SERIES,
    ensure_rba_enhancement_series,
    fetch,
    monthly_last,
    parse_abs_cpi,
    parse_abs_lending_shares,
    parse_abs_xlsx_series,
    quarter_points,
    _horizontal_ratio,
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


class AbsParserTests(unittest.TestCase):
    def test_cpi_parser_uses_stable_chart_title(self):
        markup = """
        <h3>CPI annual inflation fell, while Trimmed mean inflation was unchanged</h3>
        <div>All groups CPI and Trimmed mean, Australia, annual movement (%)</div>
        <table>
          <tr><td>Apr-26</td><td>4.2</td><td>3.4</td></tr>
          <tr><td>May-26</td><td>4.0</td><td>3.6</td></tr>
          <tr><td>Jun-26</td><td>3.8</td><td>3.6</td></tr>
        </table>
        <div>CPI Goods and Services components, annual movement (%)</div>
        """
        headline, trimmed = parse_abs_cpi(markup)
        self.assertEqual(headline[-1], {"date": "2026-06", "value": 3.8})
        self.assertEqual(trimmed[-1], {"date": "2026-06", "value": 3.6})

    def test_abs_xlsx_parser_reads_data1_by_series_id(self):
        shared = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><t>Example series</t></si><si><t>TEST123</t></si></sst>'
        )
        sheet = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="B1" t="s"><v>0</v></c></row>'
            '<row r="10"><c r="B10" t="s"><v>1</v></c></row>'
            '<row r="11"><c r="A11"><v>46082</v></c><c r="B11"><v>123.4</v></c></row>'
            '</sheetData></worksheet>'
        )
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as workbook:
            workbook.writestr("xl/sharedStrings.xml", shared)
            workbook.writestr("xl/worksheets/sheet2.xml", sheet)
        parsed = parse_abs_xlsx_series(payload.getvalue(), {"TEST123"})
        self.assertEqual(parsed["TEST123"], [{"date": "2026-Q1", "value": 123.4}])

    def test_quarter_points_normalises_rba_quarter_end_dates(self):
        self.assertEqual(
            quarter_points([{"date": "2009-03", "value": 8.3}, {"date": "2009-06", "value": 8.1}]),
            [{"date": "2009-Q1", "value": 8.3}, {"date": "2009-Q2", "value": 8.1}],
        )

    def test_abs_lending_share_parser_calculates_borrower_mix(self):
        markup = """
        Number of new loan commitments for dwellings (a), seasonally adjusted and trend, Australia
        Mar-26 100,000 70,000 30,000 14,000
        Jun-26 110,000 75,000 35,000 15,000
        Value of new loan commitments for dwellings
        """
        first_home, investor = parse_abs_lending_shares(markup)
        self.assertEqual(first_home[-1], {"date": "2026-Q2", "value": 20.0})
        self.assertEqual(investor[-1], {"date": "2026-Q2", "value": 31.82})

    def test_horizontal_ratio_uses_excel_dates_and_selected_rows(self):
        rows = {
            4: {"C": "46082", "D": "46173"},
            9: {"C": "80", "D": "90"},
            10: {"C": "20", "D": "10"},
            35: {"C": "15", "D": "10"},
        }
        self.assertEqual(
            _horizontal_ratio(rows, [35], [9, 10]),
            [
                {"date": "2026-Q1", "value": 15.0},
                {"date": "2026-Q2", "value": 10.0},
            ],
        )


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
