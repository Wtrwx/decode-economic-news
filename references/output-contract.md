# Output Contract

## Source document

Every collector returns `evidence.source/1`:

```json
{
  "schema": "evidence.source/1",
  "provider": {
    "id": "world-bank",
    "publisher": "World Bank",
    "authority_score": 0.98,
    "endpoint_stability": 0.97
  },
  "retrieval": {
    "status": "fresh",
    "retrieved_at": "ISO-8601",
    "source_url": "https://...",
    "raw_sha256": "hex"
  },
  "facts": [],
  "warnings": []
}
```

Each fact requires `fact_id`, `claim`, `publisher`, `source_url`, `retrieved_at` and `period`. Numeric facts also require `value` and `unit`. Add `vintage` when revisions matter.

Primary news collection uses `fetch_newsnook_news.py`, which returns `evidence.source/1` plus `collection.schema=newsnook.api.collection/1`. The collection block records the NewsNook API base, reviewed source-registry commit, selected source IDs, query, parser, raw checksum, item counts and an explicit success/failure outcome for every source. Facts preserve the upstream publisher and original URL; `retrieved_via` identifies the NewsNook endpoint.

`api_observed_news_item` means the API response included a usable attributed excerpt. Google News remains `discovery_lead`; an item with no excerpt is `publisher_index` and metadata-only.

Browser fallback uses `browser.news.capture/1` as documented in [browser-news-workflow.md](browser-news-workflow.md). `build_browser_news_source.py` converts it to `evidence.source/1`, removes tracking parameters, distinguishes discovery results from opened original pages, truncates excerpts and excludes browser session data.

`build_news_coverage.py --newsnook ...` returns `news.collection.coverage/2`. It passes without browser input when the NewsNook primary gate is sufficient. If the API gate fails or a fallback reason is supplied, the browser plan/capture becomes mandatory and must pass its explicit publisher gate. Browser-only `browser.news.coverage/1` remains accepted for backward compatibility, but new workflows should use version 2.

## Signal document

Every deterministic indicator script returns `evidence.signal/1` with `signal_type`, `method_version`, `as_of`, `values`, `inputs`, `coverage`, and `warnings`.

`compute_news_reaction.py` accepts a small `news.event/1` input with `event_date`, `headline_direction` and `event_stage`; optional fields may include `event_id`, `title`, `source_url`, `published_at` and analyst notes. Direction describes the text, not the expected return. Event stage must preserve the difference between rumor/proposal/draft/announcement/approval/effect/enforcement/result.

## Evidence pack

`build_evidence_pack.py` combines documents into `evidence.pack/1`. It stores input file checksums, leaves source documents intact, deduplicates fact IDs and carries every warning forward.

## Compatibility

- Add fields without changing the schema version when old consumers can ignore them.
- Increment the schema or `method_version` when semantics, formulas or units change.
- Do not encode missing observations as zero.

## Market history

`fetch_price_history.py` returns `market.history/1`. Each series contains a ticker, optional quote snapshot, retrieval metadata and ascending daily bars. A bar contains `date`, `open`, `close`, `high`, `low` and `volume`. The `adjustment` field must state `qfq` or `none`. When the input is `sector.universe/1`, preserve its sector, benchmark, market benchmark and fallback status in `universe_context`; downstream forecast, selection and backtest CLIs may infer benchmark codes from this context.

`fetch_cross_market_history.py` also returns `market.history/1`, with `market`, `currency`, exchange timezone, proxy role and `mapping_strength` for U.S./Korean series. Its adjusted-close convention is `vendor_adjusted_close`. Preserve the preset, foreign market benchmarks, transmission variables, event leaders and mapping caveat in `universe_context`.

`compute_cross_market_signal.py` returns `evidence.signal/1` with `signal_type=cross_market_readthrough`. It reports foreign sector-relative impulses, strictly-prior-close lead samples, historical correlations/direction agreement and A-share acceptance/rejection. These fields are descriptive overlays, not forecast probabilities.

## Sector presets

`sector.presets/2` stores named presets separately from reusable research profiles. Every preset requires aliases, a tradable benchmark proxy, a market benchmark, a dated seed universe and a valid `research_profile` key. Seed members are a disclosed availability fallback, not a claim that they remain constituents. Custom keyword universes must supply a benchmark proxy explicitly.

## Forecast and selection signals

Sector forecasts and stock selections remain compatible with `evidence.signal/1`:

- `signal_type=sector_trend_forecast`: values contain separate `5d` and `20d` scores, regimes, factors and coverage.
- `signal_type=stock_selection`: values contain the exact eligible universe, factor weights and ranked candidates.

`model.backtest/1` stores walk-forward settings, evaluation dates, cost assumptions, aggregate returns, score buckets and warnings. Do not merge a backtest into an evidence pack without carrying its survivorship and sample-size warnings.

`model.signal-backtest/1` tests the sector score itself. Its gate is `usable` only when the total sample is adequate, score-to-excess-return monotonicity is positive, and the current score bucket supports the claimed direction. Otherwise the mandatory status is `abstain`.

## Trade timing

`compute_trade_timing.py` returns `evidence.signal/1` with `signal_type=trade_timing`. `values.assets` contains an explicit outcome for every requested code, completed-week and daily trend states, prior-bar 20/55-day Donchian levels, volume/OBV confirmation, relative strength, ATR/channel risk references, an execution clock and an entry state. The Donchian decision threshold must exclude the decision bar. Missing observations remain null and missing series use an explicit `missing_series` state.

`backtest_trade_timing.py` returns `model.timing-backtest/1`. Each asset has its own trades, metrics and `usable|abstain` gate. The method freezes a signal at the close, enters no earlier than the next session open, prevents overlapping trades per asset, checks gap/intraday stops and deducts configured costs and slippage. A `usable` gate requires a predeclared `settings.start`; signals without a complete configured holding horizon at the data boundary are excluded and recorded in `period.skipped_incomplete_horizon`. `settings.terminal_incomplete_horizons` must be `excluded`. Preserve warnings for limit-lock execution, point-in-time constituents and corporate-action conventions.

Timing states are entry overlays, not probabilities. A `triggered` or `retest` state may feed a conditional recommendation only when the same asset's timing-backtest gate is `usable`, its evaluation window is predeclared and complete, and its risk distance fits the selected suitability profile.

## Recommendation

`build_recommendation.py` returns `stock.recommendation/1` with:

- `suitability`: risk profile, personalization status and position caps;
- `sector_view`: as-of date, horizon and direction score;
- `recommendations`: named actions, conviction, entry condition, position cap, risk reference, thesis, catalyst, invalidation and fact IDs;
- `portfolio_controls`: total recommended theme exposure and review triggers;
- `warnings`: model, data, backtest and suitability limitations.

Version `conditional-recommendation/2.0` also requires asset-level `timing_evidence`, a positive per-trade `risk_budget_pct`, a next-session execution clock and risk-budget position sizing for every `条件买入`.

Only a finalized `prediction.brief/1` may feed this output. Preserve all upstream hashes.
