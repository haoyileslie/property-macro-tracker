#!/usr/bin/env python3
"""Build deterministic analytical series from the tracker's observed data."""

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).parent
DATA_PATH = ROOT / "property_data.json"
DERIVATION_VERSION = 1


def period_index(value):
    match = re.fullmatch(r"(\d{4})(?:-(Q[1-4]|\d{2})(?:-\d{2})?)?", value)
    if not match:
        raise ValueError(f"unsupported period: {value}")
    year = int(match.group(1))
    period = match.group(2)
    if not period:
        month = 12
    elif period.startswith("Q"):
        month = int(period[1]) * 3
    else:
        month = int(period)
    return year * 12 + month


def exact_binary(left, right, operation, digits=3):
    right_by_date = {point["date"]: point["value"] for point in right}
    return [
        {"date": point["date"], "value": round(operation(point["value"], right_by_date[point["date"]]), digits)}
        for point in left
        if point["date"] in right_by_date
    ]


def asof_binary(primary, secondary, operation, digits=3):
    secondary = sorted(secondary, key=lambda point: period_index(point["date"]))
    result = []
    secondary_index = 0
    latest_secondary = None
    for point in sorted(primary, key=lambda item: period_index(item["date"])):
        target = period_index(point["date"])
        while secondary_index < len(secondary) and period_index(secondary[secondary_index]["date"]) <= target:
            latest_secondary = secondary[secondary_index]
            secondary_index += 1
        if latest_secondary is not None:
            result.append({
                "date": point["date"],
                "value": round(operation(point["value"], latest_secondary["value"]), digits),
            })
    return result


def annual_growth(points, digits=2):
    values = {period_index(point["date"]): point["value"] for point in points}
    result = []
    for point in points:
        previous = values.get(period_index(point["date"]) - 12)
        if previous not in (None, 0):
            result.append({
                "date": point["date"],
                "value": round((point["value"] / previous - 1) * 100, digits),
            })
    return result


def relative_index(numerator, denominator, digits=2):
    ratios = exact_binary(numerator, denominator, lambda left, right: left / right, digits=12)
    if not ratios:
        return []
    base = ratios[0]["value"]
    return [
        {"date": point["date"], "value": round(point["value"] / base * 100, digits)}
        for point in ratios
    ]


def source_metadata(raw_series, component_keys):
    components = [raw_series[key] for key in component_keys]
    sources = []
    seen = set()
    for component in components:
        item = {"name": component["source"], "url": component["source_url"]}
        identity = (item["name"], item["url"])
        if identity not in seen:
            sources.append(item)
            seen.add(identity)
    checks = [component.get("last_source_check") for component in components if component.get("last_source_check")]
    statuses = {component.get("status") for component in components}
    return {
        "source": "Calculated from " + " and ".join(item["name"] for item in sources),
        "source_url": sources[0]["url"],
        "component_sources": sources,
        "last_source_check": min(checks) if checks else None,
        "status": "fresh" if statuses == {"fresh"} else "watch",
    }


def make_series(raw_series, *, label, unit, frequency, points, component_keys,
                calculation, definition, usage, housing_market_link, methodology_note):
    metadata = source_metadata(raw_series, component_keys)
    return {
        "label": label,
        "unit": unit,
        "frequency": frequency,
        "definition": definition,
        "usage": usage,
        "housing_market_link": housing_market_link,
        "source": metadata["source"],
        "source_url": metadata["source_url"],
        "component_sources": metadata["component_sources"],
        "component_series": component_keys,
        "calculation": calculation,
        "methodology_note": methodology_note,
        "derivation_version": DERIVATION_VERSION,
        "status": metadata["status"],
        "last_source_check": metadata["last_source_check"],
        "latest_source_period": points[-1]["date"],
        "history_start": points[0]["date"],
        "observation_count": len(points),
        "access_tier": "calculated from public inputs",
        "update_method": "automated derivation",
        "data": {"National": points},
    }


