import unittest
from unittest.mock import MagicMock, patch

from ingest_macro import fetch


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


if __name__ == "__main__":
    unittest.main()
