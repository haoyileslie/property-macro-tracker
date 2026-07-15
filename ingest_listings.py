#!/usr/bin/env python3
"""Fetch a quota-conscious snapshot of active listings from PropRadar."""

import argparse
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
BASE_URL = "https://api.propradar.com.au/v1"
CONFIG_PATH = ROOT / "listings_config.json"
LATEST_PATH = ROOT / "market_listings_latest.json"
VINTAGES_PATH = ROOT / "market_listings_vintages.json"


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, payload):
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def fetch_json(url, api_key, attempts=3, timeout=30):
    request = urllib.request.Request(
        url,
        headers={"X-API-Key": api_key, "User-Agent": "property-macro-tracker/1.0"},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            if isinstance(error, urllib.error.HTTPError) and 400 <= error.code < 500 and error.code != 429:
                raise RuntimeError(f"PropRadar request rejected ({error.code}): {url}") from error
            if attempt == attempts:
                raise RuntimeError(f"PropRadar request failed after {attempts} attempts: {url}") from error
            time.sleep(attempt)


def listing_url(market, limit):
    state = urllib.parse.quote(market["state"], safe="")
    suburb = urllib.parse.quote(market["suburb"], safe="")
    return f"{BASE_URL}/suburbs/{state}/{suburb}/listings?limit={limit}"


def normalize_listing(raw, market, captured_at, previous=None):
    listing_id = str(raw.get("property_id") or "").strip()
    if not listing_id:
        raise ValueError(f"Listing without property_id in {market['suburb']}")
    previous = previous or {}
    return {
        "property_id": listing_id,
        "city": market["city"],
        "suburb": market["suburb"],
        "state": market["state"],
        "postcode": market["postcode"],
        "address": raw.get("address"),
        "property_type": raw.get("property_type"),
        "sale_type": raw.get("sale_type"),
        "asking_price_low": raw.get("asking_price_low"),
        "asking_price_high": raw.get("asking_price_high"),
        "bedrooms": raw.get("bedrooms"),
        "bathrooms": raw.get("bathrooms"),
        "parking": raw.get("parking"),
        "added_at": raw.get("added_at"),
        "first_seen_at": previous.get("first_seen_at", captured_at),
        "last_seen_at": captured_at,
    }


def market_summary(market, rows, limit):
    disclosed_midpoints = []
    property_types = {}
    sale_types = {}
    for row in rows:
        low, high = row.get("asking_price_low"), row.get("asking_price_high")
        if low is not None or high is not None:
            disclosed_midpoints.append((low if high is None else high if low is None else (low + high) / 2))
        property_type = row.get("property_type") or "Unknown"
        sale_type = row.get("sale_type") or "Unknown"
        property_types[property_type] = property_types.get(property_type, 0) + 1
        sale_types[sale_type] = sale_types.get(sale_type, 0) + 1
    return {
        **market,
        "listing_count": len(rows),
        "page_limit": limit,
        "auction_count": sale_types.get("Auction", 0),
        "auction_share_pct": round(100 * sale_types.get("Auction", 0) / len(rows), 1) if rows else None,
        "price_disclosed_count": len(disclosed_midpoints),
        "price_disclosed_share_pct": round(100 * len(disclosed_midpoints) / len(rows), 1) if rows else None,
        "median_asking_midpoint_aud": round(median(disclosed_midpoints)) if disclosed_midpoints else None,
        "property_type_counts": dict(sorted(property_types.items())),
        "sale_type_counts": dict(sorted(sale_types.items())),
    }


def validate_snapshot(snapshot, expected_markets):
    if snapshot["meta"]["market_count"] != expected_markets:
        raise ValueError("Market count does not match configuration")
    ids = [item["property_id"] for item in snapshot["listings"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate property_id values found in snapshot")
    allowed_sale_types = {None, "Auction", "Private Sale", "Sale", "Expressions of Interest"}
    for item in snapshot["listings"]:
        if not item.get("address"):
            raise ValueError(f"Listing {item['property_id']} has no address")
        low, high = item.get("asking_price_low"), item.get("asking_price_high")
        if low is not None and (not isinstance(low, (int, float)) or low < 0):
            raise ValueError(f"Listing {item['property_id']} has an invalid low price")
        if high is not None and (not isinstance(high, (int, float)) or high < 0):
            raise ValueError(f"Listing {item['property_id']} has an invalid high price")
        if low is not None and high is not None and low > high:
            raise ValueError(f"Listing {item['property_id']} has an inverted price range")
        if item.get("sale_type") not in allowed_sale_types:
            item["data_quality_note"] = "Unrecognised sale type retained from source"


def build_snapshot(config, api_key, captured_at=None):
    captured_at = captured_at or utc_now()
    previous = read_json(LATEST_PATH, {"listings": []})
    previous_by_id = {item["property_id"]: item for item in previous.get("listings", [])}
    listings = []
    markets = []
    limit = min(int(config.get("page_limit", 20)), 20)
    sample_size = max(0, min(int(config.get("public_sample_per_market", 3)), 5))
    observations_fetched = 0

    for market in config["markets"]:
        payload = fetch_json(listing_url(market, limit), api_key)
        rows = payload.get("listings", [])
        normalized = [
            normalize_listing(row, market, captured_at, previous_by_id.get(str(row.get("property_id"))))
            for row in rows
        ]
        observations_fetched += len(normalized)
        listings.extend(normalized[:sample_size])
        markets.append(market_summary(market, normalized, limit))

    snapshot = {
        "meta": {
            "provider": "PropRadar",
            "source_url": "https://propradar.com.au/developers/docs",
            "captured_at": captured_at,
            "status": "ok",
            "calls_used": len(config["markets"]),
            "market_count": len(config["markets"]),
            "listing_count": len(listings),
            "observations_fetched": observations_fetched,
            "public_sample_per_market": sample_size,
            "coverage_note": "Aggregate measures use one newest-first page per configured suburb. The public table is limited to three examples per suburb and is not a complete market census.",
        },
        "markets": markets,
        "listings": sorted(listings, key=lambda item: (item["city"], item["suburb"], item.get("address") or "")),
    }
    validate_snapshot(snapshot, len(config["markets"]))
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing files")
    args = parser.parse_args()
    api_key = os.environ.get("PROPRADAR_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("PROPRADAR_API_KEY is not set; no requests were made.")
    if not api_key.startswith("pr_live_"):
        raise SystemExit("PROPRADAR_API_KEY does not have the expected pr_live_ prefix.")

    config = read_json(CONFIG_PATH)
    snapshot = build_snapshot(config, api_key)
    print(
        f"Validated {snapshot['meta']['listing_count']} listings across "
        f"{snapshot['meta']['market_count']} markets using {snapshot['meta']['calls_used']} calls."
    )
    if args.dry_run:
        return

    archive = read_json(VINTAGES_PATH, {"provider": "PropRadar", "vintages": []})
    aggregate_vintage = {"meta": snapshot["meta"], "markets": snapshot["markets"]}
    archive["vintages"].append(aggregate_vintage)
    atomic_write_json(VINTAGES_PATH, archive)
    atomic_write_json(LATEST_PATH, snapshot)
    print(f"Published listing snapshot captured at {snapshot['meta']['captured_at']}.")


if __name__ == "__main__":
    main()
