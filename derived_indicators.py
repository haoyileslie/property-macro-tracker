#!/usr/bin/env python3
"""Build deterministic analytical series from the tracker's observed data."""

import argparse
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).parent
DATA_PATH = ROOT / "property_data.json"
DERIVATION_VERSION = 3


HFCI_VARIABLES = [
    {
        "key": "real_cash_rate",
        "label": "Real cash rate",
        "block": "Pricing",
        "component_series": ["cash_rate", "cpi_trimmed_mean_yoy"],
        "transformation": "Cash rate minus annual trimmed mean inflation",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "new_mortgage_rate",
        "label": "New owner-occupier mortgage rate",
        "block": "Pricing",
        "component_series": ["housing_lending_rate_owner_occupier_new"],
        "transformation": "Average owner-occupier rate on new housing loans",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 6,
    },
    {
        "key": "real_new_mortgage_rate",
        "label": "Real new mortgage rate",
        "block": "Pricing",
        "component_series": ["housing_lending_rate_owner_occupier_new", "cpi_headline_yoy"],
        "transformation": "New owner-occupier mortgage rate minus headline inflation",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 6,
    },
    {
        "key": "mortgage_cash_spread",
        "label": "Mortgage spread to cash rate",
        "block": "Pricing",
        "component_series": ["housing_lending_rate_owner_occupier_new", "cash_rate"],
        "transformation": "New owner-occupier mortgage rate minus cash rate",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 6,
    },
    {
        "key": "au_five_year_yield",
        "label": "Australian five-year government yield",
        "block": "Market Pricing",
        "component_series": ["au_zero_yield_5y"],
        "transformation": "Five-year zero-coupon Australian government yield",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "bbb_cash_spread",
        "label": "BBB financing spread",
        "block": "Market Pricing",
        "component_series": ["corporate_bbb_yield_5y", "cash_rate"],
        "transformation": "Australian five-year BBB yield minus cash rate",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 12,
    },
    {
        "key": "areit_relative_return",
        "label": "A-REIT relative annual return",
        "block": "Market Pricing",
        "component_series": ["asx_200_areit", "asx_200"],
        "transformation": "Annual growth in the A-REIT-to-ASX 200 relative price index",
        "sign": -1,
        "release_lag_months": 1,
        "minimum_observations": 12,
    },
    {
        "key": "owner_occupier_credit_growth",
        "label": "Owner-occupier housing credit growth",
        "block": "Credit Availability",
        "component_series": ["owner_occupier_credit_growth_yoy"],
        "transformation": "Annual owner-occupier housing-credit growth",
        "sign": -1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "investor_credit_growth",
        "label": "Investor housing credit growth",
        "block": "Credit Availability",
        "component_series": ["investor_credit_growth_yoy"],
        "transformation": "Annual investor housing-credit growth",
        "sign": -1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "new_lending_growth",
        "label": "New dwelling lending growth",
        "block": "Credit Availability",
        "component_series": ["lending_new_loan_commitments_dwellings_value"],
        "transformation": "Annual growth in new dwelling loan-commitment value",
        "sign": -1,
        "release_lag_months": 2,
        "minimum_observations": 8,
    },
    {
        "key": "housing_credit_growth",
        "label": "Housing credit growth",
        "block": "Credit Availability",
        "component_series": ["housing_credit_growth_yoy"],
        "transformation": "Annual housing-credit growth",
        "sign": -1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "employment_growth",
        "label": "Employment growth",
        "block": "Household Capacity",
        "component_series": ["employment_growth_yoy"],
        "transformation": "Annual employment growth",
        "sign": -1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "real_total_wage_growth",
        "label": "Real total wage growth",
        "block": "Household Capacity",
        "component_series": ["wage_growth_total_yoy", "cpi_headline_yoy"],
        "transformation": "Total wage growth minus headline inflation",
        "sign": -1,
        "release_lag_months": 2,
        "minimum_observations": 12,
    },
    {
        "key": "high_dti_share",
        "label": "High-DTI lending share",
        "block": "Credit Availability",
        "component_series": ["new_housing_loans_high_dti_share"],
        "transformation": "Share of new housing loans with DTI at or above 6x",
        "sign": -1,
        "release_lag_months": 3,
        "minimum_observations": 12,
    },
    {
        "key": "high_lvr_share",
        "label": "High-LVR lending share",
        "block": "Credit Availability",
        "component_series": ["new_housing_loans_high_lvr_share"],
        "transformation": "Share of new housing loans with LVR at or above 90%",
        "sign": -1,
        "release_lag_months": 3,
        "minimum_observations": 12,
    },
    {
        "key": "interest_only_share",
        "label": "Interest-only lending share",
        "block": "Credit Availability",
        "component_series": ["new_housing_loans_interest_only_share"],
        "transformation": "Interest-only share of new housing lending",
        "sign": -1,
        "release_lag_months": 3,
        "minimum_observations": 12,
    },
    {
        "key": "mortgage_non_performing_share",
        "label": "Non-performing mortgage share",
        "block": "Credit Availability",
        "component_series": ["housing_mortgage_non_performing_share"],
        "transformation": "Non-performing residential mortgages as a share of credit outstanding",
        "sign": 1,
        "release_lag_months": 3,
        "minimum_observations": 12,
    },
    {
        "key": "scheduled_repayment_burden",
        "label": "Scheduled repayment burden",
        "block": "Household Capacity",
        "component_series": ["scheduled_housing_repayments_to_income"],
        "transformation": "Scheduled housing repayments relative to disposable income",
        "sign": 1,
        "release_lag_months": 2,
        "minimum_observations": 12,
    },
    {
        "key": "interest_burden",
        "label": "Housing interest burden",
        "block": "Household Capacity",
        "component_series": ["housing_interest_charged_to_income"],
        "transformation": "Housing interest charged relative to disposable income",
        "sign": 1,
        "release_lag_months": 2,
        "minimum_observations": 12,
    },
    {
        "key": "unemployment",
        "label": "Unemployment rate",
        "block": "Household Capacity",
        "component_series": ["unemployment_rate"],
        "transformation": "Seasonally adjusted unemployment-rate level",
        "sign": 1,
        "release_lag_months": 1,
        "minimum_observations": 24,
    },
    {
        "key": "real_private_wage_growth",
        "label": "Real private-sector wage growth",
        "block": "Household Capacity",
        "component_series": ["wage_growth_private_yoy", "cpi_headline_yoy"],
        "transformation": "Private-sector wage growth minus headline inflation",
        "sign": -1,
        "release_lag_months": 2,
        "minimum_observations": 12,
    },
]


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


