#!/usr/bin/env python3
"""Build a point-in-time multi-timeframe timing overlay for A-share/ETF research."""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from quant_core import clean_bars, compute_features, mean


TIMING_MIN_HISTORY = 120
METHOD_VERSION = "multi-timeframe-breakout/1.0"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _bar_value(row: dict[str, Any], key: str) -> float:
    value = _number(row.get(key))
    if value is not None and value > 0:
        return value
    return float(row["close"])


def _pct_gap(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return (value / reference - 1.0) * 100.0


def _atr(rows: list[dict[str, Any]], period: int = 20) -> float | None:
    if len(rows) < period + 1:
        return None
    ranges: list[float] = []
    for index in range(len(rows) - period, len(rows)):
        current = rows[index]
        previous_close = float(rows[index - 1]["close"])
        high = _bar_value(current, "high")
        low = _bar_value(current, "low")
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return mean(ranges)


def _donchian(rows: list[dict[str, Any]], period: int, *, end: int | None = None) -> tuple[float | None, float | None]:
    """Return the prior channel ending before ``end``; the decision bar is excluded."""
    end = len(rows) - 1 if end is None else end
    start = end - period
    if start < 0 or end <= start:
        return None, None
    window = rows[start:end]
    return (
        max(_bar_value(item, "high") for item in window),
        min(_bar_value(item, "low") for item in window),
    )


def _obv_direction(rows: list[dict[str, Any]], lookback: int = 10) -> tuple[str, float | None]:
    if len(rows) < lookback + 1:
        return "unknown", None
    values = [0.0]
    for previous, current in zip(rows, rows[1:]):
        volume = _number(current.get("volume")) or 0.0
        delta = volume if float(current["close"]) > float(previous["close"]) else -volume
        if float(current["close"]) == float(previous["close"]):
            delta = 0.0
        values.append(values[-1] + delta)
    change = values[-1] - values[-lookback - 1]
    scale = mean([abs(values[index] - values[index - 1]) for index in range(len(values) - lookback, len(values))])
    normalized = change / (scale * lookback) if scale and scale > 0 else None
    if normalized is None:
        return "flat", None
    if normalized > 0.15:
        return "rising", normalized
    if normalized < -0.15:
        return "falling", normalized
    return "flat", normalized


def _weekly_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        try:
            parsed = date.fromisoformat(str(row["date"])[:10])
        except ValueError:
            continue
        iso = parsed.isocalendar()
        groups.setdefault((iso.year, iso.week), []).append(row)
    weekly: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda item: item["date"])
        volumes = [_number(item.get("volume")) for item in group]
        weekly.append({
            "date": group[-1]["date"],
            "open": _bar_value(group[0], "open"),
            "high": max(_bar_value(item, "high") for item in group),
            "low": min(_bar_value(item, "low") for item in group),
            "close": float(group[-1]["close"]),
            "volume": sum(value for value in volumes if value is not None) if any(value is not None for value in volumes) else None,
            "sessions": len(group),
        })
    return weekly


