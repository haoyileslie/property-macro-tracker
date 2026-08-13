# Property and Macro Tracker: Research Plan

## Research objective

The tracker should evolve from a data-display dashboard into a research tool for studying one central question:

> How do interest rates, credit, household income and housing supply jointly shape the Australian housing cycle?

The work serves two linked uses:

1. A practical buyer's research desk for assessing financing pressure, market activity and local housing conditions.
2. A reproducible economics research platform that can support portfolio work, job applications and, only if the evidence proves useful, a later commercial assessment.

The immediate priority is not to add more charts. It is to turn the existing macro and listings data into transparent indicators, documented hypotheses and testable research outputs.

## Proposed research streams

### 1. Australian Housing Financial Conditions Index

Build a transparent monthly index summarising the cost and availability of housing finance. The first version should use a small number of interpretable blocks rather than an opaque model:

- **Policy stance:** real cash rate and the cash-rate cycle.
- **Mortgage pricing:** new owner-occupier mortgage rate, real mortgage rate and mortgage spread to the cash rate.
- **Credit availability and momentum:** housing, owner-occupier and investor credit growth; new loan commitments where frequency permits.
- **Household capacity:** employment growth and real wage growth.
- **Market risk and funding:** government yields, corporate credit yield and listed real-estate performance.

Publish both the aggregate index and its components:

- current degree of easing or tightening;
- monthly change and three-month momentum;
- historical percentile;
- contribution by block;
- comparison with later housing and economic outcomes.

The index should initially be called the **Housing Financial Conditions Index (HFCI)** only as a research indicator. It is not an official measure and must not be presented as a causal estimate.

### 2. Monetary-policy transmission into housing

Map the transmission sequence from the cash rate to:

1. mortgage rates and mortgage spreads;
2. new loan commitments and average loan size;
3. housing credit growth, split between owner-occupiers and investors;
4. dwelling approvals and dwelling investment;
5. listed real-estate prices and, later, listings-market outcomes.

Start with cycle charts, cross-correlations and distributed lead-lag plots. Move to local projections or a small VAR only after the series transformations, sample periods and identifying assumptions are documented. Correlation must not be labelled as causation.

### 3. Housing affordability and borrowing capacity

Develop buyer-facing measures including:

- implied average new housing loan relative to annual earnings;
- modelled mortgage repayments relative to earnings;
- borrowing-capacity sensitivity to a 100-basis-point rate change;
- real private- and public-sector wage growth;
- scenarios by deposit, mortgage term, income and interest rate.

This stream should distinguish the affordability of purchasing a dwelling from the cash-flow pressure faced by existing borrowers.

### 4. Credit composition and the investor cycle

Construct and test:

- investor credit growth less owner-occupier credit growth;
- investor share of housing credit growth or new commitments;
- implied average new loan value;
- credit growth relative to wage or income growth;
- credit acceleration, not only year-on-year credit growth.

Test whether changes in investor credit lead dwelling approvals, price momentum, auction activity or listings turnover.

### 5. Housing supply pressure

Combine dwelling approvals, completions, commencements, dwelling investment, population growth, rents and vacancy rates into a supply-pressure dashboard. Candidate ratios include approvals and completions per additional resident or household.

This stream depends on adding stable public histories for dwelling completions, population growth and rents. State data should remain explicitly labelled as state proxies when capital-city measures are unavailable.

### 6. Listed real estate as a leading signal

Test whether relative returns for the S&P/ASX 200 Real Estate and A-REIT indexes, together with government yields and corporate financing costs, lead:

- dwelling approvals;
- dwelling investment;
- housing credit growth;
- listings-market activity.

This connects financial-market pricing and funding conditions to the real housing cycle and is particularly relevant to financial-economics and quantitative-research applications.

### 7. Macro conditions and the proprietary listings panel

After at least three to six months of reliable listings history, study:

- new-listing flow;
- auction share and scheduled-auction pipeline;
- price-guide disclosure and revision;
- time on market;
- withdrawal and delisting rates;
- transitions from off-market alerts to public listings;
- overlap and publication timing across Domain and realestate.com.au;
- suburb and property-type sensitivity to changes in rates, credit and employment.

