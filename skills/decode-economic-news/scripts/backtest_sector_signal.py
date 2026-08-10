#!/usr/bin/env python3
"""Walk-forward test the bundled sector score and emit an abstention gate."""

from __future__ import annotations

import argparse
import math
import statistics
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from forecast_sector import forecast
from quant_core import MIN_HISTORY, clean_bars


BUCKETS = ("<40", "40-50", "50-60", "60-70", ">=70")


def score_bucket(score: float) -> str:
    if score < 40:
        return "<40"
    if score < 50:
        return "40-50"
    if score < 60:
        return "50-60"
    if score < 70:
        return "60-70"
    return ">=70"


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys)
    )
    return round(numerator / denominator, 4) if denominator else None


def _regime_gate(current_score: float, bucket: dict[str, Any] | None) -> tuple[bool, str]:
    if 35 < current_score < 65:
        return False, "current score is in the neutral no-trade zone (35, 65)"
    if not bucket:
        return False, "current score bucket has no historical observations"
    if int(bucket.get("observations") or 0) < 20:
        return False, "current score bucket has fewer than 20 observations"
    mean_excess = float(bucket.get("mean_excess_return_pct") or 0)
    excess_hit = float(bucket.get("historical_excess_hit_rate") or 0)
    if current_score >= 65:
        return (
            mean_excess > 0 and excess_hit >= 0.50,
            "high-score bucket must have positive mean excess return and at least 50% excess hit rate",
        )
    return (
        mean_excess < 0 and excess_hit < 0.50,
        "low-score bucket must have negative mean excess return and below 50% excess hit rate",
    )


def run_signal_backtest(
    history: dict[str, Any],
    benchmark_code: str,
    market_benchmark_code: str,
    *,
    horizon: int = 20,
    step: int | None = None,
    cost_bps: float = 20.0,
) -> dict[str, Any]:
    if horizon not in (5, 20):
        raise ValueError("horizon must be 5 or 20 trading days")
    step = horizon if step is None else max(1, step)
    series = {str(item.get("code")): item for item in history.get("series") or [] if item.get("code")}
    benchmark = series.get(benchmark_code)
    market = series.get(market_benchmark_code)
    if not benchmark or not market:
        raise ValueError("sector and market benchmark series are required")
    benchmark_rows = clean_bars(benchmark.get("bars") or [])
    market_by_date = {item["date"]: item for item in clean_bars(market.get("bars") or [])}
    observations: list[dict[str, Any]] = []
    score_key = f"{horizon}d"
    for index in range(MIN_HISTORY - 1, len(benchmark_rows) - horizon, step):
        decision = benchmark_rows[index]
        future = benchmark_rows[index + horizon]
        if decision["date"] not in market_by_date or future["date"] not in market_by_date:
            continue
        truncated = {**history, "series": []}
        for item in history.get("series") or []:
            truncated["series"].append({
                **item,
                "bars": [bar for bar in item.get("bars") or [] if str(bar.get("date") or "") <= decision["date"]],
            })
        signal = forecast(truncated, benchmark_code, market_benchmark_code)
        score = (((signal.get("values") or {}).get("forecasts") or {}).get(score_key) or {}).get("score")
        if score is None:
            continue
        gross = 100.0 * (float(future["close"]) / float(decision["close"]) - 1.0)
        net = gross - cost_bps / 100.0
        market_return = 100.0 * (
            float(market_by_date[future["date"]]["close"]) / float(market_by_date[decision["date"]]["close"]) - 1.0
        )
        observations.append({
            "date": decision["date"],
            "future_date": future["date"],
            "score": round(float(score), 3),
            "bucket": score_bucket(float(score)),
            "net_return_pct": round(net, 4),
            "excess_return_pct": round(net - market_return, 4),
        })

    bucket_stats: list[dict[str, Any]] = []
    for label in BUCKETS:
        rows = [item for item in observations if item["bucket"] == label]
        if not rows:
            continue
        net = [float(item["net_return_pct"]) for item in rows]
        excess = [float(item["excess_return_pct"]) for item in rows]
        bucket_stats.append({
            "bucket": label,
            "observations": len(rows),
            "historical_up_rate": _rate([value > 0 for value in net]),
            "historical_excess_hit_rate": _rate([value > 0 for value in excess]),
            "mean_net_return_pct": _mean(net),
            "median_net_return_pct": round(statistics.median(net), 4),
            "mean_excess_return_pct": _mean(excess),
            "probability_publishable": len(rows) >= 30,
        })

    current_signal = forecast(history, benchmark_code, market_benchmark_code)
    current_score = float(current_signal["values"]["forecasts"][score_key]["score"])
    current_label = score_bucket(current_score)
    current_bucket = next((item for item in bucket_stats if item["bucket"] == current_label), None)
    regime_usable, regime_reason = _regime_gate(current_score, current_bucket)
    score_return_correlation = _pearson(
        [float(item["score"]) for item in observations],
        [float(item["excess_return_pct"]) for item in observations],
    )
    monotonic = score_return_correlation is not None and score_return_correlation >= 0.10
    enough_total = len(observations) >= 30
    gate = {
        "status": "usable" if enough_total and monotonic and regime_usable else "abstain",
        "enough_total_observations": enough_total,
        "score_excess_return_correlation": score_return_correlation,
        "positive_score_monotonicity": monotonic,
        "current_bucket_usable": regime_usable,
        "current_bucket_reason": regime_reason,
    }
    warnings = list(history.get("warnings") or [])
    warnings.extend([
        "The constituent universe must be point-in-time; a current or seed universe introduces survivorship bias.",
        "Forward-adjusted prices may contain later corporate-action adjustments.",
        "A score is not a trading signal unless this report's gate status is usable.",
    ])
    if step < horizon:
        warnings.append("Forward-return windows overlap; observations are autocorrelated.")
    if gate["status"] == "abstain":
        warnings.append("Signal validation failed; do not translate the raw score into a directional trade.")
    return {
        "schema": "model.signal-backtest/1",
        "method_version": "sector-signal/1.0",
        "created_at": utc_now(),
        "as_of": history.get("as_of") or current_signal.get("as_of"),
        "current_score": round(current_score, 3),
        "current_bucket": current_label,
        "settings": {
            "benchmark_code": benchmark_code,
            "market_benchmark_code": market_benchmark_code,
            "horizon_trading_days": horizon,
            "step_trading_days": step,
            "round_trip_cost_bps": cost_bps,
        },
        "period": {
            "first_evaluation": observations[0]["date"] if observations else None,
            "last_evaluation": observations[-1]["date"] if observations else None,
            "observations": len(observations),
        },
        "score_buckets": bucket_stats,
        "gate": gate,
        "observations": observations,
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--benchmark")
    parser.add_argument("--market-benchmark")
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=20)
    parser.add_argument("--step", type=int)
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_json(args.history)
    context = history.get("universe_context") or {}
    benchmark = args.benchmark or ((context.get("benchmark") or {}).get("code"))
    market = args.market_benchmark or ((context.get("market_benchmark") or {}).get("code")) or "000300"
    if not benchmark:
        parser.error("--benchmark is required when history has no embedded universe benchmark")
    result = run_signal_backtest(
        history, benchmark, market, horizon=args.horizon,
        step=args.step, cost_bps=max(0.0, args.cost_bps),
    )
    result["input"] = {"history_sha256": sha256_file(args.history), "history_path": str(args.history)}
    atomic_write_json(args.output, result)
    print(
        f"status={result['gate']['status']} score={result['current_score']} "
        f"bucket={result['current_bucket']} observations={result['period']['observations']}"
    )
    return 0 if result["period"]["observations"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
