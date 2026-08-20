# Forecasting and Selection Policy

## Contract

Treat prediction as a dated, testable ranking problem. A valid forecast must contain:

- observation date and forecast horizon;
- eligible universe and exclusions;
- factor values, weights and missing-data coverage;
- direction score or calibrated historical hit rate;
- walk-forward period, sample size and assumed transaction cost;
- base, upside and downside mechanisms;
- invalidation signals and material non-price risks.

Never use words such as “必涨”, “确定性”, “稳赚” or “目标价保证”. A 0–100 direction score is not a probability. Only label a value as historical probability when it comes from an out-of-sample score bucket with at least 30 observations; still describe it as a historical rate, not a future guarantee.

Run `backtest_sector_signal.py` before translating a raw score into a directional view. If the report says `abstain` because the score is neutral, the current bucket is sparse, or score/return monotonicity fails, publish the evidence and scenarios without a directional trade. Do not override abstention with narrative confidence.

## Horizons

- `5d`: short swing. Give more weight to 5/20-day momentum, current trend and 20-day breadth.
- `20d`: medium swing. Give more weight to 20/60-day momentum, relative strength and 60-day breadth.
- Do not extrapolate these signals into a 6–12 month fundamental thesis.

## Multi-timeframe timing overlay

Read `technical-timing-workflow.md` for any named A-share/ETF 5d/20d entry question, real-time buy/sell-point request, or conditional recommendation.

- Use completed weekly bars to define the higher-timeframe regime and daily bars to define the trigger. Keep an unfinished week provisional and separate.
- Compute 20/55-day Donchian thresholds from bars strictly before the decision bar. A signal observed at the close can execute no earlier than the next session.
- Use ATR, the prior 10-day channel, relative strength, volume and OBV as transparent timing/risk features. Volume or OBV confirms a setup but never replaces event, disclosure or fundamental evidence.
- Treat `triggered|retest` as eligible timing states only after the same asset and exact timing rule pass `model.timing-backtest/1`.
- `watch`, `triggered_unconfirmed`, `extended`, `trend_only`, `mixed`, `blocked`, sparse data or a timing-backtest `abstain` cannot produce `条件买入`.
- Do not mechanically add the timing state to the sector direction score. Direction/ranking and entry timing answer different questions and require separate validation.

The reference package audited in `trend-analysis-v4-reference-audit.md` inspired the weekly/daily, Donchian and ATR structure. Do not import its fixed five-module weights, universal fixed 5% stop/position rule, price-proxy CAN SLIM, pattern targets, substring vetoes or adjacent-refresh "accuracy" statistic. A fixed 5% stop may be retained only as a named backtest ablation; do not assume the current dynamic stop is superior without same-rule point-in-time evidence.

## Named A-share and ETF outlook order

Read `a-share-outlook-workflow.md` and run `build_a_share_outlook_plan.py` before analyzing a named A-share or ETF. Do not use one fixed order for news, overseas markets and momentum.

- Always resolve identity, live exposure, as-of time, horizon and benchmark first.
- Run the event-clock gate second. With no confirmed material event, read local relative momentum and breadth before deep news research so that already-priced expectations are visible. With a confirmed material event, open the original source first, then freeze the pre-event local price state.
- Use momentum to measure expectations and timing, original sources to establish mechanism, and U.S./Korean peers to test a shared variable. None can establish the conclusion alone.
- For pre-market work, inspect overnight official news and the previous U.S. close; use only a Korean close strictly earlier than the A-share observation date.
- For 60-day or longer work, prioritize earnings, cash flow, valuation and policy before momentum; use short-term momentum only for entry timing.

For ETFs, retrieve current index constituents and the fund's latest disclosed holdings with separate dates. Select cross-market proxies from verified industry exposures. If exposure weights are missing or stale, report each relevant overseas mapping separately and do not publish a blended cross-market score.

## Point-in-time discipline

At each backtest decision date, calculate factors from bars dated on or before that date. Apply future returns only after the ranking is frozen. Do not tune weights on the reported test period. Deduct explicit trading costs from candidate returns.

Warn about:

- survivorship bias when the current constituent list is reused historically;
- selection bias when a hand-picked seed universe is used;
- corporate-action and adjusted-price conventions;
- delistings, suspensions and limit-up/limit-down execution constraints;
- endpoint gaps, stale cache and low coverage;
- multiple testing when many themes, horizons or weights were tried.
- same-bar execution or using the decision bar inside its own breakout threshold;
- overlapping timing observations that count one trend repeatedly;
- unfinished weekly bars silently treated as final.
- an all-history timing gate with no predeclared evaluation start, which can hide recent regime decay;
- terminal signals settled before their full configured holding horizon exists.

## Cross-market overlay for A-shares

For every A-share sector request, inspect the mapped U.S. and Korean peers in `cross-market-presets.json`. Use the overlay to form and test a mechanism, not as an unvalidated factor in the score.

