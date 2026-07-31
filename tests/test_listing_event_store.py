import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import listing_event_store as store
import refresh_listings_from_gmail as refresh


class ListingEventStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "listing_events.sqlite3"

    def tearDown(self):
        self.temporary.cleanup()

    def listing(self, sale_type, observed_at, **extra):
        return {
            **refresh.public_item(
                "Domain", "1 Example Street, Richmond VIC 3121", "Richmond",
                "VIC", "3121", observed_at, sale_type=sale_type,
                price_text=extra.get("price_text"),
                evidence_url="https://example.test/listing/1",
            ),
            "_source_message_id": extra.get("message_id", "gmail-1"),
        }

    def test_off_market_alert_is_retained_as_pre_market_event(self):
        inserted = store.record_listing_events(
            self.db_path, [self.listing("Off Market", "2026-07-20T01:00:00Z")]
        )
        self.assertEqual(inserted, 1)
        connection = sqlite3.connect(self.db_path)
        event = connection.execute(
            "SELECT event_type, lifecycle_status, source_message_id, evidence_url FROM listing_events"
        ).fetchone()
        connection.close()
        self.assertEqual(event[:2], ("off_market_alert", "pre_market"))
        self.assertEqual(event[2], "gmail-1")
        self.assertEqual(event[3], "https://example.test/listing/1")

    def test_replaying_same_alert_is_idempotent(self):
        row = self.listing("Off Market", "2026-07-20T01:00:00Z")
        self.assertEqual(store.record_listing_events(self.db_path, [row]), 1)
        self.assertEqual(store.record_listing_events(self.db_path, [row]), 0)
        self.assertEqual(store.store_stats(self.db_path)["events"], 1)

    def test_public_alert_adds_transition_without_rewriting_history(self):
        first = self.listing("Off Market", "2026-07-20T01:00:00Z")
        active = self.listing("Auction", "2026-07-22T01:00:00Z", message_id="gmail-2")
        store.record_listing_events(self.db_path, [first, active])
        connection = sqlite3.connect(self.db_path)
        events = connection.execute(
            "SELECT event_type, lifecycle_status FROM listing_events ORDER BY observed_at"
        ).fetchall()
        current = connection.execute(
            "SELECT current_marketing_channel, current_lifecycle_status FROM listing_properties"
        ).fetchone()
        connection.close()
        self.assertEqual(events, [
            ("off_market_alert", "pre_market"),
            ("listing_alert", "active"),
        ])
        self.assertEqual(current, ("auction", "active"))

    def test_sale_outcome_keeps_prior_events_and_records_price(self):
        row = self.listing("Auction", "2026-07-20T01:00:00Z")
        store.record_listing_events(self.db_path, [row])
        store.record_outcome(
            self.db_path, row["property_id"], "sold", "2026-08-15T01:00:00Z",
            sale_price_aud=1250000, evidence_url="https://example.test/result/1",
        )
        connection = sqlite3.connect(self.db_path)
        events = connection.execute(
            "SELECT event_type, sale_outcome, sale_price_aud FROM listing_events ORDER BY observed_at"
        ).fetchall()
        status = connection.execute(
            "SELECT current_lifecycle_status FROM listing_properties"
        ).fetchone()[0]
        connection.close()
        self.assertEqual(events[-1], ("sale_outcome", "sold", 1250000))
        self.assertEqual(len(events), 2)
        self.assertEqual(status, "sold")

    def test_public_projection_removes_private_fields(self):
        row = self.listing("Off Market", "2026-07-20T01:00:00Z")
        projected = refresh.public_projection(row)
        self.assertFalse(any(key.startswith("_") for key in projected))
        self.assertNotIn("https://example.test/listing/1", json.dumps(projected))


if __name__ == "__main__":
    unittest.main()
