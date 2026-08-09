#!/usr/bin/env python3
"""Compute transparent 5-day and 20-day sector trend direction scores."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from quant_core import breadth, compute_features, sector_scores


def _series_map(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("code")): item for item in history.get("series") or [] if item.get("code")}


def forecast(history: dict[str, Any], benchmark_code: str, market_benchmark_code: str) -> dict[str, Any]:
    series = _series_map(history)
    if benchmark_code not in series:
        raise ValueError(f"sector benchmark {benchmark_code} is missing from history")
    if market_benchmark_code not in series:
        raise ValueError(f"market benchmark {market_benchmark_code} is missing from history")
    benchmark = series[benchmark_code]
    market = series[market_benchmark_code]
    constituent_bars = [
        item.get("bars") or [] for code, item in series.items()
        if code not in (benchmark_code, market_benchmark_code)
    ]
    features = compute_features(benchmark.get("bars") or [], market.get("bars") or [])
    breadth_values = breadth(constituent_bars, str(features.get("as_of") or ""))
    horizons = sector_scores(features, breadth_values)
    warnings = list(history.get("warnings") or [])
    if breadth_values.get("eligible_count", 0) < 10:
        warnings.append(
            f"sector breadth is based on only {breadth_values.get('eligible_count', 0)} eligible constituents"
        )
    for horizon, item in horizons.items():
        if item["coverage"] < 0.75:
            warnings.append(f"{horizon} forecast coverage is low: {item['coverage']:.0%}")
    warnings.extend([
        "Direction scores are uncalibrated descriptive signals, not probabilities or guarantees.",
        "Price/volume factors do not replace company fundamentals, disclosures or catalyst analysis.",
    ])
    return {
        "schema": "evidence.signal/1",
        "signal_type": "sector_trend_forecast",
        "method_version": "sector-trend/1.0",
        "as_of": features.get("as_of") or history.get("as_of") or utc_now(),
        "market": "CN-A",
        "values": {
            "benchmark": {"code": benchmark_code, "name": benchmark.get("name")},
            "market_benchmark": {"code": market_benchmark_code, "name": market.get("name")},
            "features": features,
            "breadth": breadth_values,
            "forecasts": horizons,
        },
        "inputs": {
            "history_schema": history.get("schema"),
            "history_coverage": history.get("coverage"),
            "series_count": history.get("series_count"),
        },
        "coverage": round(min((item["coverage"] for item in horizons.values()), default=0.0), 3),
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--benchmark", help="defaults to the benchmark embedded by fetch_price_history.py")
    parser.add_argument("--market-benchmark", help="defaults to the embedded market benchmark or 000300")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_json(args.history)
    context = history.get("universe_context") or {}
    benchmark = args.benchmark or ((context.get("benchmark") or {}).get("code"))
    market_benchmark = args.market_benchmark or ((context.get("market_benchmark") or {}).get("code")) or "000300"
    if not benchmark:
        parser.error("--benchmark is required when history has no embedded universe benchmark")
    result = forecast(history, benchmark, market_benchmark)
    result["inputs"]["history_sha256"] = sha256_file(args.history)
    atomic_write_json(args.output, result)
    summaries = result["values"]["forecasts"]
    print(" ".join(f"{key}={value['score']}({value['regime']})" for key, value in summaries.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
