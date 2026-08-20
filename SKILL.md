---
name: decode-economic-news
description: Research and explain economic, business, industrial-policy, company and capital-market events with reproducible NewsNook API-first news collection and browser fallback, data, sentiment, dynamic news-vs-momentum-vs-overseas priority, U.S./Korean peer read-through, named A-share/ETF outlooks, multi-sector forecasts, multi-timeframe technical timing, walk-forward backtests, stock screening, conditional recommendations, and persistent retrieval/comparison/automatic outcome review of prior research runs. Use for 财经新闻解读、新闻API采集、浏览器fallback、大A/A股、个股或ETF未来走势、美股韩股联动、跨市场映射、A股行业轮动、科技/半导体/创新药/新能源车/光伏/消费/白酒/金融/券商/军工/有色/煤炭/电力/农业/地产/基建/红利等板块走势、实时买卖点、选股、荐股、仓位与止损、股票预测、题材热度、财经口播、历史结论读取、到期结论检查、自动复盘、预测后验、研究记录比较，以及要求采用“反常现象—数据—利益—深层原因—影响”逻辑的任务。
---

# Decode Economic News

Build a source-grounded explanation before drafting commentary. Treat Python outputs as evidence, not as conclusions.

## Installation and Required Skill

Require `$a-stock-data` version 3.3.0 or newer for A-share quotes, fundamentals, fund flow, announcements, market mood and ETF options. Read the bilingual [README.md](README.md) and the machine-readable [skill-dependencies.json](skill-dependencies.json) before installing or redistributing this Skill.

Prefer a reviewed local dependency copy:

```bash
python3 scripts/install.py --a-stock-data-source /absolute/path/to/a-stock-data
```

If the dependency is already installed in the target Codex home, run `python3 scripts/install.py`. Only use `--fetch-a-stock-data` after the user explicitly accepts a mutable GitHub download. Use `--install-python-deps` to install the full A-share adapter package set into the current Python interpreter. The installer must validate the dependency before installing this Skill, exclude secrets/caches/work data, preserve the previous installation as a timestamped backup and emit a SHA-256-bearing JSON report.

Do not claim full A-share coverage when `$a-stock-data` or its required runtime packages are missing. Continue only with the available built-in adapters and disclose the degraded state.

## Workflow

1. Classify the request as company, industry, policy, macro, market, or mixed.
2. State the apparent contradiction as one question. Do not assume the answer.
3. For a named A-share or ETF outlook, first read [a-share-outlook-workflow.md](references/a-share-outlook-workflow.md), load [a-share-instrument-presets.json](references/a-share-instrument-presets.json), and run `build_a_share_outlook_plan.py`. Follow its event-clock branch instead of choosing news, foreign markets or momentum by habit. For a 5d/20d buy/sell-point question or named conditional recommendation, also read [technical-timing-workflow.md](references/technical-timing-workflow.md); completed weekly direction, daily trigger, next-session execution and asset-specific timing backtest are mandatory.
4. Read [source-catalog.md](references/source-catalog.md) and [newsnook-api-workflow.md](references/newsnook-api-workflow.md), then collect current news through NewsNook's API before considering browser use. Route by event origin: official releases lead scheduled/statutory events; NewsNook supplies publisher-attributed feeds and links for unscheduled news, exclusives, rumors, stakeholder reactions and unexplained price moves before official corroboration. Every selected NewsNook source must leave an explicit success/failure outcome. Use [browser-news-workflow.md](references/browser-news-workflow.md) only when the API gate fails, no relevant item exists, a material page needs lawful interactive rendering/login, or the user explicitly asks for browser collection. Use market portals only for data that official sources do not publish in a machine-friendly form.
   For any A-share or “大A” market question, also read [cross-market-readthrough.md](references/cross-market-readthrough.md) and check mapped U.S. and Korean peers unless the preset explicitly says no clean proxy exists.
5. Build `evidence_pack.json` with `build_evidence_pack.py` and validate it with `validate_evidence.py`.
6. Separate every material statement into fact, inference, opinion, or conditional forecast.
7. Map actors, goals, constraints, decisions and transmission effects.
8. Test at least one competing explanation or counterfactual.
9. Draft the requested outline, article, or spoken script. Cite fact IDs while reasoning; convert them to readable source links in the final output.
10. Run the final integrity checklist below.

Do not draft a confident causal story when evidence validation fails. Return missing evidence and research questions instead.

## Data Commands

Run commands from this skill directory.

