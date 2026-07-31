import tempfile
import unittest
from pathlib import Path

import import_gmail_connector_export as importer
import listing_event_store as store


class GmailConnectorImportTests(unittest.TestCase):
    def test_connector_record_is_parsed_without_retaining_raw_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            db_path = Path(temporary) / "events.sqlite3"
            result = importer.import_records(db_path, [{
                "id": "gmail-connector-1",
                "email_ts": "2026-07-29T03:31:58",
                "subject": "Domain off-market alert: 1 Example Street, Richmond, VIC, 3121",
                "body": (
                    "[1 Example Street, Richmond, VIC, 3121]"
                    "(https://example.test/listing/1)\n\n3\n\n2\n\n1"
                ),
            }])
            self.assertEqual(result["events_inserted"], 1)
            self.assertEqual(store.store_stats(db_path)["off_market_events"], 1)


if __name__ == "__main__":
    unittest.main()
