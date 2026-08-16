# Indicator Definitions

## Market mood

The market mood score is a transparent descriptive composite, not a trading signal.

### Breadth

```text
advance_ratio = advances / (advances + declines)
breadth_score = 100 * advance_ratio
```

Ignore unchanged securities in the denominator. Warn when fewer than 100 securities are observed.
The bundled collector uses Shanghai Composite and Shenzhen Component index-level advancing/declining counts and therefore excludes the Beijing Stock Exchange.

### Limit-up ecology

```text
break_rate = broken_limit / (limit_up + broken_limit)
balance = 50 + 50 * (limit_up - limit_down) / (limit_up + limit_down + 20)
break_quality = 100 * (1 - break_rate)
height_score = min(100, 20 * max_limit_height)
limit_ecology = 0.40*balance + 0.35*break_quality + 0.25*height_score
```

Use the exchange-specific limit rule when identifying individual continuations. A simple 9.8% threshold is only a broad-market approximation.

### Momentum

Map the equal-weight mean return of the configured broad indices from -4%..+4% to 0..100, with 0% equal to 50.

### Continuation

Use the share of yesterday's limit-up pool that remains at or above the configured continuation threshold. If unavailable, omit and reweight rather than substituting zero.

### Composite

Default available-component weights:

```text
breadth 0.35
limit_ecology 0.35
momentum 0.20
continuation 0.10
```

Renormalize over available components. Return component coverage and confidence. Version any change to formulas or weights.

## Text signals

- Polarity: normalized positive minus negative phrase matches.
- Uncertainty: uncertainty matches per 1,000 comparison characters.
- Urgency: urgency matches per 1,000 comparison characters.
- Causal density: explicit causal connector matches per 1,000 characters.
- Evidence density: number/date/source-language matches per 1,000 characters.

Dictionary scores are interpretable but context-insensitive. They do not resolve negation, sarcasm or target-specific stance without additional analysis.

## Topic heat

- Attention velocity: last-24-hour unique article count relative to the prior six-day daily average.
- Source diversity: unique publishers among deduplicated articles.
- Recency: share of last-24-hour items published in the last hour.
- Duplicate ratio: removed duplicates divided by matching items.

Keep attention separate from positive/negative sentiment.

## News-price reaction

Classify the source text before looking at returns: headline direction (`positive`, `negative`, `mixed`, `neutral`) and event stage (`rumor`, `proposal`, `draft`, `announced`, `approved`, `effective`, `enforced`, `result`). Then compare asset returns with the sector proxy when available, otherwise the broad benchmark.

- `positive_rejected`: positive text but first-day relative return is at most -0.75 percentage point.
- `negative_absorbed`: negative text but first-day relative return is at least +0.75 percentage point.
- `positive_confirmed` / `negative_confirmed`: text direction and first-day relative return agree beyond the same threshold.
- `ambiguous`: the threshold is not met or the direction is mixed/neutral.

Flag a possible priced-in move when the asset already moved at least 2% in the same direction during the prior five sessions. Flag a reversal when 1-day and 5-day relative returns have opposite signs and the 5-day magnitude reaches 0.75 percentage point. These are research prompts, not causal findings or return probabilities. Daily bars also cannot resolve whether a release arrived before, during or after the session.

## Sector trend forecast

The 5-day and 20-day scores are weighted, bounded summaries of price/volume evidence. Inputs include benchmark momentum, MA20/MA60 structure, relative strength versus the market benchmark, annualized 20-day volatility and constituent breadth. Missing components are omitted and weights are renormalized. Report coverage.

Regimes:

```text
score >= 65: 偏强
score <= 35: 偏弱
otherwise: 震荡/分歧
```

These thresholds are descriptive model states, not return probabilities.

## Stock selection score

Use the weights in [forecasting-policy.md](forecasting-policy.md). Each raw factor is mapped to 0–100 with declared bounds, then combined. Return raw factors and component scores so the ranking can be reproduced. Ranking is only comparable within the same universe and as-of date.

## Walk-forward metrics

- `hit_rate`: share of selected candidate observations with future net return above zero.
- `excess_hit_rate`: share with future net return above the sector benchmark return.
- `mean_net_return`: arithmetic mean after configured round-trip cost.
- `mean_excess_return`: candidate net return minus benchmark return.
- `score_bucket`: historical outcomes grouped by the score frozen at each decision date.

Do not publish a bucket rate with fewer than 30 observations as a calibrated probability.

## Recommendation conviction score

The recommendation conviction score is an explanation and ranking aid, not a return probability:

```text
conviction = 0.45*stock_selection_score
           + 0.20*sector_20d_score
           + 0.15*fundamental_verdict_score
           + 0.10*catalyst_status_score
           + 0.05*valuation_verdict_score
           + 0.05*risk_quality_score
```

Research verdicts are mapped to fixed 0–100 values in `build_recommendation.py`. A high conviction score alone cannot create a recommendation: every publication and conditional-buy gate in [recommendation-policy.md](recommendation-policy.md) must also pass. Report the gate checks, position cap, entry condition, technical risk reference, invalidation signal and review date with every recommendation.
