# Australian Property & Macro Tracker

A self-hosted dashboard for haoyileslieluo.com — no build step, no
framework. Core components:

- `index.html` — the main charts and source/policy map
- `data.html` — full underlying observation tables
- `freshness.html` — source checks, release lags and freshness status
- `listings.html` — filterable recent-listing sample for the four-city market watch
- `property_data.json` — the latest refreshed dataset consumed by the dashboard.
- `data_vintages.json` — append-only, timestamped copies of every refresh for revision and historical tracking.
- `ingest_macro.py` — optional local updater for the monitored macro
  and supply series.
- `validate_data.py` — dependency-free data-quality, freshness and
  vintage-consistency checks.
- `derived_indicators.py` — deterministic formulas that turn observed
  series into financing, affordability, supply and relative-market signals.
- `ingest_listings.py` — privacy and schema validator for the public listing export.
- `refresh_listings_from_gmail.py` — unattended read-only Gmail alert ingestor.
- `gmail_oauth_setup.py` — one-time helper for placing Google credentials in encrypted GitHub Secrets.
- `market_listings_latest.json` — the newest listing snapshot consumed by `listings.html`.
- `market_listings_vintages.json` — append-only listing snapshots for change tracking.
- `tests/` — regression tests proving that malformed dates, implausible
  values, stale labels and vintage mismatches are rejected.
- `vendor/chart.umd.min.js` — the locally hosted Chart.js runtime used
  to draw the time-series charts.

## Why this shape (Option 2 — self-hosted)

You chose to self-host rather than embed a Claude-published artifact,
since you may bring in other AI tools to build out the surrounding
infrastructure later. So the design deliberately has **zero
dependency on Claude's runtime**:

- `index.html` fetches `property_data.json` from the same folder at
  load time. That's the entire "backend."
- If you ever swap this for a real database, an API, or a static-site
  generator's data layer, only the one `fetch('./property_data.json')`
  line in `index.html` needs to change — the rest of the page doesn't care
  where the JSON came from.
- If the fetch fails (e.g. you open the file directly without a server,
  or something's misconfigured), it falls back to an embedded sample
  so the page never shows a broken blank screen.

## Deploying it

Upload the three HTML pages, `property_data.json`, and the `vendor` folder to
the same folder on your site (e.g. `haoyileslieluo.com/property-tracker/`).
Keep `vendor/chart.umd.min.js` at that exact relative path. Any static host works — since
it's plain HTML/CSS/JS with no build step, this will work identically
however you're currently hosting the rest of your site (GitHub Pages,
Netlify, plain file upload, etc.).

Serve it over HTTP(S), not by double-clicking the file locally —
`fetch()` of a local JSON file is blocked by browsers under the
`file://` protocol. Any static hosting counts as HTTP(S) automatically.

## Updating it monthly (or ad hoc)

The GitHub Actions workflow in `.github/workflows/refresh-data.yml` runs
automatically each month at 22:30 UTC on the 14th. That is 08:30 or 09:30
Melbourne time on the 15th, depending on daylight saving. It refreshes the
public feeds, validates the result, appends a timestamped snapshot to
`data_vintages.json`, and commits both JSON files back to `main`. GitHub
Pages then republishes the latest dashboard data.

For an ad hoc refresh, open the repository's **Actions** tab, select
**Refresh tracker data**, choose **Run workflow**, and run it from `main`.
The workflow uses only public endpoints and the built-in GitHub token, so
it does not require API keys or repository secrets.

After each run, review the workflow's validation summary and spot-check
the dashboard freshness page. A source, parser, or validation failure stops
the job before any data is committed.

The same refresh can still be run locally when investigating a source:

For the monitored macro series, run:

```bash
python3 ingest_macro.py
```

This fetches the RBA cash-rate page, RBA H5 labour history, RBA G1 CPI
history, RBA F6 mortgage rates, FRED Treasury yields, monthly market
index closes, and the latest ABS CPI, wages, building approvals and
lending-indicator releases. It archives the complete refresh in
`data_vintages.json`, updates `property_data.json`, and refreshes the
history-count and status metadata. Use
`python3 ingest_macro.py --dry-run` first when you want to check what
would be ingested without writing the file.

