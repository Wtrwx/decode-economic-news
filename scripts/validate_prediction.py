#!/usr/bin/env python3
"""Validate forecast, selection, backtest and blogger-logic publication gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_core import load_json


def _score(value: Any) -> bool:
    return isinstance(value, (int, float)) and 0 <= float(value) <= 100


def _contains_marker(value: Any, marker: str = "research_required") -> bool:
    if isinstance(value, dict):
        return any(_contains_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(_contains_marker(item, marker) for item in value)
    return value == marker


def validate_prediction_documents(
    forecast: dict[str, Any],
    selection: dict[str, Any],
    backtest: dict[str, Any] | None = None,
    brief: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
    *,
    publication: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if forecast.get("schema") != "evidence.signal/1" or forecast.get("signal_type") != "sector_trend_forecast":
        errors.append("forecast must be evidence.signal/1 sector_trend_forecast")
    horizons = (((forecast.get("values") or {}).get("forecasts")) or {})
    for horizon in ("5d", "20d"):
        item = horizons.get(horizon) or {}
        if not _score(item.get("score")):
            errors.append(f"forecast {horizon} score must be between 0 and 100")
        if item.get("probability_status") != "uncalibrated_direction_score":
            errors.append(f"forecast {horizon} must disclose uncalibrated probability status")
        if not isinstance(item.get("coverage"), (int, float)) or not 0 <= float(item["coverage"]) <= 1:
            errors.append(f"forecast {horizon} coverage must be between 0 and 1")

    if selection.get("schema") != "evidence.signal/1" or selection.get("signal_type") != "stock_selection":
        errors.append("selection must be evidence.signal/1 stock_selection")
    candidates = (((selection.get("values") or {}).get("candidates")) or [])
    if not candidates:
        errors.append("selection has no candidates")
    codes = [str(item.get("code") or "") for item in candidates]
    if len(codes) != len(set(codes)):
        errors.append("selection contains duplicate candidate codes")
    for item in candidates:
        if len(str(item.get("code") or "")) != 6 or not _score(item.get("score")):
            errors.append(f"invalid candidate code/score: {item.get('code')}")

    if backtest:
        if backtest.get("schema") != "model.backtest/1":
            errors.append("backtest must be model.backtest/1")
        period = backtest.get("period") or {}
        observations = int(period.get("candidate_observations") or 0)
        evaluation_periods = int(period.get("evaluation_periods") or 0)
        if observations < 30:
            warnings.append("backtest has fewer than 30 candidate observations")
        if evaluation_periods < 20:
            warnings.append("backtest has fewer than 20 evaluation periods")
        if float((backtest.get("settings") or {}).get("round_trip_cost_bps") or 0) <= 0:
            warnings.append("backtest does not deduct positive transaction costs")
        if publication and evaluation_periods < 20:
            errors.append("publication requires at least 20 walk-forward evaluation periods")
        if publication and observations < 30:
            errors.append("publication requires at least 30 candidate observations")
        if publication and float((backtest.get("settings") or {}).get("round_trip_cost_bps") or 0) <= 0:
            errors.append("publication requires positive modeled transaction costs")
        for bucket in backtest.get("score_buckets") or []:
            if bucket.get("probability_publishable") and int(bucket.get("observations") or 0) < 30:
                errors.append(f"score bucket {bucket.get('bucket')} is marked publishable with fewer than 30 observations")
    elif publication:
        errors.append("publication mode requires a walk-forward backtest")

    if brief:
        if brief.get("schema") != "prediction.brief/1":
            errors.append("brief must be prediction.brief/1")
        if not (brief.get("blogger_logic") or {}).get("contradiction"):
            errors.append("brief is missing the opening contradiction")
        if publication:
            gate = brief.get("publication_gate") or {}
            if not gate.get("ready"):
                errors.append("publication gate is not ready")
            if int(gate.get("verified_fact_count") or 0) < 3:
                errors.append("publication requires at least three verified facts")
            if not gate.get("news_coverage_complete"):
                errors.append("publication requires completed core-media coverage")
            if not gate.get("sector_signal_usable"):
                errors.append("publication requires a usable sector-signal backtest; otherwise abstain")
            if not gate.get("selector_backtest_usable"):
                errors.append("publication requires a usable stock-selector backtest")
            if _contains_marker(brief):
                errors.append("publication brief still contains research_required fields")
    elif publication:
        errors.append("publication mode requires a blogger-logic brief")

    if recommendation:
        if recommendation.get("schema") != "stock.recommendation/1":
            errors.append("recommendation must be stock.recommendation/1")
        suitability = recommendation.get("suitability") or {}
        single_cap = float(suitability.get("single_cap_pct") or 0)
        theme_cap = float(suitability.get("theme_cap_pct") or 0)
        if suitability.get("risk_profile") not in {"conservative", "balanced", "aggressive"}:
            errors.append("recommendation has an invalid risk profile")
        if suitability.get("status") not in {"user_supplied", "non_personalized_default"}:
            errors.append("recommendation must disclose personalization status")
        recs = recommendation.get("recommendations") or []
        rec_codes = [str(item.get("code") or "") for item in recs]
        if not recs or len(rec_codes) != len(set(rec_codes)):
            errors.append("recommendations must be non-empty with unique codes")
        selected_codes = {str(item.get("code") or "") for item in candidates}
        if not set(rec_codes).issubset(selected_codes):
            errors.append("recommendation contains securities outside the selected candidates")
        for item in recs:
            action = item.get("action")
            position = float(item.get("model_position_pct") or 0)
            if action not in {"条件买入", "观察等待", "回避"}:
                errors.append(f"invalid recommendation action for {item.get('code')}: {action}")
            if position < 0 or position > single_cap + 1e-9:
                errors.append(f"position exceeds single-name cap for {item.get('code')}")
            if action == "条件买入":
                if position <= 0:
                    errors.append(f"conditional buy has no position for {item.get('code')}")
                if not all((item.get("gate_checks") or {}).values()):
                    errors.append(f"conditional buy failed a gate for {item.get('code')}")
                plan = item.get("trade_plan") or {}
                if not plan.get("entry_condition") or not plan.get("technical_stop_reference"):
                    errors.append(f"conditional buy lacks entry/stop controls for {item.get('code')}")
            elif position != 0:
                errors.append(f"non-buy action has a non-zero position for {item.get('code')}")
        controls = recommendation.get("portfolio_controls") or {}
        total = sum(float(item.get("model_position_pct") or 0) for item in recs)
        if total > theme_cap + 1e-6:
            errors.append("recommendation exceeds theme position cap")
        if abs(total - float(controls.get("recommended_theme_position_pct") or 0)) > 0.02:
            errors.append("reported theme position does not equal recommendation positions")
    elif publication:
        errors.append("publication mode requires a stock recommendation document")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--backtest", type=Path)
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--recommendation", type=Path)
    parser.add_argument("--publication", action="store_true")
    args = parser.parse_args()
    report = validate_prediction_documents(
        load_json(args.forecast), load_json(args.selection),
        load_json(args.backtest) if args.backtest else None,
        load_json(args.brief) if args.brief else None,
        load_json(args.recommendation) if args.recommendation else None,
        publication=args.publication,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
