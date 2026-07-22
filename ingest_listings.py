#!/usr/bin/env python3
"""Validate the privacy-safe market-listing export used by the public page."""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LATEST_PATH = ROOT / "market_listings_latest.json"
VINTAGES_PATH = ROOT / "market_listings_vintages.json"


def read_json(path=LATEST_PATH):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_snapshot(snapshot):
    meta = snapshot.get("meta") or {}
    listings = snapshot.get("listings") or []
    markets = snapshot.get("markets") or []
    if meta.get("provider") != "Domain and realestate.com.au saved-search alerts":
        raise ValueError("Unexpected listing provider")
    if meta.get("listing_count") != len(listings):
        raise ValueError("Listing count does not match the public sample")
    if meta.get("market_count") != len(markets):
        raise ValueError("Market count does not match the market summaries")
    ids = [item.get("property_id") for item in listings]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate public property IDs")
    per_market = int(meta.get("public_sample_per_market") or 0)
    suburb_counts = Counter(
        (item.get("city"), item.get("suburb"), item.get("state"))
        for item in listings
    )
    if per_market < 1 or any(count > per_market for count in suburb_counts.values()):
        raise ValueError("Public sample exceeds the per-suburb listing cap")
    for item in listings:
        if item.get("source") not in {"Domain", "REA"}:
            raise ValueError(f"Unexpected source for {item.get('property_id')}")
        if not item.get("address") or not item.get("first_seen_at") or not item.get("last_seen_at"):
            raise ValueError(f"Incomplete public listing {item.get('property_id')}")
        if item.get("first_seen_at") > item.get("last_seen_at"):
            raise ValueError(f"Invalid chronology for {item.get('property_id')}")
        forbidden = {"message_id", "gmail_id", "source_url", "notes", "email"}
        leaked = forbidden.intersection(item)
        if leaked:
            raise ValueError(f"Private fields present in public listing: {sorted(leaked)}")
    return snapshot


def validate_vintages(snapshot, archive):
    vintages = archive.get("vintages") or []
    if not vintages:
        raise ValueError("Listing vintage archive is empty")
    latest = vintages[-1]
    if latest.get("meta") != snapshot.get("meta") or latest.get("markets") != snapshot.get("markets"):
        raise ValueError("Latest listing vintage does not match the public export")
    return archive


def main():
    snapshot = validate_snapshot(read_json())
    validate_vintages(snapshot, read_json(VINTAGES_PATH))
    print(
        f"Validated {snapshot['meta']['listing_count']} public examples across "
        f"{snapshot['meta']['market_count']} observed suburbs."
    )


if __name__ == "__main__":
    main()
