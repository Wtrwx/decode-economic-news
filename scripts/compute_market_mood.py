#!/usr/bin/env python3
"""Compute a transparent market mood score from a normalized snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, clamp, load_json, sha256_file, utc_now


METHOD_VERSION = "market-mood/1.0"
DEFAULT_WEIGHTS = {"breadth": 0.35, "limit_ecology": 0.35, "momentum": 0.20, "continuation": 0.10}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_market_mood(snapshot: dict) -> dict:
    if snapshot.get("schema") != "market.snapshot/1":
        raise ValueError("expected market.snapshot/1")
    warnings = list(snapshot.get("warnings") or [])
    components: dict[str, float] = {}
    diagnostics: dict[str, Any] = {}

    breadth = snapshot.get("breadth") or {}
    advances = _number(breadth.get("advance_count"))
    declines = _number(breadth.get("decline_count"))
    if advances is not None and declines is not None and advances + declines > 0:
        advance_ratio = advances / (advances + declines)
        components["breadth"] = round(100 * advance_ratio, 3)
        diagnostics["advance_ratio"] = round(advance_ratio, 6)
        if advances + declines < 100:
            warnings.append("breadth component has fewer than 100 advancing/declining securities")

    ecology = snapshot.get("limit_ecology") or {}
    zt = _number(ecology.get("limit_up_count"))
    dt = _number(ecology.get("limit_down_count"))
    break_rate = _number(ecology.get("break_rate_pct"))
    height = _number(ecology.get("max_limit_height"))
    ecology_parts: list[tuple[float, float]] = []
    if zt is not None and dt is not None:
        balance = clamp(50 + 50 * (zt - dt) / (zt + dt + 20))
        ecology_parts.append((balance, 0.40))
        diagnostics["limit_balance"] = round(balance, 3)
    if break_rate is not None:
        break_quality = clamp(100 - break_rate)
        ecology_parts.append((break_quality, 0.35))
        diagnostics["break_quality"] = round(break_quality, 3)
    if height is not None:
        height_score = clamp(20 * height)
        ecology_parts.append((height_score, 0.25))
        diagnostics["height_score"] = round(height_score, 3)
    if ecology_parts:
        total_weight = sum(weight for _, weight in ecology_parts)
        components["limit_ecology"] = round(sum(score * weight for score, weight in ecology_parts) / total_weight, 3)

    index_returns = [_number(row.get("change_pct")) for row in snapshot.get("indices") or []]
    index_returns = [value for value in index_returns if value is not None]
    if index_returns:
        mean_return = sum(index_returns) / len(index_returns)
        components["momentum"] = round(clamp(50 + 12.5 * mean_return), 3)
        diagnostics["equal_weight_index_return_pct"] = round(mean_return, 4)

    continuation = _number(ecology.get("continuation_rate_pct"))
    if continuation is not None:
        components["continuation"] = round(clamp(continuation), 3)

    if not components:
        raise RuntimeError("no market mood component could be computed")
    active_weights = {key: DEFAULT_WEIGHTS[key] for key in components}
    weight_sum = sum(active_weights.values())
    score = sum(components[key] * active_weights[key] for key in components) / weight_sum
    coverage = weight_sum / sum(DEFAULT_WEIGHTS.values())
    if coverage < 0.75:
        warnings.append(f"market mood coverage is low: {coverage:.0%}")
    if score < 25:
        regime = "极冷"
    elif score < 42:
        regime = "偏冷"
    elif score < 58:
        regime = "中性"
    elif score < 75:
        regime = "偏热"
    else:
        regime = "极热"
    return {
        "schema": "evidence.signal/1",
        "signal_type": "market_mood",
        "method_version": METHOD_VERSION,
        "as_of": snapshot.get("as_of") or utc_now(),
        "market": snapshot.get("market"),
        "values": {
            "score": round(score, 3),
            "regime": regime,
            "components": components,
            "diagnostics": diagnostics,
        },
        "coverage": round(coverage, 3),
        "inputs": {"snapshot_date": snapshot.get("date"), "available_components": sorted(components)},
        "warnings": warnings + ["This descriptive composite is not an investment signal."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = load_json(args.snapshot)
    result = compute_market_mood(snapshot)
    result["inputs"]["snapshot_sha256"] = sha256_file(args.snapshot)
    atomic_write_json(args.output, result)
    print(f"market mood={result['values']['score']:.1f} ({result['values']['regime']}); coverage={result['coverage']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
