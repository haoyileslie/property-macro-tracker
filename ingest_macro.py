#!/usr/bin/env python3
"""Refresh selected macro time series in property_data.json.

This is intentionally dependency-free so it can run anywhere Python 3 runs.
The parsers target the public release pages used by the dashboard and should
be checked after source-page redesigns.
"""

import argparse
import csv
import datetime as dt
import html
import io
import json
import re
import ssl
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from derived_indicators import DERIVATION_VERSION, build_derived_series
from rba_enhancements import RBA_ENHANCEMENT_SERIES, RBA_SOURCE_NAMES
from validate_data import validate_dataset, validate_vintage_archive


DATA_PATH = Path(__file__).with_name("property_data.json")
VINTAGES_PATH = Path(__file__).with_name("data_vintages.json")
TODAY = dt.date.today().isoformat()

SOURCES = {
    "cash_rate": "https://www.rba.gov.au/statistics/cash-rate/",
    "unemployment_rate": "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/latest-release",
    "labour_force_history": "https://www.rba.gov.au/statistics/tables/csv/h5-data.csv",
    "cpi": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release",
    "cpi_history": "https://www.rba.gov.au/statistics/tables/csv/g1-data.csv",
    "building_approvals_total_dwellings": "https://www.abs.gov.au/statistics/industry/building-and-construction/building-approvals-australia/latest-release",
    "housing_lending_rates": "https://www.rba.gov.au/statistics/tables/csv/f6-data.csv",
    "lending_indicators": "https://www.abs.gov.au/statistics/economy/finance/lending-indicators/latest-release",
    "wage_price_index": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia/latest-release",
    "average_weekly_earnings": "https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/average-weekly-earnings-australia/latest-release",
    "fred_dgs3": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3",
    "fred_dgs10": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    "housing_cpi_history": "https://www.rba.gov.au/statistics/tables/csv/g2-data.csv",
    "inflation_expectations": "https://www.rba.gov.au/statistics/tables/csv/g3-data.csv",
    "financial_aggregates_growth": "https://www.rba.gov.au/statistics/tables/csv/d1-data.csv",
    "corporate_bond_yields": "https://www.rba.gov.au/statistics/tables/csv/f3-data.csv",
    "exchange_rates": "https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv",
    "zero_coupon_yields": "https://www.rba.gov.au/statistics/tables/csv/f17-yields.csv",
    "gdp_income": "https://www.rba.gov.au/statistics/tables/csv/h1-data.csv",
    "demand_income": "https://www.rba.gov.au/statistics/tables/csv/h2-data.csv",
    "monthly_activity": "https://www.rba.gov.au/statistics/tables/csv/h3-data.csv",
    "labour_costs_productivity": "https://www.rba.gov.au/statistics/tables/csv/h4-data.csv",
    "commodity_prices": "https://www.rba.gov.au/statistics/tables/csv/i2-data.csv",
    "household_finances": "https://www.rba.gov.au/statistics/tables/csv/e2-data.csv",
    "housing_loan_payments": "https://www.rba.gov.au/statistics/tables/csv/e13-data.csv",
    "building_activity": "https://www.abs.gov.au/statistics/industry/building-and-construction/building-activity-australia/latest-release",
    "population": "https://www.abs.gov.au/statistics/people/population/national-state-and-territory-population/latest-release",
    "house_price_nominal": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=QAUN628BIS",
    "house_price_real": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=QAUR628BIS",
    "apra_property_exposures": "https://www.apra.gov.au/news-and-publications/quarterly-authorised-deposit-taking-institution-statistics",
    "total_value_dwellings": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/total-value-dwellings/latest-release",
    "regional_population": "https://www.abs.gov.au/statistics/people/population/regional-population/latest-release",
}

ABS_REGIONS = {
    "Australia": "National",
    "New South Wales": "Sydney",
    "Victoria": "Melbourne",
    "Queensland": "Brisbane",
    "Western Australia": "Perth",
}

XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

YAHOO_SERIES = {
    "asx_200": ("%5EAXJO", "S&P/ASX 200"),
    "sp_500": ("%5EGSPC", "S&P 500"),
    "msci_acwi": ("%5E892400-USD-STRD", "MSCI ACWI (USD, price return)"),
    "asx_200_real_estate": ("%5EAXRE", "S&P/ASX 200 Real Estate Index"),
    "asx_200_areit": ("%5EAXPJ", "S&P/ASX 200 A-REIT Index"),
}

MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def fetch(url, attempts=3, timeout=60):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; PropertyMacroTracker/1.0; "
                "+https://github.com/haoyileslie/property-macro-tracker)"
            ),
            "Accept": "text/csv,text/html,application/json,*/*;q=0.8",
        },
    )

    def fetch_once():
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                return response.read().decode("utf-8", errors="replace")

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"fetching {url} (attempt {attempt}/{attempts})", file=sys.stderr)
            return fetch_once()
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < attempts:
                delay = 2 ** (attempt - 1)
                print(f"fetch retry in {delay}s: {url}: {exc}", file=sys.stderr)
                time.sleep(delay)
    raise RuntimeError(f"fetch failed after {attempts} attempts: {url}: {last_error}") from last_error


def fetch_bytes(url, attempts=3, timeout=60):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; PropertyMacroTracker/1.0; "
                "+https://github.com/haoyileslie/property-macro-tracker)"
            ),
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8",
        },
    )
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"fetching {url} (attempt {attempt}/{attempts})", file=sys.stderr)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"fetch failed after {attempts} attempts: {url}: {last_error}") from last_error


def yahoo_monthly_close(symbol):
    period2 = int(time.time()) + 86400
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1=0&period2={period2}&interval=1mo&events=history"
    )
    payload = json.loads(fetch(url))
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0].get("close", [])
    points = []
    for timestamp, value in zip(timestamps, closes):
        if value is None:
            continue
        date = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m")
        points.append({"date": date, "value": round(float(value), 2)})
    return merge_points([], points)


def fred_month_end(markup, series_id):
    monthly = {}
    for row in csv.DictReader(io.StringIO(markup)):
        value = row.get(series_id)
        if not value or value == ".":
            continue
        monthly[row["observation_date"][:7]] = float(value)
    if not monthly:
        raise ValueError(f"No FRED observations parsed for {series_id}")
    return [{"date": date, "value": value} for date, value in sorted(monthly.items())]


def fred_quarterly(markup, series_id):
    points = []
    for row in csv.DictReader(io.StringIO(markup)):
        value = row.get(series_id)
        if not value or value == ".":
            continue
        date = dt.date.fromisoformat(row["observation_date"])
        points.append({"date": f"{date.year}-Q{(date.month - 1) // 3 + 1}", "value": round(float(value), 4)})
    if not points:
        raise ValueError(f"No FRED quarterly observations parsed for {series_id}")
    return points


def quarter_points(points):
    """Represent quarter-end RBA observations consistently as YYYY-Q#."""
    return [
        {
            "date": f"{point['date'][:4]}-Q{(int(point['date'][5:7]) - 1) // 3 + 1}",
            "value": point["value"],
        }
        for point in points
    ]


def excel_period(serial, frequency="quarterly"):
    date = dt.date(1899, 12, 30) + dt.timedelta(days=int(float(serial)))
    if frequency == "monthly":
        return date.strftime("%Y-%m")
    if frequency == "annual":
        return str(date.year)
    return f"{date.year}-Q{(date.month - 1) // 3 + 1}"


def excel_quarter(serial):
    return excel_period(serial, "quarterly")


def _xlsx_shared_strings(workbook):
    shared = []
    if "xl/sharedStrings.xml" in workbook.namelist():
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.findall(".//x:t", XLSX_NS))
            for item in root.findall("x:si", XLSX_NS)
        ]
    return shared


def _xlsx_sheet_path(workbook, sheet_name):
    if "xl/workbook.xml" not in workbook.namelist():
        return "xl/worksheets/sheet2.xml"
    root = ET.fromstring(workbook.read("xl/workbook.xml"))
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rel_id = None
    for sheet in root.findall(".//x:sheets/x:sheet", XLSX_NS):
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib.get(f"{{{rel_ns}}}id")
            break
    if not rel_id:
        raise ValueError(f"Worksheet {sheet_name!r} not found")
    rels = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    raise ValueError(f"Worksheet relationship for {sheet_name!r} not found")


def xlsx_sheet_rows(blob, sheet_name="Data1"):
    """Read a named XLSX worksheet using only the standard library."""
    with zipfile.ZipFile(io.BytesIO(blob)) as workbook:
        shared = _xlsx_shared_strings(workbook)
        root = ET.fromstring(workbook.read(_xlsx_sheet_path(workbook, sheet_name)))
        rows = {}
        for row in root.findall(".//x:sheetData/x:row", XLSX_NS):
            values = {}
            for cell in row.findall("x:c", XLSX_NS):
                column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
                node = cell.find("x:v", XLSX_NS)
                value = "" if node is None else node.text
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(item.text or "" for item in cell.findall(".//x:t", XLSX_NS))
                values[column] = value
            rows[int(row.attrib["r"])] = values
    return rows


def xlsx_rows(blob):
    """Backward-compatible reader for the ABS Data1 worksheet."""
    return xlsx_sheet_rows(blob, "Data1")


def parse_abs_xlsx_series(blob, series_ids, sheet_name="Data1", frequency="quarterly", scale=1):
    rows = xlsx_sheet_rows(blob, sheet_name)
    columns = {
        series_id: column
        for column, series_id in rows.get(10, {}).items()
        if series_id in series_ids
    }
    missing = set(series_ids) - set(columns)
    if missing:
        raise ValueError(f"ABS workbook is missing series IDs: {', '.join(sorted(missing))}")
    result = {series_id: [] for series_id in series_ids}
    for row_number in sorted(number for number in rows if number >= 11):
        row = rows[row_number]
        raw_date = row.get("A")
        if not raw_date:
            continue
        try:
            period = excel_period(raw_date, frequency)
        except (TypeError, ValueError, OverflowError):
            continue
        for series_id, column in columns.items():
            raw_value = row.get(column)
            if raw_value in (None, "", "na", "np"):
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            result[series_id].append({"date": period, "value": round(value * scale, 3)})
    return result