def month_label(index):
    year, month_zero = divmod(index - 1, 12)
    return f"{year:04d}-{month_zero + 1:02d}"


def monthly_last(points):
    """Collapse daily, monthly or quarterly observations to their final value per month."""
    by_month = {}
    for point in points:
        by_month[period_index(point["date"])] = point["value"]
    return [
        {"date": month_label(index), "value": value}
        for index, value in sorted(by_month.items())
    ]


def expanding_zscore(points, *, sign=1, lag_months=0, minimum_observations=24, digits=6):
    """Standardise each observation using only history available at that observation."""
    points = monthly_last(points)
    history = []
    result = []
    for point in points:
        history.append(float(point["value"]))
        if len(history) < minimum_observations:
            continue
        mean = sum(history) / len(history)
        variance = sum((value - mean) ** 2 for value in history) / len(history)
        if variance <= 0:
            continue
        value = sign * (history[-1] - mean) / math.sqrt(variance)
        result.append({
            "date": month_label(period_index(point["date"]) + lag_months),
            "value": round(value, digits),
        })
    return result


def monthly_block_average(component_scores, *, end_period, digits=4):
    """Forward-fill scored components and average them only when all are available."""
    if not component_scores or any(not points for points in component_scores.values()):
        return []
    values = {
        key: {period_index(point["date"]): point["value"] for point in points}
        for key, points in component_scores.items()
    }
    start = max(min(series) for series in values.values())
    latest = {key: None for key in values}
    result = []
    for index in range(start, end_period + 1):
        for key, series in values.items():
            if index in series:
                latest[key] = series[index]
        if all(value is not None for value in latest.values()):
            result.append({
                "date": month_label(index),
                "value": round(sum(latest.values()) / len(latest), digits),
            })
    return result


