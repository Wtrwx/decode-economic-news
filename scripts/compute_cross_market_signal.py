#!/usr/bin/env python3
"""Compare A-share sector returns with prior U.S. and Korean sector-relative moves."""

from __future__ import annotations

import argparse
import bisect
import statistics
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from quant_core import clean_bars, pct_change


def _series_map(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("code") or item.get("symbol")): item for item in history.get("series") or []}


def _returns(bars: list[dict[str, Any]]) -> dict[str, float]:
    rows = clean_bars(bars)
    result = {}
    for previous, current in zip(rows, rows[1:]):
        result[current["date"]] = (float(current["close"]) / float(previous["close"]) - 1.0) * 100.0
    return result


def _excess_returns(asset: list[dict[str, Any]], benchmark: list[dict[str, Any]]) -> dict[str, float]:
    own = _returns(asset)
    broad = _returns(benchmark)
    return {date: own[date] - broad[date] for date in own.keys() & broad.keys()}


def _window_return(bars: list[dict[str, Any]], periods: int) -> float | None:
    rows = clean_bars(bars)
    return pct_change([float(item["close"]) for item in rows], periods)


def _aligned_prior_pairs(a_returns: dict[str, float], foreign_returns: dict[str, float]) -> list[tuple[float, float]]:
    foreign_dates = sorted(foreign_returns)
    pairs = []
    used_foreign: set[str] = set()
    for a_date in sorted(a_returns):
        index = bisect.bisect_left(foreign_dates, a_date) - 1
        if index < 0:
            continue
        foreign_date = foreign_dates[index]
        if foreign_date in used_foreign:
            continue
        pairs.append((a_returns[a_date], foreign_returns[foreign_date]))
        used_foreign.add(foreign_date)
    return pairs