def discover_abs_workbook(release_markup, filename):
    match = re.search(rf'href="([^"]*/{re.escape(filename)})"', release_markup, flags=re.I)
    if not match:
        raise ValueError(f"ABS workbook {filename} not found on latest release page")
    path = html.unescape(match.group(1))
    return path if path.startswith("https://") else "https://www.abs.gov.au" + path


def discover_workbook_pattern(release_markup, filename_pattern, base_url="https://www.abs.gov.au"):
    match = re.search(r'href="([^"]*/(' + filename_pattern + r'))"', release_markup, flags=re.I)
    if not match:
        raise ValueError(f"Workbook matching {filename_pattern} not found")
    path = html.unescape(match.group(1))
    return path if path.startswith("https://") else base_url.rstrip("/") + "/" + path.lstrip("/")


def textify(markup):
    text = re.sub(r"<script[\s\S]*?</script>", " ", markup, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text)


def month_code(label):
    month, year = label.split("-")
    full_year = int(year)
    full_year += 2000 if full_year < 70 else 1900
    return f"{full_year}-{MONTHS[month]}"


def decision_date(label):
    day, month, year = label.split()
    return f"{year}-{MONTHS[month]}-{int(day):02d}"


def points_from_pairs(labels, values):
    return [{"date": month_code(label), "value": value} for label, value in zip(labels, values)]


def parse_rba_csv_series(markup, series_id, start=None):
    rows = list(csv.reader(io.StringIO(markup.lstrip("\ufeff"))))
    id_row = next((row for row in rows if row and row[0].strip() == "Series ID"), None)
    if not id_row or series_id not in id_row:
        raise ValueError(f"RBA series {series_id} not found")
    target_idx = id_row.index(series_id)
    points = []
    for row in rows:
        if not row or target_idx >= len(row):
            continue
        try:
            raw_date = row[0].strip()
            try:
                date_obj = dt.datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                date_obj = dt.datetime.strptime(raw_date, "%d-%b-%Y").date()
            value = float(row[target_idx].strip())
        except (ValueError, IndexError):
            continue
        if start is None or date_obj >= start:
            points.append({"date": date_obj.strftime("%Y-%m"), "value": value})
    if not points:
        raise ValueError(f"No observations parsed for RBA series {series_id}")
    return points


def monthly_last(points):
    """Collapse daily or duplicated monthly observations to the last value."""
    by_month = {}
    for point in points:
        by_month[point["date"]] = point
    return [by_month[date] for date in sorted(by_month)]


def parse_rba_cash_rate(markup):
    text = textify(markup)
    rows = re.findall(r"(\d{1,2} [A-Z][a-z]{2} (?:19|20)\d{2})\s+[+-]?\d+\.\d+\s+(\d+\.\d+)", text)
    points = [{"date": decision_date(date), "value": float(value)} for date, value in rows]
    points.sort(key=lambda point: point["date"])
    return points


def parse_abs_unemployment(markup):
    text = textify(markup)
    match = re.search(r"Unemployment rate\s+Trend\s+\(?%\)?\s*Seasonally adjusted\s+\(?%\)?", text)
    if not match:
        raise ValueError("ABS unemployment chart table not found")
    block = text[match.end():]
    block = block.split("Unemployment rate", 1)[0]
    rows = re.findall(r"([A-Z][a-z]{2}-\d{2})\s+(\d+\.\d)(?:\s+(\d+\.\d))?", block)
    points = []
    for label, trend, seasonally_adjusted in rows:
        points.append({"date": month_code(label), "value": float(seasonally_adjusted or trend)})
    return points[-36:]


def parse_abs_employed_people(markup):
    text = textify(markup)
    marker = "employment increased by"
    if marker not in text:
        raise ValueError("ABS employed people block not found")
    block = text.split(marker, 1)[1]
    block = block.split("Employment-to-population ratio", 1)[0]
    rows = re.findall(r"([A-Z][a-z]{2}-\d{2})\s+([\d,]+\.\d)(?:\s+([\d,]+\.\d))?", block)
    if not rows:
        raise ValueError("ABS employed people rows not found")
    points = []
    for label, trend, seasonally_adjusted in rows:
        value = seasonally_adjusted or trend
        points.append({"date": month_code(label), "value": float(value.replace(",", ""))})
    return points[-36:]


def parse_abs_cpi(markup):
    text = textify(markup)
    marker = "All groups CPI and Trimmed mean, Australia, annual movement (%)"
    if marker not in text:
        raise ValueError("ABS CPI annual-vs-trimmed table not found")
    block = text.split(marker, 1)[1]
    block = block.split("CPI Goods and Services components, annual movement (%)", 1)[0]
    rows = re.findall(r"([A-Z][a-z]{2}-\d{2})\s+(-?\d+\.\d|-?\d+)\s+(-?\d+\.\d|-?\d+)", block)
    if not rows:
        raise ValueError("ABS CPI annual-vs-trimmed rows not found")
    headline = []
    trimmed = []
    for label, cpi, trimmed_mean in rows:
        headline.append({"date": month_code(label), "value": float(cpi)})
        trimmed.append({"date": month_code(label), "value": float(trimmed_mean)})
    return headline[-36:], trimmed[-36:]


def parse_building_approvals(markup):
    text = textify(markup)
    block = text.split("Dwelling units approved", 1)[1]
    block = block.split("Dwelling units approved (a)", 1)[0]
    rows = re.findall(r"([A-Z][a-z]{2}-\d{2})\s+([\d,]+)\s+([\d,]+)", block)
    points = [{"date": month_code(label), "value": int(seasonal.replace(",", ""))} for label, seasonal, _trend in rows]
    return points


def parse_building_approvals_state_snapshot(markup):
    text = textify(markup)
    marker = "Dwellings approved, states and territories, seasonally adjusted"
    if marker not in text:
        raise ValueError("ABS state approvals section not found")
    block = text.split(marker, 1)[1]
    block = block.split("Dwellings approved, states and territories, trend", 1)[0]
    states = {
        "New South Wales": "Sydney",
        "Victoria": "Melbourne",
        "Queensland": "Brisbane",
        "Western Australia": "Perth",
        "Australia": "National",
    }
    out = {}
    for state_name, region in states.items():
        pattern = rf"{state_name}\s+(\d[\d,]*|na)\s+(-?\d+\.\d|na)\s+(\d[\d,]*|na)\s+(-?\d+\.\d|na)"
        matches = re.findall(pattern, block)
        if not matches:
            continue
        # "Australia" also occurs inside state names; the national row is last.
        match = matches[-1]
        total = match[2]
        if total.lower() == "na":
            continue
        out[region] = int(total.replace(",", ""))
    return out


def parse_rba_f6_owner_occ_variable(markup):
    series_id = "FLRHOOVA"
    reader = csv.reader(io.StringIO(markup))
    rows = list(reader)
    if not rows:
        raise ValueError("RBA F6 CSV is empty")
    id_row = None
    for row in rows:
        if row and row[0].strip() == "Series ID":
            id_row = row
            break
    if not id_row:
        raise ValueError("RBA F6 CSV Series ID row not found")
    try:
        target_idx = id_row.index(series_id)
    except ValueError as exc:
        raise ValueError(f"RBA F6 target series {series_id} not found") from exc

    points = []
    for row in rows:
        if not row:
            continue
        date_cell = row[0].strip()
        if not re.match(r"\d{2}/\d{2}/\d{4}$", date_cell):
            continue
        if target_idx >= len(row):
            continue
        val = row[target_idx].strip()
        if not val:
            continue
        date_obj = dt.datetime.strptime(date_cell, "%d/%m/%Y").date()
        points.append({"date": date_obj.strftime("%Y-%m"), "value": float(val)})
    if not points:
        raise ValueError("No observations parsed for RBA F6 target series")
    return points


def merge_cpi_history(history_markup, recent_headline, recent_trimmed):
    headline_history = parse_rba_csv_series(history_markup, "GCPIAGYP")
    trimmed_history = parse_rba_csv_series(history_markup, "GCPIOCPMTMYP")
    recent_start = recent_headline[0]["date"]
    headline = [point for point in headline_history if point["date"] < recent_start] + recent_headline
    trimmed = [point for point in trimmed_history if point["date"] < recent_start] + recent_trimmed
    return headline, trimmed


def parse_abs_lending_commitments(markup):
    text = textify(markup)
    def parse_graph(marker, next_marker, number_pattern, converter):
        candidates = text.split(marker)[1:]
        block = next(
            (part for part in candidates if re.search(r"[A-Z][a-z]{2}-\d{2}\s+(?:NA|" + number_pattern + r")", part)),
            "",
        ).split(next_marker, 1)[0]
        rows = re.findall(r"([A-Z][a-z]{2})-(\d{2})\s+(NA|" + number_pattern + r")", block)
        levels = []
        for month, year, value in rows:
            if value == "NA":
                continue
            full_year = 2000 + int(year)
            date = f"{full_year}-Q{(int(MONTHS[month]) - 1) // 3 + 1}"
            levels.append({"date": date, "value": converter(value)})
        return list({point["date"]: point for point in levels}.values())

    number = parse_graph(
        "Number of new loan commitments for dwellings (a), seasonally adjusted and trend, Australia",
        "Value of new loan commitments for dwellings",
        r"[\d,]+",
        lambda value: int(value.replace(",", "")),
    )
    value = parse_graph(
        "Value of new loan commitments for dwellings (a), seasonally adjusted and trend, Australia",
        "Value of new loan commitments for dwellings (a), seasonally adjusted and trend, Australia [",
        r"\d+\.\d+",
        lambda item: round(float(item), 3),
    )
    qoq = []
    for idx in range(1, len(number)):
        previous = number[idx - 1]["value"]
        current = number[idx]["value"]
        qoq.append({"date": number[idx]["date"], "value": round((current / previous - 1) * 100, 1)})
    if not number or not value or not qoq:
        raise ValueError("No ABS lending commitment history parsed")
    return number, value, qoq


