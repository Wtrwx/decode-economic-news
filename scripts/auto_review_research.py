#!/usr/bin/env python3
"""Read due research conclusions and append price-grounded outcome reviews."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from evidence_core import CachedHttpClient, atomic_write_json, load_json, sha256_file, utc_now
from fetch_price_history import build_history, normalize_code
from research_journal import add_review, load_run, review_queue


OUTCOME_SCHEMA = "research.auto-review-outcome/1"
BATCH_SCHEMA = "research.auto-review-batch/1"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def horizon_days(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+)d\s*", value.casefold())
    return max(1, int(match.group(1))) if match else None


def _artifact_path(archive: Path, item: dict[str, Any]) -> Path | None:
    relative = Path(str(item.get("object_path") or ""))
    if relative.is_absolute() or not relative.parts or relative.parts[0] != "objects" or ".." in relative.parts:
        return None
    target = archive.resolve() / relative
    return target if target.is_file() else None


def archived_json_documents(archive: Path, run: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    documents = []
    for item in run.get("artifacts") or []:
        target = _artifact_path(archive, item)
        if target is None or item.get("media_type") != "application/json":
            continue
        try:
            document = load_json(target)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(document, dict):
            documents.append((str(item.get("role") or "artifact"), document))
    return documents


def benchmark_code_from_run(archive: Path, run: dict[str, Any]) -> str | None:
    candidates: list[Any] = []
    for role, document in archived_json_documents(archive, run):
        if role == "universe":
            candidates.extend([
                (document.get("market_benchmark") or {}).get("code"),
                ((document.get("universe_context") or {}).get("market_benchmark") or {}).get("code"),
            ])
    for _, document in archived_json_documents(archive, run):
        values = document.get("values") or {}
        inputs = document.get("inputs") or {}
        candidates.extend([
            (document.get("market_benchmark") or {}).get("code"),
            ((document.get("universe_context") or {}).get("market_benchmark") or {}).get("code"),
            (values.get("market_benchmark") or {}).get("code") if isinstance(values, dict) else None,
            (inputs.get("market_benchmark") or {}).get("code") if isinstance(inputs, dict) else None,
        ])
    for candidate in candidates:
        if candidate:
            try:
                return normalize_code(str(candidate))
            except ValueError:
                continue
    return None


def primary_instrument(run: dict[str, Any]) -> str | None:
    for value in run.get("instruments") or []:
        try:
            return normalize_code(str(value))
        except ValueError:
            continue
    return None


def collect_history_paths(paths: Iterable[Path], history_dir: Path | None = None) -> list[Path]:
    candidates = [path.expanduser().resolve() for path in paths]
    if history_dir:
        candidates.extend(history_dir.expanduser().resolve().rglob("*.json"))
    results = []
    seen = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            document = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("schema") == "market.history/1":
            results.append(path)
    return results


def load_history_series(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    series_by_code: dict[str, dict[str, Any]] = {}
    for path in paths:
        document = load_json(path)
        for item in document.get("series") or []:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            try:
                code = normalize_code(str(item["code"]))
            except ValueError:
                continue
            bars = sorted(
                [bar for bar in item.get("bars") or [] if isinstance(bar, dict) and bar.get("date")],
                key=lambda bar: str(bar["date"]),
            )
            if not bars:
                continue
            candidate = {
                "code": code,
                "name": item.get("name"),
                "bars": bars,
                "source_path": path,
                "source_sha256": sha256_file(path),
                "history_as_of": document.get("as_of") or bars[-1]["date"],
                "provider": document.get("provider") or {},
            }
            existing = series_by_code.get(code)
            if existing is None or (str(bars[-1]["date"]), len(bars)) > (
                str(existing["bars"][-1]["date"]), len(existing["bars"])
            ):
                series_by_code[code] = candidate
    return series_by_code


def _price_bar(bar: dict[str, Any]) -> tuple[str, float] | None:
    close = _finite(bar.get("close"))
    return (str(bar.get("date"))[:10], close) if close is not None and close > 0 else None


def _outcome_window(series: dict[str, Any], as_of: str, periods: int) -> dict[str, Any] | None:
    valid = [pair for pair in (_price_bar(bar) for bar in series["bars"]) if pair is not None]
    future = [pair for pair in valid if pair[0] > as_of[:10]]
    required_bars = periods + 1
    if len(future) < required_bars:
        return None
    entry_date, entry_close = future[0]
    exit_date, exit_close = future[periods]
    closes = [close for _, close in future[:required_bars]]
    peak = closes[0]
    max_drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        max_drawdown = min(max_drawdown, (close / peak - 1.0) * 100.0)
    return {
        "entry_date": entry_date,
        "entry_close": entry_close,
        "exit_date": exit_date,
        "exit_close": exit_close,
        "periods": periods,
        "return_pct": round((exit_close / entry_close - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(max_drawdown, 6),
    }


def _aligned_benchmark_window(series: dict[str, Any], entry_date: str, exit_date: str) -> dict[str, Any] | None:
    by_date = {
        pair[0]: pair[1]
        for pair in (_price_bar(bar) for bar in series["bars"])
        if pair is not None
    }
    if entry_date not in by_date or exit_date not in by_date:
        return None
    entry_close = by_date[entry_date]
    exit_close = by_date[exit_date]
    return {
        "entry_date": entry_date,
        "entry_close": entry_close,
        "exit_date": exit_date,
        "exit_close": exit_close,
        "return_pct": round((exit_close / entry_close - 1.0) * 100.0, 6),
    }


def _gate_supports_abstention(queue_item: dict[str, Any]) -> bool:
    snapshots = queue_item.get("artifact_snapshots") or {}
    for snapshot in snapshots.values():
        if not isinstance(snapshot, dict):
            continue
        gate = snapshot.get("gate") or {}
        if gate.get("status") == "abstain" or gate.get("ready") is False or gate.get("passed") is False:
            return True
        if snapshot.get("status") == "research_scaffold_not_publication_ready":
            return True
    return False


def evaluate_outcome(
    stance: str,
    realized_return_pct: float,
    excess_return_pct: float | None,
    *,
    gate_supports_abstention: bool,
    directional_threshold_pct: float = 1.0,
    neutral_band_pct: float = 3.0,
) -> tuple[str, str]:
    if stance in {"abstain", "mixed", "not_applicable"}:
        quality = "good" if stance == "abstain" and gate_supports_abstention else "unrated"
        return "unresolved", quality
    if stance == "bullish":
        if realized_return_pct >= directional_threshold_pct and (excess_return_pct is None or excess_return_pct >= 0):
            return "confirmed", "good"
        if realized_return_pct > 0 or (excess_return_pct is not None and excess_return_pct > 0):
            return "partially_confirmed", "mixed"
        return "refuted", "poor"
    if stance == "bearish":
        if realized_return_pct <= -directional_threshold_pct and (excess_return_pct is None or excess_return_pct <= 0):
            return "confirmed", "good"
        if realized_return_pct < 0 or (excess_return_pct is not None and excess_return_pct < 0):
            return "partially_confirmed", "mixed"
        return "refuted", "poor"
    if stance == "neutral":
        magnitude = abs(realized_return_pct)
        if magnitude <= neutral_band_pct:
            return "confirmed", "good"
        if magnitude <= neutral_band_pct * 2:
            return "partially_confirmed", "mixed"
        return "refuted", "poor"
    return "unresolved", "unrated"


def build_outcome(
    archive: Path,
    run: dict[str, Any],
    queue_item: dict[str, Any],
    series_by_code: dict[str, dict[str, Any]],
    *,
    benchmark_override: str = "",
    directional_threshold_pct: float = 1.0,
    neutral_band_pct: float = 3.0,
) -> dict[str, Any]:
    code = primary_instrument(run)
    periods = horizon_days(str(run.get("horizon") or ""))
    if code is None:
        return {"status": "blocked", "reason": "no reviewable six-digit instrument"}
    if periods is None:
        return {"status": "blocked", "reason": f"unsupported horizon: {run.get('horizon')}"}
    asset_series = series_by_code.get(code)
    if asset_series is None:
        return {"status": "blocked", "reason": f"missing market.history/1 series for {code}"}
    asset_window = _outcome_window(asset_series, str(run.get("as_of") or ""), periods)
    if asset_window is None:
        available_after = sum(
            1 for bar in asset_series["bars"] if str(bar.get("date") or "") > str(run.get("as_of") or "")[:10]
        )
        return {
            "status": "blocked",
            "reason": f"insufficient post-conclusion bars for {code}: {available_after}/{periods + 1} required for {periods}d",
        }
    benchmark_code = None
    if benchmark_override:
        benchmark_code = normalize_code(benchmark_override)
    else:
        benchmark_code = benchmark_code_from_run(archive, run)
    benchmark_window = None
    benchmark_series = series_by_code.get(benchmark_code) if benchmark_code else None
    if benchmark_series:
        benchmark_window = _aligned_benchmark_window(
            benchmark_series, asset_window["entry_date"], asset_window["exit_date"]
        )
    excess = None
    if benchmark_window:
        excess = round(asset_window["return_pct"] - benchmark_window["return_pct"], 6)
    summary = run.get("summary") or {}
    thesis_status, decision_quality = evaluate_outcome(
        str(summary.get("stance") or "not_applicable"),
        asset_window["return_pct"],
        excess,
        gate_supports_abstention=_gate_supports_abstention(queue_item),
        directional_threshold_pct=directional_threshold_pct,
        neutral_band_pct=neutral_band_pct,
    )
    note = (
        f"自动价格复盘：{code} 从 {asset_window['entry_date']} 收盘到 "
        f"{asset_window['exit_date']} 收盘收益 {asset_window['return_pct']:.2f}%"
    )
    if benchmark_window:
        note += f"，基准 {benchmark_code} 收益 {benchmark_window['return_pct']:.2f}%，超额 {excess:.2f}%"
    note += "。自动判定只评估价格结果与门禁遵守，因果命题仍需人工复核。"
    benchmark_result = None
    if benchmark_code:
        benchmark_result = {
            "code": benchmark_code,
            "name": benchmark_series.get("name") if benchmark_series else None,
            "status": "available" if benchmark_window else "unavailable",
            "history_source_name": benchmark_series["source_path"].name if benchmark_series else None,
            "history_sha256": benchmark_series["source_sha256"] if benchmark_series else None,
        }
        if benchmark_window:
            benchmark_result.update(benchmark_window)
    return {
        "schema": OUTCOME_SCHEMA,
        "status": "ready",
        "run_id": run.get("run_id"),
        "topic": run.get("topic"),
        "conclusion_as_of": run.get("as_of"),
        "horizon": run.get("horizon"),
        "original_conclusion": {
            "instruments": run.get("instruments") or [],
            "summary": summary,
            "conclusion_snapshot": queue_item.get("conclusion") or {},
            "artifact_snapshots": queue_item.get("artifact_snapshots") or {},
        },
        "method": {
            "version": "price-outcome-review/1.0",
            "entry_rule": "first available close strictly after conclusion date",
            "exit_rule": f"close {periods} trading sessions after entry",
            "directional_threshold_pct": directional_threshold_pct,
            "neutral_band_pct": neutral_band_pct,
            "causal_review_requires_human": True,
        },
        "asset": {
            "code": code,
            "name": asset_series.get("name"),
            **asset_window,
            "history_source_name": asset_series["source_path"].name,
            "history_sha256": asset_series["source_sha256"],
        },
        "benchmark": benchmark_result,
        "evaluation": {
            "thesis_status": thesis_status,
            "decision_quality": decision_quality,
            "realized_return_pct": asset_window["return_pct"],
            "benchmark_return_pct": benchmark_window["return_pct"] if benchmark_window else None,
            "excess_return_pct": excess,
            "note": note,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("work/research-journal"))
    parser.add_argument("--as-of", default="", help="Queue date; defaults to local today")
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--history", type=Path, action="append", default=[])
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--benchmark-code", default="")
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/decode-economic-news/prices"))
    parser.add_argument("--ttl-hours", type=float, default=6)
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--directional-threshold-pct", type=float, default=1.0)
    parser.add_argument("--neutral-band-pct", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    archive = args.archive.expanduser().resolve()
    queue = review_queue(archive, as_of=args.as_of)
    selected_ids = set(args.run_id)
    queue_items = [
        item for item in queue["items"]
        if item["review_status"] in {"due", "overdue"}
        and (not selected_ids or item["run_id"] in selected_ids)
    ]
    output_root = (args.output_dir or archive / "reports" / "auto-review" / queue["as_of"]).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    history_paths = collect_history_paths(args.history, args.history_dir)
    series_by_code = load_history_series(history_paths)
    if args.fetch_missing and queue_items:
        needed = []
        for item in queue_items:
            run, _ = load_run(archive, str(item["run_id"]))
            code = primary_instrument(run)
            benchmark = normalize_code(args.benchmark_code) if args.benchmark_code else benchmark_code_from_run(archive, run)
            needed.extend(value for value in (code, benchmark) if value and value not in series_by_code)
        needed = list(dict.fromkeys(needed))
        if needed:
            client = CachedHttpClient(args.cache_dir, timeout=20, retries=3, default_min_interval=0.25)
            fetched = build_history(
                needed, max(80, args.days), "qfq", client, max(0, args.ttl_hours) * 3600
            )
            fetched_path = output_root / "fetched-history.json"
            atomic_write_json(fetched_path, fetched)
            history_paths.append(fetched_path)
            series_by_code = load_history_series(history_paths)

    reviewed = []
    blocked = []
    for item in queue_items:
        run, _ = load_run(archive, str(item["run_id"]))
        outcome = build_outcome(
            archive, run, item, series_by_code,
            benchmark_override=args.benchmark_code,
            directional_threshold_pct=max(0.0, args.directional_threshold_pct),
            neutral_band_pct=max(0.0, args.neutral_band_pct),
        )
        if outcome.get("status") != "ready":
            blocked.append({"run_id": item["run_id"], **outcome})
            continue
        observed_at = str((outcome.get("asset") or {}).get("exit_date"))
        outcome_path = output_root / f"{item['run_id']}-{observed_at}-outcome.json"
        atomic_write_json(outcome_path, outcome)
        evaluation = outcome["evaluation"]
        review_id = None
        if not args.dry_run:
            artifacts = [("auto-review-outcome", outcome_path)]
            asset_source = Path(series_by_code[str(outcome["asset"]["code"])]["source_path"])
            artifacts.append(("outcome-history-asset", asset_source))
            benchmark = outcome.get("benchmark") or {}
            benchmark_series = series_by_code.get(str(benchmark.get("code") or ""))
            benchmark_source = Path(benchmark_series["source_path"]) if benchmark_series else None
            if benchmark_source and benchmark_source != asset_source:
                artifacts.append(("outcome-history-benchmark", benchmark_source))
            review = add_review(
                archive,
                str(item["run_id"]),
                observed_at=observed_at,
                thesis_status=evaluation["thesis_status"],
                realized_return_pct=evaluation["realized_return_pct"],
                benchmark_return_pct=evaluation["benchmark_return_pct"],
                decision_quality=evaluation["decision_quality"],
                note=evaluation["note"],
                artifacts=artifacts,
                tags=["automatic-review", "price-outcome"],
            )
            review_id = review["review_id"]
        reviewed.append({
            "run_id": item["run_id"],
            "review_id": review_id,
            "observed_at": observed_at,
            "outcome_path": str(outcome_path),
            "thesis_status": evaluation["thesis_status"],
            "decision_quality": evaluation["decision_quality"],
            "realized_return_pct": evaluation["realized_return_pct"],
            "excess_return_pct": evaluation["excess_return_pct"],
        })

    report = {
        "schema": BATCH_SCHEMA,
        "created_at": utc_now(),
        "archive": str(archive),
        "as_of": queue["as_of"],
        "dry_run": args.dry_run,
        "due_runs": len(queue_items),
        "reviewed_runs": len(reviewed),
        "blocked_runs": len(blocked),
        "history_files": [str(path) for path in history_paths],
        "reviewed": reviewed,
        "blocked": blocked,
        "warnings": [
            "Automatic review evaluates realized price outcomes and gate compliance only.",
            "Causal, fundamental and source-quality conclusions still require human review.",
        ],
    }
    report_path = output_root / "auto-review-report.json"
    atomic_write_json(report_path, report)
    print(json.dumps({
        "report": str(report_path),
        "due": len(queue_items),
        "reviewed": len(reviewed),
        "blocked": len(blocked),
        "dry_run": args.dry_run,
    }, ensure_ascii=False))
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
