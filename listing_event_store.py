#!/usr/bin/env python3
"""Append-only local event store for private listing research."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS listing_properties (
    property_id TEXT PRIMARY KEY,
    canonical_address TEXT NOT NULL,
    normalized_address TEXT NOT NULL,
    source TEXT NOT NULL,
    city TEXT,
    suburb TEXT,
    state TEXT,
    postcode TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    current_event_type TEXT NOT NULL,
    current_marketing_channel TEXT NOT NULL,
    current_lifecycle_status TEXT NOT NULL,
    current_price_text TEXT,
    current_evidence_url TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listing_events (
    event_id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    marketing_channel TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL,
    source TEXT NOT NULL,
    source_message_id TEXT,
    evidence_url TEXT,
    price_text TEXT,
    sale_price_aud INTEGER,
    sale_outcome TEXT,
    bedrooms INTEGER,
    bathrooms INTEGER,
    parking INTEGER,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (property_id) REFERENCES listing_properties(property_id)
);

CREATE INDEX IF NOT EXISTS listing_events_property_time
ON listing_events(property_id, observed_at);

CREATE INDEX IF NOT EXISTS listing_events_status_time
ON listing_events(lifecycle_status, observed_at);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def normalize_address(value):
    return " ".join((value or "").lower().replace(",", " ").split())


def classify_event(listing):
    method = (listing.get("sale_type") or "").strip().lower()
    if method == "off market":
        return "off_market_alert", "off_market", "pre_market"
    if method == "coming soon":
        return "coming_soon_alert", "coming_soon", "pre_market"
    if method == "auction":
        return "listing_alert", "auction", "active"
    if method == "private sale":
        return "listing_alert", "private_sale", "active"
    return "listing_alert", "public_market", "active"


def event_identity(listing, event_type, observed_at):
    payload = {
        key: listing.get(key)
        for key in (
            "property_id", "source", "price_text", "sale_type", "bedrooms",
            "bathrooms", "parking", "_evidence_url", "_source_message_id",
        )
    }
    basis = "|".join((
        listing["property_id"],
        event_type,
        observed_at,
        listing.get("_source_message_id") or "",
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def record_listing_events(path, listings):
    """Append observations and update the current-state projection."""
    connection = connect(path)
    inserted = 0
    try:
        with connection:
            for listing in listings:
                event_type, channel, status = classify_event(listing)
                observed_at = listing.get("last_seen_at") or listing.get("first_seen_at")
                recorded_at = utc_now()
                event_id = event_identity(listing, event_type, observed_at)
                payload = {
                    key: value for key, value in listing.items()
                    if not key.startswith("_")
                }
                connection.execute(
                    """
                    INSERT INTO listing_properties (
                        property_id, canonical_address, normalized_address, source,
                        city, suburb, state, postcode, first_seen_at, last_seen_at,
                        current_event_type, current_marketing_channel,
                        current_lifecycle_status, current_price_text,
                        current_evidence_url, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(property_id) DO UPDATE SET
                        canonical_address = excluded.canonical_address,
                        normalized_address = excluded.normalized_address,
                        city = COALESCE(excluded.city, listing_properties.city),
                        suburb = COALESCE(excluded.suburb, listing_properties.suburb),
                        state = COALESCE(excluded.state, listing_properties.state),
                        postcode = COALESCE(excluded.postcode, listing_properties.postcode),
                        first_seen_at = MIN(listing_properties.first_seen_at, excluded.first_seen_at),
                        last_seen_at = MAX(listing_properties.last_seen_at, excluded.last_seen_at),
                        current_event_type = CASE WHEN excluded.last_seen_at >= listing_properties.last_seen_at
                            THEN excluded.current_event_type ELSE listing_properties.current_event_type END,
                        current_marketing_channel = CASE WHEN excluded.last_seen_at >= listing_properties.last_seen_at
                            THEN excluded.current_marketing_channel ELSE listing_properties.current_marketing_channel END,
                        current_lifecycle_status = CASE WHEN excluded.last_seen_at >= listing_properties.last_seen_at
                            THEN excluded.current_lifecycle_status ELSE listing_properties.current_lifecycle_status END,
                        current_price_text = CASE WHEN excluded.last_seen_at >= listing_properties.last_seen_at
                            THEN COALESCE(excluded.current_price_text, listing_properties.current_price_text)
                            ELSE listing_properties.current_price_text END,
                        current_evidence_url = CASE WHEN excluded.last_seen_at >= listing_properties.last_seen_at
                            THEN COALESCE(excluded.current_evidence_url, listing_properties.current_evidence_url)
                            ELSE listing_properties.current_evidence_url END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        listing["property_id"], listing["address"], normalize_address(listing["address"]),
                        listing["source"], listing.get("city"), listing.get("suburb"),
                        listing.get("state"), listing.get("postcode"),
                        listing.get("first_seen_at") or observed_at, observed_at,
                        event_type, channel, status, listing.get("price_text"),
                        listing.get("_evidence_url"), recorded_at,
                    ),
                )
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO listing_events (
                        event_id, property_id, observed_at, event_type, marketing_channel,
                        lifecycle_status, source, source_message_id, evidence_url,
                        price_text, sale_price_aud, sale_outcome, bedrooms, bathrooms,
                        parking, payload_json, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id, listing["property_id"], observed_at, event_type, channel,
                        status, listing["source"], listing.get("_source_message_id"),
                        listing.get("_evidence_url"), listing.get("price_text"),
                        listing.get("bedrooms"), listing.get("bathrooms"),
                        listing.get("parking"), json.dumps(payload, sort_keys=True), recorded_at,
                    ),
                )
                inserted += cursor.rowcount
    finally:
        connection.close()
    return inserted