def parse_abs_lending_shares(markup):
    """Parse first-home-buyer and investor shares from the ABS number table."""
    text = textify(markup)
    marker = "Number of new loan commitments for dwellings (a), seasonally adjusted and trend, Australia"
    candidates = text.split(marker)[1:]
    block = next(
        (
            part for part in candidates
            if re.search(r"[A-Z][a-z]{2}-\d{2}\s+[\d,]+\s+[\d,]+\s+[\d,]+\s+[\d,]+", part)
        ),
        "",
    ).split("Value of new loan commitments for dwellings", 1)[0]
    rows = re.findall(
        r"([A-Z][a-z]{2})-(\d{2})\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)",
        block,
    )
    fhb_share = []
    investor_share = []
    for month, year, total, owner, investor, first_home in rows:
        values = [int(item.replace(",", "")) for item in (total, owner, investor, first_home)]
        if values[0] <= 0 or values[1] <= 0:
            continue
        date = f"{2000 + int(year)}-Q{(int(MONTHS[month]) - 1) // 3 + 1}"
        investor_share.append({"date": date, "value": round(values[2] / values[0] * 100, 2)})
        fhb_share.append({"date": date, "value": round(values[3] / values[1] * 100, 2)})
    if not fhb_share or not investor_share:
        raise ValueError("No ABS lending borrower-share history parsed")
    return merge_points([], fhb_share), merge_points([], investor_share)


def _column_number(column):
    number = 0
    for character in column:
        number = number * 26 + ord(character) - 64
    return number


def _horizontal_ratio(rows, numerator_rows, denominator_rows, date_row=4):
    points = []
    date_columns = sorted(rows.get(date_row, {}), key=_column_number)
    for column in date_columns:
        raw_date = rows[date_row].get(column)
        if not raw_date or _column_number(column) < 3:
            continue
        try:
            numerator = sum(float(rows[row].get(column, 0) or 0) for row in numerator_rows)
            denominator = sum(float(rows[row].get(column, 0) or 0) for row in denominator_rows)
            if denominator <= 0:
                continue
            points.append({
                "date": excel_period(raw_date, "quarterly"),
                "value": round(numerator / denominator * 100, 3),
            })
        except (TypeError, ValueError, OverflowError):
            continue
    if not points:
        raise ValueError("No horizontal ratio observations parsed")
    return points


def parse_apra_property_risk_shares(blob):
    """Calculate four housing-credit risk shares from APRA's aggregate ADI tables."""
    new_loans = xlsx_sheet_rows(blob, "Tab 1c")
    exposures = xlsx_sheet_rows(blob, "Tab 1b")
    return {
        "new_housing_loans_high_dti_share": _horizontal_ratio(new_loans, [35], [9, 10]),
        "new_housing_loans_high_lvr_share": _horizontal_ratio(new_loans, [43, 44], [40, 41, 42, 43, 44]),
        "new_housing_loans_interest_only_share": _horizontal_ratio(new_loans, [25, 26], [9, 10]),
        "housing_mortgage_non_performing_share": _horizontal_ratio(exposures, [69], [16]),
    }


def sum_series_by_date(series_list):
    values = {}
    for points in series_list:
        for point in points:
            values.setdefault(point["date"], 0)
            values[point["date"]] += point["value"]
    return [
        {"date": date, "value": round(value, 3)}
        for date, value in sorted(values.items())
    ]


def parse_capital_city_population_growth(blob):
    rows = xlsx_sheet_rows(blob, "Table 4")
    columns = sorted(rows.get(5, {}), key=_column_number)
    labels = {
        "Sydney": "Greater Sydney",
        "Melbourne": "Greater Melbourne",
        "Brisbane": "Greater Brisbane",
        "Perth": "Greater Perth",
    }
    all_capitals = {
        "Greater Sydney", "Greater Melbourne", "Greater Brisbane", "Greater Adelaide",
        "Greater Perth", "Greater Hobart", "Greater Darwin", "Australian Capital Territory",
    }
    levels = {}
    for row in rows.values():
        label = row.get("D")
        if label not in all_capitals:
            continue
        levels[label] = [
            {"date": str(int(float(rows[5][column]))), "value": float(row[column])}
            for column in columns if rows[5].get(column) and row.get(column)
        ]
    national_levels = sum_series_by_date([levels[label] for label in all_capitals])

    def growth(points):
        return [
            {
                "date": points[index]["date"],
                "value": round((points[index]["value"] / points[index - 1]["value"] - 1) * 100, 3),
            }
            for index in range(1, len(points)) if points[index - 1]["value"]
        ]

    result = {"National": growth(national_levels)}
    result.update({region: growth(levels[label]) for region, label in labels.items()})
    return result


def parse_abs_wage_growth_by_sector(markup):
    text = textify(markup)
    marker = "Annual wage growth by sector, seasonally adjusted (a)"
    if marker not in text:
        raise ValueError("ABS annual wage growth by sector table not found")
    block = text.split(marker, 1)[1].split(marker, 1)[0]
    rows = re.findall(r"([A-Z][a-z]{2})-(\d{2})\s+(-?\d+\.\d)\s+(-?\d+\.\d)", block)
    private = []
    public = []
    for month, year, private_value, public_value in rows:
        date = f"{2000 + int(year)}-Q{(int(MONTHS[month]) - 1) // 3 + 1}"
        private.append({"date": date, "value": float(private_value)})
        public.append({"date": date, "value": float(public_value)})
    if not private:
        raise ValueError("No ABS wage-growth observations parsed")
    return private, public


def parse_abs_average_weekly_earnings_by_sector(markup):
    text = textify(markup)
    marker = "Average weekly ordinary time earnings, full-time adults by sector, original"
    if marker not in text:
        raise ValueError("ABS sector average weekly earnings table not found")
    candidates = text.split(marker)[1:]
    block = next(
        (part for part in candidates if re.search(r"[A-Z][a-z]{2}-\d{2}\s+[\d,]+\.\d+", part)),
        "",
    ).split(marker, 1)[0]
    rows = re.findall(
        r"([A-Z][a-z]{2})-(\d{2})\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)",
        block,
    )
    private = []
    public = []
    for month, year, private_value, public_value in rows:
        date = f"{2000 + int(year)}-{MONTHS[month]}"
        private.append({"date": date, "value": float(private_value.replace(",", ""))})
        public.append({"date": date, "value": float(public_value.replace(",", ""))})
    if not private:
        raise ValueError("No ABS sector average weekly earnings observations parsed")
    return private, public


def merge_points(existing, incoming):
    """Preserve deep history while replacing overlapping observations with current releases."""
    merged = {point["date"]: point for point in existing}
    merged.update({point["date"]: point for point in incoming})
    return [merged[date] for date in sorted(merged)]


def ensure_lending_level_series(data):
    definitions = {
        "lending_new_loan_commitments_dwellings_number": {
            "label": "New dwelling loan commitments (number)",
            "unit": "count",
            "definition": "Number of borrower-accepted new dwelling loan commitments, seasonally adjusted and excluding refinancing.",
            "usage": "Use it to track the volume of financed housing transactions without the direct effect of changing dwelling prices or average loan sizes.",
            "housing_market_link": "Rising commitments generally signal stronger funded buyer demand and can lead settlement and turnover activity.",
        },
        "lending_new_loan_commitments_dwellings_value": {
            "label": "New dwelling loan commitments (value)",
            "unit": " AUD bn",
            "definition": "Dollar value of borrower-accepted new dwelling loan commitments, seasonally adjusted and excluding refinancing.",
            "usage": "Use it to measure the flow of new housing credit, while recognising that it reflects both transaction volumes and average loan size.",
            "housing_market_link": "Credit-flow growth can support purchasing capacity and prices; divergence from commitment counts often reflects changing prices or borrower mix.",
        },
    }
    for key, metadata in definitions.items():
        data["series"].setdefault(key, {})
        series = data["series"][key]
        series.update(metadata)
        series.update({
            "frequency": "quarterly",
            "source": "ABS Lending Indicators",
            "source_url": SOURCES["lending_indicators"],
            "data": series.get("data", {"National": []}),
            "access_tier": "public",
        })


