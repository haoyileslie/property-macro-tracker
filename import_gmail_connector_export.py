#!/usr/bin/env python3
"""Import Gmail connector records from stdin without retaining raw email bodies."""

import argparse
import json
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

import listing_event_store as store
import refresh_listings_from_gmail as gmail
from sync_private_listing_events import SYNC_KEY


def connector_message(record):
    message = EmailMessage()
    message["Subject"] = record.get("subject") or ""
    timestamp = datetime.fromisoformat((record.get("email_ts") or "").replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    message["Date"] = timestamp
    message["X-Property-Desk-Message-Id"] = record.get("id") or ""
    message.set_content(record.get("body") or "")
    return message


def import_records(db_path, records):
    observations = []
    supported_messages = []
    skipped_unattributed = 0
    for record in records:
        message = connector_message(record)
        if not gmail.supported_alert(message):
            continue
        supported_messages.append(message)
        parsed = gmail.parse_message(message)
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
        for item in parsed:
            item["_source_message_id"] = message.get("X-Property-Desk-Message-Id")
        observations.extend(parsed)
    inserted = store.record_listing_events(db_path, observations) if observations else 0
    if supported_messages:
        latest = max(gmail.message_timestamp(message) for message in supported_messages)
        current = store.get_sync_state(db_path, SYNC_KEY)
        if not current or latest > current:
            store.set_sync_state(db_path, SYNC_KEY, latest)
    return {
        "messages": len(supported_messages),
        "observations": len(observations),
        "events_inserted": inserted,
        "unattributed_cards_skipped": skipped_unattributed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="private/listing_events.sqlite3")
    parser.add_argument("--input", help="Private connector JSON file; defaults to stdin")
    args = parser.parse_args()
    if args.input:
        with open(args.input, encoding="utf-8") as handle:
            records = json.load(handle)
    else:
        records = json.loads(sys.stdin.readline())
    result = import_records(args.db, records)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