Network requests are retried up to three times with bounded backoff. The
workflow logs the exact failing URL when a provider times out or rejects a
request, which keeps source outages distinguishable from parser or data
quality failures.

The ingestor validates the complete refresh before replacing either JSON
file. A failed check exits with an error and leaves the published dataset
and vintage archive unchanged.

## Validating the data

Run the same checks used by GitHub Actions:

```bash
python3 -m unittest discover -s tests -v
python3 validate_data.py
```

The validator checks required source and explanatory metadata, valid and
strictly chronological dates, duplicate observations, finite values,
indicator-specific plausible ranges, source-check freshness, reported
observation counts, and exact agreement between `property_data.json` and
the latest timestamped vintage. The workflow in
`.github/workflows/validate.yml` runs these checks on every push and pull
request, as well as on demand from the Actions tab.

## Recent-listings prototype

The listing page uses saved-search alerts received from Domain and
realestate.com.au. The private research desk parses and deduplicates those
alerts, then exports no more than three recent examples per observed suburb.
Both portals are represented where the alert evidence allows it. Historical
vintages retain aggregate measures only, not listing-level records.

The public export excludes Gmail message IDs, email content, notes and
personalized campaign links. The Details link performs an exact-address public
search instead. The dataset supports portal coverage, listing mix, auction
share, disclosed-price coverage and longitudinal analysis; it is alert evidence,
not a complete market census.

For a local validation:

```bash
python3 ingest_listings.py
python3 -m unittest tests.test_ingest_listings -v
```

The **Refresh market listings** GitHub Action checks the Gmail label
`Property Desk` every day at 21:25 UTC, parses only newer Domain and REA alert
messages, keeps no more than three recent examples per suburb, validates the
privacy-safe export, and commits changed JSON files back to the repository.
This is 07:25 or 08:25 Melbourne time depending on daylight saving. It can also
be run on demand from the Actions tab.

The Action needs one-time read-only Gmail authorization. In Google Cloud:

1. Create a project, enable the Gmail API, and configure the OAuth consent screen.
2. Add your Google account as a test user, then create an OAuth **Desktop app** client.
3. Download its JSON file and run:

```bash
python3 gmail_oauth_setup.py ~/Downloads/client_secret_*.json
```

The helper opens Google consent and stores `GMAIL_CLIENT_ID`,
`GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN` directly as encrypted repository
secrets using GitHub CLI. It never writes their values into this repository.
Google expires refresh tokens for external apps left in Testing after seven days.
Moving an app to Production avoids that short token lifetime, but Gmail read-only
is a restricted scope and Google may require OAuth verification. Keep this setup
in Testing for the pilot, then choose between verification and a local scheduled
refresh before treating it as durable production infrastructure.

The workflow has read-only Gmail scope. Public output excludes message IDs, raw
email content, notes, recipient details and portal tracking links. Details links
on the page remain exact-address public searches.

### Access and download links (public)

- ABS Labour Force latest release (employment, unemployment charts/tables):
  https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/latest-release
- ABS Building Approvals latest release (national + state snapshots):
  https://www.abs.gov.au/statistics/industry/building-and-construction/building-approvals-australia/latest-release
- ABS CPI latest release:
  https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/latest-release
- RBA Housing Lending Rates public CSV (F6):
  https://www.rba.gov.au/statistics/tables/csv/f6-data.csv
- RBA Labour Force public CSV (H5):
  https://www.rba.gov.au/statistics/tables/csv/h5-data.csv
- RBA Consumer Price Inflation public CSV (G1):
  https://www.rba.gov.au/statistics/tables/csv/g1-data.csv
- ABS Lending Indicators latest release:
  https://www.abs.gov.au/statistics/economy/finance/lending-indicators/latest-release

For commercial market providers, full time series may require licensed
access. Keep those series as optional overlays (`subscription` +
`manual`) and use ABS/RBA public feeds as the maintainable baseline.