def ensure_external_macro_series(data):
    definitions = {
        "asx_200": ("S&P/ASX 200", "index points", "Australian large-cap equity-market conditions.", "Use it as a broad Australian risk-sentiment and listed-economy indicator.", "Equity strength can accompany improving confidence and wealth, but the index is not a direct housing-price measure."),
        "sp_500": ("S&P 500", "index points", "US large-cap equity-market conditions.", "Use it to track global risk appetite and US financial conditions.", "Large global market moves can affect Australian funding conditions, confidence and household portfolios."),
        "msci_acwi": ("MSCI ACWI (USD, price return)", "index points", "Global developed and emerging-market equity performance in US dollars.", "Use it as a broad global risk-appetite benchmark.", "Global risk cycles can influence capital flows, funding costs and Australian household wealth."),
        "asx_200_real_estate": ("S&P/ASX 200 Real Estate Index", "index points", "Price-return index for S&P/ASX 200 companies classified in the GICS real-estate sector.", "Use it to monitor listed-market expectations for Australian real-estate businesses.", "It is a liquid sentiment indicator, but includes commercial property and does not directly measure dwelling values."),
        "asx_200_areit": ("S&P/ASX 200 A-REIT Index", "index points", "Price-return index for listed vehicles classified as Australian real-estate investment trusts.", "Use it to track listed property valuations and sensitivity to bond yields and funding costs.", "A-REIT performance is mostly commercial-property exposure and should not be read as a residential-price index."),
        "us_treasury_3y": ("US Treasury 3-year yield", "%", "Month-end 3-year US Treasury constant-maturity yield.", "Use it to monitor medium-term US policy and growth expectations.", "US yields influence global funding costs and can flow through to Australian wholesale funding and mortgage pricing."),
        "us_treasury_10y": ("US Treasury 10-year yield", "%", "Month-end 10-year US Treasury constant-maturity yield.", "Use it as a global long-term discount-rate and inflation-expectations indicator.", "Higher global long yields can pressure bank funding, fixed mortgage rates and listed property valuations."),
        "wage_growth_private_yoy": ("Private-sector wage growth, year-on-year", "%", "Annual growth in private-sector hourly rates of pay excluding bonuses, seasonally adjusted.", "Use it to assess household purchasing-power growth and labour-cost pressure in the private economy.", "Income growth supports borrowing capacity and repayments, while persistent wage pressure can also keep interest rates higher."),
        "wage_growth_public_yoy": ("Public-sector wage growth, year-on-year", "%", "Annual growth in public-sector hourly rates of pay excluding bonuses, seasonally adjusted.", "Use it alongside private wages to identify sector differences in household income momentum.", "Public-sector wages support incomes in government-heavy regions and contribute to aggregate serviceability and demand."),
        "average_weekly_earnings_private": ("Private-sector average weekly ordinary earnings", "AUD per week", "Average weekly ordinary time earnings for private-sector full-time adults, persons, in current dollars and before tax; original series.", "Use it as a dollar-level earnings measure. Compare it with WPI because changes can also reflect shifts in workforce composition.", "Higher weekly earnings generally increase borrowing capacity and repayment resilience, although averages do not describe the income distribution."),
        "average_weekly_earnings_public": ("Public-sector average weekly ordinary earnings", "AUD per week", "Average weekly ordinary time earnings for public-sector full-time adults, persons, in current dollars and before tax; original series.", "Use it to compare the dollar level of public-sector earnings with private-sector earnings, allowing for different occupational composition.", "Public-sector earnings can support housing demand in government-employment centres, but this average is not a typical-household income measure."),
    }
    for key, (label, unit, definition, usage, housing_link) in definitions.items():
        series = data["series"].setdefault(key, {})
        series.update({
            "label": label,
            "unit": unit,
            "definition": definition,
            "usage": usage,
            "housing_market_link": housing_link,
            "frequency": (
                "quarterly" if key in {"wage_growth_private_yoy", "wage_growth_public_yoy"}
                else "six-monthly" if key in {"average_weekly_earnings_private", "average_weekly_earnings_public"}
                else "monthly"
            ),
            "data": series.get("data", {"National": []}),
            "access_tier": "public",
        })


def ensure_research_foundation_series(data):
    definitions = {
        "house_price_nominal_index": {
            "label": "Australian residential property prices (nominal)",
            "unit": "index (2010=100)",
            "frequency": "quarterly",
            "definition": "BIS selected nominal residential property price index for Australia, covering the longest available linked history.",
            "usage": "Use it as the primary long-run housing-cycle measure and as a target variable for national backtests.",
            "housing_market_link": "It measures the long-run level and cycle of Australian dwelling prices, but its historical coverage and property definitions change at documented break points.",
            "source_series_id": "QAUN628BIS",
            "release_lag_days": 90,
        },
        "house_price_real_index": {
            "label": "Australian residential property prices (real)",
            "unit": "index (2010=100)",
            "frequency": "quarterly",
            "definition": "BIS selected residential property price index for Australia deflated by consumer prices.",
            "usage": "Use it to distinguish real housing wealth cycles from movements that merely reflect general inflation.",
            "housing_market_link": "Sustained real price increases indicate housing values outpacing consumer prices and can signal valuation and affordability pressure.",
            "source_series_id": "QAUR628BIS",
            "release_lag_days": 90,
        },
        "household_debt_to_income": {
            "label": "Household debt to disposable income",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Total household debt as a percentage of annualised household disposable income.",
            "usage": "Use it as a stock measure of household leverage and sensitivity to income or interest-rate shocks.",
            "housing_market_link": "Higher leverage can amplify both housing upswings and the cash-flow effect of mortgage-rate increases.",
            "source_series_id": "BHFDDIT",
            "release_lag_days": 90,
        },
        "housing_debt_to_income": {
            "label": "Housing debt to disposable income",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Household housing debt as a percentage of annualised household disposable income.",
            "usage": "Use it to isolate mortgage-related leverage from other household borrowing.",
            "housing_market_link": "It captures the debt stock most directly connected to dwelling purchases and mortgage serviceability.",
            "source_series_id": "BHFDDIH",
            "release_lag_days": 90,
        },
        "owner_occupier_housing_debt_to_income": {
            "label": "Owner-occupier housing debt to disposable income",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Seasonally adjusted owner-occupier housing debt as a percentage of annualised household disposable income.",
            "usage": "Use it to track leverage associated with owner-occupied rather than investor housing debt.",
            "housing_market_link": "It indicates how exposed owner-occupier household balance sheets are to mortgage rates and income shocks.",
            "source_series_id": "BHFDDIO",
            "release_lag_days": 90,
        },
        "housing_interest_charged_to_income": {
            "label": "Housing interest charged to disposable income",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Interest charged on total housing loans relative to household disposable income.",
            "usage": "Use it as a direct interest-burden measure rather than relying only on mortgage rates or debt stocks.",
            "housing_market_link": "A rising ratio reduces household free cash flow and can weaken purchasing capacity and discretionary consumption.",
            "source_series_id": "LPHTICRI",
            "release_lag_days": 45,
        },
        "scheduled_housing_repayments_to_income": {
            "label": "Scheduled housing repayments to disposable income",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Scheduled principal and interest repayments on total housing loans relative to household disposable income.",
            "usage": "Use it as the closest aggregate public measure of required mortgage cash-flow pressure.",
            "housing_market_link": "Higher scheduled repayments constrain borrowing capacity and household spending more directly than an interest-only burden measure.",
            "source_series_id": "LPHTSPRI",
            "release_lag_days": 45,
        },
        "excess_housing_payments_to_income": {
            "label": "Excess housing payments to disposable income",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Housing-loan payments above scheduled repayments relative to household disposable income.",
            "usage": "Use it as an indicator of voluntary repayment buffers and household balance-sheet resilience.",
            "housing_market_link": "Falling excess payments may show households drawing down repayment buffers as required mortgage costs rise.",
            "source_series_id": "LPHTEXRI",
            "release_lag_days": 45,
        },
        "dwelling_commencements": {
            "label": "Dwelling commencements (Australia total; state proxies for cities)",
            "unit": "count",
            "frequency": "quarterly",
            "definition": "Seasonally adjusted dwelling units commenced across all building types and sectors; city labels display their corresponding state totals.",
            "usage": "Use it after approvals to measure projects that actually entered construction, while treating city tabs as state proxies.",
            "housing_market_link": "Commencements are a firmer future-supply signal than approvals but still precede completed, occupiable dwellings.",
            "release_lag_days": 120,
        },
        "dwelling_completions": {
            "label": "Dwelling completions (Australia total; state proxies for cities)",
            "unit": "count",
            "frequency": "quarterly",
            "definition": "Seasonally adjusted completed dwelling units across all building types and sectors; city labels display their corresponding state totals.",
            "usage": "Use it as the closest standard quarterly measure of newly delivered housing supply.",
            "housing_market_link": "Completions add usable housing stock and can relieve market pressure when they keep pace with household formation and population growth.",
            "release_lag_days": 120,
        },
        "estimated_resident_population": {
            "label": "Estimated resident population (Australia total; state proxies for cities)",
            "unit": "persons",
            "frequency": "quarterly",
            "definition": "ABS estimated resident population; city labels display the corresponding state population rather than capital-city population.",
            "usage": "Use state values with state supply measures and the national value with national supply measures.",
            "housing_market_link": "Population growth raises potential housing demand, though household formation, age structure and location determine the number and type of dwellings required.",
            "release_lag_days": 180,
        },
        "net_overseas_migration": {
            "label": "Net overseas migration (Australia total; state proxies for cities)",
            "unit": "persons",
            "frequency": "quarterly",
            "definition": "Quarterly net overseas migration; city labels display their corresponding state flows.",
            "usage": "Use it as a major cyclical driver of population growth, rental demand and initial household formation.",
            "housing_market_link": "Migration shocks can affect rental demand quickly and owner-occupier demand later, with impacts varying across states and dwelling types.",
            "release_lag_days": 180,
        },
    }
    for key, metadata in definitions.items():
        series = data["series"].setdefault(key, {})
        series.update(metadata)
        series.update({
            "data": series.get("data", {region: [] for region in data["meta"]["regions"]}),
            "access_tier": "public",
        })
        series.setdefault("methodology_note", "Latest revised history; use release-lag metadata in pseudo-real-time backtests.")


