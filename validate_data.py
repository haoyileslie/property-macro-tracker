#!/usr/bin/env python3
"""Validate tracker data, metadata, freshness, and vintage consistency."""

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

from derived_indicators import DERIVATION_VERSION, build_derived_series


ROOT = Path(__file__).parent
DATA_PATH = ROOT / "property_data.json"
VINTAGES_PATH = ROOT / "data_vintages.json"
DATE_PATTERN = re.compile(r"^(\d{4})(?:-(Q[1-4]|\d{2})(?:-(\d{2}))?)?$")
REQUIRED_SERIES_FIELDS = (
    "label", "unit", "frequency", "definition", "usage",
    "housing_market_link", "source", "source_url", "data", "status",
    "last_source_check", "latest_source_period",
)
ALLOWED_STATUSES = {"fresh", "watch", "stale", "discontinued"}
RANGES = {
    "cash_rate": (-1, 25),
    "unemployment_rate": (0, 30),
    "employed_people": (0, 100_000),
    "cpi_headline_yoy": (-20, 30),
    "cpi_trimmed_mean_yoy": (-20, 30),
    "building_approvals_total_dwellings": (0, 100_000),
    "building_approvals_total_dwellings_state_proxy": (0, 100_000),
    "housing_lending_rate_owner_occupier_variable": (0, 30),
    "lending_new_loan_commitments_dwellings_number": (0, 1_000_000),
    "lending_new_loan_commitments_dwellings_value": (0, 1_000),
    "lending_new_loan_commitments_dwellings_qoq": (-100, 200),
    "home_value_index_mom": (-20, 20),
    "vacancy_rate": (0, 20),
    "us_treasury_3y": (-5, 25),
    "us_treasury_10y": (-5, 25),
    "wage_price_index_private_yoy": (-10, 30),
    "wage_price_index_public_yoy": (-10, 30),
    "average_weekly_earnings_private": (0, 10_000),
    "average_weekly_earnings_public": (0, 10_000),
    "asx_200": (0, 100_000),
    "sp_500": (0, 100_000),
    "msci_acwi": (0, 100_000),
    "asx_200_real_estate": (0, 100_000),
    "asx_200_areit": (0, 100_000),
}