### Data file shape

```json
"home_value_index_mom": {
  "label": "Home value growth, month-on-month",
  "unit": "%",
  "source": "PropTrack Home Price Index",
  "frequency": "monthly",
  "data": {
    "National": [
      { "date": "2026-04", "value": 9.8 },
      { "date": "2026-05", "value": 9.4 }
    ],
    "Sydney": [ ... ],
    "Melbourne": [ ... ],
    "Brisbane": [ ... ],
    "Perth": [ ... ]
  }
}
```

Add a new `{ "date": ..., "value": ... }` object to the end of the
relevant region's array each round. Dates are `YYYY-MM` for monthly
series, `YYYY-Q#` for quarterly ones (lending indicators).

Bump `meta.last_updated` at the top of the file each time you update
— it drives the "Last updated" line in the page header.

### Data freshness metadata

Live or monitored series should carry these fields:

```json
"source_url": "https://www.abs.gov.au/...",
"release_lag_days": 35,
"last_source_check": "2026-07-14",
"latest_source_period": "2026-05",
"status": "fresh",
"status_note": "Short human-readable audit note.",
"access_tier": "public",
"update_method": "automated"
```

Use `access_tier` as `public` or `subscription`, and `update_method`
as `automated` or `manual` so the dashboard can clearly separate
core maintainable feeds from optional overlays.

The dashboard renders these fields on the separate `freshness.html` page.
Use the following statuses:

- `fresh`: latest observation is within the expected release lag
- `watch`: source or methodology needs manual review
- `stale`: latest observation is older than expected
- `discontinued`: keep the history, but do not treat it as a live feed

This matters because not every source is a stable monthly feed. For
example, the old ABS Monthly CPI Indicator ceased after September 2025.
The ingestor now maps `cpi_headline_yoy` and `cpi_trimmed_mean_yoy` to
the replacement **Consumer Price Index, Australia** monthly release.
For continuity, earlier observations in that ABS table are retained
even where annual comparisons were quarter-to-quarter before the full
monthly rollout.

## Macro time-series workspace

`index.html` includes one consolidated "Macro Indicator Time Series"
workspace and links each indicator to `data.html`, the ABS-style
observation-table layer:

- select an indicator from the series list
- inspect the full smoothed time-series chart with an area fill
- read its definition, usage guidance and housing-market relationship
- open the underlying observation table on its own page
- download that series as CSV

The table is generated directly from `property_data.json`, so if a
series has 36 observations in the JSON, the page lists all 36. This is
intended to make the dashboard auditable rather than only showing
summary cards.

## Derived housing and market indicators

The second time-series workspace is calculated from the observed series on
every refresh. It currently includes:

- real cash and variable mortgage rates
- the variable mortgage-rate spread to the cash rate
- private- and public-sector real wage growth
- the US 10-year minus 3-year Treasury spread
- the implied average value of a new dwelling loan commitment
- annual dwelling-approvals growth
- ASX 200 Real Estate and A-REIT performance relative to the ASX 200

Each derived series carries its formula, component-series keys, component
source links and a methodology note. `validate_data.py` independently
recalculates all derived observations and rejects the dataset if any stored
value or metadata differs from the configured formula. The data-table page
and CSV downloads cover observed and derived series through the same UI.
Timestamped vintages retain the underlying observed inputs and derivation
version, so a historical derived reading can be reproduced without copying
the calculated layer into every archive snapshot.

## Source and policy map

The dashboard now carries a `meta.source_registry` block in
`property_data.json`. This is the working source map behind the tracker
and is rendered on the page as the "Source & Policy Map."

The source registry supports the recurring research workflow described
in the job ad:

- maintain residential housing market indicators
- build forecasting and nowcasting inputs
- interpret ABS, RBA, and government releases quickly
- monitor policy changes that can affect demand, credit, supply, and
  affordability
- compare national conditions with Sydney, Melbourne, Brisbane, and Perth

### Core source stack

