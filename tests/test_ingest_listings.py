import json
import unittest
from unittest.mock import MagicMock, patch

import ingest_listings


class ListingIngestionTests(unittest.TestCase):
    def setUp(self):
        self.market = {
            "city": "Melbourne",
            "state": "VIC",
            "suburb": "Richmond",
            "postcode": "3121",
        }

    def test_listing_url_encodes_suburb(self):
        market = {**self.market, "suburb": "New Farm", "state": "QLD"}
        self.assertEqual(
            ingest_listings.listing_url(market, 20),
            "https://api.propradar.com.au/v1/suburbs/QLD/New%20Farm/listings?limit=20",
        )

    def test_normalize_listing_preserves_first_seen(self):
        raw = {
            "property_id": "8644b8fd",
            "address": "1 Example Street, Richmond, VIC, 3121",
            "sale_type": "Auction",
            "asking_price_low": 700000,
            "asking_price_high": 750000,
        }
        result = ingest_listings.normalize_listing(
            raw,
            self.market,
            "2026-07-15T01:00:00Z",
            {"first_seen_at": "2026-06-15T01:00:00Z"},
        )
        self.assertEqual(result["first_seen_at"], "2026-06-15T01:00:00Z")
        self.assertEqual(result["last_seen_at"], "2026-07-15T01:00:00Z")

    @patch("ingest_listings.urllib.request.urlopen")
    def test_fetch_json_sends_api_key_header(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"listings": []}).encode()
        urlopen.return_value = response
        ingest_listings.fetch_json("https://example.com", "pr_live_test")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), "pr_live_test")

    def test_validation_rejects_duplicate_ids(self):
        item = {
            "property_id": "same-id",
            "address": "1 Example Street",
            "sale_type": "Auction",
            "asking_price_low": 700000,
            "asking_price_high": 750000,
        }
        snapshot = {
            "meta": {"market_count": 1},
            "listings": [item, dict(item)],
        }
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            ingest_listings.validate_snapshot(snapshot, 1)

    def test_market_summary_calculates_derived_measures(self):
        rows = [
            {"sale_type": "Auction", "property_type": "House", "asking_price_low": 700000, "asking_price_high": 800000},
            {"sale_type": "Private Sale", "property_type": "Apartment", "asking_price_low": 500000, "asking_price_high": 500000},
            {"sale_type": "Auction", "property_type": "House", "asking_price_low": None, "asking_price_high": None},
        ]
        result = ingest_listings.market_summary(self.market, rows, 20)
        self.assertEqual(result["listing_count"], 3)
        self.assertEqual(result["auction_count"], 2)
        self.assertEqual(result["auction_share_pct"], 66.7)
        self.assertEqual(result["price_disclosed_share_pct"], 66.7)
        self.assertEqual(result["median_asking_midpoint_aud"], 625000)
        self.assertEqual(result["property_type_counts"], {"Apartment": 1, "House": 2})


if __name__ == "__main__":
    unittest.main()