def weighted_blocks(blocks, weights, *, end_period, digits=4):
    """Combine forward-filled block scores and retain exact weighted contributions."""
    if set(blocks) != set(weights) or any(not points for points in blocks.values()):
        return [], {}
    values = {
        key: {period_index(point["date"]): point["value"] for point in points}
        for key, points in blocks.items()
    }
    start = max(min(series) for series in values.values())
    latest = {key: None for key in values}
    index_points = []
    contributions = {key: [] for key in blocks}
    for index in range(start, end_period + 1):
        for key, series in values.items():
            if index in series:
                latest[key] = series[index]
        if not all(value is not None for value in latest.values()):
            continue
        date = month_label(index)
        weighted = {key: latest[key] * weights[key] for key in blocks}
        index_points.append({"date": date, "value": round(sum(weighted.values()), digits)})
        for key, value in weighted.items():
            contributions[key].append({"date": date, "value": round(value, digits)})
    return index_points, contributions


def expanding_percentile(points, digits=1):
    history = []
    result = []
    for point in points:
        history.append(point["value"])
        rank = sum(value <= point["value"] for value in history)
        result.append({"date": point["date"], "value": round(rank / len(history) * 100, digits)})
    return result


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


def annual_change(points, digits=2):
    values = {period_index(point["date"]): point["value"] for point in points}
    return [
        {"date": point["date"], "value": round(point["value"] - values[period_index(point["date"]) - 12], digits)}
        for point in points
        if period_index(point["date"]) - 12 in values
    ]


def rolling_four_quarter_sum(points, digits=2):
    ordered = sorted(points, key=lambda point: period_index(point["date"]))
    values = {period_index(point["date"]): point["value"] for point in ordered}
    result = []
    for point in ordered:
        index = period_index(point["date"])
        quarters = [values.get(index - offset) for offset in (0, 3, 6, 9)]
        if all(value is not None for value in quarters):
            result.append({"date": point["date"], "value": round(sum(quarters), digits)})
    return result


def rebased_index(points, digits=2):
    if not points:
        return []
    base = points[0]["value"]
    return [
        {"date": point["date"], "value": round(point["value"] / base * 100, digits)}
        for point in points if base
    ]


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


def make_hfci_series(raw_series, *, label, points, component_keys, variable_keys, contributions,
                     definition, usage, calculation):
    metadata = source_metadata(raw_series, component_keys)
    dictionary = [
        {
            "key": item["key"],
            "label": item["label"],
            "block": item["block"],
            "transformation": item["transformation"],
            "direction": "higher=tighter" if item["sign"] > 0 else "higher=easier; sign inverted",
            "release_lag_months": item["release_lag_months"],
            "minimum_observations": item["minimum_observations"],
        }
        for item in HFCI_VARIABLES if item["key"] in variable_keys
    ]
    return {
        "label": label,
        "unit": "index points (0=historical average)",
        "frequency": "monthly, publication-lag adjusted",
        "definition": definition,
        "usage": usage,
        "housing_market_link": (
            "Positive readings indicate tighter-than-history housing financial conditions; negative readings indicate easier conditions. "
            "Use turning points and block contributions rather than treating the level as a causal estimate."
        ),
        "source": metadata["source"],
        "source_url": metadata["source_url"],
        "component_sources": metadata["component_sources"],
        "component_series": component_keys,
        "calculation": calculation,
        "methodology_note": (
            "Each input is sign-aligned, shifted by its estimated publication lag and standardised using only its expanding history. "
            "Variables are equally weighted within blocks and blocks are equally weighted. Complete block composition is required; "
            "the index is a transparent research indicator, not an official measure or causal estimate."
        ),
        "variable_dictionary": dictionary,
        "block_contributions": contributions,
        "historical_percentile": expanding_percentile(points),
        "positive_direction": "tighter",
        "derivation_version": DERIVATION_VERSION,
        "status": metadata["status"],
        "last_source_check": metadata["last_source_check"],
        "latest_source_period": points[-1]["date"],
        "history_start": points[0]["date"],
        "observation_count": len(points),
        "access_tier": "calculated from public inputs",
        "update_method": "automated deterministic derivation",
        "data": {"National": points},
    }