The lifecycle data are the most distinctive part of the project. They must retain source evidence, event timestamps and data-quality flags while the public page continues to show only a deliberately limited sample.

## Delivery sequence

### Next few days

- Define the HFCI variable dictionary, signs, transformations and release lags.
- Build a transparent equal-block-weight baseline index.
- Add historical percentiles and block-contribution charts.
- Add mortgage repayment pressure and borrowing-capacity scenarios.
- Mark RBA tightening, easing and hold phases on relevant charts.

### Next few weeks

- Compare equal-weight, principal-component and outcome-weighted HFCI variants.
- Run lead-lag analysis of cash rates, mortgage pricing, credit and housing activity.
- Develop the investor-versus-owner-occupier credit indicators.
- Add the first housing supply-pressure measures.
- Produce a four-to-six-page research note explaining method, results and limitations.

### Next few months

- Link the listings lifecycle panel to macro conditions.
- Build a suburb-level panel with stable property and portal identifiers.
- Estimate heterogeneity across cities, transport-linked suburbs and property types.
- Test modest nowcasting models for credit, approvals or listings activity.
- Evaluate out-of-sample accuracy and vintage sensitivity before adding any forecasting language to the public dashboard.

## HFCI construction principles

### Economic definition

Financial conditions describe the affordability and availability of finance faced by households and firms. A housing-specific measure should therefore capture the price of mortgage credit, the transmission of policy rates, observable credit availability and household capacity to service debt.

### Baseline specification

For each monthly input series:

1. transform it into an economically meaningful rate, spread, return or growth measure;
2. align higher values so that they consistently mean either tighter or easier conditions;
3. standardise it using an expanding or fixed historical window;
4. average variables within conceptual blocks;
5. average the block scores so blocks with many similar variables do not dominate;
6. express the final index in standard deviations from its historical mean and also publish a percentile.

For the first public version, define positive HFCI values as **tighter-than-average housing financial conditions**.

### Why start with equal block weights

Equal block weights are transparent, easy to reproduce and suitable for a research prototype. They make the economic judgement visible and avoid allowing a group of highly correlated interest-rate series to dominate merely because more of them are available.

Principal components or dynamic factors should be reported as robustness variants, not silently substituted for the baseline. Outcome-weighted methods based on a VAR or local projections should be considered only after selecting a clear target such as housing credit growth, dwelling investment or listings activity.

### Variables that should not enter the baseline mechanically

- **House-price growth:** primarily an outcome to be explained. Including it in the baseline would make subsequent tests against prices partly circular.
- **Building approvals and dwelling investment:** transmission outcomes rather than current financing terms.
- **Raw listings activity:** a later validation or nowcasting target.
- **Consumer sentiment:** potentially informative, but it mixes financing conditions with broader economic expectations. Keep it as a robustness variable.
- **Employment and wages:** household capacity variables rather than purely financial prices. Publish an HFCI both with and without this block.
- **Credit quantities:** useful evidence on availability and realised demand, but potentially lagging and endogenous. Compare a price-only core index with an augmented index containing credit quantities.

### Real-time and validation requirements

- Use release dates rather than observation dates when assessing information that would have been available in real time.
- Preserve data vintages and distinguish revised history from true real-time estimates.
- Report sensitivity to standardisation window, weights and variable set.
- Test whether the HFCI adds out-of-sample information beyond the cash rate alone.
- Compare forecasting performance for several targets and horizons.
- Treat signs, lags and turning points as empirical questions rather than assumptions.

## Literature basis

The HFCI is an application of the broader financial-conditions literature, adapted to Australia's mortgage-heavy household sector. No single paper supplies the exact proposed formula; the design combines several established strands.

### Composite financial-conditions indexes

