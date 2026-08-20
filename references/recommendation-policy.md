# Conditional Recommendation Policy

## Allowed output

After the publication gate passes, give named securities one of three actions:

- `条件买入`: evidence, sector trend, candidate score, causal thesis and backtest all pass.
- `观察等待`: the thesis may be valid but price, sector trend, valuation, catalyst or evidence is not yet sufficient.
- `回避`: fundamental review fails, risk is very high, valuation is explicitly expensive without an offsetting verified mechanism, or the quantitative structure is weak.

This skill does not place orders or promise returns. State that the recommendation is research-based and conditional. The investor remains responsible for the decision and losses.

## Suitability

Ask for risk capacity, horizon, liquidity needs, existing concentration and maximum acceptable drawdown when the user requests personalized allocation. If these are unavailable, use the `balanced` general profile and label the result `non_personalized_default`.

Default profiles:

| Profile | Single-name cap | Theme cap | Maximum accepted timing-stop distance | Per-trade risk budget |
|---|---:|---:|---:|---:|
| conservative | 3% | 10% | 10% | 0.25% |
| balanced | 5% | 20% | 12% | 0.50% |
| aggressive | 8% | 30% | 15% | 0.75% |

The internal 5%/6%/8% `risk_floor_pct` values only bound a volatility fallback shown when point-in-time timing data is absent. They are not minimum buy-gate distances. A valid timing document is mandatory for `条件买入`, and its positive stop distance only needs to stay at or below the profile cap.

Position caps are percentages of investable assets, not instructions to deploy all capital. Do not recommend leverage, margin financing or options unless the user explicitly requests them and the relevant suitability workflow is completed.

Final position is the smallest of the conviction-based allocation, single-name cap, remaining theme cap and `per-trade risk budget / technical stop distance`. Never increase the stop distance to justify a larger position.

## Recommendation gate

Require all of the following for `条件买入`:

- finalized blogger-logic brief with no unresolved research marker;
- at least three verified facts in the evidence pack and candidate-specific fact IDs;
- at least 20 walk-forward evaluation periods, 30 candidate observations and positive modeled costs;
- forecast and selection coverage of at least 75%;
- candidate factor score of at least 65;
- 20-day sector score of at least 55;
- positive mean excess return and historical excess hit rate of at least 50%;
- `fundamental_verdict=pass`;
- `catalyst_status=confirmed|plausible`;
- `valuation_verdict=attractive|fair`, or `not_meaningful` for loss-making biotech with an explicitly verified pipeline thesis;
- `risk_level` no higher than `high`.
- current `trade_timing` state is `triggered|retest` for that exact security;
- the same security's `model.timing-backtest/1` gate is `usable` with next-session execution, positive costs and slippage;
- that timing backtest has a predeclared evaluation start and excludes incomplete terminal holding periods;
- technical stop distance is positive and no wider than the selected profile's risk cap.

Anything weaker becomes `观察等待` or `回避`; do not lower the gate just to produce a pick.

## Entry and exit

- Read `technical-timing-workflow.md` and generate the asset-level timing documents before naming an entry.
- Freeze a signal at the close and state that the earliest modeled execution is the next session; never imply same-bar fills.
- Avoid chasing when `state=extended` or price is more than 8% above MA20; wait for a pullback, consolidation or independently confirmed retest.
- When `state=triggered|retest`, split the allowed risk-budget position into two or three entries only if live liquidity and price still satisfy the trigger.
- When price is below MA20 or the high-timeframe state is bearish, require a new completed setup rather than merely a one-day reclaim.
- Use the timing report's ATR/prior-channel stop reference. The risk profile caps acceptable stop distance and position; it does not manufacture a universal stop.
- Treat an upside level as a review point, not a guaranteed target price.
- Exit or reassess when the stated fundamental invalidation occurs, the catalyst fails, disclosure contradicts the thesis, or the 20-day sector regime falls below the defined threshold.

Do not report a local-storage refresh comparison, a fixed-weight score, or an in-sample chart pattern rate as “accuracy”. Only publish a historical rate from a dated, non-overlapping, point-in-time sample with the stated horizon, benchmark, costs and minimum sample.

## Required final format

```text
Risk profile / whether personalized:
As-of date / horizon:
Sector view:
Timing state / asset-specific timing backtest:
Conditional buys:
  code, name, thesis, entry condition, position cap, stop/review reference,
  catalyst, invalidation, supporting fact IDs
Watch list:
Avoid list:
Backtest evidence and limitations:
Risk statement:
```

The CSRC suitability framework emphasizes understanding investor circumstances, matching risk-bearing capacity and fully disclosing risks. Use this policy as a research-output safeguard, not as a claim that Codex is a licensed securities institution: <https://www.csrc.gov.cn/csrc/c106256/c1653849/content.shtml>.
