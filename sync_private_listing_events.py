#!/usr/bin/env python3
"""Sync labelled Gmail alerts into the local private listing-event ledger."""

import argparse
import os

import listing_event_store as store
import refresh_listings_from_gmail as gmail


SYNC_KEY = "property_desk_last_email_at"


def annotate(records, message):
    message_id = message.get("X-Property-Desk-Message-Id")
    for record in records:
        record["_source_message_id"] = message_id
    return records


def sync_messages(db_path, messages):
    watermark = store.get_sync_state(db_path, SYNC_KEY)
    eligible = [
        message for message in messages
        if gmail.supported_alert(message)
        and (not watermark or gmail.message_timestamp(message) > watermark)
    ]
    observations = []
    skipped_unattributed = 0
    for message in eligible:
        parsed = annotate(gmail.parse_message(message), message)
        if not parsed:
            body = gmail.message_body(message)
            subject = message.get("Subject") or ""
            skipped = (
                gmail.hidden_rea_card_count(body, subject)
                + gmail.unattributed_domain_card_count(body, subject)
                + gmail.unattributed_domain_featured_card_count(body, subject)
            )
            if skipped:
                skipped_unattributed += skipped
                continue
            raise RuntimeError(f"Recognized an alert but could not parse it: {subject}")
        observations.extend(parsed)
    inserted = store.record_listing_events(db_path, observations) if observations else 0
    if eligible:
        store.set_sync_state(
            db_path, SYNC_KEY, max(gmail.message_timestamp(message) for message in eligible)
        )
    return {
        "messages": len(eligible),
        "observations": len(observations),
        "events_inserted": inserted,
        "unattributed_cards_skipped": skipped_unattributed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="private/listing_events.sqlite3")
    parser.add_argument("--label", default="Property Desk")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    secrets = {name: os.environ.get(name, "").strip() for name in (
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"
    )}
    missing = [name for name, value in secrets.items() if not value]
    if missing:
        raise SystemExit("Missing local environment values: " + ", ".join(missing))
    token = gmail.refresh_access_token(
        secrets["GMAIL_CLIENT_ID"], secrets["GMAIL_CLIENT_SECRET"],
        secrets["GMAIL_REFRESH_TOKEN"],
    )
    label_id = gmail.find_label_id(token, args.label)
    watermark = store.get_sync_state(args.db, SYNC_KEY)
    query = "-in:trash -in:spam"
    if watermark:
        query = f"after:{int(gmail.parse_timestamp(watermark).timestamp())} {query}"
    messages = []
    for message_id in gmail.list_message_ids(token, query, label_id, limit=args.limit):
        message = gmail.fetch_message(token, message_id)
        message["X-Property-Desk-Message-Id"] = message_id
        messages.append(message)
    result = sync_messages(args.db, messages)
    stats = store.store_stats(args.db)
    print(
        f"Read {result['messages']} alerts, appended {result['events_inserted']} events; "
        f"ledger now has {stats['events']} events for {stats['properties']} properties."
    )


if __name__ == "__main__":
    main()