1. Compare the foreign sector proxy with its own broad market to remove part of the global risk-on/risk-off move.
2. Use only a foreign close strictly earlier than the A-share observation date in a lead test. Korean daily closes cannot be treated as available at that morning's A-share open.
3. Open the original earnings release, filing or policy source for any foreign leader whose move is central to the thesis.
4. State the shared variable: capital expenditure, product price, order, inventory, rate, commodity, regulation or risk appetite.
5. Classify the A-share response as confirmation, `foreign_positive_a_rejected`, `foreign_negative_a_resilient`, or mixed.
6. Explain the local modifier: policy, FX, valuation, crowding, market support, capital controls or a broken product/customer linkage.

Do not force analogs. Liquor, Chinese property developers, coal and agriculture have weak or missing Korean mappings; disclose that limitation. Do not promote an A-share candidate or change a model score solely because a foreign proxy rose. Correlations and direction-agreement rates are historical descriptive statistics, never future probabilities.

## Candidate logic

The bundled selector uses price/volume factors only:

```text
20d momentum       18%
60d momentum       12%
20d relative strength vs sector ETF 18%
60d relative strength vs sector ETF 12%
MA20/MA60 trend structure            15%
20d/60d volume confirmation          10%
20d volatility quality                8%
60d drawdown quality                   7%
```

Exclude securities with insufficient history, non-positive prices, or names containing ST/退 by default. Do not use portal “main force” labels as a substitute for price, disclosure or fundamental evidence.

The selector ranks candidates; it does not choose an entry. After ranking, run `compute_trade_timing.py` and `backtest_trade_timing.py` for every candidate that may appear as a conditional buy. Use a long history, freeze `--start` before viewing outcomes, and exclude incomplete terminal horizons. Pattern, Chan-theory, MACD, RSI, KDJ or other chart labels remain exploratory unless the exact rule has an independent point-in-time backtest. Pooled evidence from the v4 audit does not substitute for the same-asset gate.

## Sector-specific review

### Technology

Review valuation dispersion, capital expenditure cycle, inventory, export controls, customer concentration, product substitution and R&D conversion. A price trend can reverse even when the long-term technology thesis remains intact.

The `technology` preset uses the CSI Technology Top methodology as a conceptual reference and `515000` as a tradable price proxy. The official index methodology describes a universe spanning electronics, computers, communications and biotechnology: <https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208180413-931087_Index_Methodology_cn.pdf>.

### Innovative drugs

Price factors cannot evaluate molecule quality. Before naming candidates, add point-in-time evidence for clinical readouts, trial phase, endpoints, safety, regulatory review, licensing terms, cash runway, dilution, patent life and commercialization. Treat CRO/CDMO companies separately from drug developers.

The `innovative-drug` preset uses `159992` as a tradable price proxy. The CSI Brand Name Drug Industry methodology selects companies whose main business involves innovative-drug R&D: <https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208180434-931152_Index_Methodology_cn.pdf>.

### New-energy vehicles and photovoltaic

Separate demand growth from price competition. Review capacity utilization, inventory, unit economics, raw-material exposure, overseas policy, customer concentration, technology substitution and cash conversion. Do not infer company earnings from installation or vehicle-sales growth alone.

### Consumer and liquor

Decompose revenue into volume, price and mix. Verify channel inventory, distributor profitability, sell-through, discounting, input costs, brand strength and free cash flow. Treat reported shipments without end-demand evidence as an incomplete signal.

### Finance and brokerage

Use PB/ROE and credit-cycle evidence rather than a universal growth-stock PE anchor. Review net interest margin, asset quality, provisions, capital adequacy, fee income, trading volumes, market beta and regulatory constraints. A low PB can represent impaired asset quality rather than undervaluation.

### Defense and infrastructure

Trace policy or budget claims into dated tenders, orders, deliveries, revenue recognition, receivables and cash collection. Review certification, procurement cycles, customer concentration, working capital and margin dilution. Policy attention without executable orders is not a catalyst.

### Nonferrous metals and coal

Use normalized mid-cycle earnings, cost curves and balance-sheet resilience. Separate physical supply/demand, inventory and capacity discipline from currency or speculative price effects. Stress-test commodity prices, royalties, energy costs, environmental limits and capital expenditure.

### Electric power and dividend

Test whether dividends are covered by normalized free cash flow after maintenance and growth capital expenditure. Review regulated tariffs, utilization, fuel costs, hydrology, debt, payout policy and one-off gains. Do not recommend solely because trailing dividend yield is high.

### Agriculture

Map biological and planting cycles explicitly. Review inventory or herd capacity, feed and input costs, weather, disease, selling prices, unit cost, cash burn and leverage. Use normalized earnings rather than extrapolating a cycle peak or trough.

### Real estate

Use net asset value, contracted sales, collections, inventory quality, land reserves, funding cost, debt maturity and contingent liabilities. Distinguish policy support for project completion or demand from support for equity holders. A NAV discount is not automatically mispricing.

## Minimum reporting template

```text
As of / horizon:
Universe / benchmark:
Trend score and coverage:
Leading factors:
Candidate ranking:
Walk-forward evidence:
Timing state / timing walk-forward gate:
Fundamental/catalyst checks still required:
Downside scenario:
Invalidation signals:
Data limitations:
```
