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
        self.assertEqual(rows[0]["_evidence_url"], "https://example.test/listing")
        self.assertNotIn("url", rows[0])

    def test_rea_alert_parses_live_inline_icon_facts(self):
        message = alert(
            'New to market: Alert for your "Strathfield, NSW 2135" saved search',
            '<a href="https://example.test/image">4/1 Example Crescent</a>'
            '<div>$1,100,000</div>'
            '<a href="https://example.test/listing">4/1 Example Crescent, Strathfield 2135</a>'
            '<div><img alt="Bedrooms"><span>&nbsp;&nbsp;2&nbsp;&nbsp;</span>'
            '<img alt="Bathrooms"><span>&nbsp;&nbsp;1&nbsp;&nbsp;</span>'
            '<img alt="Parking spaces"><span>&nbsp;&nbsp;1</span></div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "4/1 Example Crescent, Strathfield NSW 2135")
        self.assertEqual(rows[0]["price_text"], "$1,100,000")
        self.assertEqual((rows[0]["bedrooms"], rows[0]["bathrooms"], rows[0]["parking"]), (2, 1, 1))

    def test_rea_alert_accepts_lot_number_but_skips_hidden_address(self):
        message = alert(
            'New to market: Alert for your "Cockburn Central, WA 6164" saved search',
            '<a href="https://example.test/hidden">Address available on request, Cockburn Central 6164</a>'
            '<div>3</div><div>2</div><div>0</div>'
            '<a href="https://example.test/lot">Lot 191 Example Court, Cockburn Central 6164</a>'
            '<div>4</div><div>3</div><div>2</div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "Lot 191 Example Court, Cockburn Central WA 6164")
        self.assertEqual((rows[0]["bedrooms"], rows[0]["bathrooms"], rows[0]["parking"]), (4, 3, 2))

    def test_rea_alert_parses_land_card_without_dwelling_facts(self):
        message = alert(
            'New to market: Alert for your "Sunnybank, QLD 4109" saved search',
            '<a href="https://example.test/image">Lot 3, 1 Example Street</a>'
            '<div>New Land Release From $977,000</div>'
            '<a href="https://example.test/listing">Lot 3, 1 Example Street, Sunnybank 4109</a>'
            '<a href="https://example.test/listing">View Property</a>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "Lot 3, 1 Example Street, Sunnybank QLD 4109")
        self.assertEqual(rows[0]["property_type"], "Land")
        self.assertEqual(rows[0]["price_text"], "New Land Release From $977,000")
        self.assertIsNone(rows[0]["bedrooms"])
        self.assertIsNone(rows[0]["bathrooms"])
        self.assertIsNone(rows[0]["parking"])

    def test_rea_alert_parses_verified_address_when_facts_are_omitted(self):
        message = alert(
            'New to market: Alert for your "Bassendean, WA 6054" saved search',
            '<a href="https://example.test/image">3B Hardy Road</a>'
            '<div>End Date Process</div>'
            '<a href="https://example.test/listing">3B Hardy Road, Bassendean 6054</a>'
            '<a href="https://example.test/listing">View Property</a>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "3B Hardy Road, Bassendean WA 6054")
        self.assertIsNone(rows[0]["property_type"])
        self.assertIsNone(rows[0]["bedrooms"])
        self.assertIsNone(rows[0]["bathrooms"])
        self.assertIsNone(rows[0]["parking"])

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

    def test_domain_saved_search_accepts_explicit_unit_prefix(self):
        message = alert(
            "Home Alert for Oxley QLD 4075",
            '<a href="https://example.test/price">Contact Agent</a>'
            '<a href="https://example.test/listing">Unit 15/84 Estramina Street, Oxley</a>'
            '<div>4</div><div>Beds</div><div>2</div><div>Baths</div>'
            '<div>2</div><div>Cars</div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "Unit 15/84 Estramina Street, Oxley QLD 4075")
        self.assertEqual((rows[0]["bedrooms"], rows[0]["bathrooms"], rows[0]["parking"]), (4, 2, 2))

    def test_domain_saved_search_accepts_explicit_apartment_prefix(self):
        message = alert(
            "Home Alert for Box Hill VIC 3128",
            '<a href="https://example.test/price">$139,000 - $149,000</a>'
            '<a href="https://example.test/listing">APARTMENT 306/8 Bruce Street, Box Hill</a>'
            '<div>1</div><div>bed</div><div>1</div><div>bath</div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["address"], "APARTMENT 306/8 Bruce Street, Box Hill VIC 3128")
        self.assertEqual((rows[0]["bedrooms"], rows[0]["bathrooms"]), (1, 1))

    def test_domain_off_market_alert_retains_private_evidence_link(self):
        message = alert(
            "Domain off-market alert: 1 Example Street, Richmond, VIC, 3121",
            '<a href="https://example.test/off-market/1">1 Example Street, Richmond, VIC, 3121</a>'
            '<div>3</div><div>2</div><div>1</div>',
        )
        rows = refresh.parse_message(message)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sale_type"], "Off Market")
        self.assertEqual(rows[0]["_evidence_url"], "https://example.test/off-market/1")

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
        self.assertFalse(any(key.startswith("_") for row in merged for key in row))

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

    def test_build_refresh_counts_hidden_address_card_without_publishing_it(self):
        snapshot = {
            "meta": {
                "captured_at": "2026-07-23T00:00:00Z",
                "last_alert_email_at": "2026-07-23T00:00:00Z",
                "alert_messages": 2,
                "observations_fetched": 4,
                "unique_listings_analysed": 4,
            },
            "markets": [],
            "listings": [],
        }
        message = alert(
            'New to market: Alert for your "Footscray, VIC 3011" saved search',
            '<div>$750,000</div>'
            '<a href="https://example.test/hidden">Address available on request, Footscray 3011</a>'
            '<div>2</div><div>3</div><div>1</div>'
            '<a href="https://example.test/hidden">View Property</a>',
            "2026-07-25T07:55:19Z",
        )
        refreshed = refresh.build_refresh(snapshot, [message])
        self.assertEqual(refreshed["listings"], [])
        self.assertEqual(refreshed["meta"]["alert_messages"], 3)
        self.assertEqual(refreshed["meta"]["observations_fetched"], 4)
        self.assertEqual(refreshed["meta"]["unattributed_alert_cards_skipped"], 1)
        self.assertEqual(refreshed["meta"]["last_alert_email_at"], "2026-07-25T07:55:19Z")

    def test_build_refresh_counts_domain_suburb_only_card_without_inventing_address(self):
        snapshot = {
            "meta": {
                "captured_at": "2026-07-23T00:00:00Z",
                "last_alert_email_at": "2026-07-23T00:00:00Z",
                "alert_messages": 2,
                "observations_fetched": 4,
                "unique_listings_analysed": 4,
            },
            "markets": [],
            "listings": [],
        }
        message = alert(
            "Home Alert for Maylands WA 6051",
            '<a href="https://example.test/headline">Build Brand New in Maylands</a>'
            '<div>$1,256,100</div>'
            '<a href="https://example.test/suburb">Maylands</a>'
            '<div>4</div><div>beds</div><div>2</div><div>baths</div>'
            '<div>2</div><div>cars</div>'
            '<a href="https://example.test/details">Find out more</a>',
            "2026-07-25T07:49:32Z",
        )
        refreshed = refresh.build_refresh(snapshot, [message])
        self.assertEqual(refreshed["listings"], [])
        self.assertEqual(refreshed["meta"]["alert_messages"], 3)
        self.assertEqual(refreshed["meta"]["observations_fetched"], 4)
        self.assertEqual(refreshed["meta"]["unattributed_alert_cards_skipped"], 1)
        self.assertEqual(refreshed["meta"]["last_alert_email_at"], "2026-07-25T07:49:32Z")

    def test_domain_suburb_only_card_allows_missing_parking_and_details_label(self):
        message = alert(
            "Home Alert for St Leonards NSW 2065",
            '<a href="https://example.test/suburb">St Leonards</a>'
            '<div>2</div><div>beds</div><div>2</div><div>baths</div>'
            '<a href="https://example.test/details">Details</a>',
        )
        self.assertEqual(
            refresh.unattributed_domain_card_count(
                refresh.message_body(message), message["Subject"]
            ),
            1,
        )

    def test_build_refresh_counts_domain_featured_card_without_street_address(self):
        snapshot = {
            "meta": {
                "captured_at": "2026-07-30T00:00:00Z",
                "last_alert_email_at": "2026-07-30T00:00:00Z",
                "alert_messages": 10,
                "observations_fetched": 20,
                "unique_listings_analysed": 20,
            },
            "markets": [],
            "listings": [],
        }
        message = alert(
            "St Leonards NSW 2065 nsw: For sale",
            '<div>Premium North Shore location</div>'
            '<div>St Leonards NSW 2065</div>'
            '<div>1</div><div>1</div><div>1</div>'
            '<a href="https://example.test/details">Find out more</a>',
            "2026-07-31T04:16:59Z",
        )
        refreshed = refresh.build_refresh(snapshot, [message])
        self.assertEqual(refreshed["listings"], [])
        self.assertEqual(refreshed["meta"]["alert_messages"], 11)
        self.assertEqual(refreshed["meta"]["unattributed_alert_cards_skipped"], 1)
        self.assertEqual(refreshed["meta"]["last_alert_email_at"], "2026-07-31T04:16:59Z")

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