```bash
# Official international indicators
python3 scripts/fetch_world_bank.py --country CHN \
  --indicator NY.GDP.MKTP.KD.ZG --start 2015 --end 2025 \
  --output work/world-bank.json

# FRED requires FRED_API_KEY
python3 scripts/fetch_fred.py --series-id DGS10 --start 2024-01-01 \
  --output work/fred.json

# A-share breadth, limit-up ecology and index momentum
python3 scripts/fetch_a_share_sentiment.py --output work/a-share-snapshot.json
python3 scripts/compute_market_mood.py work/a-share-snapshot.json \
  --output work/market-mood.json

# Primary NewsNook API collection; NewsNook is transport, not publisher authority
python3 scripts/fetch_newsnook_news.py --preset finance \
  --query 'semiconductor export controls' --output work/newsnook-news.json
python3 scripts/build_news_coverage.py --newsnook work/newsnook-news.json \
  --output work/news-coverage.json

# Supplemental global discovery leads; GDELT is not a substitute for an original article
# Optional proxy: inject GDELT_PROXY_URL at runtime; plain socks5 is upgraded to socks5h.
# Never store proxy credentials in this skill.
python3 scripts/fetch_gdelt_news.py --query 'semiconductor export controls' \
  --timespan 7d --max-records 50 --output work/gdelt-news.json

# Browser fallback only when the NewsNook gate identifies a gap.
# Create browser-capture.json with explicit outcomes for every planned fallback publisher.
python3 scripts/list_browser_news_sites.py --tier core \
  --topic 'semiconductor export controls' --output work/browser-search-plan.json
python3 scripts/build_browser_news_source.py work/browser-capture.json \
  --output work/browser-news.json
python3 scripts/build_news_coverage.py --newsnook work/newsnook-news.json \
  --plan work/browser-search-plan.json --capture work/browser-capture.json \
  --output work/news-coverage.json

# Original U.S. filings; identify the caller per SEC policy
export SEC_USER_AGENT='Research Team contact@example.com'
python3 scripts/fetch_sec_filings.py --ticker NVDA --form 8-K --form 10-Q \
  --output work/sec-filings.json

# Innovative-drug pipeline and official regulator/energy release feeds
python3 scripts/fetch_clinical_trials.py --intervention 'drug name' \
  --page-size 100 --output work/trials.json
python3 scripts/fetch_official_feed.py --list-presets
python3 scripts/fetch_official_feed.py --preset fda-press \
  --output work/fda-press.json

# Text signals and topic attention
python3 scripts/compute_text_signals.py article.txt --output work/text-signals.json
python3 scripts/compute_topic_heat.py news.jsonl --keyword 新能源 --keyword 出口 \
  --output work/topic-heat.json

# Compare a classified source event with asset/sector/market reactions
python3 scripts/compute_news_reaction.py event.json work/technology-history.json \
  --asset-code 688001 --sector-code 515000 --benchmark-code 000300 \
  --output work/news-reaction.json

# Multi-timeframe technical timing; use a long history for the asset gate.
# Freeze the evaluation start before viewing outcomes; prior channels exclude the decision bar.
python3 scripts/compute_trade_timing.py work/technology-history.json \
  --asset-code 688001 --asset-code 688002 --benchmark-code 515000 \
  --output work/technology-trade-timing.json
python3 scripts/backtest_trade_timing.py work/technology-history.json \
  --asset-code 688001 --asset-code 688002 --benchmark-code 515000 \
  --horizon 20 --start 2022-01-01 --cost-bps 20 --slippage-bps 10 \
  --output work/technology-timing-backtest.json

# U.S./Korean same-sector overlay for an A-share question
# Optional runtime-only proxy: CROSS_MARKET_PROXY_URL; never store credentials.
python3 scripts/fetch_cross_market_history.py --preset semiconductor --days 360 \
  --output work/semiconductor-cross-market-history.json
python3 scripts/compute_cross_market_signal.py work/semiconductor-history.json \
  work/semiconductor-cross-market-history.json --a-sector-code 512480 \
  --a-market-code 000300 --output work/semiconductor-cross-market-signal.json

# Evidence contract
python3 scripts/build_evidence_pack.py --topic "主题" \
  --source work/world-bank.json --signal work/market-mood.json \
  --output work/evidence-pack.json
python3 scripts/validate_evidence.py work/evidence-pack.json

# Check configured endpoints without drafting
python3 scripts/source_health.py --output work/source-health.json
```