| Category | Use it for | Main sources |
|---|---|---|
| Price | Home value indexes, city momentum, medians | PropTrack HPI, Domain research |
| Market activity | Auctions, listings, days on market, vendor discounting | Domain and realestate.com.au auction results, Ray White Economics, McGrath, PRD, SQM stock on market |
| Supply pipeline | Approvals, commencements, completions, supply gap | ABS Building Approvals, ABS Building Activity, National Housing Supply and Affordability Council |
| Credit and lending | Loan commitments, investor share, FHB share, lending risk | ABS Lending Indicators, APRA property exposures, RBA statistics |
| Rental market | Vacancies, advertised rents, rental yields | SQM Research, Domain Rent Report |
| Macro conditions | Cash rate, CPI, labour market, wages, GDP, population | RBA, ABS Labour Force, ABS CPI, ABS National Accounts, ABS Population |
| Income and affordability | Household income, wages, price-to-income and repayment burdens | ABS Household Income and Wealth, Census, Wage Price Index |
| Policy and regulation | Macroprudential policy, buyer schemes, duty/tax, planning | APRA, Housing Australia, Revenue NSW, Victorian SRO, Queensland Revenue Office, WA Treasury/Finance |
| Listed housing exposure | Residential developers, platforms, lenders and A-REIT total returns | ASX indices and company announcements |

Use official ABS/RBA/APRA/government releases as the audit trail for
professional commentary. Use market providers such as PropTrack,
Domain, and SQM for faster property-market reads, especially
where official statistics lag or do not provide city-level granularity.

The current setup is **public-first**: key monitoring relies on ABS/RBA
series you can always refresh. Commercial market series are flagged
`watch` + `manual` when their maintenance depends on licensed updates.

## Current macro database

The current JSON includes:

- RBA cash rate target: 398 decision observations from February 1990 to June 2026
- ABS unemployment rate and employed people: 580 monthly national seasonally adjusted observations from February 1978 to May 2026
- ABS dwelling approvals: 515 monthly seasonally adjusted observations
  from July 1983 to May 2026 for Australia, NSW/Sydney, Victoria/Melbourne,
  Queensland/Brisbane and WA/Perth state proxies
- ABS headline CPI: 422 observations from June 1923; annual trimmed mean:
  183 observations from March 1983. Both use RBA G1 quarterly history
  before the complete monthly CPI observations
- RBA owner-occupier variable mortgage rate: all 83 observations
  available under the current definition, from July 2019
- ABS new dwelling-loan commitments growth: 26 quarterly changes from
  December quarter 2019 to March quarter 2026
- ABS new dwelling-loan commitments: 27 quarterly count observations
  from September quarter 2019 and 41 quarterly value observations from
  March quarter 2016
- S&P/ASX 200, S&P 500 and MSCI ACWI monthly price-return indices
- S&P/ASX 200 Real Estate and A-REIT monthly price-return indices
- FRED 3-year and 10-year US Treasury yields, sampled at each month end
- ABS private- and public-sector annual wage growth from March quarter 2011
- ABS private- and public-sector full-time adult average weekly ordinary
  earnings in current dollars, six-monthly from November 2015

These are now rendered in the "Macro Indicator Time Series" panel. The
older city/property indicators remain in the original region-comparison
chart panel.

## What's seeded vs. what's still thin

Home value growth and vacancy rates remain single-observation commercial
series because their historical chart data is access-gated. They are retained in `property_data.json`,
carry `snapshot_captured_at` timestamps, and remain available on
`data.html`, but are withheld from the homepage until more observations
are available.

## Extending it later

- Add a new series: add a new key under `"series"` in the JSON with
  the same shape (`label`, `unit`, `source`, `frequency`, `data`),
  then add its key to the `seriesToShow` array near the bottom of
  `index.html`.
- Add a new region: add its name to `meta.regions` and to each
  series' `data` object.
- Add a new source: add an object to `meta.source_registry`. The page
  will render it automatically; no HTML change is needed.
- Want annotations (e.g. "RBA hiked here")? That's a reasonable next
  addition — flag it and we can add a simple markers layer to the
  charts.