def _completed_weekly(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    weekly = _weekly_bars(rows)
    if not weekly:
        return [], None, None
    last = weekly[-1]
    try:
        weekday = date.fromisoformat(last["date"]).weekday()
    except ValueError:
        weekday = 0
    if weekday < 4:
        return weekly[:-1], last, "last weekly bar is treated as incomplete because the latest session is before Friday"
    return weekly, None, None


def _trend_state(closes: list[float], fast_period: int, slow_period: int, slope_lookback: int) -> dict[str, Any]:
    if len(closes) < slow_period + slope_lookback:
        return {"state": "insufficient_data", "close": closes[-1] if closes else None}
    close = closes[-1]
    fast = mean(closes[-fast_period:])
    slow = mean(closes[-slow_period:])
    prior_fast = mean(closes[-fast_period - slope_lookback:-slope_lookback])
    slope = _pct_gap(fast, prior_fast)
    if fast is not None and slow is not None and slope is not None:
        if close > fast > slow and slope > 0:
            state = "bullish"
        elif close < fast < slow and slope < 0:
            state = "bearish"
        else:
            state = "mixed"
    else:
        state = "insufficient_data"
    return {
        "state": state,
        "close": round(close, 6),
        f"ma{fast_period}": round(fast, 6) if fast is not None else None,
        f"ma{slow_period}": round(slow, 6) if slow is not None else None,
        f"ma{fast_period}_slope_pct": round(slope, 4) if slope is not None else None,
    }


def _recent_breakout(rows: list[dict[str, Any]], period: int = 20, lookback: int = 10) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    first_index = max(period, len(rows) - lookback - 1)
    for index in range(first_index, len(rows) - 1):
        high, _ = _donchian(rows, period, end=index)
        if high is not None and float(rows[index]["close"]) > high:
            latest = {
                "date": rows[index]["date"],
                "index": index,
                "level": high,
                "sessions_ago": len(rows) - 1 - index,
            }
    return latest


def compute_asset_timing(
    asset: dict[str, Any],
    benchmark: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    code = str(asset.get("code") or "")
    rows = clean_bars(asset.get("bars") or [], as_of)
    benchmark_rows = clean_bars(benchmark.get("bars") or [], rows[-1]["date"] if rows else as_of)
    if len(rows) < TIMING_MIN_HISTORY:
        return {
            "code": code,
            "name": asset.get("name"),
            "as_of": rows[-1]["date"] if rows else as_of,
            "history_count": len(rows),
            "coverage": 0.0,
            "state": "insufficient_data",
            "directional_role": "timing_overlay_only",
            "warnings": [f"requires at least {TIMING_MIN_HISTORY} daily bars"],
        }

    closes = [float(item["close"]) for item in rows]
    current = rows[-1]
    current_close = closes[-1]
    daily = _trend_state(closes, 20, 60, 5)
    weekly_rows, partial_week, weekly_warning = _completed_weekly(rows)
    weekly = _trend_state([float(item["close"]) for item in weekly_rows], 10, 20, 3)

    atr20 = _atr(rows, 20)
    prior20_high, prior20_low = _donchian(rows, 20)
    prior55_high, prior55_low = _donchian(rows, 55)
    _, prior10_low = _donchian(rows, 10)
    current_high = _bar_value(current, "high")
    current_low = _bar_value(current, "low")
    close_breakout_20 = bool(prior20_high is not None and current_close > prior20_high)
    close_breakout_55 = bool(prior55_high is not None and current_close > prior55_high)
    intraday_breakout_20 = bool(prior20_high is not None and current_high > prior20_high)
    gap_to_20 = _pct_gap(current_close, prior20_high)
    near_breakout = bool(gap_to_20 is not None and -2.5 <= gap_to_20 <= 0)

    recent = _recent_breakout(rows, 20, 10)
    retest = False
    failed_breakout = False
    if recent:
        level = float(recent["level"])
        retest = current_low <= level * 1.015 and current_close >= level and float(daily.get("ma20") or 0) <= current_close
        failed_breakout = current_close < level * 0.98

    volumes = [_number(item.get("volume")) for item in rows]
    prior_volumes = [value for value in volumes[-21:-1] if value is not None]
    current_volume = volumes[-1]
    volume_ratio = current_volume / mean(prior_volumes) if current_volume is not None and prior_volumes and mean(prior_volumes) else None
    obv_direction, obv_normalized_change = _obv_direction(rows, 10)
    volume_confirmed = bool(
        (volume_ratio is not None and volume_ratio >= 1.20)
        or (volume_ratio is not None and volume_ratio >= 1.0 and obv_direction == "rising")
    )

    features = compute_features(rows, benchmark_rows, as_of=rows[-1]["date"])
    ma20_gap = _number(features.get("ma20_gap_pct"))
    atr_extension = (
        (current_close - prior20_high) / atr20
        if atr20 and prior20_high is not None and current_close > prior20_high
        else None
    )
    extended = bool((ma20_gap is not None and ma20_gap > 8.0) or (atr_extension is not None and atr_extension > 2.0))

    weekly_state = weekly.get("state")
    daily_state = daily.get("state")
    if failed_breakout or weekly_state == "bearish" or (daily_state == "bearish" and current_close < float(daily.get("ma60") or current_close)):
        state = "blocked"
    elif extended and weekly_state == "bullish":
        state = "extended"
    elif retest and weekly_state == "bullish" and daily_state != "bearish":
        state = "retest"
    elif (close_breakout_20 or close_breakout_55) and weekly_state == "bullish" and daily_state == "bullish":
        state = "triggered" if volume_confirmed else "triggered_unconfirmed"
    elif weekly_state == "bullish" and daily_state != "bearish" and near_breakout:
        state = "watch"
    elif weekly_state == "bullish" and daily_state == "bullish":
        state = "trend_only"
    elif {weekly_state, daily_state} == {"bullish", "bearish"}:
        state = "mixed"
    else:
        state = "no_setup"

    stop_candidates: dict[str, float | None] = {
        "two_atr": current_close - 2.0 * atr20 if atr20 else None,
        "prior_10d_low": prior10_low,
    }
    valid_stops = [value for value in stop_candidates.values() if value is not None and 0 < value < current_close]
    stop_reference = max(valid_stops) if valid_stops else None
    risk_distance = _pct_gap(current_close, stop_reference)
    risk_distance_pct = -risk_distance if risk_distance is not None else None
    upside_review = current_close + 2.0 * (current_close - stop_reference) if stop_reference else None

    if state == "triggered":
        entry_condition = "收盘突破已确认；最早下一交易日核验未涨停锁单、价差与量能后执行，禁止按信号当日收盘回填成交。"
    elif state == "retest":
        entry_condition = "突破回踩承接已确认；最早下一交易日仅在突破位上方保持相对强势时分批。"
    elif state == "watch":
        entry_condition = "接近20日通道上沿，等待收盘突破与量能/OBV确认。"
    elif state in {"extended", "triggered_unconfirmed"}:
        entry_condition = "不追价；等待回踩、横盘消化或新的量能确认。"
    else:
        entry_condition = "当前没有通过多周期门禁的技术入场条件。"

    core_values = [
        daily_state not in {None, "insufficient_data"},
        weekly_state not in {None, "insufficient_data"},
        atr20 is not None,
        prior20_high is not None,
        volume_ratio is not None,
        features.get("relative_20d_pct") is not None,
    ]
    warnings: list[str] = []
    if weekly_warning:
        warnings.append(weekly_warning)
    if partial_week:
        warnings.append(f"partial weekly bar through {partial_week['date']} is excluded from the higher-timeframe gate")
    warnings.extend([
        "This is a timing overlay, not a return probability or a substitute for fundamentals and event evidence.",
        "Pattern labels, Chan-theory labels and portal fund-flow labels are not used as standalone entry signals.",
    ])
    return {
        "code": code,
        "name": asset.get("name"),
        "as_of": rows[-1]["date"],
        "history_count": len(rows),
        "coverage": round(sum(core_values) / len(core_values), 3),
        "state": state,
        "directional_role": "timing_overlay_only",
        "timeframes": {
            "daily": daily,
            "weekly_completed": weekly,
            "partial_week": partial_week,
        },
        "breakout": {
            "prior_20d_high": round(prior20_high, 6) if prior20_high is not None else None,
            "prior_20d_low": round(prior20_low, 6) if prior20_low is not None else None,
            "prior_55d_high": round(prior55_high, 6) if prior55_high is not None else None,
            "prior_55d_low": round(prior55_low, 6) if prior55_low is not None else None,
            "close_breakout_20d": close_breakout_20,
            "close_breakout_55d": close_breakout_55,
            "intraday_breakout_20d": intraday_breakout_20,
            "near_breakout_20d": near_breakout,
            "recent_breakout": recent,
            "retest_confirmed": retest,
            "failed_breakout": failed_breakout,
            "atr_extension_from_20d_high": round(atr_extension, 4) if atr_extension is not None else None,
        },
        "volume": {
            "current_vs_prior_20d": round(volume_ratio, 4) if volume_ratio is not None else None,
            "obv_direction_10d": obv_direction,
            "obv_normalized_change_10d": round(obv_normalized_change, 4) if obv_normalized_change is not None else None,
            "confirmed": volume_confirmed,
        },
        "relative_strength": {
            "benchmark_code": str(benchmark.get("code") or ""),
            "relative_20d_pct": features.get("relative_20d_pct"),
            "relative_60d_pct": features.get("relative_60d_pct"),
        },
        "risk": {
            "atr20": round(atr20, 6) if atr20 is not None else None,
            "stop_candidates": {key: round(value, 6) if value is not None else None for key, value in stop_candidates.items()},
            "technical_stop_reference": round(stop_reference, 6) if stop_reference is not None else None,
            "risk_distance_pct": round(risk_distance_pct, 4) if risk_distance_pct is not None else None,
            "upside_review_reference_2r": round(upside_review, 6) if upside_review is not None else None,
            "execution_clock": "signal_at_close_earliest_execution_next_session",
        },
        "entry_condition": entry_condition,
        "invalidation": [
            "收盘跌破最近有效突破位且未在下一观察窗修复",
            "周线完成周期转为空头或日线跌破MA60并持续走弱",
            "事件原稿或公司披露否定基本面传导链",
        ],
        "warnings": warnings,
    }


def compute_timing(
    history: dict[str, Any],
    asset_codes: list[str],
    benchmark_code: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    series = {str(item.get("code")): item for item in history.get("series") or [] if item.get("code")}
    benchmark = series.get(benchmark_code)
    if not benchmark:
        raise ValueError(f"benchmark {benchmark_code} is missing from history")
    assets: list[dict[str, Any]] = []
    for code in dict.fromkeys(asset_codes):
        asset = series.get(code)
        if not asset:
            assets.append({
                "code": code,
                "as_of": as_of,
                "history_count": 0,
                "coverage": 0.0,
                "state": "missing_series",
                "directional_role": "timing_overlay_only",
                "warnings": ["asset series is missing from history"],
            })
            continue
        assets.append(compute_asset_timing(asset, benchmark, as_of=as_of))
    coverage = mean([float(item.get("coverage") or 0.0) for item in assets]) or 0.0
    dates = [str(item.get("as_of") or "") for item in assets if item.get("as_of")]
    warnings = list(history.get("warnings") or [])
    warnings.extend([
        "Donchian thresholds exclude the decision bar; same-bar execution is prohibited.",
        "The weekly gate uses completed weekly bars by default and treats an unfinished week as provisional.",
        "Any conditional trade still requires a point-in-time timing backtest with costs and next-session execution.",
    ])
    return {
        "schema": "evidence.signal/1",
        "signal_type": "trade_timing",
        "method_version": METHOD_VERSION,
        "created_at": utc_now(),
        "as_of": max(dates) if dates else as_of,
        "coverage": round(coverage, 3),
        "values": {
            "benchmark_code": benchmark_code,
            "assets": assets,
        },
        "inputs": {
            "history_schema": history.get("schema"),
            "asset_codes": list(dict.fromkeys(asset_codes)),
            "benchmark_code": benchmark_code,
            "as_of": as_of,
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--asset-code", action="append", required=True)
    parser.add_argument("--benchmark-code", help="defaults to the sector benchmark embedded in history")
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_json(args.history)
    benchmark_code = args.benchmark_code or ((((history.get("universe_context") or {}).get("benchmark") or {}).get("code")))
    if not benchmark_code:
        parser.error("--benchmark-code is required when history has no embedded sector benchmark")
    result = compute_timing(history, args.asset_code, str(benchmark_code), as_of=args.as_of)
    result["inputs"]["history_sha256"] = sha256_file(args.history)
    result["inputs"]["history_path"] = str(args.history)
    atomic_write_json(args.output, result)
    states = {item["code"]: item["state"] for item in result["values"]["assets"]}
    print(f"states={states} coverage={result['coverage']:.0%}")
    return 0 if any(item.get("coverage", 0) > 0 for item in result["values"]["assets"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