def _correlation(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    left = [item[0] for item in pairs]
    right = [item[1] for item in pairs]
    if statistics.pstdev(left) == 0 or statistics.pstdev(right) == 0:
        return None
    return statistics.correlation(left, right)


def _direction_agreement(pairs: list[tuple[float, float]]) -> float | None:
    directional = [(a, f) for a, f in pairs if a != 0 and f != 0]
    if not directional:
        return None
    return 100.0 * sum((a > 0) == (f > 0) for a, f in directional) / len(directional)


def _weighted(values: list[tuple[float | None, float]]) -> float | None:
    usable = [(float(value), float(weight)) for value, weight in values if value is not None and weight > 0]
    total = sum(weight for _, weight in usable)
    return sum(value * weight for value, weight in usable) / total if total else None


def _market_regime(value: float | None, threshold: float = 1.0) -> str:
    if value is None:
        return "insufficient"
    if value > threshold:
        return "positive"
    if value < -threshold:
        return "negative"
    return "mixed_or_flat"


def _acceptance(a_value: float | None, foreign_value: float | None) -> str:
    a_regime = _market_regime(a_value)
    foreign_regime = _market_regime(foreign_value)
    if foreign_regime == "positive" and a_regime == "negative":
        return "foreign_positive_a_rejected"
    if foreign_regime == "negative" and a_regime == "positive":
        return "foreign_negative_a_resilient"
    if foreign_regime == "positive" and a_regime == "positive":
        return "positive_confirmed"
    if foreign_regime == "negative" and a_regime == "negative":
        return "negative_confirmed"
    return "mixed_or_insufficient"


def compute_signal(
    a_history: dict[str, Any], cross_history: dict[str, Any], a_sector_code: str, a_market_code: str
) -> dict[str, Any]:
    a_series = _series_map(a_history)
    cross_series = _series_map(cross_history)
    if a_sector_code not in a_series or a_market_code not in a_series:
        raise ValueError("A-share history must contain the sector and market benchmarks")
    a_sector = a_series[a_sector_code]
    a_market = a_series[a_market_code]
    a_excess = _excess_returns(a_sector.get("bars") or [], a_market.get("bars") or [])
    a_5d = _window_return(a_sector.get("bars") or [], 5)
    a_market_5d = _window_return(a_market.get("bars") or [], 5)
    a_excess_5d = a_5d - a_market_5d if a_5d is not None and a_market_5d is not None else None
    context = cross_history.get("universe_context") or {}
    benchmark_config = context.get("market_benchmarks") or {}
    peers = []
    for symbol, item in cross_series.items():
        if item.get("role") == "market_benchmark":
            continue
        market = str(item.get("market") or "")
        benchmark_symbol = str((benchmark_config.get(market) or {}).get("symbol") or "")
        benchmark = cross_series.get(benchmark_symbol)
        if not benchmark:
            continue
        own_bars = item.get("bars") or []
        benchmark_bars = benchmark.get("bars") or []
        foreign_excess = _excess_returns(own_bars, benchmark_bars)
        pairs = _aligned_prior_pairs(a_excess, foreign_excess)
        lead_correlation = _correlation(pairs)
        direction_agreement = _direction_agreement(pairs)
        own_rows = clean_bars(own_bars)
        own_5d = _window_return(own_bars, 5)
        broad_5d = _window_return(benchmark_bars, 5)
        own_20d = _window_return(own_bars, 20)
        broad_20d = _window_return(benchmark_bars, 20)
        peers.append(
            {
                "market": market,
                "symbol": symbol,
                "name": item.get("name"),
                "role": item.get("role"),
                "mapping_strength": item.get("mapping_strength"),
                "as_of": own_rows[-1]["date"] if own_rows else None,
                "return_5d_pct": round(own_5d, 4) if own_5d is not None else None,
                "excess_5d_pct": round(own_5d - broad_5d, 4) if own_5d is not None and broad_5d is not None else None,
                "return_20d_pct": round(own_20d, 4) if own_20d is not None else None,
                "excess_20d_pct": round(own_20d - broad_20d, 4) if own_20d is not None and broad_20d is not None else None,
                "prior_close_lead_samples": len(pairs),
                "prior_close_lead_correlation": round(lead_correlation, 4) if lead_correlation is not None else None,
                "prior_close_direction_agreement_pct": round(direction_agreement, 2) if direction_agreement is not None else None,
                "relationship_status": "historical_descriptive_not_probability",
            }
        )
    impulses = {}
    for market in ("us", "kr"):
        market_peers = [item for item in peers if item["market"] == market]
        impulses[market] = {
            "peer_count": len(market_peers),
            "weighted_excess_5d_pct": None,
            "weighted_excess_20d_pct": None,
            "regime_5d": "insufficient",
        }
        five = _weighted([(item["excess_5d_pct"], float(item.get("mapping_strength") or 0)) for item in market_peers])
        twenty = _weighted([(item["excess_20d_pct"], float(item.get("mapping_strength") or 0)) for item in market_peers])
        impulses[market].update(
            {
                "weighted_excess_5d_pct": round(five, 4) if five is not None else None,
                "weighted_excess_20d_pct": round(twenty, 4) if twenty is not None else None,
                "regime_5d": _market_regime(five),
            }
        )
    foreign_5d = _weighted(
        [(item["excess_5d_pct"], float(item.get("mapping_strength") or 0)) for item in peers]
    )
    requested_benchmarks = sum(item.get("role") == "market_benchmark" for item in cross_series.values())
    expected_peers = max(0, int(cross_history.get("requested_count") or 0) - requested_benchmarks)
    coverage = len(peers) / expected_peers if expected_peers else 0.0
    warnings = list(a_history.get("warnings") or []) + list(cross_history.get("warnings") or [])
    warnings.extend(
        [
            "Cross-market returns are an evidence overlay, not a mechanical addition to the A-share forecast score.",
            "Prior-close correlations and direction agreement are historical descriptive statistics, not causal proof or future probabilities.",
            "Company earnings, product prices, FX and local policy must verify the proposed transmission mechanism.",
        ]
    )
    if any(int(item["prior_close_lead_samples"]) < 30 for item in peers):
        warnings.append("At least one lead/lag comparison has fewer than 30 paired observations.")
    return {
        "schema": "evidence.signal/1",
        "signal_type": "cross_market_readthrough",
        "method_version": "cross-market-readthrough/1.0",
        "as_of": a_history.get("as_of") or utc_now(),
        "market": "CN-A",
        "values": {
            "a_share": {
                "sector_code": a_sector_code,
                "sector_name": a_sector.get("name"),
                "market_code": a_market_code,
                "return_5d_pct": round(a_5d, 4) if a_5d is not None else None,
                "excess_5d_pct": round(a_excess_5d, 4) if a_excess_5d is not None else None,
            },
            "foreign_impulse_5d_pct": round(foreign_5d, 4) if foreign_5d is not None else None,
            "a_share_acceptance": _acceptance(a_excess_5d, foreign_5d),
            "market_impulses": impulses,
            "peers": peers,
            "transmission_variables": context.get("transmission_variables") or [],
            "event_leaders_for_fundamental_check": context.get("event_leaders") or {},
            "mapping_caveat": context.get("caveat"),
        },
        "inputs": {
            "a_history_schema": a_history.get("schema"),
            "cross_history_schema": cross_history.get("schema"),
            "cross_preset": context.get("preset"),
            "timing_rule": "foreign_close_date_strictly_before_a_share_date",
        },
        "coverage": round(coverage, 3),
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a_history", type=Path)
    parser.add_argument("cross_history", type=Path)
    parser.add_argument("--a-sector-code", required=True)
    parser.add_argument("--a-market-code", default="000300")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    a_history = load_json(args.a_history)
    cross_history = load_json(args.cross_history)
    result = compute_signal(a_history, cross_history, args.a_sector_code, args.a_market_code)
    result["inputs"].update(
        {"a_history_sha256": sha256_file(args.a_history), "cross_history_sha256": sha256_file(args.cross_history)}
    )
    atomic_write_json(args.output, result)
    print(
        f"acceptance={result['values']['a_share_acceptance']} foreign_5d="
        f"{result['values']['foreign_impulse_5d_pct']} coverage={result['coverage']:.0%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
