#!/usr/bin/env python3
"""Deterministic price/volume factors shared by forecasts, selection and backtests."""

from __future__ import annotations

import math
import statistics
from typing import Any

from evidence_core import clamp


MIN_HISTORY = 80


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def clean_bars(bars: list[dict[str, Any]], as_of: str | None = None) -> list[dict[str, Any]]:
    cleaned: dict[str, dict[str, Any]] = {}
    for raw in bars:
        date = str(raw.get("date") or "")[:10]
        close = _number(raw.get("close"))
        if not date or close is None or close <= 0 or (as_of and date > as_of):
            continue
        item = dict(raw)
        item["date"] = date
        item["close"] = close
        for key in ("open", "high", "low", "volume"):
            item[key] = _number(raw.get(key))
        cleaned[date] = item
    return [cleaned[key] for key in sorted(cleaned)]


def pct_change(values: list[float], periods: int) -> float | None:
    if periods <= 0 or len(values) <= periods or values[-periods - 1] <= 0:
        return None
    return (values[-1] / values[-periods - 1] - 1.0) * 100.0


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def annualized_volatility(values: list[float], periods: int = 20) -> float | None:
    if len(values) < periods + 1:
        return None
    returns = [values[i] / values[i - 1] - 1.0 for i in range(len(values) - periods, len(values))]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(252) * 100.0


def max_drawdown(values: list[float], periods: int = 60) -> float | None:
    window = values[-periods:] if len(values) >= periods else values
    if len(window) < 2:
        return None
    peak = window[0]
    worst = 0.0
    for value in window:
        peak = max(peak, value)
        worst = min(worst, (value / peak - 1.0) * 100.0)
    return worst


def scaled(value: float | None, low: float, high: float, *, inverse: bool = False) -> float | None:
    if value is None or high <= low:
        return None
    score = clamp((value - low) / (high - low) * 100.0)
    return 100.0 - score if inverse else score


def weighted_score(components: dict[str, float | None], weights: dict[str, float]) -> tuple[float | None, float]:
    available = [(key, value, weights[key]) for key, value in components.items() if value is not None and key in weights]
    available_weight = sum(weight for _, _, weight in available)
    total_weight = sum(weights.values())
    if available_weight <= 0 or total_weight <= 0:
        return None, 0.0
    score = sum(float(value) * weight for _, value, weight in available) / available_weight
    return round(score, 3), round(available_weight / total_weight, 3)


def compute_features(
    bars: list[dict[str, Any]],
    benchmark_bars: list[dict[str, Any]] | None = None,
    *,
    as_of: str | None = None,
) -> dict[str, float | str | None]:
    rows = clean_bars(bars, as_of)
    closes = [float(item["close"]) for item in rows]
    volumes = [float(item["volume"]) for item in rows if item.get("volume") is not None]
    if len(closes) < MIN_HISTORY:
        return {"as_of": rows[-1]["date"] if rows else as_of, "history_count": len(closes)}

    sma20 = mean(closes[-20:])
    sma60 = mean(closes[-60:])
    prior_sma20 = mean(closes[-30:-10])
    volume20 = mean(volumes[-20:]) if len(volumes) >= 20 else None
    volume60 = mean(volumes[-60:]) if len(volumes) >= 60 else None
    features: dict[str, float | str | None] = {
        "as_of": rows[-1]["date"],
        "history_count": len(closes),
        "close": round(closes[-1], 6),
        "return_5d_pct": pct_change(closes, 5),
        "return_20d_pct": pct_change(closes, 20),
        "return_60d_pct": pct_change(closes, 60),
        "ma20_gap_pct": ((closes[-1] / sma20 - 1.0) * 100.0) if sma20 else None,
        "ma20_vs_ma60_pct": ((sma20 / sma60 - 1.0) * 100.0) if sma20 and sma60 else None,
        "ma20_slope_10d_pct": ((sma20 / prior_sma20 - 1.0) * 100.0) if sma20 and prior_sma20 else None,
        "volume_20d_vs_60d": (volume20 / volume60) if volume20 is not None and volume60 else None,
        "volatility_20d_annualized_pct": annualized_volatility(closes, 20),
        "max_drawdown_60d_pct": max_drawdown(closes, 60),
    }
    if benchmark_bars:
        benchmark_rows = clean_bars(benchmark_bars, str(features["as_of"]))
        benchmark_closes = [float(item["close"]) for item in benchmark_rows]
        for periods in (20, 60):
            own = features.get(f"return_{periods}d_pct")
            benchmark = pct_change(benchmark_closes, periods)
            features[f"relative_{periods}d_pct"] = (
                float(own) - benchmark if isinstance(own, (int, float)) and benchmark is not None else None
            )
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in features.items()}


STOCK_WEIGHTS = {
    "momentum_20d": 0.18,
    "momentum_60d": 0.12,
    "relative_20d": 0.18,
    "relative_60d": 0.12,
    "trend": 0.15,
    "volume_confirmation": 0.10,
    "volatility_quality": 0.08,
    "drawdown_quality": 0.07,
}


def stock_component_scores(features: dict[str, Any]) -> dict[str, float | None]:
    trend_parts = [
        scaled(_number(features.get("ma20_gap_pct")), -10, 10),
        scaled(_number(features.get("ma20_vs_ma60_pct")), -8, 8),
        scaled(_number(features.get("ma20_slope_10d_pct")), -6, 6),
    ]
    valid_trend = [value for value in trend_parts if value is not None]
    return {
        "momentum_20d": scaled(_number(features.get("return_20d_pct")), -15, 15),
        "momentum_60d": scaled(_number(features.get("return_60d_pct")), -30, 30),
        "relative_20d": scaled(_number(features.get("relative_20d_pct")), -10, 10),
        "relative_60d": scaled(_number(features.get("relative_60d_pct")), -20, 20),
        "trend": mean(valid_trend),
        "volume_confirmation": scaled(_number(features.get("volume_20d_vs_60d")), 0.6, 1.6),
        "volatility_quality": scaled(
            _number(features.get("volatility_20d_annualized_pct")), 15, 70, inverse=True
        ),
        "drawdown_quality": scaled(_number(features.get("max_drawdown_60d_pct")), -40, 0),
    }


