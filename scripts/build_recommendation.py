#!/usr/bin/env python3
"""Generate gated conditional stock recommendations with position and exit controls."""

from __future__ import annotations

import argparse
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, clamp, load_json, sha256_file, utc_now


RISK_PROFILES = {
    "conservative": {
        "single_cap_pct": 3.0, "theme_cap_pct": 10.0, "risk_floor_pct": 5.0,
        "risk_cap_pct": 10.0, "risk_budget_pct": 0.25,
    },
    "balanced": {
        "single_cap_pct": 5.0, "theme_cap_pct": 20.0, "risk_floor_pct": 6.0,
        "risk_cap_pct": 12.0, "risk_budget_pct": 0.50,
    },
    "aggressive": {
        "single_cap_pct": 8.0, "theme_cap_pct": 30.0, "risk_floor_pct": 8.0,
        "risk_cap_pct": 15.0, "risk_budget_pct": 0.75,
    },
}


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _review_date(as_of: str, horizon: int) -> str | None:
    try:
        return (date.fromisoformat(as_of[:10]) + timedelta(days=round(horizon * 1.45))).isoformat()
    except (TypeError, ValueError):
        return None


def _entry_and_risk(
    candidate: dict[str, Any],
    profile: dict[str, float],
    timing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = candidate.get("features") or {}
    close = _number(features.get("close"))
    gap = _number(features.get("ma20_gap_pct"))
    alignment = _number(features.get("ma20_vs_ma60_pct"))
    annual_vol = _number(features.get("volatility_20d_annualized_pct"))
    ma20 = close / (1 + gap / 100) if close and gap is not None and (1 + gap / 100) > 0 else None
    ma60 = ma20 / (1 + alignment / 100) if ma20 and alignment is not None and (1 + alignment / 100) > 0 else None
    timing_risk = (timing or {}).get("risk") or {}
    timing_close = _number(((((timing or {}).get("timeframes") or {}).get("daily") or {}).get("close")))
    timing_stop = _number(timing_risk.get("technical_stop_reference"))
    timing_risk_pct = _number(timing_risk.get("risk_distance_pct"))
    timing_upside = _number(timing_risk.get("upside_review_reference_2r"))
    if timing and timing.get("entry_condition"):
        entry = str(timing["entry_condition"])
        close = timing_close or close
    elif gap is None:
        entry = "等待补齐MA20位置后再决定入场"
    elif gap > 8:
        entry = "不追高；等待回踩MA20附近±2%，或放量突破后完成回测确认"
    elif gap >= -3:
        entry = "可分2至3次建仓；首笔不超过建议仓位的三分之一"
    else:
        entry = "暂不左侧接刀；等待重新站上MA20并出现量能确认"
    if timing_stop is not None and timing_risk_pct is not None and timing_risk_pct > 0:
        risk_pct = timing_risk_pct
        technical_stop = timing_stop
        review_upside = timing_upside
        risk_method = "point_in_time_atr_and_prior_channel"
    else:
        daily_vol = annual_vol / math.sqrt(252) if annual_vol is not None else profile["risk_floor_pct"] / 2.5
        risk_pct = clamp(
            2.5 * daily_vol,
            profile["risk_floor_pct"],
            profile["risk_cap_pct"],
        )
        volatility_stop = close * (1 - risk_pct / 100) if close else None
        ma60_stop = ma60 * 0.98 if ma60 and close and ma60 * 0.98 < close else None
        stops = [value for value in (volatility_stop, ma60_stop) if value is not None]
        technical_stop = max(stops) if stops else None
        review_upside = close * (1 + 2 * risk_pct / 100) if close else None
        risk_method = "volatility_and_ma60_fallback"
    return {
        "last_close": round(close, 4) if close else None,
        "ma20_reference": round(ma20, 4) if ma20 else None,
        "ma60_reference": round(ma60, 4) if ma60 else None,
        "entry_condition": entry,
        "technical_risk_pct": round(risk_pct, 2),
        "technical_stop_reference": round(technical_stop, 4) if technical_stop else None,
        "upside_review_reference": round(review_upside, 4) if review_upside else None,
        "risk_method": risk_method,
        "timing_state": (timing or {}).get("state"),
        "execution_clock": timing_risk.get("execution_clock") if timing else None,
        "level_note": "止损与上行价格均为技术复核参考，不是保证成交或目标价。",
    }


def build_recommendation(
    forecast: dict[str, Any],
    selection: dict[str, Any],
    backtest: dict[str, Any],
    brief: dict[str, Any],
    *,
    risk_profile: str = "balanced",
    personalized: bool = False,
    trade_timing: dict[str, Any] | None = None,
    timing_backtest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate = brief.get("publication_gate") or {}
    if not gate.get("ready"):
        raise ValueError(f"prediction brief is not publication ready: {gate.get('errors')}")
    if trade_timing and (
        trade_timing.get("schema") != "evidence.signal/1"
        or trade_timing.get("signal_type") != "trade_timing"
    ):
        raise ValueError("trade_timing must be evidence.signal/1 with signal_type=trade_timing")
    if timing_backtest and timing_backtest.get("schema") != "model.timing-backtest/1":
        raise ValueError("timing_backtest must be model.timing-backtest/1")
    profile = RISK_PROFILES[risk_profile]
    candidates = (((selection.get("values") or {}).get("candidates")) or [])
    theses = {str(item.get("code")): item for item in brief.get("candidate_theses") or []}
    sector_20 = (((forecast.get("values") or {}).get("forecasts") or {}).get("20d") or {})
    sector_score = _number(sector_20.get("score"), 0.0) or 0.0
    metrics = backtest.get("metrics") or {}
    mean_excess = _number(metrics.get("mean_excess_return_pct"), 0.0) or 0.0
    excess_hit = _number(metrics.get("excess_hit_rate"), 0.0) or 0.0
    timing_assets = {
        str(item.get("code")): item
        for item in (((trade_timing or {}).get("values") or {}).get("assets") or [])
        if item.get("code")
    }
    timing_tests = {
        str(item.get("code")): item
        for item in ((timing_backtest or {}).get("assets") or [])
        if item.get("code")
    }
    timing_backtest_settings = (timing_backtest or {}).get("settings") or {}
    timing_backtest_window_valid = bool(
        timing_backtest_settings.get("start")
        and timing_backtest_settings.get("usable_gate_requires_predeclared_start") is True
        and timing_backtest_settings.get("terminal_incomplete_horizons") == "excluded"
    )
    maps = {
        "fundamental_verdict": {"pass": 85, "watch": 55, "fail": 10},
        "valuation_verdict": {"attractive": 85, "fair": 65, "expensive": 20, "not_meaningful": 55},
        "catalyst_status": {"confirmed": 85, "plausible": 65, "absent": 20},
        "risk_level": {"medium": 75, "high": 45, "very_high": 10},
    }
    recommendations = []
    for candidate in candidates:
        code = str(candidate.get("code"))
        thesis = theses.get(code) or {}
        stock_score = _number(candidate.get("score"), 0.0) or 0.0
        fundamental = maps["fundamental_verdict"].get(thesis.get("fundamental_verdict"), 0)
        valuation = maps["valuation_verdict"].get(thesis.get("valuation_verdict"), 0)
        catalyst = maps["catalyst_status"].get(thesis.get("catalyst_status"), 0)
        risk_quality = maps["risk_level"].get(thesis.get("risk_level"), 0)
        timing = timing_assets.get(code) or {}
        timing_test = timing_tests.get(code) or {}
        timing_state = str(timing.get("state") or "missing")
        timing_gate_status = str((timing_test.get("gate") or {}).get("status") or "missing")
        timing_risk_pct = _number(((timing.get("risk") or {}).get("risk_distance_pct")))
        timing_state_allowed = timing_state in {"triggered", "retest"}
        timing_backtest_usable = timing_gate_status == "usable" and timing_backtest_window_valid
        timing_risk_allowed = bool(
            timing_risk_pct is not None and 0 < timing_risk_pct <= profile["risk_cap_pct"]
        )
        conviction = round(
            0.45 * stock_score + 0.20 * sector_score + 0.15 * fundamental
            + 0.10 * catalyst + 0.05 * valuation + 0.05 * risk_quality,
            2,
        )
        valuation_framework = ((brief.get("sector_research_profile") or {}).get("valuation_framework") or "")
        pipeline_valuation = valuation_framework == "pipeline_milestone_and_risk_adjusted_cashflow"
        valuation_allowed = thesis.get("valuation_verdict") in {"attractive", "fair"} or (
            pipeline_valuation and thesis.get("valuation_verdict") == "not_meaningful"
        )
        buy_gate = all([
            stock_score >= 65,
            sector_score >= 55,
            mean_excess > 0,
            excess_hit >= 0.50,
            thesis.get("fundamental_verdict") == "pass",
            thesis.get("catalyst_status") in {"confirmed", "plausible"},
            valuation_allowed,
            thesis.get("risk_level") in {"medium", "high"},
            timing_state_allowed,
            timing_backtest_usable,
            timing_risk_allowed,
        ])
        hard_avoid = (
            thesis.get("fundamental_verdict") == "fail"
            or thesis.get("risk_level") == "very_high"
            or stock_score < 45
        )
        action = "条件买入" if buy_gate else ("回避" if hard_avoid else "观察等待")
        trade_plan = _entry_and_risk(candidate, profile, timing or None)
        preliminary_position = 0.0
        risk_position_cap = 0.0
        if action == "条件买入":
            strength = clamp((conviction - 60) / 25, 0, 1)
            preliminary_position = profile["single_cap_pct"] * (0.5 + 0.5 * strength)
            risk_distance = _number(trade_plan.get("technical_risk_pct"))
            if risk_distance and risk_distance > 0:
                risk_position_cap = profile["risk_budget_pct"] / risk_distance * 100.0
                preliminary_position = min(preliminary_position, risk_position_cap, profile["single_cap_pct"])
            else:
                preliminary_position = 0.0
        recommendations.append({
            "code": code,
            "name": candidate.get("name"),
            "action": action,
            "conviction_score": conviction,
            "model_position_pct": round(preliminary_position, 2),
            "quantitative_score": stock_score,
            "sector_20d_score": sector_score,
            "thesis": {
                "expectation_gap": thesis.get("expectation_gap"),
                "role_in_industry_chain": thesis.get("role_in_industry_chain"),
                "fundamental_confirmation": thesis.get("fundamental_confirmation"),
                "catalyst": thesis.get("catalyst"),
                "competing_explanation": thesis.get("competing_explanation"),
                "invalidation_signal": thesis.get("invalidation_signal"),
                "supporting_fact_ids": thesis.get("supporting_fact_ids") or [],
            },
            "research_verdicts": {
                key: thesis.get(key) for key in (
                    "fundamental_verdict", "valuation_verdict", "catalyst_status", "risk_level"
                )
            },
            "trade_plan": trade_plan,
            "timing_evidence": {
                "state": timing_state,
                "as_of": timing.get("as_of"),
                "coverage": timing.get("coverage"),
                "timing_backtest_gate": timing_gate_status,
                "timing_backtest_period": timing_test.get("period"),
                "timing_backtest_evaluation_start": timing_backtest_settings.get("start"),
                "risk_budget_position_cap_pct": round(risk_position_cap, 2) if risk_position_cap else 0.0,
            },
            "gate_checks": {
                "stock_score_at_least_65": stock_score >= 65,
                "sector_score_at_least_55": sector_score >= 55,
                "backtest_positive_excess": mean_excess > 0,
                "backtest_excess_hit_at_least_50pct": excess_hit >= 0.50,
                "fundamental_pass": thesis.get("fundamental_verdict") == "pass",
                "catalyst_present": thesis.get("catalyst_status") in {"confirmed", "plausible"},
                "valuation_allowed": valuation_allowed,
                "risk_level_allowed": thesis.get("risk_level") in {"medium", "high"},
                "timing_state_triggered_or_retest": timing_state_allowed,
                "timing_backtest_usable": timing_backtest_usable,
                "timing_backtest_window_predeclared_and_complete": timing_backtest_window_valid,
                "timing_risk_within_profile_cap": timing_risk_allowed,
            },
        })

    total_preliminary = sum(float(item["model_position_pct"]) for item in recommendations)
    scale = min(1.0, profile["theme_cap_pct"] / total_preliminary) if total_preliminary > 0 else 1.0
    for item in recommendations:
        item["model_position_pct"] = round(float(item["model_position_pct"]) * scale, 2)
    recommendations.sort(key=lambda item: (item["action"] == "条件买入", item["conviction_score"]), reverse=True)
    total_position = round(sum(float(item["model_position_pct"]) for item in recommendations), 2)
    as_of = str(forecast.get("as_of") or selection.get("as_of") or "")
    warnings = list(forecast.get("warnings") or []) + list(selection.get("warnings") or []) + list(backtest.get("warnings") or [])
    warnings.extend([
        "Recommendations are conditional research outputs and do not guarantee returns.",
        "No order is placed; verify price, disclosures and suitability again before any trade.",
        "A conditional buy requires a triggered/retest multi-timeframe setup and an asset-specific usable timing backtest.",
    ])
    if not trade_timing or not timing_backtest:
        warnings.append("Trade timing or its walk-forward backtest is missing; named candidates cannot pass the conditional-buy gate.")
    elif not timing_backtest_window_valid:
        warnings.append("Timing backtest lacks a predeclared evaluation start or includes incomplete terminal horizons; named candidates cannot pass the conditional-buy gate.")
    if not personalized:
        warnings.append("Risk profile is a non-personalized default because investor-specific information was not supplied.")
    if not any(item["action"] == "条件买入" for item in recommendations):
        warnings.append("No candidate passed every conditional-buy gate.")
    return {
        "schema": "stock.recommendation/1",
        "method_version": "conditional-recommendation/2.0",
        "created_at": utc_now(),
        "as_of": as_of,
        "valid_until": _review_date(as_of, 20),
        "suitability": {
            "risk_profile": risk_profile,
            "status": "user_supplied" if personalized else "non_personalized_default",
            **profile,
        },
        "sector_view": {
            "benchmark": ((forecast.get("values") or {}).get("benchmark")),
            "horizon": "20 trading days",
            "score": sector_score,
            "regime": sector_20.get("regime"),
            "coverage": sector_20.get("coverage"),
        },
        "backtest_evidence": {
            "metrics": metrics,
            "period": backtest.get("period"),
            "settings": backtest.get("settings"),
        },
        "recommendations": recommendations,
        "portfolio_controls": {
            "recommended_theme_position_pct": total_position,
            "theme_position_cap_pct": profile["theme_cap_pct"],
            "single_name_cap_pct": profile["single_cap_pct"],
            "review_triggers": [
                "20日板块评分跌破45",
                "公司公告或业绩否定核心因果链",
                "催化剂延迟、失败或已被价格充分兑现",
                "触发个股技术止损参考或用户风险承受能力变化",
                "技术择时状态不再是triggered/retest，或其样本外门禁转为abstain",
            ],
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--backtest", type=Path, required=True)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--risk-profile", choices=tuple(RISK_PROFILES), default="balanced")
    parser.add_argument("--personalized", action="store_true", help="mark that the user supplied suitability inputs")
    parser.add_argument("--trade-timing", type=Path)
    parser.add_argument("--timing-backtest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trade_timing = load_json(args.trade_timing) if args.trade_timing else None
    timing_backtest = load_json(args.timing_backtest) if args.timing_backtest else None
    result = build_recommendation(
        load_json(args.forecast), load_json(args.selection), load_json(args.backtest), load_json(args.brief),
        risk_profile=args.risk_profile, personalized=args.personalized,
        trade_timing=trade_timing, timing_backtest=timing_backtest,
    )
    result["inputs"] = {
        "forecast_sha256": sha256_file(args.forecast),
        "selection_sha256": sha256_file(args.selection),
        "backtest_sha256": sha256_file(args.backtest),
        "brief_sha256": sha256_file(args.brief),
    }
    if args.trade_timing:
        result["inputs"]["trade_timing_sha256"] = sha256_file(args.trade_timing)
    if args.timing_backtest:
        result["inputs"]["timing_backtest_sha256"] = sha256_file(args.timing_backtest)
    atomic_write_json(args.output, result)
    counts = {action: sum(item["action"] == action for item in result["recommendations"]) for action in ("条件买入", "观察等待", "回避")}
    print(f"actions={counts} theme_position={result['portfolio_controls']['recommended_theme_position_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