def build_derived_series(data):
    raw = data["series"]
    points = lambda key: raw[key]["data"]["National"]
    derived = {}

    derived["real_cash_rate_trimmed_mean"] = make_series(
        raw, label="Real cash rate (trimmed mean basis)", unit="percentage points", frequency="quarterly/monthly",
        points=asof_binary(points("cpi_trimmed_mean_yoy"), points("cash_rate"), lambda inflation, cash: cash - inflation),
        component_keys=["cash_rate", "cpi_trimmed_mean_yoy"],
        calculation="RBA cash rate target minus annual trimmed mean CPI inflation",
        definition="An ex-post real policy-rate proxy, expressed as the cash rate less underlying annual inflation.",
        usage="Read positive values as restrictive in real terms and negative values as accommodative, while allowing for the backward-looking inflation denominator.",
        housing_market_link="Higher real policy rates generally weaken borrowing capacity and housing demand; easing real rates can improve financing conditions.",
        methodology_note="The cash rate is carried to each CPI observation period. This is an analytical proxy, not an expected real rate.",
    )
    derived["real_mortgage_rate_headline"] = make_series(
        raw, label="Real variable mortgage rate", unit="percentage points", frequency="monthly",
        points=asof_binary(points("housing_lending_rate_owner_occupier_variable"), points("cpi_headline_yoy"), lambda rate, inflation: rate - inflation),
        component_keys=["housing_lending_rate_owner_occupier_variable", "cpi_headline_yoy"],
        calculation="Owner-occupier variable mortgage rate minus annual headline CPI inflation",
        definition="An ex-post real mortgage-rate proxy using the average outstanding owner-occupier variable lending rate.",
        usage="Use it to compare nominal mortgage pricing with realised inflation, not as a direct household cash-flow measure.",
        housing_market_link="A rising real mortgage rate increases the inflation-adjusted financing hurdle facing leveraged buyers and existing borrowers.",
        methodology_note="The latest CPI observation at or before each mortgage-rate month is used. Borrower-specific rates differ from this system average.",
    )
    derived["mortgage_cash_spread"] = make_series(
        raw, label="Variable mortgage rate spread to cash rate", unit="percentage points", frequency="monthly",
        points=asof_binary(points("housing_lending_rate_owner_occupier_variable"), points("cash_rate"), lambda mortgage, cash: mortgage - cash),
        component_keys=["housing_lending_rate_owner_occupier_variable", "cash_rate"],
        calculation="Owner-occupier variable mortgage rate minus RBA cash rate target",
        definition="The gap between the average outstanding variable owner-occupier mortgage rate and the policy cash rate.",
        usage="Track whether lender pricing is amplifying or cushioning changes in the policy rate.",
        housing_market_link="A wider spread tightens household financing conditions beyond the cash-rate setting; a narrower spread provides some offset.",
        methodology_note="The latest cash-rate setting in each mortgage-rate month is used.",
    )
    for sector in ("private", "public"):
        key = f"wage_growth_{sector}_yoy"
        derived[f"real_wage_growth_{sector}"] = make_series(
            raw, label=f"Real {sector}-sector wage growth", unit="percentage points", frequency="quarterly",
            points=asof_binary(points(key), points("cpi_headline_yoy"), lambda wages, inflation: wages - inflation),
            component_keys=[key, "cpi_headline_yoy"],
            calculation=f"Annual {sector}-sector Wage Price Index growth minus annual headline CPI inflation",
            definition=f"A purchasing-power proxy for {sector}-sector wages after headline consumer-price inflation.",
            usage="Use the sign and direction to assess whether wage growth is gaining or losing ground against consumer prices.",
            housing_market_link="Sustained positive real wage growth can improve deposit accumulation and mortgage serviceability; negative growth can constrain both.",
            methodology_note="The latest CPI observation at or before each wage quarter is used. This is a growth differential, not a household-income level.",
        )
    derived["us_yield_curve_10y_3y"] = make_series(
        raw, label="US Treasury 10-year minus 3-year spread", unit="percentage points", frequency="monthly",
        points=exact_binary(points("us_treasury_10y"), points("us_treasury_3y"), lambda ten, three: ten - three),
        component_keys=["us_treasury_10y", "us_treasury_3y"],
        calculation="US 10-year Treasury yield minus US 3-year Treasury yield",
        definition="A medium-to-long US yield-curve slope measure; negative readings indicate inversion between these maturities.",
        usage="Use it as a global growth and rate-cycle signal rather than a direct Australian mortgage-rate forecast.",
        housing_market_link="Global bond conditions influence Australian wholesale funding and longer-term discount rates, indirectly affecting lenders and property assets.",
        methodology_note="Calculated from matched monthly FRED observations.",
    )
    derived["average_new_dwelling_loan_value"] = make_series(
        raw, label="Implied average new dwelling loan commitment", unit="AUD", frequency="quarterly",
        points=exact_binary(points("lending_new_loan_commitments_dwellings_value"), points("lending_new_loan_commitments_dwellings_number"), lambda value_bn, number: value_bn * 1_000_000_000 / number, digits=0),
        component_keys=["lending_new_loan_commitments_dwellings_value", "lending_new_loan_commitments_dwellings_number"],
        calculation="Total value of new dwelling loan commitments divided by total number of commitments",
        definition="The implied average dollar value per new dwelling loan commitment in the ABS aggregate data.",
        usage="Use it to track changes in the typical financed amount, while remembering that shifts in borrower and dwelling mix also move the average.",
        housing_market_link="Rising average commitments may signal higher prices, larger deposits, stronger borrowing capacity, or a shift toward more expensive markets.",
        methodology_note="Aggregate value divided by aggregate count. It is not the ABS median loan size and excludes refinancing consistently with the inputs.",
    )
    derived["dwelling_approvals_yoy"] = make_series(
        raw, label="Dwelling approvals annual growth", unit="%", frequency="monthly",
        points=annual_growth(points("building_approvals_total_dwellings")),
        component_keys=["building_approvals_total_dwellings"],
        calculation="Percentage change in seasonally adjusted dwelling approvals from 12 months earlier",
        definition="The annual growth rate of total seasonally adjusted Australian dwelling approvals.",
        usage="Use it to identify acceleration or contraction in the prospective residential construction pipeline while looking through monthly volatility.",
        housing_market_link="Stronger approvals growth points to a potentially larger future supply pipeline, although approvals do not always translate into commencements or completions.",
        methodology_note="Calculated only where an observation exists exactly 12 months earlier.",
    )
    for source_key, output_key, label in [
        ("asx_200_real_estate", "asx_real_estate_relative", "ASX 200 Real Estate relative to ASX 200"),
        ("asx_200_areit", "asx_areit_relative", "ASX 200 A-REIT relative to ASX 200"),
    ]:
        derived[output_key] = make_series(
            raw, label=label, unit="index (start=100)", frequency="monthly",
            points=relative_index(points(source_key), points("asx_200")),
            component_keys=[source_key, "asx_200"],
            calculation=f"Ratio of {raw[source_key]['label']} to S&P/ASX 200, rebased to 100 at the first common month",
            definition="A relative-price index showing whether listed real-estate exposure has outperformed or underperformed the broad Australian equity market.",
            usage="Values above 100 indicate cumulative outperformance since the common start; focus on direction and cycles rather than the absolute level.",
            housing_market_link="Relative performance captures market expectations for property earnings, funding costs and valuations, but listed exposures are not a direct measure of dwelling prices.",
            methodology_note="Monthly price-index levels are divided and rebased. Dividends are excluded where the component series is a price-return index.",
        )
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--write", action="store_true", help="Write derived_series into the dataset")
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    derived = build_derived_series(data)
    if args.write:
        data["derived_series"] = derived
        data["meta"]["derived_series_version"] = DERIVATION_VERSION
        args.data.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({key: len(series["data"]["National"]) for key, series in derived.items()}, indent=2))


if __name__ == "__main__":
    main()