All network scripts cache raw responses, retry transient failures, record checksums and surface stale/degraded results. Never suppress an empty or malformed response as success. Treat NewsNook as an API transport and preserve each upstream publisher and original URL. Treat Google News/GDELT/browser search entries as discovery leads, NewsNook items with excerpts as attributed API observations, browser-opened pages as visible-page observations, feed entries as publication indexes, filing metadata as submission facts, registry status as sponsor-submitted data, and Yahoo Finance charts as undocumented auxiliary market data; verify linked or authoritative source text before making a central substantive claim. Read [newsnook-api-workflow.md](references/newsnook-api-workflow.md) before news collection; read [browser-news-workflow.md](references/browser-news-workflow.md) and [blogger-news-sites.json](references/blogger-news-sites.json) only when browser fallback is triggered.

## Research Journal and Review

Read [research-journal.md](references/research-journal.md) before saving or reusing prior research. Prefer a persistent archive outside the installed Skill:

```bash
export DECODE_ECONOMIC_NEWS_ARCHIVE=/absolute/workspace/path/research-journal
python3 scripts/research_journal.py list --instrument 588080 --limit 10
python3 scripts/research_journal.py show <run-id>
python3 scripts/research_journal.py compare <older-run-id> <newer-run-id>
python3 scripts/research_journal.py due --days-ahead 7
python3 scripts/auto_review_research.py --history-dir /absolute/workspace/work/runs
python3 scripts/research_journal.py stats --group-by tag
python3 scripts/research_journal.py verify
```

Keep each original run immutable. Use `research_journal.py due` to read scheduled conclusions and their archived gate snapshots. Use `auto_review_research.py` only with point-in-time price history covering the full horizon; let it append price outcomes and exact history artifacts. If bars, instruments or horizons are insufficient, preserve the blocked report and do not invent a review. Automatic review evaluates returns and gate compliance; manually review causal, fundamental and source-quality claims. Never rewrite the old conclusion after observing the result.

## Forecasting and Stock Selection

Read [forecasting-policy.md](references/forecasting-policy.md) before producing any market forecast or candidate list. Read [sector-presets.json](references/sector-presets.json) for supported aliases, ETF proxies, seed universes and sector-specific research profiles. Read [technical-timing-workflow.md](references/technical-timing-workflow.md) before any named 5d/20d entry, exit, real-time buy/sell-point or conditional-buy output. The audited external reference and adopted/rejected design choices are recorded in [trend-analysis-v4-reference-audit.md](references/trend-analysis-v4-reference-audit.md); never run code from that reference tree.

For a named A-share or ETF, build the order before fetching deeply:

```bash
python3 scripts/build_a_share_outlook_plan.py --code 588080 \
  --horizon 20d --session after_close --event-state unknown \
  --output work/588080-outlook-plan.json
```

The immutable first step is identity and live exposure. The second is an event-clock gate. With no confirmed material event, inspect local relative momentum and breadth before deep news research to expose what is already priced; with a confirmed material event, open the original source first and then measure the pre-event price state. Momentum measures expectations and timing, original sources establish mechanism, and overseas peers test a shared variable. None is a standalone direction signal.

For an ETF, date the current index constituents separately from the fund's latest disclosed holdings. Choose foreign proxies from verified live industry weights. If weights are unavailable or stale, present relevant U.S./Korean mappings separately and never calculate a spurious blended score. Use `$a-stock-data` for ETF flows, premium/discount, options IV/skew/OI and other A-share positioning layers when available; omit unavailable fields explicitly.

For A-share requests, load [cross-market-presets.json](references/cross-market-presets.json) and generate a cross-market overlay. Start with the previous U.S. close and previous Korean close; never use a Korean end-of-day bar as information available at the same morning's A-share open. Explain the overseas event, shared structural variable, industrial linkage, A-share acceptance/rejection and local modifier. Do not add the overlay mechanically to the direction score without a point-in-time walk-forward test of that exact rule.