def get_sync_state(path, key):
    connection = connect(path)
    try:
        row = connection.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        connection.close()


def set_sync_state(path, key, value):
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, utc_now()),
            )
    finally:
        connection.close()


def store_stats(path):
    connection = connect(path)
    try:
        return {
            "properties": connection.execute("SELECT COUNT(*) FROM listing_properties").fetchone()[0],
            "events": connection.execute("SELECT COUNT(*) FROM listing_events").fetchone()[0],
            "off_market_events": connection.execute(
                "SELECT COUNT(*) FROM listing_events WHERE event_type = 'off_market_alert'"
            ).fetchone()[0],
            "pre_market_properties": connection.execute(
                "SELECT COUNT(*) FROM listing_properties WHERE current_lifecycle_status = 'pre_market'"
            ).fetchone()[0],
        }
    finally:
        connection.close()


def record_outcome(path, property_id, outcome, observed_at, sale_price_aud=None,
                   evidence_url=None, source="manual_follow_up"):
    allowed = {"sold", "withdrawn", "passed_in"}
    if outcome not in allowed:
        raise ValueError(f"Outcome must be one of: {', '.join(sorted(allowed))}")
    connection = connect(path)
    try:
        property_row = connection.execute(
            "SELECT * FROM listing_properties WHERE property_id = ?", (property_id,)
        ).fetchone()
        if not property_row:
            raise ValueError(f"Unknown property_id: {property_id}")
        lifecycle_status = "active" if outcome == "passed_in" else outcome
        payload = {
            "property_id": property_id,
            "outcome": outcome,
            "sale_price_aud": sale_price_aud,
            "evidence_url": evidence_url,
        }
        basis = "|".join((
            property_id, "sale_outcome", observed_at, outcome,
            str(sale_price_aud or ""), evidence_url or "",
        ))
        event_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
        recorded_at = utc_now()
        with connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO listing_events (
                    event_id, property_id, observed_at, event_type, marketing_channel,
                    lifecycle_status, source, source_message_id, evidence_url,
                    price_text, sale_price_aud, sale_outcome, bedrooms, bathrooms,
                    parking, payload_json, recorded_at
                ) VALUES (?, ?, ?, 'sale_outcome', ?, ?, ?, NULL, ?, NULL, ?, ?,
                          NULL, NULL, NULL, ?, ?)
                """,
                (
                    event_id, property_id, observed_at,
                    property_row["current_marketing_channel"],
                    lifecycle_status, source, evidence_url, sale_price_aud, outcome,
                    json.dumps(payload, sort_keys=True), recorded_at,
                ),
            )
            if observed_at >= property_row["last_seen_at"]:
                connection.execute(
                    """
                    UPDATE listing_properties
                    SET last_seen_at = ?, current_event_type = 'sale_outcome',
                        current_lifecycle_status = ?,
                        current_evidence_url = COALESCE(?, current_evidence_url),
                        updated_at = ?
                    WHERE property_id = ?
                    """,
                    (observed_at, lifecycle_status, evidence_url, recorded_at, property_id),
                )
        return cursor.rowcount
    finally:
        connection.close()


def seed_snapshot(path, snapshot_path):
    with Path(snapshot_path).open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    return record_listing_events(path, snapshot.get("listings", []))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "seed", "stats", "outcome"))
    parser.add_argument("--db", default="private/listing_events.sqlite3")
    parser.add_argument("--snapshot", default="market_listings_latest.json")
    parser.add_argument("--property-id")
    parser.add_argument("--outcome", choices=("sold", "withdrawn", "passed_in"))
    parser.add_argument("--observed-at")
    parser.add_argument("--sale-price", type=int)
    parser.add_argument("--evidence-url")
    args = parser.parse_args()
    if args.command == "init":
        connect(args.db).close()
        print(f"Initialised private listing ledger at {args.db}")
    elif args.command == "seed":
        inserted = seed_snapshot(args.db, args.snapshot)
        print(f"Added {inserted} retained observations to the private ledger.")
    elif args.command == "stats":
        print(json.dumps(store_stats(args.db), indent=2))
    else:
        missing = [
            name for name, value in (
                ("--property-id", args.property_id),
                ("--outcome", args.outcome),
                ("--observed-at", args.observed_at),
            ) if not value
        ]
        if missing:
            parser.error("outcome requires " + ", ".join(missing))
        inserted = record_outcome(
            args.db, args.property_id, args.outcome, args.observed_at,
            args.sale_price, args.evidence_url,
        )
        print("Outcome appended." if inserted else "Outcome already recorded.")


if __name__ == "__main__":
    main()