def ensure_housing_condition_series(data):
    definitions = {
        "new_housing_loans_high_dti_share": {
            "label": "New housing loans with debt-to-income ratio at or above 6x",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Share of new owner-occupier and investor housing lending with a debt-to-income ratio of at least six times.",
            "usage": "Use it to monitor the riskier tail of new borrower leverage rather than the average borrower.",
            "housing_market_link": "A rising high-DTI share can indicate stronger credit-fuelled purchasing capacity and greater sensitivity to income or rate shocks.",
            "release_lag_days": 90,
        },
        "new_housing_loans_high_lvr_share": {
            "label": "New housing loans with LVR at or above 90%",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Share of new housing term loans with a loan-to-valuation ratio of at least 90%, excluding loans whose LVR was not reported.",
            "usage": "Use it to track the share of new lending with a relatively small borrower equity buffer.",
            "housing_market_link": "High-LVR lending can support marginal buyer demand but leaves borrowers more exposed to price declines and refinancing constraints.",
            "release_lag_days": 90,
        },
        "housing_mortgage_non_performing_share": {
            "label": "Non-performing residential mortgage share",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Non-performing residential mortgage loans as a share of total residential mortgage credit outstanding at Australian ADIs.",
            "usage": "Use it as an aggregate realised mortgage-stress indicator, while recognising that arrears respond with a lag.",
            "housing_market_link": "Rising non-performance can foreshadow lender caution, distressed sales and weaker housing-credit transmission.",
            "release_lag_days": 90,
        },
        "new_housing_loans_interest_only_share": {
            "label": "Interest-only share of new housing lending",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Owner-occupier and investor interest-only new housing loans as a share of new owner-occupier and investor housing lending.",
            "usage": "Use it to monitor lending structures that initially defer principal repayment and are often more prevalent among investors.",
            "housing_market_link": "A higher share can boost near-term borrowing flexibility but may increase refinancing and repayment-reset risk.",
            "release_lag_days": 90,
        },
        "first_home_buyer_share": {
            "label": "First-home-buyer share of owner-occupier commitments",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "First-home-buyer owner-occupier loan commitments divided by all owner-occupier dwelling loan commitments, by number.",
            "usage": "Use it to assess the composition of financed owner-occupier demand rather than the total level of lending.",
            "housing_market_link": "Changes can reflect affordability, grants, deposit constraints and competition between first and repeat buyers.",
            "release_lag_days": 45,
        },
        "investor_lending_share": {
            "label": "Investor share of new dwelling commitments",
            "unit": "%",
            "frequency": "quarterly",
            "definition": "Investor dwelling loan commitments divided by total new dwelling loan commitments, by number.",
            "usage": "Use it to measure the investor composition of financed housing demand.",
            "housing_market_link": "Investor participation can affect apartment demand, rental supply and the sensitivity of market activity to tax and credit policy.",
            "release_lag_days": 45,
        },
        "capital_city_rent_index": {
            "label": "Consumer rent index by capital city",
            "unit": "index (Sep 2025=100)",
            "frequency": "monthly from July 2022",
            "definition": "ABS CPI rents index for the weighted average of eight capital cities and for Sydney, Melbourne, Brisbane and Perth.",
            "usage": "Use it to compare the direction and pace of advertised-and-existing tenancy rent inflation across capital cities.",
            "housing_market_link": "Rent growth is a direct signal of housing scarcity and affects investor yields, affordability and the rent-versus-buy decision.",
            "release_lag_days": 35,
        },
        "residential_property_transfers": {
            "label": "Residential property transfers by capital city",
            "unit": "count",
            "frequency": "quarterly",
            "definition": "Number of established-house and attached-dwelling transfers in each capital city; National is the sum of the eight published capital cities.",
            "usage": "Use it as a settled transaction-volume measure rather than an advertised-listing or finance-approval measure.",
            "housing_market_link": "Turnover tends to weaken when credit conditions tighten and strengthen as confidence and market liquidity recover.",
            "release_lag_days": 90,
        },
        "residential_dwelling_stock": {
            "label": "Estimated residential dwelling stock (Australia total; state proxies for cities)",
            "unit": "dwellings",
            "frequency": "quarterly",
            "definition": "ABS estimated number of residential dwellings; city-labelled views use NSW, Victoria, Queensland and Western Australia as state proxies.",
            "usage": "Use it as the denominator for supply, turnover and population-per-dwelling indicators, keeping the proxy geography explicit.",
            "housing_market_link": "The stock grows slowly, so demand shocks can produce large rent and price effects when additions lag household formation.",
            "release_lag_days": 90,
        },
        "capital_city_population_growth": {
            "label": "Capital-city population growth",
            "unit": "% y/y",
            "frequency": "annual",
            "definition": "Annual growth in estimated resident population for Greater Sydney, Melbourne, Brisbane and Perth; National combines all eight Greater Capital City Statistical Areas.",
            "usage": "Use it with capital-city rents, transfers and supply indicators to compare demand pressure across metropolitan markets.",
            "housing_market_link": "Population growth raises housing demand, but dwelling requirements also depend on household size, age structure and vacancy rates.",
            "release_lag_days": 240,
        },
    }
    for key, metadata in definitions.items():
        series = data["series"].setdefault(key, {})
        series.update(metadata)
        regional = key in {"capital_city_rent_index", "residential_property_transfers", "residential_dwelling_stock", "capital_city_population_growth"}
        default_data = {region: [] for region in data["meta"]["regions"]} if regional else {"National": []}
        series.update({"data": series.get("data", default_data), "access_tier": "public"})
        series.setdefault("methodology_note", "Latest revised public history; apply the stated release lag in pseudo-real-time tests.")


def ensure_rba_enhancement_series(data):
    """Create metadata shells without overwriting any stored observations."""
    for key, spec in RBA_ENHANCEMENT_SERIES.items():
        series = data["series"].setdefault(key, {})
        default_definition = (
            f"RBA analytical zero-coupon yield at the {key.split('_')[-1][:-1]}-year maturity, "
            "sampled at the last available observation each month."
            if key.startswith("au_zero_yield_")
            else spec["label"]
        )
        series.update({
            "label": spec["label"],
            "unit": spec["unit"],
            "definition": spec.get("definition", default_definition),
            "usage": spec.get(
                "usage",
                "Use as a public analytical yield-curve input for rate scenarios and synthetic bond-return diagnostics.",
            ),
            "housing_market_link": spec.get(
                "housing_market_link",
                "Long yields influence fixed mortgage pricing, discount rates and property relative valuation.",
            ),
            "frequency": spec["frequency"],
            "release_lag_days": spec["release_lag_days"],
            "data": series.get("data", {"National": []}),
            "access_tier": "public",
            "source_series_id": spec["series_id"],
            "source_table": spec["table"],
        })
        if key.startswith("au_zero_yield_"):
            series["methodology_note"] = (
                "RBA F17 analytical zero-coupon yield; useful for research and synthetic repricing, "
                "but not itself an investable bond-return series. The current public history begins in 2017."
            )
        elif key == "breakeven_inflation_10y":
            series["methodology_note"] = (
                "Breakeven inflation combines expected inflation with inflation-risk and liquidity premia; "
                "it must not be interpreted as a pure inflation forecast."
            )


