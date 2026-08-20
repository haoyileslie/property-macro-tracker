#!/usr/bin/env python3
"""Run expanding-window pseudo-real-time backtests for the HFCI family."""

import argparse
import json
import math
from pathlib import Path

from derived_indicators import period_index


ROOT = Path(__file__).parent
DATA_PATH = ROOT / "property_data.json"
OUTPUT_PATH = ROOT / "hfci_backtest.json"
HFCI_KEYS = ("hfci_core", "hfci_augmented", "hfci_long_history", "hfci_full")
HORIZONS = (3, 6, 12)

TARGETS = {
    "house_price_growth": {
        "series": "house_price_nominal_index",
        "label": "Forward nominal house-price growth",
        "unit": "%",
        "transformation": "Forward percentage change in the national nominal house-price index",
        "mode": "pct_change",
    },
    "housing_credit_growth": {
        "series": "housing_credit_growth_yoy",
        "label": "Future housing-credit growth",
        "unit": "% y/y",
        "transformation": "Future level of annual housing-credit growth",
        "mode": "future_level",
    },
    "dwelling_approvals_growth": {
        "series": "building_approvals_total_dwellings",
        "label": "Forward dwelling-approvals growth",
        "unit": "%",
        "transformation": "Forward percentage change in seasonally adjusted dwelling approvals",
        "mode": "pct_change",
    },
    "new_lending_growth": {
        "series": "lending_new_loan_commitments_dwellings_value",
        "label": "Forward new-lending growth",
        "unit": "%",
        "transformation": "Forward percentage change in new dwelling loan-commitment value",
        "mode": "pct_change",
    },
    "housing_turnover_change": {
        "series": "housing_turnover_rate",
        "derived": True,
        "label": "Future change in housing-turnover proxy",
        "unit": "percentage points",
        "transformation": "Forward change in the capital-city housing-turnover-rate proxy",
        "mode": "change",
    },
}

MODELS = {
    "autoregressive": "Target state only",
    "cash_rate": "Target state + cash rate",
    "hfci": "Target state + HFCI",
    "cash_plus_hfci": "Target state + cash rate + HFCI",
}


def monthly_map(points):
    result = {}
    for point in points:
        result[period_index(point["date"])] = float(point["value"])
    return result


def asof_value(values, target):
    eligible = [index for index in values if index <= target]
    return values[max(eligible)] if eligible else None


def trailing_growth(values, index):
    previous = values.get(index - 12)
    current = values.get(index)
    if previous in (None, 0) or current is None:
        return None
    return (current / previous - 1) * 100


def build_rows(target_points, hfci_points, cash_points, horizon, mode):
    target = monthly_map(target_points)
    hfci = monthly_map(hfci_points)
    cash = monthly_map(cash_points)
    rows = []
    for index in sorted(target):
        future = target.get(index + horizon)
        current = target[index]
        if future is None:
            continue
        if mode == "pct_change":
            if current == 0:
                continue
            outcome = (future / current - 1) * 100
            state = trailing_growth(target, index)
        elif mode == "future_level":
            outcome = future
            state = current
        elif mode == "change":
            outcome = future - current
            state = current
        else:
            raise ValueError(f"unsupported target mode: {mode}")
        hfci_value = asof_value(hfci, index)
        cash_value = asof_value(cash, index)
        if None in (state, hfci_value, cash_value):
            continue
        rows.append({
            "date_index": index,
            "y": outcome,
            "state": state,
            "cash": cash_value,
            "hfci": hfci_value,
            "current_level": current,
        })
    return rows


def solve_linear(matrix, vector):
    size = len(vector)
    augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][item] - factor * augmented[column][item]
                for item in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def ols_coefficients(features, outcomes):
    columns = len(features[0]) + 1
    design = [[1.0] + list(row) for row in features]
    xtx = [[0.0] * columns for _ in range(columns)]
    xty = [0.0] * columns
    for row, outcome in zip(design, outcomes):
        for left in range(columns):
            xty[left] += row[left] * outcome
            for right in range(columns):
                xtx[left][right] += row[left] * row[right]
    for index in range(1, columns):
        xtx[index][index] += 1e-8
    return solve_linear(xtx, xty)


def feature_row(row, model):
    if model == "autoregressive":
        return [row["state"]]
    if model == "cash_rate":
        return [row["state"], row["cash"]]
    if model == "hfci":
        return [row["state"], row["hfci"]]
    if model == "cash_plus_hfci":
        return [row["state"], row["cash"], row["hfci"]]
    raise ValueError(model)


