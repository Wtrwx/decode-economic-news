#!/usr/bin/env python3
"""Run an expanding-window, point-in-time backtest of the bundled stock selector."""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from quant_core import MIN_HISTORY, clean_bars
from select_stocks import rank_candidates


def _future_return(bars: list[dict[str, Any]], as_of: str, horizon: int) -> float | None:
    rows = clean_bars(bars)
    current_index = None
    for index, item in enumerate(rows):
        if item["date"] <= as_of:
            current_index = index
        else:
            break
    if current_index is None or current_index + horizon >= len(rows):
        return None
    current = float(rows[current_index]["close"])
    future = float(rows[current_index + horizon]["close"])
    return (future / current - 1.0) * 100.0 if current > 0 else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def _bucket(score: float) -> str:
    if score < 40:
        return "<40"
    if score < 50:
        return "40-50"
    if score < 60:
        return "50-60"
    if score < 70:
        return "60-70"
    return ">=70"


def run_backtest(
    history: dict[str, Any],
    benchmark_code: str,
    *,
    horizon: int = 20,
    top_n: int = 10,
    step: int = 5,
    cost_bps: float = 20.0,
    start: str | None = None,
) -> dict[str, Any]:
    series = {str(item.get("code")): item for item in history.get("series") or [] if item.get("code")}
    benchmark = series.get(benchmark_code)
    if not benchmark:
        raise ValueError(f"sector benchmark {benchmark_code} is missing from history")
    benchmark_rows = clean_bars(benchmark.get("bars") or [])
    dates = [item["date"] for item in benchmark_rows]
    evaluation_dates = dates[MIN_HISTORY - 1 : max(MIN_HISTORY - 1, len(dates) - horizon) : max(1, step)]
    if start:
        evaluation_dates = [date for date in evaluation_dates if date >= start]

    observations = []
    periods = []
    cost_pct = cost_bps / 100.0
    for as_of in evaluation_dates:
        ranked = rank_candidates(history, benchmark_code, as_of=as_of, top_n=top_n)
        benchmark_return = _future_return(benchmark.get("bars") or [], as_of, horizon)
        if benchmark_return is None:
            continue
        period_returns = []
        selected_codes = []
        for candidate in ranked["values"]["candidates"]:
            item = series.get(candidate["code"])
            future_return = _future_return((item or {}).get("bars") or [], as_of, horizon)
            if future_return is None:
                continue
            net_return = future_return - cost_pct
            excess_return = net_return - benchmark_return
            observation = {
                "as_of": as_of,
                "code": candidate["code"],
                "name": candidate.get("name"),
                "rank": candidate["rank"],
                "score": candidate["score"],
                "future_gross_return_pct": round(future_return, 4),
                "future_net_return_pct": round(net_return, 4),
                "benchmark_return_pct": round(benchmark_return, 4),
                "excess_return_pct": round(excess_return, 4),
            }
            observations.append(observation)
            period_returns.append(net_return)
            selected_codes.append(candidate["code"])
        if period_returns:
            periods.append({
                "as_of": as_of,
                "selected_codes": selected_codes,
                "portfolio_net_return_pct": round(statistics.fmean(period_returns), 4),
                "benchmark_return_pct": round(benchmark_return, 4),
                "excess_return_pct": round(statistics.fmean(period_returns) - benchmark_return, 4),
            })

    net_returns = [float(item["future_net_return_pct"]) for item in observations]
    excess_returns = [float(item["excess_return_pct"]) for item in observations]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in observations:
        buckets.setdefault(_bucket(float(item["score"])), []).append(item)
    bucket_stats = []
    for label in ("<40", "40-50", "50-60", "60-70", ">=70"):
        rows = buckets.get(label, [])
        if not rows:
            continue
        bucket_stats.append({
            "bucket": label,
            "observations": len(rows),
            "historical_up_rate": _rate([float(item["future_net_return_pct"]) > 0 for item in rows]),
            "historical_excess_hit_rate": _rate([float(item["excess_return_pct"]) > 0 for item in rows]),
            "mean_net_return_pct": _mean([float(item["future_net_return_pct"]) for item in rows]),
            "mean_excess_return_pct": _mean([float(item["excess_return_pct"]) for item in rows]),
            "probability_publishable": len(rows) >= 30,
        })

    warnings = list(history.get("warnings") or [])
    warnings.extend([
        "The current universe is reused historically, so results contain survivorship bias.",
        "Forward-adjusted histories may embed later corporate-action adjustments.",
        "The backtest does not model suspension, limit execution, spread or market impact beyond configured costs.",
    ])
    if len(periods) < 20:
        warnings.append(f"walk-forward sample is small: only {len(periods)} evaluation periods")
    if len(observations) < 30:
        warnings.append("fewer than 30 candidate observations; do not publish a historical rate as probability")
    return {
        "schema": "model.backtest/1",
        "method_version": "stock-selection/1.0",
        "created_at": utc_now(),
        "settings": {
            "benchmark_code": benchmark_code,
            "horizon_trading_days": horizon,
            "top_n": top_n,
            "step_trading_days": step,
            "round_trip_cost_bps": cost_bps,
            "minimum_history_days": MIN_HISTORY,
            "start": start,
        },
        "period": {
            "first_evaluation": periods[0]["as_of"] if periods else None,
            "last_evaluation": periods[-1]["as_of"] if periods else None,
            "evaluation_periods": len(periods),
            "candidate_observations": len(observations),
        },
        "metrics": {
            "hit_rate": _rate([value > 0 for value in net_returns]),
            "excess_hit_rate": _rate([value > 0 for value in excess_returns]),
            "mean_net_return_pct": _mean(net_returns),
            "median_net_return_pct": _median(net_returns),
            "mean_excess_return_pct": _mean(excess_returns),
            "portfolio_period_mean_net_return_pct": _mean([
                float(item["portfolio_net_return_pct"]) for item in periods
            ]),
        },
        "score_buckets": bucket_stats,
        "periods": periods,
        "observations": observations,
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--benchmark", help="defaults to the benchmark embedded by fetch_price_history.py")
    parser.add_argument("--horizon", type=int, choices=(5, 10, 20, 60), default=20)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--start")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_json(args.history)
    benchmark = args.benchmark or ((((history.get("universe_context") or {}).get("benchmark") or {}).get("code")))
    if not benchmark:
        parser.error("--benchmark is required when history has no embedded universe benchmark")
    result = run_backtest(
        history, benchmark, horizon=args.horizon,
        top_n=max(1, args.top), step=max(1, args.step), cost_bps=max(0.0, args.cost_bps), start=args.start,
    )
    result["input"] = {"history_sha256": sha256_file(args.history), "history_path": str(args.history)}
    atomic_write_json(args.output, result)
    print(
        f"periods={result['period']['evaluation_periods']} observations={result['period']['candidate_observations']} "
        f"hit_rate={result['metrics']['hit_rate']} excess_hit_rate={result['metrics']['excess_hit_rate']}"
    )
    return 0 if result["period"]["evaluation_periods"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
