import copy
import unittest

import ingest_listings


class ListingExportTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "meta": {
                "provider": "Domain and realestate.com.au saved-search alerts",
                "listing_count": 1,
                "market_count": 1,
                "public_sample_per_market": 3,
            },
            "markets": [{"city": "Melbourne", "suburb": "Richmond"}],
            "listings": [{
                "property_id": "public-id",
                "source": "Domain",
                "city": "Melbourne",
                "suburb": "Richmond",
                "state": "VIC",
                "address": "1 Example Street, Richmond VIC 3121",
                "first_seen_at": "2026-07-21T01:00:00Z",
                "last_seen_at": "2026-07-22T01:00:00Z",
            }],
        }

    def test_current_export_is_valid(self):
        snapshot = ingest_listings.validate_snapshot(ingest_listings.read_json())
        ingest_listings.validate_vintages(
            snapshot, ingest_listings.read_json(ingest_listings.VINTAGES_PATH)
        )

    def test_validation_rejects_duplicate_ids(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["listings"].append(dict(snapshot["listings"][0]))
        snapshot["meta"]["listing_count"] = 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            ingest_listings.validate_snapshot(snapshot)

    def test_validation_rejects_personal_email_fields(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["listings"][0]["message_id"] = "private-gmail-id"
        with self.assertRaisesRegex(ValueError, "Private fields"):
            ingest_listings.validate_snapshot(snapshot)

    def test_validation_rejects_invalid_chronology(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["listings"][0]["first_seen_at"] = "2026-07-23T01:00:00Z"
        with self.assertRaisesRegex(ValueError, "chronology"):
            ingest_listings.validate_snapshot(snapshot)

    def test_latest_vintage_must_match_export(self):
        archive = {"vintages": [{"meta": {}, "markets": []}]}
        with self.assertRaisesRegex(ValueError, "does not match"):
            ingest_listings.validate_vintages(self.snapshot, archive)

    def test_validation_rejects_more_than_three_per_suburb(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["listings"] = [
            {**snapshot["listings"][0], "property_id": f"public-{index}"}
            for index in range(4)
        ]
        snapshot["meta"]["listing_count"] = 4
        with self.assertRaisesRegex(ValueError, "per-suburb"):
            ingest_listings.validate_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
