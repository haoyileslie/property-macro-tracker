import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest.mock import patch

import refresh_listings_from_gmail as refresh


def alert(subject, html, sent_at="2026-07-23T01:00:00Z"):
    message = EmailMessage()
    message["Subject"] = subject
    message["Date"] = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    message.set_content("HTML alert")
    message.add_alternative(html, subtype="html")
    return message


class RefreshListingsTests(unittest.TestCase):
    def test_rea_alert_parses_linked_address_and_facts(self):
        message = alert(
            'New to market: Alert for your "Indooroopilly, QLD 4068"',
            '<a href="https://example.test/listing">4/12 Station Road, Indooroopilly 4068</a>'
            '<div>2</div><div>1</div><div>1</div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "4/12 Station Road, Indooroopilly QLD 4068")
        self.assertEqual((rows[0]["bedrooms"], rows[0]["bathrooms"], rows[0]["parking"]), (2, 1, 1))
        self.assertNotIn("url", rows[0])

    def test_domain_saved_search_parses_card(self):
        message = alert(
            "Domain Home Alert for Richmond VIC 3121",
            '<a href="https://example.test/price">Auction Saturday</a>'
            '<a href="https://example.test/listing">8 Test Street, Richmond</a>'
            '<div>3</div><div>Beds</div><div>2</div><div>Baths</div>'
            '<div>1</div><div>Car</div><div>House</div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "Melbourne")
        self.assertEqual(rows[0]["property_type"], "House")
        self.assertEqual(rows[0]["bedrooms"], 3)
        self.assertEqual(rows[0]["bathrooms"], 2)
        self.assertEqual(rows[0]["parking"], 1)

    def test_merge_enforces_three_per_suburb_and_preserves_both_sources(self):
        rows = [
            refresh.public_item(
                "Domain" if index < 4 else "REA",
                f"{index} Sample Street, Richmond VIC 3121",
                "Richmond", "VIC", "3121", f"2026-07-{20 + index:02d}T00:00:00Z",
            )
            for index in range(5)
        ]
        merged = refresh.merge_listings([], rows)
        self.assertEqual(len(merged), 3)
        self.assertEqual({row["source"] for row in merged}, {"Domain", "REA"})

    def test_build_refresh_ignores_already_processed_email(self):
        snapshot = {
            "meta": {
                "captured_at": "2026-07-22T00:00:00Z",
                "last_alert_email_at": "2026-07-23T02:00:00Z",
                "alert_messages": 2,
                "observations_fetched": 2,
                "unique_listings_analysed": 2,
            },
            "markets": [],
            "listings": [],
        }
        message = alert(
            'New to market: Alert for your "Indooroopilly, QLD 4068"',
            '<a href="https://example.test/listing">4 Test Road, Indooroopilly 4068</a>'
            '<div>2</div><div>1</div><div>1</div>',
            "2026-07-23T01:00:00Z",
        )
        self.assertIsNone(refresh.build_refresh(snapshot, [message]))

    def test_recognized_alert_with_changed_template_stops_refresh(self):
        snapshot = {
            "meta": {
                "captured_at": "2026-07-22T00:00:00Z",
                "last_alert_email_at": "2026-07-22T00:00:00Z",
            },
            "markets": [],
            "listings": [],
        }
        message = alert(
            'New to market: Alert for your "Indooroopilly, QLD 4068"',
            "<div>A changed card layout with no address</div>",
        )
        with self.assertRaisesRegex(RuntimeError, "could not parse"):
            refresh.build_refresh(snapshot, [message])

    def test_refresh_token_is_never_logged_or_embedded(self):
        with patch.object(refresh, "request_json", return_value={"access_token": "temporary"}) as request:
            token = refresh.refresh_access_token("client", "secret", "refresh-value")
        self.assertEqual(token, "temporary")
        self.assertEqual(request.call_args.kwargs["data"]["refresh_token"], "refresh-value")


if __name__ == "__main__":
    unittest.main()