```bash
# Inspect every configured sector and benchmark
python3 scripts/fetch_sector_universe.py --list-presets

# Discover a dynamic sector universe; fall back to a dated seed universe if the portal is unavailable
SECTOR=semiconductor
python3 scripts/fetch_sector_universe.py --preset "$SECTOR" \
  --output "work/$SECTOR-universe.json"
# Add --seed-only when the portal is rate-limited; the output will disclose the seed date.

# Fetch forward-adjusted daily bars for the sector ETF, market benchmark and constituents
python3 scripts/fetch_price_history.py --universe "work/$SECTOR-universe.json" \
  --days 3000 --output "work/$SECTOR-history.json"

# The history embeds the preset benchmark, so downstream commands infer it automatically
python3 scripts/forecast_sector.py "work/$SECTOR-history.json" \
  --output "work/$SECTOR-forecast.json"

# Rank candidates, then test the exact ranking rule with expanding walk-forward windows
python3 scripts/select_stocks.py "work/$SECTOR-history.json" \
  --top 10 --output "work/$SECTOR-selection.json"
python3 scripts/backtest_selector.py "work/$SECTOR-history.json" \
  --horizon 20 --top 10 --cost-bps 20 \
  --output "work/$SECTOR-backtest.json"
python3 scripts/backtest_sector_signal.py "work/$SECTOR-history.json" \
  --horizon 20 --output "work/$SECTOR-signal-backtest.json"

# Timing is a separate entry gate, not an additive forecast factor.
# Repeat --asset-code for every candidate that may be named as a conditional buy.
python3 scripts/compute_trade_timing.py "work/$SECTOR-history.json" \
  --asset-code 688001 \
  --output "work/$SECTOR-trade-timing.json"
python3 scripts/backtest_trade_timing.py "work/$SECTOR-history.json" \
  --asset-code 688001 --horizon 20 --start 2022-01-01 \
  --cost-bps 20 --slippage-bps 10 \
  --output "work/$SECTOR-timing-backtest.json"

# Convert quantitative leads into the corpus-derived causal research scaffold
python3 scripts/build_prediction_brief.py --topic "$SECTOR 板块未来20日" \
  --preset "$SECTOR" --forecast "work/$SECTOR-forecast.json" \
  --selection "work/$SECTOR-selection.json" --backtest "work/$SECTOR-backtest.json" \
  --cross-market-signal "work/$SECTOR-cross-market-signal.json" \
  --news-coverage "work/$SECTOR-news-coverage.json" \
  --signal-backtest "work/$SECTOR-signal-backtest.json" \
  --output "work/$SECTOR-brief.json"
python3 scripts/validate_prediction.py --forecast "work/$SECTOR-forecast.json" \
  --selection "work/$SECTOR-selection.json" --backtest "work/$SECTOR-backtest.json" \
  --brief "work/$SECTOR-brief.json"
```

Configured presets include `technology`, `semiconductor`, `innovative-drug`, `new-energy-vehicle`, `photovoltaic`, `consumer`, `liquor`, `finance`, `brokerage`, `defense`, `nonferrous`, `coal`, `electric-power`, `agriculture`, `real-estate`, `infrastructure` and `dividend`.

For any unlisted theme, call `fetch_sector_universe.py` with one or more `--keyword` values plus `--benchmark-code` and optional `--benchmark-name`; use `--preset custom` when building its research brief. Never describe an uncalibrated direction score as a probability. Report the as-of date, horizon, coverage, backtest period, costs, sample size, survivorship bias and invalidation conditions with every forecast.

Do not write the final prediction directly from the ranking. Run `build_prediction_brief.py`, then resolve every `research_required` field with dated evidence. Apply the same contradiction → actor incentives → structural cause → transmission → competing explanation → second-order effect → conditional conclusion architecture used for commentary.

## Conditional Recommendations

Read [recommendation-policy.md](references/recommendation-policy.md) before recommending named securities. Recommendations are allowed after the research gate passes.

1. Complete every `research_required` field in the prediction brief with dated evidence. Add `supporting_fact_ids`, `fundamental_verdict`, `valuation_verdict`, `catalyst_status` and `risk_level` for every named candidate.
2. Finalize the brief. This computes the gate; do not set `ready=true` manually.
3. Generate recommendations with an explicit risk profile. When the user provides none, use `balanced` and label it non-personalized.
4. Validate the recommendation in publication mode before showing named actions.

```bash
python3 scripts/finalize_prediction_brief.py --brief work/technology-brief-completed.json \
  --forecast work/technology-forecast.json --selection work/technology-selection.json \
  --evidence-pack work/evidence-pack.json --backtest work/technology-backtest.json \
  --news-coverage work/technology-news-coverage.json \
  --signal-backtest work/technology-signal-backtest.json \
  --output work/technology-brief-final.json
python3 scripts/build_recommendation.py --forecast work/technology-forecast.json \
  --selection work/technology-selection.json --backtest work/technology-backtest.json \
  --brief work/technology-brief-final.json \
  --trade-timing work/technology-trade-timing.json \
  --timing-backtest work/technology-timing-backtest.json \
  --risk-profile balanced \
  --output work/technology-recommendation.json
python3 scripts/validate_prediction.py --forecast work/technology-forecast.json \
  --selection work/technology-selection.json --backtest work/technology-backtest.json \
  --brief work/technology-brief-final.json \
  --recommendation work/technology-recommendation.json --publication
```