def score_stock(features: dict[str, Any]) -> tuple[float | None, float, dict[str, float | None]]:
    components = stock_component_scores(features)
    score, coverage = weighted_score(components, STOCK_WEIGHTS)
    return score, coverage, {key: round(value, 3) if value is not None else None for key, value in components.items()}


def regime(score: float | None) -> str:
    if score is None:
        return "数据不足"
    if score >= 65:
        return "偏强"
    if score <= 35:
        return "偏弱"
    return "震荡/分歧"


def component_explanations(components: dict[str, float | None], limit: int = 3) -> tuple[list[str], list[str]]:
    labels = {
        "momentum_20d": "20日动量",
        "momentum_60d": "60日动量",
        "relative_20d": "20日相对强弱",
        "relative_60d": "60日相对强弱",
        "trend": "均线趋势",
        "volume_confirmation": "量能确认",
        "volatility_quality": "波动质量",
        "drawdown_quality": "回撤控制",
    }
    available = [(key, float(value)) for key, value in components.items() if value is not None]
    strengths = [f"{labels[key]} {value:.1f}" for key, value in sorted(available, key=lambda item: item[1], reverse=True)[:limit]]
    risks = [f"{labels[key]} {value:.1f}" for key, value in sorted(available, key=lambda item: item[1])[:limit]]
    return strengths, risks


def breadth(constituent_bars: list[list[dict[str, Any]]], as_of: str | None = None) -> dict[str, float | int | None]:
    above20 = above60 = positive20 = eligible = 0
    for bars in constituent_bars:
        rows = clean_bars(bars, as_of)
        closes = [float(item["close"]) for item in rows]
        if len(closes) < MIN_HISTORY:
            continue
        eligible += 1
        sma20 = mean(closes[-20:])
        sma60 = mean(closes[-60:])
        above20 += int(bool(sma20 and closes[-1] > sma20))
        above60 += int(bool(sma60 and closes[-1] > sma60))
        ret20 = pct_change(closes, 20)
        positive20 += int(ret20 is not None and ret20 > 0)
    if not eligible:
        return {"eligible_count": 0, "above_ma20_pct": None, "above_ma60_pct": None, "positive_20d_pct": None}
    return {
        "eligible_count": eligible,
        "above_ma20_pct": round(100.0 * above20 / eligible, 3),
        "above_ma60_pct": round(100.0 * above60 / eligible, 3),
        "positive_20d_pct": round(100.0 * positive20 / eligible, 3),
    }


def sector_scores(features: dict[str, Any], breadth_values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    trend_parts = [
        scaled(_number(features.get("ma20_gap_pct")), -8, 8),
        scaled(_number(features.get("ma20_vs_ma60_pct")), -8, 8),
        scaled(_number(features.get("ma20_slope_10d_pct")), -5, 5),
    ]
    trend = mean([value for value in trend_parts if value is not None])
    common = {
        "trend": trend,
        "breadth_20d": scaled(_number(breadth_values.get("above_ma20_pct")), 20, 80),
        "breadth_60d": scaled(_number(breadth_values.get("above_ma60_pct")), 20, 80),
        "volatility_quality": scaled(
            _number(features.get("volatility_20d_annualized_pct")), 12, 55, inverse=True
        ),
    }
    short_components = {
        "momentum_5d": scaled(_number(features.get("return_5d_pct")), -8, 8),
        "momentum_20d": scaled(_number(features.get("return_20d_pct")), -15, 15),
        "relative_20d": scaled(_number(features.get("relative_20d_pct")), -10, 10),
        "trend": common["trend"],
        "breadth_20d": common["breadth_20d"],
        "volatility_quality": common["volatility_quality"],
    }
    swing_components = {
        "momentum_20d": scaled(_number(features.get("return_20d_pct")), -15, 15),
        "momentum_60d": scaled(_number(features.get("return_60d_pct")), -30, 30),
        "relative_60d": scaled(_number(features.get("relative_60d_pct")), -20, 20),
        "trend": common["trend"],
        "breadth_20d": common["breadth_20d"],
        "breadth_60d": common["breadth_60d"],
        "volatility_quality": common["volatility_quality"],
    }
    specs = {
        "5d": (short_components, {
            "momentum_5d": 0.25, "momentum_20d": 0.20, "relative_20d": 0.10,
            "trend": 0.20, "breadth_20d": 0.15, "volatility_quality": 0.10,
        }),
        "20d": (swing_components, {
            "momentum_20d": 0.20, "momentum_60d": 0.20, "relative_60d": 0.10,
            "trend": 0.20, "breadth_20d": 0.10, "breadth_60d": 0.10,
            "volatility_quality": 0.10,
        }),
    }
    result: dict[str, dict[str, Any]] = {}
    for horizon, (components, weights) in specs.items():
        score, coverage = weighted_score(components, weights)
        result[horizon] = {
            "score": score,
            "regime": regime(score),
            "coverage": coverage,
            "components": {key: round(value, 3) if value is not None else None for key, value in components.items()},
            "weights": weights,
            "probability_status": "uncalibrated_direction_score",
        }
    return result