def ensure_source_registry(data):
    registry = data["meta"].setdefault("source_registry", [])
    by_category = {item["category"]: item for item in registry}
    market = by_category.get("Market Activity")
    if market:
        market["primary_sources"] = [
            {"name": "Domain auction results and research", "url": "https://www.domain.com.au/auction-results/"},
            {"name": "realestate.com.au auction results", "url": "https://www.realestate.com.au/auction-results/"},
            {"name": "Ray White Economics and auction reports", "url": "https://www.raywhite.com/join-the-family/become-a-business-owner/economics"},
            {"name": "McGrath Research", "url": "https://www.mcgrath.com.au/research"},
            {"name": "PRD Research", "url": "https://www.prd.com.au/research-hub/"},
            {"name": "SQM Research stock on market", "url": "https://sqmresearch.com.au/property/stock-on-market"},
        ]
    price = by_category.get("Price")
    if price:
        price["primary_sources"] = [
            {"name": "PropTrack Home Price Index", "url": "https://www.proptrack.com.au/insights-hub/proptrack-home-price-index/"},
            {"name": "Domain Research", "url": "https://www.domain.com.au/research/"},
            {"name": "Ray White Property Outlook", "url": "https://www.raywhite.com/ray-white-property-outlook-report"},
            {"name": "McGrath Research", "url": "https://www.mcgrath.com.au/research"},
            {"name": "PRD Research Hub", "url": "https://www.prd.com.au/research-hub/"},
            {"name": "LJ Hooker property reports", "url": "https://www.ljhooker.com.au/ebooks"},
        ]
    rental = by_category.get("Rental Market")
    if rental:
        rental["primary_sources"] = [
            {"name": "SQM Research vacancy rates", "url": "https://sqmresearch.com.au/property/vacancy-rates"},
            {"name": "Domain Rent Report", "url": "https://www.domain.com.au/research/"},
            {"name": "Ray White Economics", "url": "https://www.raywhite.com/join-the-family/become-a-business-owner/economics"},
            {"name": "McGrath Research", "url": "https://www.mcgrath.com.au/research"},
            {"name": "PRD Research Hub", "url": "https://www.prd.com.au/research-hub/"},
            {"name": "LJ Hooker research reports", "url": "https://www.ljhooker.com.au/ebooks"},
        ]
    income = {
        "category": "Income And Affordability",
        "watch": "Mean and median household income, wages, disposable income, dwelling-price-to-income and repayment burdens",
        "primary_sources": [
            {"name": "ABS Household Income and Wealth", "url": "https://www.abs.gov.au/statistics/economy/finance/household-income-and-wealth-australia/latest-release"},
            {"name": "ABS Census income and work", "url": "https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/income-and-work-census/latest-release"},
            {"name": "ABS Wage Price Index", "url": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia/latest-release"},
            {"name": "ABS Average Weekly Earnings", "url": "https://www.abs.gov.au/statistics/labour/earnings-and-working-conditions/average-weekly-earnings-australia/latest-release"},
        ],
        "update_cadence": "Quarterly for wages; periodic survey and five-year Census for household income",
        "scope": "National and state where survey quality supports publication",
    }
    listed = {
        "category": "Listed Housing Exposure",
        "watch": "Total returns, valuation and earnings signals for residential developers, housing platforms, lenders and A-REITs",
        "primary_sources": [
            {"name": "ASX indices", "url": "https://www.asx.com.au/markets/trade-our-cash-market/overview/indices"},
            {"name": "ASX A-REIT overview", "url": "https://www.asx.com.au/investors/learn-about-our-investment-solutions/a-reits"},
            {"name": "ASX company announcements", "url": "https://www.asx.com.au/markets/trade-our-cash-market/announcements"},
        ],
        "update_cadence": "Daily prices; quarterly market-cap rebalance; reporting-cycle fundamentals",
        "scope": "Australian listed securities; separate residential-exposure basket recommended",
    }
    by_category["Income And Affordability"] = income
    by_category["Listed Housing Exposure"] = listed
    data["meta"]["source_registry"] = list(by_category.values())


def update_series(data, key, points, status, source_period=None, note=None, source_url=None, source_name=None):
    series = data["series"][key]
    series["data"]["National"] = points
    series["last_source_check"] = TODAY
    series["latest_source_period"] = source_period or points[-1]["date"]
    series["status"] = status
    series["history_start"] = points[0]["date"]
    series["observation_count"] = len(points)
    series["update_method"] = "automated"
    series["access_tier"] = series.get("access_tier", "public")
    if source_url:
        series["source_url"] = source_url
    if source_name:
        series["source"] = source_name
    if note:
      series["status_note"] = note


def update_regional_series(data, key, region_points, source_url, source_name, note):
    series = data["series"][key]
    series["data"] = {
        region: region_points.get(region, [])
        for region in data["meta"]["regions"]
    }
    national = series["data"]["National"]
    if not national:
        raise ValueError(f"No National observations parsed for {key}")
    series.update({
        "last_source_check": TODAY,
        "latest_source_period": national[-1]["date"],
        "status": "fresh",
        "history_start": min(points[0]["date"] for points in series["data"].values() if points),
        "observation_count": len(national),
        "observation_count_by_region": {region: len(points) for region, points in series["data"].items()},
        "update_method": "automated",
        "access_tier": "public",
        "source_url": source_url,
        "source": source_name,
        "status_note": note,
    })


def refresh_research_foundations(data):
    """Refresh long prices, household debt service, construction and population."""
    ensure_research_foundation_series(data)

    for key, source_key, series_id in [
        ("house_price_nominal_index", "house_price_nominal", "QAUN628BIS"),
        ("house_price_real_index", "house_price_real", "QAUR628BIS"),
    ]:
        points = fred_quarterly(fetch(SOURCES[source_key]), series_id)
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            "BIS selected series retrieved through FRED; linked history contains documented coverage and methodology breaks.",
            source_url=f"https://data.bis.org/topics/RPP/BIS%2CWS_SPP%2C1.0/Q.AU.{'N' if series_id == 'QAUN628BIS' else 'R'}.628",
            source_name="Bank for International Settlements (via FRED)",
        )
        data["series"][key]["data_provider"] = f"FRED {series_id}"
        data["series"][key]["methodology_note"] = (
            "Linked BIS history: state-capital median prices to 1986 Q2, detached houses in eight cities to 2003 Q2, "
            "all dwellings in eight cities to 2021 Q4, and national all-dwelling coverage thereafter. "
            "Do not interpret the joins as a single unchanged hedonic sample."
        )

    rba_payloads = {
        "household_finances": fetch(SOURCES["household_finances"]),
        "housing_loan_payments": fetch(SOURCES["housing_loan_payments"]),
    }
    rba_series = [
        ("household_debt_to_income", "household_finances", "BHFDDIT"),
        ("housing_debt_to_income", "household_finances", "BHFDDIH"),
        ("owner_occupier_housing_debt_to_income", "household_finances", "BHFDDIO"),
        ("housing_interest_charged_to_income", "housing_loan_payments", "LPHTICRI"),
        ("scheduled_housing_repayments_to_income", "housing_loan_payments", "LPHTSPRI"),
        ("excess_housing_payments_to_income", "housing_loan_payments", "LPHTEXRI"),
    ]
    for key, source_key, series_id in rba_series:
        points = quarter_points(parse_rba_csv_series(rba_payloads[source_key], series_id))
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            f"Public RBA series {series_id}; latest revised observation is {points[-1]['date']}.",
            source_url=SOURCES[source_key],
            source_name=("RBA Household Finances (E2)" if source_key == "household_finances" else "RBA Housing Loan Payments (E13)"),
        )
        data["series"][key]["source_table"] = "E2" if source_key == "household_finances" else "E13"

    building_page = fetch(SOURCES["building_activity"])
    building_specs = {
        "dwelling_commencements": {
            "national_file": "87520033.xlsx",
            "state_file": "87520034.xlsx",
            "ids": {
                "National": "A83801544L", "Sydney": "A83801520V", "Melbourne": "A83801576F",
                "Brisbane": "A83801528L", "Perth": "A83801560L",
            },
        },
        "dwelling_completions": {
            "national_file": "87520037.xlsx",
            "state_file": "87520038.xlsx",
            "ids": {
                "National": "A83801545R", "Sydney": "A83801521W", "Melbourne": "A83801577J",
                "Brisbane": "A83801529R", "Perth": "A83801561R",
            },
        },
    }
    for key, spec in building_specs.items():
        national_url = discover_abs_workbook(building_page, spec["national_file"])
        state_url = discover_abs_workbook(building_page, spec["state_file"])
        national = parse_abs_xlsx_series(fetch_bytes(national_url), {spec["ids"]["National"]})
        states = parse_abs_xlsx_series(fetch_bytes(state_url), set(spec["ids"].values()) - {spec["ids"]["National"]})
        region_points = {"National": national[spec["ids"]["National"]]}
        region_points.update({region: states[series_id] for region, series_id in spec["ids"].items() if region != "National"})
        update_regional_series(
            data, key, region_points, SOURCES["building_activity"], "ABS Building Activity, Australia",
            "National is Australia. Sydney, Melbourne, Brisbane and Perth labels are NSW, Victoria, Queensland and Western Australia state proxies.",
        )
        data["series"][key]["source_series_ids"] = spec["ids"]

    population_page = fetch(SOURCES["population"])
    population_specs = {
        "estimated_resident_population": {
            "file": "310104.xlsx",
            "ids": {
                "National": "A2060842F", "Sydney": "A2060843J", "Melbourne": "A2060844K",
                "Brisbane": "A2060845L", "Perth": "A2060847T",
            },
        },
        "net_overseas_migration": {
            "file": "310102.xlsx",
            "ids": {
                "National": "A2060785W", "Sydney": "A2060789F", "Melbourne": "A2060793W",
                "Brisbane": "A2060797F", "Perth": "A2060805V",
            },
        },
    }
    for key, spec in population_specs.items():
        workbook_url = discover_abs_workbook(population_page, spec["file"])
        parsed = parse_abs_xlsx_series(fetch_bytes(workbook_url), set(spec["ids"].values()))
        region_points = {region: parsed[series_id] for region, series_id in spec["ids"].items()}
        update_regional_series(
            data, key, region_points, SOURCES["population"], "ABS National, state and territory population",
            "National is Australia. Sydney, Melbourne, Brisbane and Perth labels are NSW, Victoria, Queensland and Western Australia state proxies.",
        )
        data["series"][key]["source_series_ids"] = spec["ids"]

    data["meta"]["last_updated"] = TODAY
    data["meta"]["research_foundations_note"] = (
        "Long-run prices, debt service, construction and population use latest revised public history. "
        "Publication lags and documented definition breaks must be enforced in backtests."
    )
    return data