- [Hatzius et al. (2010), *Financial Conditions Indexes: A Fresh Look after the Financial Crisis*](https://www.nber.org/papers/w16150) argues for combining interest rates and asset prices with quantitative and survey measures, while controlling for past macroeconomic conditions when the objective is forecasting future activity. This supports a broad candidate set and warns against confusing financial conditions with contemporaneous macro outcomes.
- [Matheson (2011), *Financial Conditions Indexes for the United States and Euro Area*](https://www.elibrary.imf.org/view/journals/001/2011/093/article-A001-en.xml) uses a dynamic factor model and an unbalanced data set. It motivates a later dynamic-factor robustness index and is especially relevant when indicators have different publication lags.
- [Swiston (2008), *A U.S. Financial Conditions Index: Putting Credit Where Credit Is Due*](https://www.elibrary.imf.org/view/journals/001/2008/161/article-A001-en.xml) uses VAR responses to weight financial variables and emphasises credit availability. It provides the basis for a later outcome-weighted version rather than the transparent first-stage index.
- [Lombardi, Manea and Schrimpf (2025), *Financial Conditions and the Macroeconomy: A Two-factor View*](https://www.bis.org/publ/work1272.htm) separates latent dimensions of financial conditions using a dynamic factor model. It supports reporting distinct pricing/risk and credit-availability blocks instead of forcing every signal into one unexplained number.

### Credit, property prices and the financial cycle

- [Jordà, Schularick and Taylor (2016), *The Great Mortgaging: Housing Finance, Crises and Business Cycles*](https://academic.oup.com/economicpolicy/article-abstract/31/85/107/2392378) documents the central role of mortgage credit in modern advanced-economy financial cycles. It supports treating housing credit as a core object of analysis rather than a peripheral macro series.
- [IMF (2020), *Predicting Downside Risks to House Prices and Macro-Financial Stability*](https://www.elibrary.imf.org/view/journals/001/2020/011/article-A001-en.xml) links tighter financial conditions to greater downside risk to house prices and separately considers household leverage and credit growth. It motivates using the HFCI to study distributions and downside risk, not only average price growth.

### Australian monetary transmission and housing

- [Atkin and La Cava (2017), *The Transmission of Monetary Policy: How Does It Work?*](https://www.rba.gov.au/publications/bulletin/2017/sep/1.html) describes the Australian transmission chain from the cash rate to other lending rates, cash flows, credit, asset prices and activity. This is the conceptual basis for the policy and mortgage-pricing blocks.
- [La Cava, Hughson and Kaplan (2016), *The Household Cash Flow Channel of Monetary Policy*](https://www.rba.gov.au/publications/rdp/2016/2016-12/conclusion.html) finds an important borrower cash-flow channel in Australia, particularly for variable-rate mortgage debt and liquidity-constrained households. This supports adding repayment pressure separately from the financing index.
- [Jennison and Miller (2025), *An Update on the Household Cash-flow Channel of Monetary Policy*](https://www.rba.gov.au/publications/bulletin/2025/jan/an-update-on-the-household-cash-flow-channel-of-monetary-policy.html) highlights pass-through, debt and asset holdings, and spending responses as the three key elements of household cash-flow transmission. It provides a practical basis for the mortgage-repayment scenario module.
- [He and La Cava (2020), *The Distributional Effects of Monetary Policy: Evidence from Local Housing Markets*](https://www.rba.gov.au/publications/rdp/2020/2020-02/full.html) shows that Australian local housing markets respond heterogeneously to monetary policy and that supply constraints matter. This supports linking a national HFCI to city and suburb outcomes rather than assuming a single Australian housing market.
- [RBA (2024), *Financial Conditions*](https://www.rba.gov.au/publications/smp/2024/may/financial-conditions.html) assesses household financial conditions using housing lending rates, scheduled debt payments, credit and borrower characteristics. It supports the proposed emphasis on mortgage pricing and servicing pressure while also showing that no single series is sufficient.

## Proposed first research output

**Australian Housing Financial Conditions and Monetary Transmission Monitor**

The initial output should contain:

1. the transparent baseline HFCI and component contributions;
2. a price-only core index and an augmented credit/capacity index;
3. historical episodes and RBA cycle annotations;
4. mortgage repayment and borrowing-capacity scenarios;
5. lead-lag evidence for credit, approvals and listed real estate;
6. explicit caveats on endogeneity, revisions and the difference between predictive and causal evidence.
