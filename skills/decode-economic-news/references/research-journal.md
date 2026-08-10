# Research Journal

Use the journal to preserve what was known, what was concluded and what happened later. Keep the original run immutable; add outcome reviews instead of rewriting history.

## Contents

1. Storage model
2. Before research
3. Save a completed run
4. Read and compare runs
5. Add an outcome review
6. Measure improvement
7. Integrity and safety

## 1. Storage model

Set one persistent archive outside the installed Skill so reinstalling or updating the Skill cannot remove research history:

```bash
export DECODE_ECONOMIC_NEWS_ARCHIVE=/absolute/workspace/path/research-journal
```

Without this variable, `research_journal.py` uses `work/research-journal` under the current directory.

The archive contains:

```text
research-journal/
├── objects/<prefix>/<sha256>             # deduplicated immutable artifacts
└── runs/<year>/<month>/<run-id>/
    ├── manifest.json                     # original conclusion and provenance
    └── reviews/<review-id>.json          # append-only later outcomes
```

`research.journal-run/1` stores topic, observation date, horizon, instruments, tags, stance, decision, thesis, review date and content-addressed artifacts. `research.journal-review/1` stores later returns, benchmark returns, thesis status, decision quality, notes and review artifacts.

## 2. Before research

Search by instrument, topic or tag before fetching the same evidence again:

```bash
python3 scripts/research_journal.py list --instrument 588080 --limit 10
python3 scripts/research_journal.py list --query 半导体 --tag semiconductor
```

Open a relevant run and locate an exact archived artifact:

```bash
python3 scripts/research_journal.py show <run-id>
python3 scripts/research_journal.py show <run-id> --artifact-role evidence-pack
```

Treat an old run as historical evidence, never as current data. Recheck staleness, observation dates, method versions and invalidation conditions before reusing it.

## 3. Save a completed run

Save after validators finish and before publishing a forecast, recommendation or source-intensive causal conclusion. Use the final machine-readable recommendation, finalized brief, forecast JSON or final Markdown as `--conclusion`. Attach every artifact that materially supported or constrained the conclusion.

```bash
python3 scripts/research_journal.py save \
  --topic '半导体板块未来20日' --as-of 2026-08-10 --horizon 20d \
  --instrument 512480 --tag semiconductor --tag after-close \
  --stance abstain --decision '观察等待' --confidence medium \
  --thesis '产业变量改善，但本地价格与走样本门禁尚未确认' \
  --review-date 2026-09-07 \
  --conclusion work/semiconductor-recommendation.json \
  --artifact evidence-pack=work/evidence-pack.json \
  --artifact forecast=work/semiconductor-forecast.json \
  --artifact selection=work/semiconductor-selection.json \
  --artifact selector-backtest=work/semiconductor-backtest.json \
  --artifact signal-backtest=work/semiconductor-signal-backtest.json \
  --artifact news-coverage=work/semiconductor-news-coverage.json \
  --artifact cross-market=work/semiconductor-cross-market-signal.json
```

At minimum preserve the conclusion, evidence pack, relevant signals, gate outputs and source-coverage result. For a named recommendation, also preserve the eligible universe, selection and both backtests. The command is idempotent when metadata and artifact hashes are identical.

## 4. Read and compare runs

```bash
python3 scripts/research_journal.py show <run-id> --json
python3 scripts/research_journal.py compare <older-run-id> <newer-run-id>
```

Compare observation date, method version, evidence schemas, stance, decision, thesis, gate state and the latest outcome review. Do not compare returns across different horizons or benchmarks without normalizing them first.

## 5. Add an outcome review

Never edit `manifest.json` to make an old conclusion look better. At the review date, append what actually happened:

```bash
python3 scripts/research_journal.py review <run-id> \
  --observed-at 2026-09-07 \
  --thesis-status partially_confirmed \
  --realized-return-pct 3.5 --benchmark-return-pct 1.0 \
  --decision-quality good \
  --note '产业数据改善，但价格确认比预期晚一周' \
  --artifact outcome-prices=work/semiconductor-review-history.json
```

Use `confirmed`, `partially_confirmed`, `refuted` or `unresolved` for thesis status. Judge decision quality separately from return: a disciplined abstention can be good even when price rises, and a weak process can make money by chance.

## 6. Measure improvement

```bash
python3 scripts/research_journal.py stats --group-by horizon
python3 scripts/research_journal.py stats --group-by tag --date-from 2026-01-01
```

Track review coverage before interpreting performance. Diagnose repeated errors by evidence gap, event-clock branch, source coverage, mapping strength, signal gate, valuation, catalyst timing and invalidation discipline. Change a method only after identifying a recurring error class; record a new `method_version` when semantics change.

## 7. Integrity and safety

```bash
python3 scripts/research_journal.py verify
```

Run verification before a large review or migration. It checks manifests, review links, object existence and SHA-256 hashes. The journal rejects obvious `.env` and secret files; still never archive credentials, cookies, browser storage, authorization headers, private suitability data or proxy secrets.