def refresh_housing_conditions(data):
    """Refresh borrower composition, rental, turnover, stock and metro population series."""
    ensure_housing_condition_series(data)

    apra_release = fetch(SOURCES["apra_property_exposures"])
    apra_url = discover_workbook_pattern(
        apra_release,
        r"Quarterly%20authorised%20deposit-taking%20institution%20property%20exposures%20statistics%20[^\"]+\.xlsx",
        "https://www.apra.gov.au",
    )
    for key, points in parse_apra_property_risk_shares(fetch_bytes(apra_url)).items():
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            "Calculated from APRA aggregate ADI property-exposure tables; ratios may change when APRA revises history.",
            source_url=SOURCES["apra_property_exposures"],
            source_name="APRA Quarterly ADI Property Exposures",
        )
        data["series"][key]["source_workbook_url"] = apra_url

    lending_markup = fetch(SOURCES["lending_indicators"])
    fhb_share, investor_share = parse_abs_lending_shares(lending_markup)
    for key, points in [
        ("first_home_buyer_share", fhb_share),
        ("investor_lending_share", investor_share),
    ]:
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            "Calculated from the ABS seasonally adjusted number of new dwelling loan commitments.",
            source_url=SOURCES["lending_indicators"], source_name="ABS Lending Indicators",
        )

    cpi_release = fetch(SOURCES["cpi"])
    cpi_national_url = discover_abs_workbook(cpi_release, "640103.xlsx")
    cpi_city_url = discover_abs_workbook(cpi_release, "6401010.xlsx")
    national_rent = parse_abs_xlsx_series(
        fetch_bytes(cpi_national_url), {"A130390094A"}, frequency="monthly"
    )["A130390094A"]
    city_specs = {
        "Sydney": ("Data1", "A130392586J"),
        "Melbourne": ("Data1", "A130397627J"),
        "Brisbane": ("Data2", "A130398799W"),
        "Perth": ("Data3", "A130392593F"),
    }
    cpi_city_blob = fetch_bytes(cpi_city_url)
    rent_regions = {"National": national_rent}
    for region, (sheet, series_id) in city_specs.items():
        rent_regions[region] = parse_abs_xlsx_series(
            cpi_city_blob, {series_id}, sheet_name=sheet, frequency="monthly"
        )[series_id]
    update_regional_series(
        data, "capital_city_rent_index", rent_regions, SOURCES["cpi"],
        "ABS Consumer Price Index, Australia",
        "Official monthly rents indexes. The current monthly methodology begins in July 2022 and is referenced to September 2025=100.",
    )
    data["series"]["capital_city_rent_index"]["methodology_note"] = (
        "ABS introduced complete monthly CPI publication and a new rents data source from July 2022. "
        "This series deliberately avoids mechanically splicing differently referenced older quarterly indexes."
    )

    tvd_release = fetch(SOURCES["total_value_dwellings"])
    tvd1_url = discover_abs_workbook(tvd_release, "643201.xlsx")
    tvd2_url = discover_abs_workbook(tvd_release, "643202.xlsx")
    stock_ids = {
        "National": "A83728645A", "Sydney": "A83728605J", "Melbourne": "A83728610A",
        "Brisbane": "A83728615L", "Perth": "A83728625T",
    }
    stock_parsed = parse_abs_xlsx_series(fetch_bytes(tvd1_url), set(stock_ids.values()), scale=1000)
    stock_regions = {region: stock_parsed[series_id] for region, series_id in stock_ids.items()}
    update_regional_series(
        data, "residential_dwelling_stock", stock_regions, SOURCES["total_value_dwellings"],
        "ABS Total Value of Dwellings",
        "National is Australia; city labels are state proxies (NSW, Victoria, Queensland and Western Australia).",
    )

    transfer_ids = {
        "Sydney": ("A83728543L", "A83728544R"),
        "Melbourne": ("A83728547W", "A83728548X"),
        "Brisbane": ("A83728551L", "A83728552R"),
        "Adelaide": ("A83728555W", "A83728556X"),
        "Perth": ("A83728559F", "A83728560R"),
        "Hobart": ("A83728563W", "A83728564X"),
        "Darwin": ("A83728567F", "A83728568J"),
        "Canberra": ("A83728571W", "A83728572X"),
    }
    transfer_blob = fetch_bytes(tvd2_url)
    transfer_parsed = parse_abs_xlsx_series(
        transfer_blob, {series_id for pair in transfer_ids.values() for series_id in pair}
    )
    all_transfer_regions = {
        region: sum_series_by_date([transfer_parsed[first], transfer_parsed[second]])
        for region, (first, second) in transfer_ids.items()
    }
    transfer_regions = {
        "National": sum_series_by_date(list(all_transfer_regions.values())),
        **{region: all_transfer_regions[region] for region in ("Sydney", "Melbourne", "Brisbane", "Perth")},
    }
    update_regional_series(
        data, "residential_property_transfers", transfer_regions, SOURCES["total_value_dwellings"],
        "ABS Total Value of Dwellings",
        "Established-house plus attached-dwelling transfers. National is the sum of the eight published capital cities.",
    )

    population_release = fetch(SOURCES["regional_population"])
    population_url = discover_workbook_pattern(population_release, r"32180DS0003_\d{4}-\d{2}\.xlsx")
    population_growth = parse_capital_city_population_growth(fetch_bytes(population_url))
    update_regional_series(
        data, "capital_city_population_growth", population_growth, SOURCES["regional_population"],
        "ABS Regional Population",
        "Growth calculated from annual GCCSA estimated resident population. National combines the eight greater capital cities.",
    )

    data["meta"]["last_updated"] = TODAY
    data["meta"]["housing_conditions_note"] = (
        "Ten additional public series cover borrower risk composition, buyer composition, rents, "
        "transaction turnover, dwelling stock and capital-city population growth."
    )
    return data


def refresh_rba_enhancements(data):
    """Refresh the additional public macro/credit/curve series table by table."""
    ensure_rba_enhancement_series(data)
    payloads = {}
    for table in sorted({spec["table"] for spec in RBA_ENHANCEMENT_SERIES.values()}):
        payloads[table] = fetch(SOURCES[table])

    for key, spec in RBA_ENHANCEMENT_SERIES.items():
        points = parse_rba_csv_series(payloads[spec["table"]], spec["series_id"])
        if spec.get("monthly_last"):
            points = monthly_last(points)
        update_series(
            data,
            key,
            points,
            "fresh",
            points[-1]["date"],
            (
                f"Public RBA series {spec['series_id']}; latest published observation is "
                f"{points[-1]['date']} ({points[-1]['value']})."
            ),
            source_url=SOURCES[spec["table"]],
            source_name=RBA_SOURCE_NAMES[spec["table"]],
        )
        data["series"][key]["availability_basis"] = (
            "Pseudo-real-time metadata only: the latest revised historical series is used, "
            "with the stated publication lag enforced in forecasting applications."
        )

    data["meta"]["last_updated"] = TODAY
    data["meta"]["macro_enhancement_note"] = (
        "Additional public RBA time series were integrated for model enhancement and macro/property research. "
        "They use latest revised history plus explicit release-lag metadata; they are not a true vintage database."
    )
    return data