def build_hfci_series(data, candidate_points):
    raw = data["series"]
    variable_specs = {item["key"]: item for item in HFCI_VARIABLES}
    variable_scores = {
        key: expanding_zscore(
            candidate_points[item["key"]],
            sign=item["sign"],
            lag_months=item["release_lag_months"],
            minimum_observations=item["minimum_observations"],
        )
        for key, item in variable_specs.items()
    }
    as_of = period_index(data["meta"]["last_updated"])
    specifications = {
        "hfci_core": {
            "label": "Core Housing Financial Conditions Index",
            "variables": ["real_cash_rate", "new_mortgage_rate", "real_new_mortgage_rate", "mortgage_cash_spread", "au_five_year_yield", "bbb_cash_spread", "areit_relative_return"],
            "definition": "A financial-price index combining real policy and mortgage rates, the mortgage spread, government and BBB yields, and listed real-estate relative performance.",
            "usage": "Use it as the comparatively pure financing-price benchmark, excluding credit quantities, employment and wages.",
            "calculation": "50% Pricing block and 50% Market Pricing block",
        },
        "hfci_augmented": {
            "label": "Augmented Housing Financial Conditions Index",
            "variables": ["real_cash_rate", "new_mortgage_rate", "real_new_mortgage_rate", "mortgage_cash_spread", "au_five_year_yield", "bbb_cash_spread", "areit_relative_return", "housing_credit_growth", "owner_occupier_credit_growth", "investor_credit_growth", "new_lending_growth", "employment_growth", "real_total_wage_growth"],
            "definition": "The Core HFCI augmented with realised credit growth, new lending, employment and real wage growth.",
            "usage": "Compare it with the Core HFCI to test whether quantities and household capacity add information, while recognising that these inputs may lag the housing cycle.",
            "calculation": "Equal weights on Pricing, Market Pricing, Credit Availability and Household Capacity blocks",
        },
        "hfci_long_history": {
            "label": "Long-history Housing Financial Conditions Index",
            "variables": ["real_cash_rate", "bbb_cash_spread", "areit_relative_return", "housing_credit_growth", "owner_occupier_credit_growth", "investor_credit_growth", "employment_growth", "real_total_wage_growth"],
            "definition": "A reduced specification using longer-running policy, credit, corporate-yield, listed-property, employment and wage histories.",
            "usage": "Use this version for longer-cycle backtests and robustness checks; compare results with the richer post-2019 indexes.",
            "calculation": "Equal weights on available Pricing, Market Pricing, Credit Availability and Household Capacity blocks",
        },
        "hfci_full": {
            "label": "Full Housing Financial Conditions Index",
            "variables": [item["key"] for item in HFCI_VARIABLES],
            "definition": "The broadest specification, adding detailed APRA credit composition, repayment burdens, unemployment and private real wages to the Augmented HFCI.",
            "usage": "Use it for current-condition monitoring and recent-cycle decomposition, not for long-horizon estimation because the common sample is short.",
            "calculation": "Equal weights on Pricing, Market Pricing, Credit Availability and Household Capacity blocks",
        },
    }

    result = {}
    for key, spec in specifications.items():
        selected_blocks = {}
        for block in dict.fromkeys(variable_specs[name]["block"] for name in spec["variables"]):
            selected_blocks[block] = monthly_block_average(
                {name: variable_scores[name] for name in spec["variables"] if variable_specs[name]["block"] == block},
                end_period=as_of,
            )
        weight = 1 / len(selected_blocks)
        points, contributions = weighted_blocks(
            selected_blocks,
            {block: weight for block in selected_blocks},
            end_period=as_of,
        )
        result[key] = make_hfci_series(
            raw,
            label=spec["label"],
            points=points,
            component_keys=sorted({component for name in spec["variables"] for component in variable_specs[name]["component_series"]}),
            variable_keys=set(spec["variables"]),
            contributions=contributions,
            definition=spec["definition"],
            usage=spec["usage"],
            calculation=spec["calculation"],
        )
    return result


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
    average_loan_points = derived["average_new_dwelling_loan_value"]["data"]["National"]
    derived["housing_turnover_rate"] = make_series(
        raw, label="Capital-city housing turnover rate proxy", unit="% of dwelling stock", frequency="quarterly",
        points=exact_binary(points("residential_property_transfers"), points("residential_dwelling_stock"), lambda transfers, stock: transfers / stock * 100),
        component_keys=["residential_property_transfers", "residential_dwelling_stock"],
        calculation="Residential property transfers divided by estimated residential dwelling stock, multiplied by 100",
        definition="Capital-city residential transfers expressed as a share of the Australia-wide dwelling stock during each quarter.",
        usage="Use it as a broad market-liquidity and transaction-intensity measure; compare the same quarter across years to allow for seasonality.",
        housing_market_link="Higher turnover generally accompanies stronger buyer-seller matching and market activity, while low turnover can signal affordability or financing constraints.",
        methodology_note="The numerator sums eight capital cities while the available denominator is Australia-wide dwelling stock, so the level understates a like-for-like capital-city turnover rate. It is not annualised and can include transfers that are not ordinary arm's-length sales.",
    )
    price_rent_ratio = asof_binary(
        points("capital_city_rent_index"),
        points("house_price_nominal_index"),
        lambda rent, price: price / rent,
        digits=8,
    )
    derived["price_to_rent_ratio_proxy"] = make_series(
        raw, label="House price-to-rent ratio proxy", unit="index (start=100)", frequency="monthly",
        points=rebased_index(price_rent_ratio),
        component_keys=["house_price_nominal_index", "capital_city_rent_index"],
        calculation="BIS nominal house-price index divided by the ABS capital-city rent index, rebased to 100 at the first common period",
        definition="A relative valuation proxy comparing national dwelling prices with capital-city rents.",
        usage="Use changes and turning points rather than the absolute level because the two source indexes have different bases and geographic coverage.",
        housing_market_link="A rising ratio means purchase prices are increasing faster than rents, often implying lower gross rental yield and greater valuation sensitivity to financing costs.",
        methodology_note="The latest quarterly house-price observation is carried to each monthly rent observation. This is an indexed proxy, not a dollar price-to-annual-rent multiple.",
    )
    derived["average_loan_to_income_proxy"] = make_series(
        raw, label="Average new loan-to-income proxy", unit="multiple of annual earnings", frequency="quarterly/semiannual",
        points=asof_binary(average_loan_points, points("average_weekly_earnings_private"), lambda loan, weekly: loan / (weekly * 52), digits=2),
        component_keys=["lending_new_loan_commitments_dwellings_value", "lending_new_loan_commitments_dwellings_number", "average_weekly_earnings_private"],
        calculation="Implied average new dwelling loan divided by 52 times private-sector average weekly ordinary-time earnings",
        definition="A borrowing-size proxy comparing the average new dwelling commitment with one annual private-sector wage.",
        usage="Track direction rather than interpreting it as a regulated borrower DTI: household loans may have multiple incomes and the earnings denominator is an economy-wide average.",
        housing_market_link="A rising multiple can indicate that financed dwelling purchases are stretching further relative to wage income.",
        methodology_note="The latest available semiannual earnings observation is carried to each lending quarter. This is not household disposable income and is not an individual loan-serviceability measure.",
    )
    quality_components = {
        key: expanding_zscore(points(key), sign=1, lag_months=3, minimum_observations=12)
        for key in (
            "new_housing_loans_high_dti_share",
            "new_housing_loans_high_lvr_share",
            "new_housing_loans_interest_only_share",
            "housing_mortgage_non_performing_share",
        )
    }
    quality_points = monthly_block_average(quality_components, end_period=period_index(data["meta"]["last_updated"]))
    derived["mortgage_credit_quality_risk_index"] = make_series(
        raw, label="Mortgage credit-quality risk index", unit="index points (0=historical average)", frequency="monthly, publication-lag adjusted",
        points=quality_points,
        component_keys=list(quality_components),
        calculation="Equal average of expanding z-scores for high-DTI, high-LVR, interest-only and non-performing mortgage shares",
        definition="A transparent composite of riskier new-lending composition and realised mortgage non-performance.",
        usage="Positive values indicate higher measured credit risk than the history available at that date; inspect the four components before drawing conclusions.",
        housing_market_link="Looser origination composition can support near-term demand but may increase later household and lender vulnerability, while non-performance is usually a lagging stress signal.",
        methodology_note="All inputs are sign-aligned so higher means riskier, shifted by an estimated three-month release lag and standardised using expanding history only.",
    )
    annual_completions = rolling_four_quarter_sum(points("dwelling_completions"))
    derived["dwelling_completions_per_1000_population"] = make_series(
        raw, label="Dwelling completions per 1,000 population", unit="dwellings per 1,000 people", frequency="quarterly, trailing year",
        points=asof_binary(annual_completions, points("estimated_resident_population"), lambda completions, population: completions / population * 1000),
        component_keys=["dwelling_completions", "estimated_resident_population"],
        calculation="Trailing four-quarter dwelling completions divided by estimated resident population, multiplied by 1,000",
        definition="The annual flow of completed dwellings scaled by population.",
        usage="Use it to compare supply delivery through time without allowing population size alone to dominate the count.",
        housing_market_link="Persistently low completions per capita can intensify housing scarcity when household formation and migration remain strong.",
        methodology_note="Population is matched as of each completion quarter. State/city extensions should retain the existing state-proxy labels.",
    )
    population_change = annual_change(points("estimated_resident_population"), digits=0)
    implied_household_demand = [
        {"date": point["date"], "value": round(point["value"] / 2.5, 0)}
        for point in population_change
    ]
    derived["estimated_housing_demand_gap"] = make_series(
        raw, label="Estimated housing demand less completions", unit="dwellings", frequency="quarterly, trailing year",
        points=exact_binary(implied_household_demand, annual_completions, lambda demand, completions: demand - completions, digits=0),
        component_keys=["estimated_resident_population", "dwelling_completions"],
        calculation="Annual population increase divided by an assumed 2.5 persons per dwelling, minus trailing four-quarter dwelling completions",
        definition="A simple demographic-demand-minus-new-supply gap expressed as an estimated number of dwellings.",
        usage="Treat it as a scenario indicator, not a forecast: household size, vacancies, demolitions and internal migration can materially change realised demand.",
        housing_market_link="A positive gap suggests population-implied household formation is running ahead of completions, which can add pressure to rents and prices if sustained.",
        methodology_note="Uses a fixed 2.5 persons-per-dwelling assumption for transparency. Future work should replace it with household-formation projections and account for demolitions and vacant stock.",
    )
    total_commitment_count = points("lending_new_loan_commitments_dwellings_number")
    investor_count = exact_binary(total_commitment_count, points("investor_lending_share"), lambda total, share: total * share / 100, digits=1)
    owner_occupier_count = exact_binary(total_commitment_count, points("investor_lending_share"), lambda total, share: total * (1 - share / 100), digits=1)
    first_home_buyer_count = exact_binary(owner_occupier_count, points("first_home_buyer_share"), lambda owner, share: owner * share / 100, digits=1)
    for segment_points, component_keys, output_key, label, segment_formula in [
        (
            first_home_buyer_count,
            ["lending_new_loan_commitments_dwellings_number", "investor_lending_share", "first_home_buyer_share"],
            "first_home_buyer_credit_impulse",
            "First-home-buyer commitment impulse proxy",
            "total commitment count times the estimated owner-occupier share times the first-home-buyer share",
        ),
        (
            investor_count,
            ["lending_new_loan_commitments_dwellings_number", "investor_lending_share"],
            "investor_credit_impulse",
            "Investor commitment impulse proxy",
            "total commitment count times the investor share",
        ),
    ]:
        impulse_points = annual_change(annual_growth(segment_points), digits=2)
        derived[output_key] = make_series(
            raw, label=label, unit="percentage points", frequency="quarterly",
            points=impulse_points,
            component_keys=component_keys,
            calculation=f"Annual growth in imputed segment commitment count ({segment_formula}) minus its annual growth rate four quarters earlier",
            definition="A commitment-acceleration proxy for the selected borrower segment; positive values mean annual loan-count growth is accelerating.",
            usage="Use it to identify changes in segment momentum, not the level of credit supplied or a structural estimate of demand.",
            housing_market_link="A positive impulse can precede stronger buyer competition from that segment, while a negative impulse indicates fading lending momentum.",
            methodology_note="Segment counts are imputed from aggregate commitment counts and published count shares. The impulse is the annual change in the segment's year-on-year growth rate, not a dollar credit-flow measure.",
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
    hfci_candidates = {
        "real_cash_rate": derived["real_cash_rate_trimmed_mean"]["data"]["National"],
        "new_mortgage_rate": points("housing_lending_rate_owner_occupier_new"),
        "real_new_mortgage_rate": asof_binary(points("housing_lending_rate_owner_occupier_new"), points("cpi_headline_yoy"), lambda rate, inflation: rate - inflation),
        "mortgage_cash_spread": asof_binary(points("housing_lending_rate_owner_occupier_new"), points("cash_rate"), lambda rate, cash: rate - cash),
        "au_five_year_yield": points("au_zero_yield_5y"),
        "bbb_cash_spread": asof_binary(points("corporate_bbb_yield_5y"), points("cash_rate"), lambda bbb, cash: bbb - cash),
        "areit_relative_return": annual_growth(derived["asx_areit_relative"]["data"]["National"]),
        "housing_credit_growth": points("housing_credit_growth_yoy"),
        "owner_occupier_credit_growth": points("owner_occupier_credit_growth_yoy"),
        "investor_credit_growth": points("investor_credit_growth_yoy"),
        "new_lending_growth": annual_growth(points("lending_new_loan_commitments_dwellings_value")),
        "high_dti_share": points("new_housing_loans_high_dti_share"),
        "high_lvr_share": points("new_housing_loans_high_lvr_share"),
        "interest_only_share": points("new_housing_loans_interest_only_share"),
        "mortgage_non_performing_share": points("housing_mortgage_non_performing_share"),
        "scheduled_repayment_burden": points("scheduled_housing_repayments_to_income"),
        "interest_burden": points("housing_interest_charged_to_income"),
        "unemployment": points("unemployment_rate"),
        "employment_growth": points("employment_growth_yoy"),
        "real_total_wage_growth": asof_binary(points("wage_growth_total_yoy"), points("cpi_headline_yoy"), lambda wages, inflation: wages - inflation),
        "real_private_wage_growth": derived["real_wage_growth_private"]["data"]["National"],
    }
    derived.update(build_hfci_series(data, hfci_candidates))
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