class ValidationError(Exception):
    """Raised with all validation failures found in one pass."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("\n".join(f"- {error}" for error in errors))


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("must be a string")
    match = DATE_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("must use YYYY, YYYY-MM, YYYY-MM-DD, or YYYY-Q#")
    year = int(match.group(1))
    period = match.group(2)
    day = match.group(3)
    if period is None:
        return year, 0, 0
    if period.startswith("Q"):
        return year, int(period[1]) * 3, 0
    month = int(period)
    if not 1 <= month <= 12:
        raise ValueError("contains an invalid month")
    day_number = int(day or 0)
    if day:
        dt.date(year, month, day_number)
    return year, month, day_number


def parse_iso_date(value):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def validate_dataset(data, *, require_refresh_metadata=True, as_of=None):
    errors = []
    if not isinstance(data, dict):
        raise ValidationError(["dataset root must be an object"])
    meta = data.get("meta")
    series_map = data.get("series")
    if not isinstance(meta, dict):
        errors.append("meta must be an object")
        meta = {}
    if not isinstance(series_map, dict) or not series_map:
        errors.append("series must be a non-empty object")
        series_map = {}

    regions = meta.get("regions")
    if not isinstance(regions, list) or "National" not in regions:
        errors.append("meta.regions must be a list containing National")
    last_updated = parse_iso_date(meta.get("last_updated"))
    if last_updated is None:
        errors.append("meta.last_updated must be an ISO date")
    if require_refresh_metadata:
        for field in ("last_refreshed_at", "latest_refresh_id", "vintage_file"):
            if not meta.get(field):
                errors.append(f"meta.{field} is required")

    today = as_of or dt.date.today()
    observation_count = 0
    for key, series in series_map.items():
        prefix = f"series.{key}"
        if not isinstance(series, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in REQUIRED_SERIES_FIELDS:
            if field not in series or series[field] in (None, "", {}):
                errors.append(f"{prefix}.{field} is required")
        source_url = series.get("source_url", "")
        if source_url and not source_url.startswith("https://"):
            errors.append(f"{prefix}.source_url must use HTTPS")
        if series.get("status") not in ALLOWED_STATUSES:
            errors.append(f"{prefix}.status is not recognised")

        check_date = parse_iso_date(series.get("last_source_check"))
        if check_date is None:
            errors.append(f"{prefix}.last_source_check must be an ISO date")
        elif check_date > today:
            errors.append(f"{prefix}.last_source_check is in the future")
        elif series.get("status") == "fresh" and (today - check_date).days > 45:
            errors.append(f"{prefix} is marked fresh but was last checked {(today - check_date).days} days ago")

        data_by_region = series.get("data")
        if not isinstance(data_by_region, dict):
            continue
        if "National" not in data_by_region:
            errors.append(f"{prefix}.data must contain National")
        all_dates = []
        for region, points in data_by_region.items():
            region_prefix = f"{prefix}.data.{region}"
            if not isinstance(points, list):
                errors.append(f"{region_prefix} must be a list")
                continue
            if not points:
                if region == "National":
                    errors.append(f"{region_prefix} must be non-empty")
                continue
            seen = set()
            previous = None
            for index, point in enumerate(points):
                point_prefix = f"{region_prefix}[{index}]"
                if not isinstance(point, dict):
                    errors.append(f"{point_prefix} must be an object")
                    continue
                date_value = point.get("date")
                try:
                    sort_key = parse_date(date_value)
                except ValueError as exc:
                    errors.append(f"{point_prefix}.date {exc}")
                    continue
                if date_value in seen:
                    errors.append(f"{region_prefix} contains duplicate date {date_value}")
                if previous is not None and sort_key <= previous:
                    errors.append(f"{region_prefix} is not strictly chronological at {date_value}")
                seen.add(date_value)
                previous = sort_key
                all_dates.append((sort_key, date_value))

                value = point.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    errors.append(f"{point_prefix}.value must be a finite number")
                elif key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
                    low, high = RANGES[key]
                    errors.append(f"{point_prefix}.value {value} is outside plausible range {low} to {high}")
                observation_count += 1

        national = data_by_region.get("National", [])
        if "observation_count" in series and series["observation_count"] != len(national):
            errors.append(f"{prefix}.observation_count does not match National data")
        region_counts = series.get("observation_count_by_region")
        if region_counts is not None:
            expected = {region: len(points) for region, points in data_by_region.items()}
            if region_counts != expected:
                errors.append(f"{prefix}.observation_count_by_region does not match data")
        if series.get("history_start") and all_dates:
            earliest = min(all_dates)[1]
            if series["history_start"] != earliest:
                errors.append(f"{prefix}.history_start should be {earliest}")
        if national and series.get("latest_source_period") != national[-1].get("date"):
            errors.append(f"{prefix}.latest_source_period does not match latest National observation")

    derived_series = data.get("derived_series")
    if not isinstance(derived_series, dict) or not derived_series:
        errors.append("derived_series must be a non-empty object")
        derived_series = {}
    if meta.get("derived_series_version") != DERIVATION_VERSION:
        errors.append(f"meta.derived_series_version must be {DERIVATION_VERSION}")
    if series_map:
        expected_derived = build_derived_series(data)
        if set(derived_series) != set(expected_derived):
            errors.append("derived_series keys do not match the configured derivations")
        else:
            for key, expected in expected_derived.items():
                if derived_series[key] != expected:
                    errors.append(f"derived_series.{key} does not match its source formula")

    if errors:
        raise ValidationError(errors)
    derived_observations = sum(
        len(series.get("data", {}).get("National", []))
        for series in derived_series.values()
    )
    return {
        "series": len(series_map),
        "observations": observation_count,
        "derived series": len(derived_series),
        "derived observations": derived_observations,
    }


def validate_vintage_archive(archive, current_data):
    errors = []
    if not isinstance(archive, dict):
        raise ValidationError(["vintage archive root must be an object"])
    refreshes = archive.get("refreshes")
    if not isinstance(refreshes, list) or not refreshes:
        raise ValidationError(["vintage archive must contain at least one refresh"])
    ids = []
    previous = None
    for index, refresh in enumerate(refreshes):
        prefix = f"refreshes[{index}]"
        refresh_id = refresh.get("refresh_id")
        captured_at = refresh.get("captured_at")
        if not refresh_id:
            errors.append(f"{prefix}.refresh_id is required")
        elif refresh_id in ids:
            errors.append(f"{prefix}.refresh_id is duplicated")
        ids.append(refresh_id)
        try:
            captured = dt.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if previous and captured <= previous:
                errors.append(f"{prefix}.captured_at is not strictly chronological")
            previous = captured
        except (AttributeError, TypeError, ValueError):
            errors.append(f"{prefix}.captured_at must be an ISO timestamp")
        if not isinstance(refresh.get("series"), dict):
            errors.append(f"{prefix}.series must be an object")

    latest = refreshes[-1]
    latest_id = latest.get("refresh_id")
    if archive.get("latest_refresh_id") != latest_id:
        errors.append("archive.latest_refresh_id does not match the final refresh")
    if current_data.get("meta", {}).get("latest_refresh_id") != latest_id:
        errors.append("dataset latest_refresh_id does not match the vintage archive")
    current_series = current_data.get("series", {})
    snapshot_series = latest.get("series", {})
    if set(snapshot_series) != set(current_series):
        errors.append("latest vintage and dataset contain different series")
    else:
        for key, series in current_series.items():
            snapshot = snapshot_series[key]
            for field in ("source", "source_url", "latest_source_period", "data"):
                if snapshot.get(field) != series.get(field):
                    errors.append(f"latest vintage series.{key}.{field} does not match dataset")
    if latest.get("data_as_of") != current_data.get("meta", {}).get("last_updated"):
        errors.append("latest vintage data_as_of does not match meta.last_updated")

    if errors:
        raise ValidationError(errors)
    return {"vintages": len(refreshes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--vintages", type=Path, default=VINTAGES_PATH)
    parser.add_argument("--skip-vintages", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.data.read_text())
    report = validate_dataset(data)
    if not args.skip_vintages:
        archive = json.loads(args.vintages.read_text())
        report.update(validate_vintage_archive(archive, data))
    details = ", ".join(f"{value:,} {key}" for key, value in report.items())
    print(f"Validation passed: {details}.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Validation failed:\n{exc}", file=sys.stderr)
        sys.exit(1)