def refresh(data):
    ensure_lending_level_series(data)
    ensure_external_macro_series(data)
    ensure_research_foundation_series(data)
    ensure_housing_condition_series(data)
    ensure_source_registry(data)
    approvals_proxy = data["series"]["building_approvals_total_dwellings_state_proxy"]
    approvals_proxy["label"] = "Dwelling approvals (Australia total; state proxies for cities)"
    approvals_proxy["definition"] = (
        "Seasonally adjusted dwelling approvals: the National view is the Australia total, "
        "while Sydney, Melbourne, Brisbane and Perth display NSW, Victoria, Queensland and WA respectively."
    )
    approvals_proxy["usage"] = (
        "Use the National view for the aggregate construction pipeline and the city tabs for directional state comparisons; "
        "the city-labelled observations are not capital-city-only counts."
    )
    approvals_proxy["housing_market_link"] = (
        "Approvals lead potential new supply, but not every approval commences and state totals can differ materially from capital-city conditions."
    )
    lending_qoq = data["series"]["lending_new_loan_commitments_dwellings_qoq"]
    lending_qoq["definition"] = "Quarterly percentage change in the seasonally adjusted number of new dwelling loan commitments."
    lending_qoq["usage"] = "Use it as a short-run momentum measure for funded housing demand; refer to the level series to distinguish growth from scale."

    cash = parse_rba_cash_rate(fetch(SOURCES["cash_rate"]))
    update_series(
        data,
        "cash_rate",
        cash,
        "fresh",
        cash[-1]["date"],
        f"Latest parsed RBA cash rate target is {cash[-1]['value']}%.",
        source_url=SOURCES["cash_rate"],
        source_name="Reserve Bank of Australia",
    )

    labour_history = fetch(SOURCES["labour_force_history"])
    unemployment = parse_rba_csv_series(labour_history, "GLFSURSA")
    update_series(
        data,
        "unemployment_rate",
        unemployment,
        "fresh",
        unemployment[-1]["date"],
        f"Latest parsed ABS seasonally adjusted unemployment rate is {unemployment[-1]['value']}%.",
        source_url=SOURCES["labour_force_history"],
        source_name="ABS Labour Force, Australia",
    )

    employed_people = parse_rba_csv_series(labour_history, "GLFSEPTSA")
    update_series(
        data,
        "employed_people",
        employed_people,
        "fresh",
        employed_people[-1]["date"],
        f"Latest parsed ABS seasonally adjusted employed people is {employed_people[-1]['value']} ('000 persons).",
        source_url=SOURCES["labour_force_history"],
        source_name="ABS Labour Force, Australia",
    )

    recent_headline, recent_trimmed = parse_abs_cpi(fetch(SOURCES["cpi"]))
    headline, trimmed = merge_cpi_history(
        fetch(SOURCES["cpi_history"]), recent_headline, recent_trimmed
    )
    update_series(
        data,
        "cpi_headline_yoy",
        headline,
        "fresh",
        headline[-1]["date"],
        "Full available RBA G1 quarterly annual inflation history joined to the ABS complete monthly CPI publication at its first available recent observation.",
        source_url=SOURCES["cpi"],
        source_name="ABS Consumer Price Index, Australia",
    )
    update_series(
        data,
        "cpi_trimmed_mean_yoy",
        trimmed,
        "fresh",
        trimmed[-1]["date"],
        "Full available RBA G1 quarterly trimmed mean inflation history joined to the ABS complete monthly CPI publication at its first available recent observation.",
        source_url=SOURCES["cpi"],
        source_name="ABS Consumer Price Index, Australia",
    )
    for key in ("cpi_headline_yoy", "cpi_trimmed_mean_yoy"):
        data["series"][key]["frequency"] = "quarterly through 2025-03; monthly thereafter"
        data["series"][key]["history_source_url"] = SOURCES["cpi_history"]
        data["series"][key]["methodology_note"] = (
            "Quarterly RBA G1 history is joined to the ABS complete monthly CPI series. "
            "Treat the frequency transition as a documented series break when reading cycles."
        )

    approvals_markup = fetch(SOURCES["building_approvals_total_dwellings"])
    approvals = merge_points(
        data["series"]["building_approvals_total_dwellings"]["data"].get("National", []),
        parse_building_approvals(approvals_markup),
    )
    update_series(
        data,
        "building_approvals_total_dwellings",
        approvals,
        "fresh",
        approvals[-1]["date"],
        f"Latest parsed ABS seasonally adjusted dwelling approvals value is {approvals[-1]['value']}.",
        source_url=SOURCES["building_approvals_total_dwellings"],
        source_name="ABS Building Approvals, Australia",
    )

    state_snapshot = parse_building_approvals_state_snapshot(approvals_markup)
    state_series = data["series"]["building_approvals_total_dwellings_state_proxy"]
    latest_period = approvals[-1]["date"]
    for region, value in state_snapshot.items():
        region_points = state_series["data"].setdefault(region, [])
        if region_points and region_points[-1]["date"] == latest_period:
            region_points[-1]["value"] = value
        else:
            region_points.append({"date": latest_period, "value": value})
    state_series["last_source_check"] = TODAY
    state_series["latest_source_period"] = latest_period
    state_series["status"] = "fresh"
    state_series["history_start"] = min(
        points[0]["date"] for points in state_series["data"].values() if points
    )
    state_series["observation_count_by_region"] = {
        region: len(points) for region, points in state_series["data"].items()
    }
    state_series["update_method"] = "automated"
    state_series["access_tier"] = "public"
    state_series["source_url"] = SOURCES["building_approvals_total_dwellings"]
    state_series["source"] = "ABS Building Approvals, Australia"
    state_series["status_note"] = "National is the Australia total. City labels are state proxies: Sydney→NSW, Melbourne→VIC, Brisbane→QLD, Perth→WA."

    housing_lending = parse_rba_f6_owner_occ_variable(fetch(SOURCES["housing_lending_rates"]))
    update_series(
        data,
        "housing_lending_rate_owner_occupier_variable",
        housing_lending,
        "fresh",
        housing_lending[-1]["date"],
        f"Latest parsed RBA F6 owner-occupier outstanding variable housing lending rate (all institutions) is {housing_lending[-1]['value']}%.",
        source_url=SOURCES["housing_lending_rates"],
        source_name="RBA Housing Lending Rates (F6)",
    )

    lending_number, lending_value, lending_commitments = parse_abs_lending_commitments(
        fetch(SOURCES["lending_indicators"])
    )
    update_series(
        data,
        "lending_new_loan_commitments_dwellings_number",
        lending_number,
        "fresh",
        lending_number[-1]["date"],
        "ABS seasonally adjusted total number of borrower-accepted new dwelling loan commitments; excludes refinancing and the comparable total series begins in September quarter 2019.",
        source_url=SOURCES["lending_indicators"],
        source_name="ABS Lending Indicators",
    )
    update_series(
        data,
        "lending_new_loan_commitments_dwellings_value",
        lending_value,
        "fresh",
        lending_value[-1]["date"],
        "ABS seasonally adjusted dollar value of borrower-accepted new dwelling loan commitments; excludes refinancing.",
        source_url=SOURCES["lending_indicators"],
        source_name="ABS Lending Indicators",
    )
    update_series(
        data,
        "lending_new_loan_commitments_dwellings_qoq",
        lending_commitments,
        "fresh",
        lending_commitments[-1]["date"],
        "Quarter-on-quarter change calculated from the ABS seasonally adjusted total number of new dwelling loan commitments; comparable total series begins in September quarter 2019.",
        source_url=SOURCES["lending_indicators"],
        source_name="ABS Lending Indicators",
    )
    data["series"]["lending_new_loan_commitments_dwellings_qoq"].pop("snapshot_captured_at", None)

    for key, (symbol, label) in YAHOO_SERIES.items():
        points = yahoo_monthly_close(symbol)
        source_urls = {
            "asx_200": "https://www.asx.com.au/markets/trade-our-cash-market/overview/indices",
            "sp_500": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
            "msci_acwi": "https://www.msci.com/indexes/index/892400/msci-acwi-index",
            "asx_200_real_estate": "https://www.spglobal.com/spdji/en/indices/equity/sp-asx-200-real-estate-sector",
            "asx_200_areit": "https://www.spglobal.com/spdji/en/indices/equity/sp-asx-200-a-reit/",
        }
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            f"Monthly closing index level retrieved via Yahoo Finance; latest observation is {points[-1]['date']}.",
            source_url=source_urls[key], source_name=label,
        )
        data["series"][key]["data_provider"] = "Yahoo Finance chart endpoint"
        data["series"][key]["methodology_note"] = "Monthly close; price-return index unless otherwise stated. Values may be revised by the data provider."

    for key, source_key, fred_id in [
        ("us_treasury_3y", "fred_dgs3", "DGS3"),
        ("us_treasury_10y", "fred_dgs10", "DGS10"),
    ]:
        points = fred_month_end(fetch(SOURCES[source_key]), fred_id)
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            f"Last available daily FRED observation in each month; latest month-end value is {points[-1]['value']}%.",
            source_url=f"https://fred.stlouisfed.org/series/{fred_id}",
            source_name=f"Federal Reserve Bank of St. Louis (FRED {fred_id})",
        )

    private_wages, public_wages = parse_abs_wage_growth_by_sector(fetch(SOURCES["wage_price_index"]))
    for key, points, sector in [
        ("wage_growth_private_yoy", private_wages, "private"),
        ("wage_growth_public_yoy", public_wages, "public"),
    ]:
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            f"ABS annual {sector}-sector wage growth, seasonally adjusted; latest observation is {points[-1]['value']}%.",
            source_url=SOURCES["wage_price_index"], source_name="ABS Wage Price Index, Australia",
        )

    private_earnings, public_earnings = parse_abs_average_weekly_earnings_by_sector(
        fetch(SOURCES["average_weekly_earnings"])
    )
    for key, points, sector in [
        ("average_weekly_earnings_private", private_earnings, "private"),
        ("average_weekly_earnings_public", public_earnings, "public"),
    ]:
        update_series(
            data, key, points, "fresh", points[-1]["date"],
            f"ABS original full-time adult average weekly ordinary time earnings for the {sector} sector; latest value is ${points[-1]['value']:,.2f} per week.",
            source_url=SOURCES["average_weekly_earnings"],
            source_name="ABS Average Weekly Earnings, Australia",
        )
        data["series"][key]["methodology_note"] = (
            "Original six-monthly average. It is affected by workforce composition and is not directly comparable with the fixed-job Wage Price Index."
        )

    refresh_research_foundations(data)
    refresh_housing_conditions(data)
    refresh_rba_enhancements(data)
    data["derived_series"] = build_derived_series(data)
    data["meta"]["derived_series_version"] = DERIVATION_VERSION
    data["meta"]["last_updated"] = TODAY
    return data


def prepare_vintage(data):
    captured_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    refresh_id = captured_at.replace(":", "").replace("+00:00", "Z")
    archive = {"schema_version": 1, "refreshes": []}
    if VINTAGES_PATH.exists():
        archive = json.loads(VINTAGES_PATH.read_text())
    snapshot = {
        "refresh_id": refresh_id,
        "captured_at": captured_at,
        "data_as_of": data["meta"].get("last_updated"),
        "derived_series_version": data["meta"].get("derived_series_version"),
        "series": {
            key: {
                "label": series.get("label"),
                "source": series.get("source"),
                "source_url": series.get("source_url"),
                "latest_source_period": series.get("latest_source_period"),
                "data": series.get("data", {}),
            }
            for key, series in data["series"].items()
        },
    }
    archive.setdefault("refreshes", []).append(snapshot)
    archive["latest_refresh_id"] = refresh_id
    data["meta"]["last_refreshed_at"] = captured_at
    data["meta"]["latest_refresh_id"] = refresh_id
    data["meta"]["vintage_file"] = VINTAGES_PATH.name
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse, but do not write property_data.json")
    parser.add_argument(
        "--enhancements-only",
        action="store_true",
        help="Refresh only the additional public RBA macro, credit and yield-curve series",
    )
    parser.add_argument(
        "--foundations-only",
        action="store_true",
        help="Refresh only long prices, household debt service, construction and population",
    )
    parser.add_argument(
        "--housing-conditions-only",
        action="store_true",
        help="Refresh only the ten borrower, rent, turnover, stock and metro-population series",
    )
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text())
    if args.enhancements_only:
        refreshed = refresh_rba_enhancements(data)
        refreshed["derived_series"] = build_derived_series(refreshed)
        refreshed["meta"]["derived_series_version"] = DERIVATION_VERSION
    elif args.foundations_only:
        refreshed = refresh_research_foundations(data)
        refreshed["derived_series"] = build_derived_series(refreshed)
        refreshed["meta"]["derived_series_version"] = DERIVATION_VERSION
    elif args.housing_conditions_only:
        refreshed = refresh_housing_conditions(data)
        refreshed["derived_series"] = build_derived_series(refreshed)
        refreshed["meta"]["derived_series_version"] = DERIVATION_VERSION
    else:
        refreshed = refresh(data)

    if args.dry_run:
        validate_dataset(refreshed, require_refresh_metadata=False)
    else:
        archive = prepare_vintage(refreshed)
        validate_dataset(refreshed)
        validate_vintage_archive(archive, refreshed)

    if args.enhancements_only:
        summary_keys = list(RBA_ENHANCEMENT_SERIES)
    elif args.foundations_only:
        summary_keys = [
            "house_price_nominal_index",
            "house_price_real_index",
            "household_debt_to_income",
            "housing_debt_to_income",
            "owner_occupier_housing_debt_to_income",
            "housing_interest_charged_to_income",
            "scheduled_housing_repayments_to_income",
            "excess_housing_payments_to_income",
            "dwelling_commencements",
            "dwelling_completions",
            "estimated_resident_population",
            "net_overseas_migration",
        ]
    elif args.housing_conditions_only:
        summary_keys = [
            "new_housing_loans_high_dti_share",
            "new_housing_loans_high_lvr_share",
            "housing_mortgage_non_performing_share",
            "new_housing_loans_interest_only_share",
            "first_home_buyer_share",
            "investor_lending_share",
            "capital_city_rent_index",
            "residential_property_transfers",
            "residential_dwelling_stock",
            "capital_city_population_growth",
        ]
    else:
        summary_keys = [
            "cash_rate",
            "unemployment_rate",
            "employed_people",
            "cpi_headline_yoy",
            "cpi_trimmed_mean_yoy",
            "building_approvals_total_dwellings",
            "housing_lending_rate_owner_occupier_variable",
            "lending_new_loan_commitments_dwellings_number",
            "lending_new_loan_commitments_dwellings_value",
            "lending_new_loan_commitments_dwellings_qoq",
        ]
    summary = {
        key: refreshed["series"][key]["data"]["National"][-1]
        for key in summary_keys
    }
    print(json.dumps(summary, indent=2))

    if not args.dry_run:
        VINTAGES_PATH.write_text(json.dumps(archive, indent=2) + "\n")
        DATA_PATH.write_text(json.dumps(refreshed, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        sys.exit(1)