def expanding_predictions(rows, model, initial_train):
    predictions = []
    for test_index in range(initial_train, len(rows)):
        training = rows[:test_index]
        features = [feature_row(row, model) for row in training]
        outcomes = [row["y"] for row in training]
        coefficients = ols_coefficients(features, outcomes)
        if coefficients is None:
            continue
        test_features = [1.0] + feature_row(rows[test_index], model)
        prediction = sum(coefficient * value for coefficient, value in zip(coefficients, test_features))
        predictions.append((rows[test_index], prediction))
    return predictions


def sign(value):
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def metrics(predictions, mode):
    errors = [prediction - row["y"] for row, prediction in predictions]
    if not errors:
        return None
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mae = sum(abs(error) for error in errors) / len(errors)
    correct = 0
    for row, prediction in predictions:
        if mode == "future_level":
            actual_direction = sign(row["y"] - row["current_level"])
            predicted_direction = sign(prediction - row["current_level"])
        else:
            actual_direction = sign(row["y"])
            predicted_direction = sign(prediction)
        correct += actual_direction == predicted_direction
    return {
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "direction_accuracy": round(correct / len(errors) * 100, 1),
        "oos_observations": len(errors),
    }


def pearson(left, right):
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    if not left_scale or not right_scale:
        return None
    return numerator / (left_scale * right_scale)


def month_label(index):
    year, month_zero = divmod(index - 1, 12)
    return f"{year:04d}-{month_zero + 1:02d}"


def run_backtests(data):
    raw = data["series"]
    derived = data["derived_series"]
    cash_points = raw["cash_rate"]["data"]["National"]
    performance = []
    correlations = []
    for target_key, target_spec in TARGETS.items():
        source = derived if target_spec.get("derived") else raw
        target_points = source[target_spec["series"]]["data"]["National"]
        for hfci_key in HFCI_KEYS:
            hfci_points = derived[hfci_key]["data"]["National"]
            for horizon in HORIZONS:
                rows = build_rows(target_points, hfci_points, cash_points, horizon, target_spec["mode"])
                if len(rows) < 18:
                    continue
                initial_train = max(12, min(60, int(len(rows) * 0.6)))
                if len(rows) - initial_train < 6:
                    continue
                model_metrics = {}
                for model in MODELS:
                    result = metrics(expanding_predictions(rows, model, initial_train), target_spec["mode"])
                    if result:
                        model_metrics[model] = result
                if len(model_metrics) != len(MODELS):
                    continue
                benchmark_rmse = model_metrics["cash_rate"]["rmse"]
                for model, result in model_metrics.items():
                    result["rmse_improvement_vs_cash"] = round((benchmark_rmse - result["rmse"]) / benchmark_rmse * 100, 1) if benchmark_rmse else None
                    performance.append({
                        "target": target_key,
                        "hfci": hfci_key,
                        "horizon_months": horizon,
                        "model": model,
                        "sample_start": month_label(rows[0]["date_index"]),
                        "test_start": month_label(rows[initial_train]["date_index"]),
                        "sample_end": month_label(rows[-1]["date_index"]),
                        **result,
                    })
                correlation = pearson([row["hfci"] for row in rows], [row["y"] for row in rows])
                correlations.append({
                    "target": target_key,
                    "hfci": hfci_key,
                    "horizon_months": horizon,
                    "correlation": round(correlation, 3) if correlation is not None else None,
                    "observations": len(rows),
                    "sample_start": month_label(rows[0]["date_index"]),
                    "sample_end": month_label(rows[-1]["date_index"]),
                })

    pairwise = []
    for left_index, left_key in enumerate(HFCI_KEYS):
        left = monthly_map(derived[left_key]["data"]["National"])
        for right_key in HFCI_KEYS[left_index:]:
            right = monthly_map(derived[right_key]["data"]["National"])
            dates = sorted(set(left) & set(right))
            correlation = pearson([left[date] for date in dates], [right[date] for date in dates])
            pairwise.append({
                "left": left_key,
                "right": right_key,
                "correlation": round(correlation, 3) if correlation is not None else None,
                "observations": len(dates),
            })

    return {
        "meta": {
            "generated_at": data["meta"].get("last_refreshed_at") or data["meta"]["last_updated"],
            "data_as_of": data["meta"]["last_updated"],
            "method": "Expanding-window direct OLS forecasts using publication-lag-adjusted HFCIs and latest revised source histories",
            "initial_training_rule": "60% of aligned observations, bounded between 12 and 60 observations",
            "warning": "Pseudo-real-time, not a full vintage backtest: HFCI publication lags are respected, but most source histories are the latest revised vintages.",
        },
        "targets": TARGETS,
        "models": MODELS,
        "performance": performance,
        "lead_correlations": correlations,
        "hfci_pairwise_correlations": pairwise,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    result = run_backtests(data)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "performance_rows": len(result["performance"]),
        "correlation_rows": len(result["lead_correlations"]),
        "pairwise_rows": len(result["hfci_pairwise_correlations"]),
    }, indent=2))


if __name__ == "__main__":
    main()