The final answer may say `条件买入`, `观察等待`, or `回避`. For every `条件买入`, give the as-of date, horizon, thesis, evidence, entry condition, maximum position, stop/review level, catalyst, invalidation and data limitations. Never imply guaranteed return, execute a trade, or fabricate suitability information.

## Reasoning Contract

Use this internal outline:

```text
Contradiction:
Verified facts:
Actors and incentives:
Surface explanations:
Structural constraints:
Causal chain: shock -> constraint -> decision -> transmission -> result
Competing explanation:
Second-order effects:
Conditional conclusion:
Missing evidence:
```

Read [logic-model.md](references/logic-model.md) before causal analysis. Read [topic-archetypes.md](references/topic-archetypes.md) for the selected topic class.

## Evidence Policy

Read [source-policy.md](references/source-policy.md) before collecting current or high-stakes data. Read [indicator-definitions.md](references/indicator-definitions.md) before interpreting sentiment scores. Use [output-contract.md](references/output-contract.md) when adding a new adapter or consuming its JSON.
For the GitHub/API selection record and known stability limits, read [interface-provenance.md](references/interface-provenance.md).

Apply these rules:

- Prefer publisher authority over convenient aggregation.
- Record the observation period separately from retrieval time.
- Preserve raw response checksums and revision/vintage fields when available.
- Corroborate surprising numerical claims with a second independent source.
- Label undocumented public endpoints as market auxiliary sources.
- Treat sentiment, attention and fund-flow labels as signals, never as proof of causality.
- Do not convert correlation, timing or stakeholder benefit into intent without evidence.

## Drafting

Read [writing-style.md](references/writing-style.md) only after the evidence and causal outline are complete.

For spoken commentary, default to:

1. Counterintuitive event or numerical contrast.
2. Minimum context and exact date.
3. Common explanation and its limitation.
4. Actor incentives and the main mechanism.
5. One calculation, comparison, or counterfactual.
6. Second-order effect.
7. Conditional conclusion.

Do not copy signature phrases from the corpus mechanically. Reproduce the reasoning architecture, not a person's verbal fingerprint.

## Integrity Checklist

- Every precise current number has a source and period.
- Facts, inferences and opinions remain distinguishable.
- The causal chain contains no unexplained jump.
- At least one plausible rival explanation is addressed.
- Forecasts state conditions and invalidation signals.
- Stock screens state the universe, as-of date, horizon and exclusion rules.
- Backtests use only information available at each historical decision date and include costs.
- Historical hit rates are omitted when the walk-forward sample is insufficient.
- Every selected NewsNook API source has an explicit success/failure outcome; if fallback is triggered, every planned browser publisher has an explicit opened/no-result/restricted/failed outcome. A plan alone is not coverage.
- Browser collection is skipped when NewsNook/API evidence is sufficient, unless the user explicitly requested a browser or a material claim still needs lawful visible-page confirmation.
- A raw sector score is translated into a directional view only when `model.signal-backtest/1` says `usable`; otherwise the conclusion is `abstain`.
- Recommendations match the stated or explicitly defaulted risk profile.
- Every conditional buy has a position cap, entry rule, exit/invalidation rule and review date.
- Every conditional buy has `trade_timing.state=triggered|retest`, a same-asset `model.timing-backtest/1` gate of `usable`, a predeclared evaluation start, complete terminal holding horizons, a next-session execution clock and risk-budget position sizing. An all-history gate with no `start` must abstain.
- Donchian thresholds exclude the decision bar; unfinished weekly bars are provisional and same-bar fills are prohibited.
- Fixed-weight composites, local-refresh "accuracy", price-proxy CAN SLIM, chart-pattern targets and unvalidated Chan/MACD/RSI/KDJ labels cannot override `abstain`.
- Market mood and text sentiment are supporting signals, not standalone recommendation grounds.
- Stale, degraded or single-source evidence is disclosed.
- Every A-share outlook states the mapped U.S./Korean observation date, shared driver, mapping strength and whether A-shares accepted or rejected the foreign move; omit unavailable/false analogs explicitly.
- Every named A-share/ETF outlook states the event-clock branch and why news, local price state or overseas markets came first.
- Every ETF outlook states constituent and fund-holding dates, concentration and whether foreign mappings were exposure-weighted or reported separately.
