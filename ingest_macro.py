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
from pathlib import Path

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
}

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


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "property-macro-tracker/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=context) as response:
            return response.read().decode("utf-8", errors="replace")


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
            date_obj = dt.datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
            value = float(row[target_idx].strip())
        except (ValueError, IndexError):
            continue
        if start is None or date_obj >= start:
            points.append({"date": date_obj.strftime("%Y-%m"), "value": value})
    if not points:
        raise ValueError(f"No observations parsed for RBA series {series_id}")
    return points


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
    marker = "CPI annual inflation fell, while Trimmed mean inflation rose"
    if marker not in text:
        raise ValueError("ABS CPI annual-vs-trimmed table not found")
    block = text.split(marker, 1)[1]
    block = block.split("Annual inflation for Goods", 1)[0]
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


def refresh(data):
    ensure_lending_level_series(data)
    ensure_external_macro_series(data)
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
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text())
    refreshed = refresh(data)

    if args.dry_run:
        validate_dataset(refreshed, require_refresh_metadata=False)
    else:
        archive = prepare_vintage(refreshed)
        validate_dataset(refreshed)
        validate_vintage_archive(archive, refreshed)

    summary = {
        key: refreshed["series"][key]["data"]["National"][-1]
        for key in [
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
