#!/usr/bin/env python3
"""Compare a classified news event with asset and benchmark price reactions."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now


METHOD_VERSION = "news-price-reaction/1.0"
VALID_DIRECTIONS = {"positive", "negative", "mixed", "neutral", "unknown"}
STAGE_MATURITY = {
    "rumor": 0.15,
    "proposal": 0.30,
    "draft": 0.35,
    "announced": 0.55,
    "approved": 0.75,
    "effective": 0.90,
    "enforced": 1.00,
    "result": 1.00,
    "unknown": 0.25,
}


def _series(history: dict[str, Any], code: str) -> dict[str, Any]:
    target = code.lower().replace("sh", "").replace("sz", "")
    for item in history.get("series") or []:
        candidate = str(item.get("code") or "").lower().replace("sh", "").replace("sz", "")
        if candidate == target:
            return item
    raise ValueError(f"series not found in market history: {code}")


def _returns(series: dict[str, Any], event_date: str) -> dict[str, Any]:
    bars = sorted((series.get("bars") or []), key=lambda item: str(item.get("date") or ""))
    index = next((i for i, bar in enumerate(bars) if str(bar.get("date") or "") >= event_date), None)
    if index is None or index < 1:
        raise ValueError(f"insufficient pre-event history for {series.get('code')}")
    previous_close = float(bars[index - 1]["close"])

    def window_return(offset: int) -> float | None:
        target = index + offset - 1
        if target >= len(bars):
            return None
        return 100.0 * (float(bars[target]["close"]) / previous_close - 1.0)

    pre_return = None
    if index >= 6:
        pre_return = 100.0 * (previous_close / float(bars[index - 6]["close"]) - 1.0)
    prior_volumes = [float(item.get("volume") or 0) for item in bars[max(0, index - 20):index]]
    positive_volumes = [value for value in prior_volumes if value > 0]
    volume_ratio = None
    if positive_volumes and float(bars[index].get("volume") or 0) > 0:
        volume_ratio = float(bars[index]["volume"]) / (sum(positive_volumes) / len(positive_volumes))
    return {
        "code": series.get("code"),
        "name": series.get("name"),
        "event_trading_date": bars[index]["date"],
        "pre_5d_return_pct": pre_return,
        "return_1d_pct": window_return(1),
        "return_3d_pct": window_return(3),
        "return_5d_pct": window_return(5),
        "event_volume_ratio_20d": volume_ratio,
    }


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def interpret_reaction(event: dict[str, Any], reaction: dict[str, Any]) -> dict[str, Any]:
    direction = str(event.get("headline_direction") or "unknown").lower()
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"invalid headline_direction: {direction}")
    asset = reaction["asset"]
    benchmark = reaction["benchmark"]
    sector = reaction.get("sector")
    baseline = sector or benchmark
    relative_1d = _difference(asset.get("return_1d_pct"), baseline.get("return_1d_pct"))
    relative_5d = _difference(asset.get("return_5d_pct"), baseline.get("return_5d_pct"))
    threshold = 0.75
    if direction == "positive" and relative_1d is not None and relative_1d <= -threshold:
        regime = "positive_rejected"
        interpretation = "利好后相对走弱：可能已被定价、力度低于预期或存在未解决约束。"
    elif direction == "negative" and relative_1d is not None and relative_1d >= threshold:
        regime = "negative_absorbed"
        interpretation = "利空后相对走强：市场可能已提前定价、怀疑落地力度或出现流动性修复。"
    elif direction == "positive" and relative_1d is not None and relative_1d >= threshold:
        regime = "positive_confirmed"
        interpretation = "利好与相对上涨同向，但仍需用后续窗口检验是否延续。"
    elif direction == "negative" and relative_1d is not None and relative_1d <= -threshold:
        regime = "negative_confirmed"
        interpretation = "利空与相对下跌同向，但价格反应本身不能证明新闻中的因果叙事。"
    else:
        regime = "ambiguous"
        interpretation = "相对反应不足以区分预期差、噪声与基本面重估。"
    flags: list[str] = []
    pre_return = asset.get("pre_5d_return_pct")
    if direction == "positive" and pre_return is not None and pre_return >= 2.0:
        flags.append("possible_positive_priced_in")
    if direction == "negative" and pre_return is not None and pre_return <= -2.0:
        flags.append("possible_negative_priced_in")
    if relative_1d is not None and relative_5d is not None and relative_1d * relative_5d < 0 and abs(relative_5d) >= threshold:
        flags.append("reaction_reversed_by_5d")
    volume_ratio = asset.get("event_volume_ratio_20d")
    if volume_ratio is not None and volume_ratio >= 1.8:
        flags.append("high_event_volume")
    stage = str(event.get("event_stage") or "unknown").lower()
    return {
        "regime": regime,
        "interpretation": interpretation,
        "relative_return_1d_pct": None if relative_1d is None else round(relative_1d, 4),
        "relative_return_5d_pct": None if relative_5d is None else round(relative_5d, 4),
        "baseline": "sector" if sector else "market_benchmark",
        "event_stage": stage,
        "stage_maturity": STAGE_MATURITY.get(stage, STAGE_MATURITY["unknown"]),
        "flags": flags,
    }


def compute_news_reaction(
    event: dict[str, Any],
    history: dict[str, Any],
    *,
    asset_code: str,
    benchmark_code: str,
    sector_code: str = "",
) -> dict[str, Any]:
    event_date = str(event.get("event_date") or "")
    if not event_date:
        raise ValueError("event_date is required")
    reaction = {
        "asset": _returns(_series(history, asset_code), event_date),
        "benchmark": _returns(_series(history, benchmark_code), event_date),
    }
    if sector_code:
        reaction["sector"] = _returns(_series(history, sector_code), event_date)
    interpretation = interpret_reaction(event, reaction)
    required = [
        reaction["asset"].get("return_1d_pct"),
        reaction["asset"].get("return_5d_pct"),
        reaction["benchmark"].get("return_1d_pct"),
        reaction["benchmark"].get("return_5d_pct"),
    ]
    coverage = sum(value is not None for value in required) / len(required)
    warnings = [
        "This is a descriptive expectation-gap signal, not a return probability or standalone trading signal.",
        "Daily closes cannot distinguish intraday publication timing; use intraday data when event time matters.",
        "Price reaction is evidence of repricing, not proof that the headline caused the move.",
    ]
    return {
        "schema": "evidence.signal/1",
        "signal_type": "news_price_reaction",
        "method_version": METHOD_VERSION,
        "as_of": utc_now(),
        "values": {"event": event, "reaction": reaction, "market_read": interpretation},
        "inputs": {
            "asset_code": asset_code,
            "benchmark_code": benchmark_code,
            "sector_code": sector_code or None,
            "event_date": event_date,
        },
        "coverage": round(coverage, 3),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", type=Path, help="news.event/1 JSON with event_date and headline_direction")
    parser.add_argument("history", type=Path, help="market.history/1 JSON")
    parser.add_argument("--asset-code", required=True)
    parser.add_argument("--benchmark-code", required=True)
    parser.add_argument("--sector-code", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    event = load_json(args.event)
    history = load_json(args.history)
    result = compute_news_reaction(
        event,
        history,
        asset_code=args.asset_code,
        benchmark_code=args.benchmark_code,
        sector_code=args.sector_code,
    )
    result["inputs"]["event_file"] = str(args.event.resolve())
    result["inputs"]["event_sha256"] = sha256_file(args.event)
    result["inputs"]["history_file"] = str(args.history.resolve())
    result["inputs"]["history_sha256"] = sha256_file(args.history)
    atomic_write_json(args.output, result)
    print(f"wrote news reaction signal to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
