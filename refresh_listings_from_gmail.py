#!/usr/bin/env python3
"""Refresh the public listing sample from labelled Gmail portal alerts."""

import base64
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

import ingest_listings

ROOT = Path(__file__).resolve().parent
LATEST_PATH = ROOT / "market_listings_latest.json"
VINTAGES_PATH = ROOT / "market_listings_vintages.json"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
CITY_BY_STATE = {"NSW": "Sydney", "VIC": "Melbourne", "QLD": "Brisbane", "WA": "Perth"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


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


def request_json(url, token=None, data=None):
    headers = {"User-Agent": "property-macro-tracker/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def refresh_access_token(client_id, client_secret, refresh_token):
    payload = request_json(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Google OAuth refresh did not return an access token")
    return token


def find_label_id(token, label_name):
    payload = request_json(f"{GMAIL_API}/labels", token)
    match = next(
        (item for item in payload.get("labels", []) if item.get("name", "").casefold() == label_name.casefold()),
        None,
    )
    if not match:
        raise RuntimeError(f'Gmail label not found: "{label_name}"')
    return match["id"]


def list_message_ids(token, query, label_id, limit=500):
    ids = []
    page_token = None
    while len(ids) < limit:
        params = {
            "q": query,
            "labelIds": label_id,
            "maxResults": min(100, limit - len(ids)),
        }
        if page_token:
            params["pageToken"] = page_token
        payload = request_json(f"{GMAIL_API}/messages?{urllib.parse.urlencode(params)}", token)
        ids.extend(item["id"] for item in payload.get("messages", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return ids


def fetch_message(token, message_id):
    payload = request_json(f"{GMAIL_API}/messages/{message_id}?format=raw", token)
    raw = payload.get("raw")
    if not raw:
        raise RuntimeError(f"Gmail message {message_id} did not include raw MIME")
    return BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


class EmailHTMLText(HTMLParser):
    """Reduce email HTML to readable lines while retaining anchor targets."""

    BLOCKS = {"br", "div", "p", "tr", "td", "li", "table", "h1", "h2", "h3"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.anchor_href = None
        self.anchor_parts = []

    def newline(self):
        target = self.anchor_parts if self.anchor_href else self.parts
        if target and target[-1] != "\n":
            target.append("\n")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.BLOCKS:
            self.newline()
        if tag == "a":
            self.anchor_href = dict(attrs).get("href")
            self.anchor_parts = []
        if tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                (self.anchor_parts if self.anchor_href else self.parts).append(alt)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self.anchor_href:
            label = " ".join("".join(self.anchor_parts).split())
            if label:
                self.parts.append(f"[{label}]({self.anchor_href})")
            self.anchor_href = None
            self.anchor_parts = []
            self.newline()
        if tag in self.BLOCKS:
            self.newline()

    def handle_data(self, data):
        (self.anchor_parts if self.anchor_href else self.parts).append(data)

    def text(self):
        return "".join(self.parts)


def message_body(message):
    plain = []
    html = []
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_disposition() == "attachment":
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError):
            continue
        if part.get_content_type() == "text/plain":
            plain.append(content)
        elif part.get_content_type() == "text/html":
            parser = EmailHTMLText()
            parser.feed(content)
            html.append(parser.text())
    # HTML retains the listing-card links needed to distinguish addresses from headlines.
    return "\n".join(html or plain)


def message_timestamp(message):
    value = parsedate_to_datetime(message.get("Date"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def markdown_lines(body):
    joined = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda match: f"[{' '.join(match.group(1).split())}]({match.group(2)})",
        body or "",
        flags=re.S,
    )
    return [line.strip() for line in joined.splitlines() if line.strip()]


def markdown_link(line):
    match = re.match(r"^\[([^\]]+)\]\((https?://[^)]+)\)", line)
    return match.groups() if match else (None, None)


def public_item(source, address, suburb, state, postcode, captured_at, **facts):
    identity = f"{source}|{' '.join(address.lower().split())}"
    return {
        "property_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "source": source,
        "city": CITY_BY_STATE.get(state),
        "suburb": suburb,
        "state": state,
        "postcode": postcode,
        "address": address,
        "property_type": facts.get("property_type"),
        "sale_type": facts.get("sale_type"),
        "price_text": facts.get("price_text"),
        "asking_price_low": None,
        "asking_price_high": None,
        "bedrooms": facts.get("bedrooms"),
        "bathrooms": facts.get("bathrooms"),
        "parking": facts.get("parking"),
        "first_seen_at": captured_at,
        "last_seen_at": captured_at,
    }


def parse_domain_saved_search(body, subject, captured_at):
    locations = {}
    scope = re.sub(r"^.*?Home Alert for\s+", "", subject, flags=re.I)
    for segment in scope.split(","):
        match = re.search(r"^\s*(.+?)\s+(NSW|VIC|QLD|WA)\s+(\d{4})\s*$", segment, re.I)
        if match:
            name, state, postcode = match.groups()
            locations[name.strip().lower()] = (state.upper(), postcode)
    if not locations:
        return []
    default = next(iter(locations.values()))
    lines = markdown_lines(body)
    records = []
    for index, line in enumerate(lines):
        label, _ = markdown_link(line)
        if not label:
            continue
        match = re.match(r"^(.+),\s*([^,]+)$", label)
        if not match or not re.match(r"^\d", match.group(1)):
            continue
        street, suburb = match.groups()
        state, postcode = locations.get(suburb.strip().lower(), default)
        facts = {}
        window = lines[index + 1:index + 11]
        for position, value in enumerate(window[:-1]):
            fact = window[position + 1].lower()
            if value.isdigit() and fact in {"bed", "beds", "bath", "baths", "car", "cars"}:
                key = "bedrooms" if fact.startswith("bed") else "bathrooms" if fact.startswith("bath") else "parking"
                facts[key] = int(value)
        property_type = next((value for value in window if value.lower() in {"house", "apartment", "unit", "townhouse", "villa", "land"}), None)
        price = None
        for prior in reversed(lines[max(0, index - 5):index]):
            prior_label, _ = markdown_link(prior)
            candidate = prior_label or prior
            if re.search(r"\$|auction|contact agent|for sale|expressions? of interest|offers", candidate, re.I):
                price = candidate
                break
        records.append(public_item(
            "Domain", f"{street}, {suburb} {state} {postcode}", suburb, state, postcode,
            captured_at, property_type=property_type, price_text=price, **facts,
        ))
    return records


def parse_rea(body, subject, captured_at, coming_soon=False):
    match = re.search(r'Alert for your "[^\"]+,\s*(NSW|VIC|QLD|WA)\s+(\d{4})"', subject, re.I)
    if not match:
        return []
    state, postcode = match.group(1).upper(), match.group(2)
    lines = markdown_lines(body)
    records = []
    for index, line in enumerate(lines):
        label, _ = markdown_link(line)
        if not label:
            continue
        address_match = re.match(r"^(.+),\s*([^,]+)\s+(\d{4})$", label)
        if not address_match:
            continue
        street, suburb, address_postcode = address_match.groups()
        if not re.match(r"^(?:\d|Lot\s+\d)", street, re.I) or address_postcode != postcode:
            continue
        fact_lines = lines[index + 1:index + 8]
        facts = {}
        fact_text = " ".join(fact_lines)
        for key, pattern in {
            "bedrooms": r"\bBedrooms?\s*(\d+)\b",
            "bathrooms": r"\bBathrooms?\s*(\d+)\b",
            "parking": r"\b(?:Parking(?:\s+spaces?)?|Cars?)\s*(\d+)\b",
        }.items():
            fact_match = re.search(pattern, fact_text, re.I)
            if fact_match:
                facts[key] = int(fact_match.group(1))
        if len(facts) != 3:
            numeric = [int(value) for value in fact_lines[:3] if value.isdigit()]
            if len(numeric) == 3:
                facts = dict(zip(("bedrooms", "bathrooms", "parking"), numeric))
        if len(facts) != 3:
            continue
        price = None
        for prior in reversed(lines[max(0, index - 4):index]):
            if prior.upper().startswith("THE DEAL:"):
                price = prior.split(":", 1)[1].strip()
                break
            if not prior.startswith("[") and re.search(r"\$|offer", prior, re.I):
                price = prior
                break
        records.append(public_item(
            "REA", f"{street}, {suburb} {state} {postcode}", suburb, state, postcode,
            captured_at, sale_type="Coming Soon" if coming_soon else None,
            price_text=price, **facts,
        ))
    return records


def parse_domain_single(body, subject, captured_at, off_market=False):
    lines = markdown_lines(body)
    if off_market:
        subject_match = re.search(r",\s*(NSW|VIC|QLD|WA),\s*(\d{4})$", subject, re.I)
        address_pattern = r"^(.+?),\s*([^,]+),\s*(NSW|VIC|QLD|WA),?\s*(\d{4})$"
    else:
        subject_match = re.search(r"(NSW|VIC|QLD|WA)\s+(\d{4}).*?:\s+For\s+(?:sale|auction)$", subject, re.I)
        address_pattern = r"^(.+?),\s*([^,]+?)\s+(NSW|VIC|QLD|WA)\s+(\d{4})$"
    if not subject_match:
        return []
    expected_state, expected_postcode = subject_match.group(1).upper(), subject_match.group(2)
    for index, line in enumerate(lines):
        label, _ = markdown_link(line)
        candidate = label or line
        match = re.match(address_pattern, candidate, re.I)
        if not match:
            continue
        street, suburb, state, postcode = match.groups()
        state = state.upper()
        if state != expected_state or postcode != expected_postcode:
            continue
        facts = lines[index + 1:index + 4]
        numeric = len(facts) == 3 and all(value.isdigit() for value in facts)
        price = None
        for prior in reversed(lines[max(0, index - 5):index]):
            prior_label, _ = markdown_link(prior)
            candidate_price = prior_label or prior
            if re.search(r"\$|auction|contact agent|for sale|price guide", candidate_price, re.I):
                price = candidate_price.removeprefix("Price Guide:").strip()
                break
        method = "Off Market" if off_market else "Auction" if re.search(r"For auction$", subject, re.I) else "Private Sale"
        return [public_item(
            "Domain", f"{street}, {suburb} {state} {postcode}", suburb, state, postcode,
            captured_at, sale_type=method, price_text=price,
            bedrooms=int(facts[0]) if numeric else None,
            bathrooms=int(facts[1]) if numeric else None,
            parking=int(facts[2]) if numeric else None,
        )]
    return []


def parse_message(message):
    subject = message.get("Subject") or ""
    body = message_body(message)
    captured_at = message_timestamp(message)
    if re.search(r"\bHome Alert for\b", subject, re.I):
        return parse_domain_saved_search(body, subject, captured_at)
    if re.search(r"\bNew to market:\s*Alert for your\b", subject, re.I):
        return parse_rea(body, subject, captured_at)
    if re.search(r"\bComing Soon properties:\s*Alert for your\b", subject, re.I):
        return parse_rea(body, subject, captured_at, coming_soon=True)
    if re.search(r"^Domain off-market alert:", subject, re.I):
        return parse_domain_single(body, subject, captured_at, off_market=True)
    if re.search(r"(?:NSW|VIC|QLD|WA)\s+\d{4}.*?:\s+For\s+(?:sale|auction)$", subject, re.I):
        return parse_domain_single(body, subject, captured_at)
    return []


def supported_alert(message):
    subject = message.get("Subject") or ""
    return any(re.search(pattern, subject, re.I) for pattern in (
        r"\bHome Alert for\b",
        r"\bNew to market:\s*Alert for your\b",
        r"\bComing Soon properties:\s*Alert for your\b",
        r"^Domain off-market alert:",
        r"(?:NSW|VIC|QLD|WA)\s+\d{4}.*?:\s+For\s+(?:sale|auction)$",
    ))


def merge_listings(existing, observed, limit=3):
    by_id = {item["property_id"]: dict(item) for item in existing}
    for item in observed:
        previous = by_id.get(item["property_id"])
        if previous:
            item["first_seen_at"] = min(previous["first_seen_at"], item["first_seen_at"])
            merged = {**previous, **{key: value for key, value in item.items() if value is not None}}
            merged["last_seen_at"] = max(previous["last_seen_at"], item["last_seen_at"])
            by_id[item["property_id"]] = merged
        else:
            by_id[item["property_id"]] = item
    grouped = defaultdict(list)
    for item in by_id.values():
        grouped[(item.get("city"), item.get("suburb"), item.get("state"))].append(item)
    selected = []
    for key in sorted(grouped):
        candidates = sorted(grouped[key], key=lambda item: (item["last_seen_at"], item["address"]), reverse=True)
        chosen = []
        for source in ("Domain", "REA"):
            match = next((item for item in candidates if item["source"] == source), None)
            if match:
                chosen.append(match)
        for item in candidates:
            if len(chosen) >= limit:
                break
            if item not in chosen:
                chosen.append(item)
        selected.extend(chosen[:limit])
    return selected


def market_summaries(listings):
    grouped = defaultdict(list)
    for item in listings:
        grouped[(item["city"], item["suburb"], item["state"])].append(item)
    markets = []
    for (city, suburb, state), rows in sorted(grouped.items()):
        postcodes = Counter(row.get("postcode") for row in rows if row.get("postcode"))
        auctions = sum((row.get("sale_type") or "").lower() == "auction" for row in rows)
        markets.append({
            "city": city, "suburb": suburb, "state": state,
            "postcode": postcodes.most_common(1)[0][0] if postcodes else None,
            "listing_count": len(rows), "auction_count": auctions,
            "auction_share_pct": round(100 * auctions / len(rows), 1) if rows else None,
            "price_disclosed_count": sum(bool(row.get("price_text")) for row in rows),
            "median_asking_midpoint_aud": None,
            "source_counts": {source: sum(row["source"] == source for row in rows) for source in ("Domain", "REA")},
        })
    return markets


def build_refresh(snapshot, messages):
    cutoff = parse_timestamp(snapshot["meta"].get("last_alert_email_at") or snapshot["meta"]["captured_at"])
    fresh_messages = [
        message for message in messages
        if parse_timestamp(message_timestamp(message)) > cutoff and supported_alert(message)
    ]
    observed = []
    for message in fresh_messages:
        parsed = parse_message(message)
        if not parsed:
            raise RuntimeError(
                "Recognized a portal alert but could not parse any listing cards: "
                + (message.get("Subject") or "No subject")
            )
        observed.extend(parsed)
    if not fresh_messages:
        return None
    latest_email_at = max(message_timestamp(message) for message in fresh_messages)
    listings = merge_listings(snapshot.get("listings", []), observed, limit=3)
    markets = market_summaries(listings)
    prior_ids = {item["property_id"] for item in snapshot.get("listings", [])}
    new_ids = {item["property_id"] for item in observed} - prior_ids
    meta = {
        **snapshot["meta"],
        "captured_at": max((item["last_seen_at"] for item in listings), default=latest_email_at),
        "last_alert_email_at": latest_email_at,
        "published_at": utc_now(),
        "alert_messages": int(snapshot["meta"].get("alert_messages") or 0) + len(fresh_messages),
        "market_count": len(markets),
        "listing_count": len(listings),
        "observations_fetched": int(snapshot["meta"].get("observations_fetched") or 0) + len(observed),
        "unique_listings_analysed": int(snapshot["meta"].get("unique_listings_analysed") or 0) + len(new_ids),
    }
    return {"meta": meta, "markets": markets, "listings": listings}


def main():
    secrets = {name: os.environ.get(name, "").strip() for name in (
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"
    )}
    missing = [name for name, value in secrets.items() if not value]
    if missing:
        raise SystemExit("Missing GitHub secrets: " + ", ".join(missing))
    snapshot = ingest_listings.read_json(LATEST_PATH)
    cutoff = parse_timestamp(snapshot["meta"].get("last_alert_email_at") or snapshot["meta"]["captured_at"])
    token = refresh_access_token(**{
        "client_id": secrets["GMAIL_CLIENT_ID"],
        "client_secret": secrets["GMAIL_CLIENT_SECRET"],
        "refresh_token": secrets["GMAIL_REFRESH_TOKEN"],
    })
    label_id = find_label_id(token, "Property Desk")
    query = f'after:{int(cutoff.timestamp())} -in:trash -in:spam'
    messages = [
        fetch_message(token, message_id)
        for message_id in list_message_ids(token, query, label_id)
    ]
    refreshed = build_refresh(snapshot, messages)
    if refreshed is None:
        print("No new Property Desk alert messages.")
        return
    archive = ingest_listings.read_json(VINTAGES_PATH)
    archive.setdefault("vintages", []).append({"meta": refreshed["meta"], "markets": refreshed["markets"]})
    ingest_listings.validate_snapshot(refreshed)
    ingest_listings.validate_vintages(refreshed, archive)
    atomic_write_json(LATEST_PATH, refreshed)
    atomic_write_json(VINTAGES_PATH, archive)
    print(
        f"Published {len(refreshed['listings'])} examples after reading "
        f"{len(messages)} candidate Gmail messages."
    )


if __name__ == "__main__":
    main()
