#!/usr/bin/env python3
"""Generate the reproducible HFCI methodology report and comparison chart."""

import json
import math
import statistics
from pathlib import Path

from derived_indicators import HFCI_VARIABLES, build_derived_series, build_hfci_candidates


ROOT = Path(__file__).parent
HFCI_KEYS = ("hfci_core", "hfci_augmented", "hfci_long_history", "hfci_full")


def quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(points):
    values = [float(point["value"]) for point in points]
    return {
        "start": points[0]["date"], "end": points[-1]["date"], "n": len(values),
        "min": min(values), "q1": quantile(values, .25), "median": statistics.median(values),
        "mean": statistics.mean(values), "q3": quantile(values, .75), "max": max(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0,
    }


def fmt(value):
    return f"{value:,.2f}"


def source_links(spec, raw):
    links = []
    for key in spec["component_series"]:
        series = raw.get(key)
        if not series:
            continue
        label = series.get("source", key)
        url = series.get("source_url")
        entry = f"[{label}]({url})" if url else label
        if entry not in links:
            links.append(entry)
    return " + ".join(links) or "Derived input"


def svg_chart(series_map, output):
    width, height = 1100, 520
    pad = {"l": 72, "r": 28, "t": 34, "b": 58}
    all_points = [point for key in HFCI_KEYS for point in series_map[key]["data"]["National"]]
    dates = sorted({point["date"] for point in all_points})
    date_pos = {date: index for index, date in enumerate(dates)}
    values = [float(point["value"]) for point in all_points]
    low, high = min(values), max(values)
    spread = high - low or 1
    low -= spread * .08
    high += spread * .08
    x = lambda date: pad["l"] + date_pos[date] / max(1, len(dates) - 1) * (width - pad["l"] - pad["r"])
    y = lambda value: pad["t"] + (high - value) / (high - low) * (height - pad["t"] - pad["b"])
    colors = {"hfci_core": "#1F3A6E", "hfci_augmented": "#C08A3E", "hfci_long_history": "#437A68", "hfci_full": "#9A4F4F"}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Comparison of four Housing Financial Conditions Index variants">', '<rect width="100%" height="100%" fill="#fff"/>']
    for tick in range(math.floor(low), math.ceil(high) + 1):
        yy = y(tick)
        parts.append(f'<line x1="{pad["l"]}" y1="{yy:.1f}" x2="{width-pad["r"]}" y2="{yy:.1f}" stroke="#E6E2D8"/>')
        parts.append(f'<text x="{pad["l"]-12}" y="{yy+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12" fill="#5C6773">{tick}</text>')
    parts.append(f'<line x1="{pad["l"]}" y1="{y(0):.1f}" x2="{width-pad["r"]}" y2="{y(0):.1f}" stroke="#7E8790"/>')
    for index, key in enumerate(HFCI_KEYS):
        points = series_map[key]["data"]["National"]
        path = " ".join(("M" if i == 0 else "L") + f"{x(point['date']):.1f},{y(float(point['value'])):.1f}" for i, point in enumerate(points))
        parts.append(f'<path d="{path}" fill="none" stroke="{colors[key]}" stroke-width="2.5"/>')
        parts.append(f'<line x1="{pad["l"] + index*245}" y1="{height-20}" x2="{pad["l"]+28 + index*245}" y2="{height-20}" stroke="{colors[key]}" stroke-width="3"/>')
        parts.append(f'<text x="{pad["l"]+36 + index*245}" y="{height-16}" font-family="sans-serif" font-size="13" fill="#1B1F26">{series_map[key]["label"].replace(" Housing Financial Conditions Index", "")}</text>')
    parts.append('</svg>')
    output.parent.mkdir(exist_ok=True)
    output.write_text("\n".join(parts) + "\n")


def generate(data, backtest):
    raw = data["series"]
    derived = build_derived_series(data)
    candidates = build_hfci_candidates(data, derived)
    specs = {item["key"]: item for item in HFCI_VARIABLES}
    variable_rows = []
    for key, points in candidates.items():
        if not points:
            continue
        spec, stats = specs[key], describe(points)
        variable_rows.append(
            f'| {spec["block"]} | {spec["label"]} | {stats["start"]}–{stats["end"]} | {stats["n"]} | {fmt(stats["min"])} | {fmt(stats["q1"])} | {fmt(stats["median"])} | {fmt(stats["mean"])} | {fmt(stats["q3"])} | {fmt(stats["max"])} | {fmt(stats["sd"])} | {spec["release_lag_months"]} | {source_links(spec, raw)} |'
        )
    index_rows = []
    for key in HFCI_KEYS:
        series, stats = derived[key], describe(derived[key]["data"]["National"])
        percentile = series["historical_percentile"][-1]["value"]
        index_rows.append(f'| {series["label"]} | {stats["start"]}–{stats["end"]} | {stats["n"]} | {fmt(stats["min"])} | {fmt(stats["median"])} | {fmt(stats["mean"])} | {fmt(stats["max"])} | {fmt(stats["sd"])} | {fmt(percentile)} |')
    best_rows = []
    for target, spec in backtest["targets"].items():
        candidates_perf = [row for row in backtest["performance"] if row["target"] == target and row["model"] == "cash_plus_hfci"]
        if not candidates_perf:
            continue
        best = max(candidates_perf, key=lambda row: row["rmse_improvement_vs_cash"])
        best_rows.append(f'| {spec["label"]} | {best["horizon_months"]} | {derived[best["hfci"]]["label"]} | {best["oos_observations"]} | {best["rmse_improvement_vs_cash"]:.1f}% | {best["direction_accuracy"]:.1f}% |')

    report = rf"""# 住房金融条件指数（HFCI）：构建方法与回测报告

_数据截至 {data['meta']['last_updated']}。本报告由 `property_data.json` 可复现生成。_

## 1. 构建目的

住房金融条件指数（Housing Financial Conditions Index, HFCI）用少量、透明的月度指标概括澳大利亚住房融资的价格、信贷可得性和家庭偿付能力。其用途是识别周期转折、比较不同阶段，并检验金融条件是否包含对未来住房活动有用的信息。它不是官方统计、估值模型或因果估计。

正值表示相对于当时可获得历史而言金融条件偏紧，负值表示偏松。四个版本在近期信息丰富度和长期覆盖之间作出不同取舍：

| 版本 | 主要用途 | 主要取舍 |
|---|---|---|
| Core | 当前金融价格信号 | 新发按揭利率历史较短，因此共同样本较短 |
| Augmented | Core 加信贷数量和家庭能力 | 覆盖更广，但部分数量指标可能具有内生性 |
| Long-history | 周期分析和长期回测 | 省略较新的借款人结构指标 |
| Full | 近期压力、偿付负担与信贷标准监测 | 共同样本最短 |

![四个 HFCI 版本比较](assets/hfci_comparison.svg)

## 2. 构建方法

对原始序列 \(x_{{i,t}}\)，先进行预设的经济含义转换：

**(1)** \( q_{{i,t}} = g_i(x_{{i,t}}) \)

随后统一方向，使数值越高始终表示条件越紧：

**(2)** \( a_{{i,t}} = s_i q_{{i,t}}, \quad s_i \in \{{-1,+1\}} \)

为近似历史时点的信息集，根据估计发布滞后 \(L_i\) 平移观测：

**(3)** \( a^*_{{i,t}} = a_{{i,t-L_i}} \)

标准化仅使用截至当时的扩展样本，防止未来观测改变历史 z-score：

**(4)** \( z_{{i,t}} = (a^*_{{i,t}}-\bar a^*_{{i,1:t}})/\sigma_{{i,1:t}} \)

变量先在经济模块 \(b\) 内等权平均：

**(5)** \( B_{{b,t}} = N_{{b,t}}^{{-1}}\sum_{{i\in b}} z_{{i,t}} \)

再对当时可用的模块等权平均：

**(6)** \( HFCI_t = K_t^{{-1}}\sum_{{b=1}}^{{K_t}}B_{{b,t}} \)

网页显示的历史分位数采用扩展历史排名：

**(7)** \( P_t = 100\times rank(HFCI_t\mid HFCI_{{1:t}})/t \)

## 3. 输入数据与描述性统计

下表统计的是完成经济转换、但尚未进行方向调整、发布滞后和平滑标准化之前的输入。只有在构建规则明确要求时，低频数据才会向前填充。

| 模块 | 变量 | 转换后跨度 | N | 最小值 | Q1 | 中位数 | 均值 | Q3 | 最大值 | 标准差 | 发布滞后（月） | 来源 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(variable_rows)}

## 4. 指数特征

| 指数 | 时间跨度 | N | 最小值 | 中位数 | 均值 | 最大值 | 标准差 | 最新历史分位数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(index_rows)}

四个指数在主要紧缩和宽松阶段应大致同向，但当信贷数量或家庭偿付能力与市场价格信号背离时会出现差异。Long-history 更适合周期比较；Core 和 Full 更适合分析当前政策传导。

## 5. 伪实时回测

For horizon \(h\), the expanding-window direct regression is:

**(8)** \( y_{{t+h}} = \alpha_t + \rho_t state_t + \beta_t cash_t + \gamma_t HFCI_t + \varepsilon_{{t+h}} \)

在完全相同的对齐样本上比较四个嵌套模型：仅目标变量状态、目标状态加现金利率、目标状态加 HFCI、目标状态加现金利率和 HFCI。每次样本外预测前重新估计参数。结果报告 RMSE、MAE、方向准确率，以及相对于现金利率基准的 RMSE 改善。

| 目标变量 | 最优期限 | HFCI 版本 | 样本外 N | 相对现金利率 RMSE 改善 | 方向准确率 |
|---|---:|---|---:|---:|---:|
{chr(10).join(best_rows)}

这些是模型筛选诊断，而不是稳定预测能力的证明。表中最大改善来自多个组合的事后选择，因此存在选择偏差。更严格的下一阶段应预先确定目标、期限和评估窗口。

## 6. 为什么采用等权重？

等权重适合作为基准，因为它透明、可复现，对短且不平衡的样本更稳健，也不会利用之后用于回测的结果变量来挑选权重。模块内等权还可以避免某一模块仅因包含更多高度相关的利率序列而机械性占据主导。

它并非理论上的最优权重。其他方法回答的是不同问题：

| 方法 | 优点 | 本项目中的主要风险 |
|---|---|---|
| Principal components | Captures maximum common variance | Variance is not the same as housing relevance; loadings can shift |
| Dynamic factor model | Handles ragged edges and missing releases | More model risk and revision complexity |
| VAR/impulse-response weights | Links weights to macro responses | Target-specific, unstable in short samples, vulnerable to endogeneity |
| Supervised regression or ML | Optimises a chosen forecast loss | Overfitting and outcome leakage; weak interpretability |
| Volatility or inverse-covariance weights | Controls noisy/redundant inputs | Can generate unstable or economically unintuitive weights |

实际研究顺序应是：将等权 HFCI 作为公开基准；把 PCA、动态因子和结果变量加权版本作为稳健性检验；用于预测时，任何估计权重都必须只在每个历史训练窗口内重新估计。

## 7. 解读与局限

- 应同时观察正负号、历史分位数、持续性和模块贡献，不能把单月变化直接当作政策信号。
- HFCI 相对于自身扩展历史标准化，因此不同版本更适合比较方向，而不是机械比较绝对数值。
- 信贷、就业和工资可能是住房周期的原因、同步变量或滞后结果；这也是同时保留 Core 和 Augmented 的原因。
- 发布滞后得到近似处理，但大多数来源采用最新修订历史。因此这是**伪实时**回测，而不是完整 vintage 回测。
- Full 和 Core 的短样本包含疫情、非常规政策和快速加息阶段，估计关系未必能外推。

## 8. 文献依据

- [Hatzius et al. (2010), Financial Conditions Indexes: A Fresh Look after the Financial Crisis](https://www.nber.org/papers/w16150): broad financial-condition measurement and transparent benchmark constructions.
- [Matheson (2011), Financial Conditions Indexes for the United States and Euro Area](https://www.imf.org/external/pubs/ft/wp/2011/wp1193.pdf): dynamic-factor treatment of missing indicators and publication lags.
- [Swiston (2008), A U.S. Financial Conditions Index](https://www.imf.org/en/publications/wp/issues/2016/12/31/a-u-s-22077): VAR-based weighting as an alternative to equal weights.
- [Lombardi, Manea and Schrimpf (2025), Financial conditions and the macroeconomy](https://www.bis.org/publ/work1272.htm): interpretable safe-rate and risk factors.
- [RBA, Financial Conditions, May 2024](https://www.rba.gov.au/publications/smp/2024/may/financial-conditions.html): Australian mortgage rates, repayments, credit growth and borrower constraints.
- [RBA, Recent Drivers of Housing Loan Arrears, July 2024](https://www.rba.gov.au/publications/bulletin/2024/jul/recent-drivers-of-housing-loan-arrears.html): household stress and mortgage performance.
"""
    (ROOT / "HFCI_REPORT.md").write_text(report)
    svg_chart(derived, ROOT / "assets" / "hfci_comparison.svg")


def main():
    data = json.loads((ROOT / "property_data.json").read_text())
    backtest = json.loads((ROOT / "hfci_backtest.json").read_text())
    generate(data, backtest)
    print("Generated HFCI_REPORT.md and assets/hfci_comparison.svg")


if __name__ == "__main__":
    main()
