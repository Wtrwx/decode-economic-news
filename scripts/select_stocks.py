#!/usr/bin/env python3
"""Rank stocks within one sector using reproducible price/volume factors."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from quant_core import MIN_HISTORY, STOCK_WEIGHTS, component_explanations, compute_features, score_stock


def rank_candidates(
    history: dict[str, Any],
    benchmark_code: str,
    *,
    as_of: str | None = None,
    top_n: int = 10,
    exclude_codes: set[str] | None = None,
) -> dict[str, Any]:
    series = {str(item.get("code")): item for item in history.get("series") or [] if item.get("code")}
    benchmark = series.get(benchmark_code)
    if not benchmark:
        raise ValueError(f"sector benchmark {benchmark_code} is missing from history")
    excluded = set(exclude_codes or set()) | {benchmark_code, "000300"}
    actual_excluded = {code for code in excluded if code in series}
    eligible = []
    exclusions = []
    for code, item in series.items():
        if code in excluded:
            continue
        name = str(item.get("name") or "")
        if "退" in name or "ST" in name.upper():
            exclusions.append({"code": code, "name": name, "reason": "ST/delisting-risk name filter"})
            continue
        features = compute_features(item.get("bars") or [], benchmark.get("bars") or [], as_of=as_of)
        if int(features.get("history_count") or 0) < MIN_HISTORY:
            exclusions.append({"code": code, "name": name, "reason": "insufficient history"})
            continue
        score, coverage, components = score_stock(features)
        if score is None or coverage < 0.75:
            exclusions.append({"code": code, "name": name, "reason": f"factor coverage {coverage:.0%}"})
            continue
        strengths, risks = component_explanations(components)
        eligible.append({
            "code": code,
            "name": name,
            "score": score,
            "coverage": coverage,
            "as_of": features.get("as_of"),
            "features": features,
            "components": components,
            "strengths": strengths,
            "risks": risks,
            "quote": item.get("quote") or {},
        })
    eligible.sort(key=lambda item: (float(item["score"]), item["code"]), reverse=True)
    for rank, item in enumerate(eligible, 1):
        item["rank"] = rank
    chosen = eligible[: max(1, top_n)]
    warnings = list(history.get("warnings") or [])
    warnings.extend([
        "This is a within-universe statistical ranking, not a buy recommendation.",
        "The current constituent universe creates survivorship bias when reused for historical testing.",
        "Price/volume factors omit earnings quality, valuation, announcements and sector-specific catalysts.",
    ])
    return {
        "schema": "evidence.signal/1",
        "signal_type": "stock_selection",
        "method_version": "stock-selection/1.0",
        "as_of": max((str(item.get("as_of") or "") for item in eligible), default=as_of or history.get("as_of") or utc_now()),
        "market": "CN-A",
        "values": {
            "benchmark": {"code": benchmark_code, "name": benchmark.get("name")},
            "factor_weights": STOCK_WEIGHTS,
            "eligible_count": len(eligible),
            "selected_count": len(chosen),
            "candidates": chosen,
            "all_ranked": eligible,
            "exclusions": exclusions,
        },
        "inputs": {
            "history_schema": history.get("schema"),
            "history_coverage": history.get("coverage"),
            "series_count": history.get("series_count"),
        },
        "coverage": round(len(eligible) / max(1, len(series) - len(actual_excluded)), 3),
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--benchmark", help="defaults to the benchmark embedded by fetch_price_history.py")
    parser.add_argument("--as-of")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_json(args.history)
    benchmark = args.benchmark or ((((history.get("universe_context") or {}).get("benchmark") or {}).get("code")))
    if not benchmark:
        parser.error("--benchmark is required when history has no embedded universe benchmark")
    result = rank_candidates(history, benchmark, as_of=args.as_of, top_n=max(1, args.top))
    result["inputs"]["history_sha256"] = sha256_file(args.history)
    atomic_write_json(args.output, result)
    print(
        f"selected={result['values']['selected_count']} eligible={result['values']['eligible_count']} "
        f"as_of={result['as_of']}"
    )
    return 0 if result["values"]["selected_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
