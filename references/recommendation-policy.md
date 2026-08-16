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

| Profile | Single-name cap | Theme cap | Technical risk band |
|---|---:|---:|---:|
| conservative | 3% | 10% | 5–10% |
| balanced | 5% | 20% | 6–12% |
| aggressive | 8% | 30% | 8–15% |

Position caps are percentages of investable assets, not instructions to deploy all capital. Do not recommend leverage, margin financing or options unless the user explicitly requests them and the relevant suitability workflow is completed.

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

Anything weaker becomes `观察等待` or `回避`; do not lower the gate just to produce a pick.

## Entry and exit

- Avoid chasing when price is more than 8% above MA20; wait for a pullback or breakout retest.
- When price is near MA20, split the position into two or three entries.
- When price is below MA20, require a reclaim with volume confirmation.
- Derive a technical risk reference from recent volatility, capped by the risk-profile band. Combine it with MA60 where available.
- Treat an upside level as a review point, not a guaranteed target price.
- Exit or reassess when the stated fundamental invalidation occurs, the catalyst fails, disclosure contradicts the thesis, or the 20-day sector regime falls below the defined threshold.

## Required final format

```text
Risk profile / whether personalized:
As-of date / horizon:
Sector view:
Conditional buys:
  code, name, thesis, entry condition, position cap, stop/review reference,
  catalyst, invalidation, supporting fact IDs
Watch list:
Avoid list:
Backtest evidence and limitations:
Risk statement:
```

The CSRC suitability framework emphasizes understanding investor circumstances, matching risk-bearing capacity and fully disclosing risks. Use this policy as a research-output safeguard, not as a claim that Codex is a licensed securities institution: <https://www.csrc.gov.cn/csrc/c106256/c1653849/content.shtml>.
