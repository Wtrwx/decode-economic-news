#!/usr/bin/env python3
"""Compute the publication gate for a completed blogger-logic prediction brief."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from validate_evidence import validate_document


VALID_VERDICTS = {
    "fundamental_verdict": {"pass", "watch", "fail"},
    "valuation_verdict": {"attractive", "fair", "expensive", "not_meaningful"},
    "catalyst_status": {"confirmed", "plausible", "absent"},
    "risk_level": {"medium", "high", "very_high"},
}


def contains_marker(value: Any, marker: str = "research_required") -> bool:
    if isinstance(value, dict):
        return any(contains_marker(item, marker) for item in value.values())
    if isinstance(value, list):
        return any(contains_marker(item, marker) for item in value)
    return value == marker


def finalize_brief(
    brief: dict[str, Any],
    forecast: dict[str, Any],
    selection: dict[str, Any],
    evidence_pack: dict[str, Any],
    backtest: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(brief)
    errors: list[str] = []
    warnings: list[str] = []
    if result.get("schema") != "prediction.brief/1":
        errors.append("brief must be prediction.brief/1")
    evidence_validation = validate_document(evidence_pack)
    if not evidence_validation["valid"]:
        errors.extend(f"evidence: {item}" for item in evidence_validation["errors"])
    facts = evidence_pack.get("facts") or []
    fact_ids = {str(item.get("fact_id")) for item in facts if item.get("fact_id")}
    if len(facts) < 3:
        errors.append("at least three verified facts are required")
    if contains_marker(result):
        errors.append("brief still contains research_required fields")

    selected_codes = {
        str(item.get("code")) for item in (((selection.get("values") or {}).get("candidates")) or [])
    }
    thesis_codes = {str(item.get("code")) for item in result.get("candidate_theses") or []}
    if selected_codes != thesis_codes:
        errors.append("candidate theses must match the selected candidate codes")
    for thesis in result.get("candidate_theses") or []:
        code = str(thesis.get("code") or "")
        supporting = {str(item) for item in thesis.get("supporting_fact_ids") or []}
        if not supporting:
            errors.append(f"{code} has no supporting_fact_ids")
        missing = supporting - fact_ids
        if missing:
            errors.append(f"{code} references unknown fact IDs: {sorted(missing)}")
        for field, allowed in VALID_VERDICTS.items():
            if thesis.get(field) not in allowed:
                errors.append(f"{code} invalid {field}: {thesis.get(field)}")

    forecast_coverage = float(forecast.get("coverage") or 0)
    selection_coverage = float(selection.get("coverage") or 0)
    if forecast_coverage < 0.75:
        errors.append(f"forecast coverage below 75%: {forecast_coverage:.0%}")
    if selection_coverage < 0.75:
        errors.append(f"selection coverage below 75%: {selection_coverage:.0%}")
    period = backtest.get("period") or {}
    settings = backtest.get("settings") or {}
    evaluation_periods = int(period.get("evaluation_periods") or 0)
    observations = int(period.get("candidate_observations") or 0)
    costs = float(settings.get("round_trip_cost_bps") or 0)
    if evaluation_periods < 20:
        errors.append(f"at least 20 walk-forward periods required: {evaluation_periods}")
    if observations < 30:
        errors.append(f"at least 30 candidate observations required: {observations}")
    if costs <= 0:
        errors.append("backtest must include positive transaction costs")

    gate = {
        "has_evidence_pack": True,
        "verified_fact_count": len(facts),
        "has_walk_forward_backtest": True,
        "walk_forward_periods": evaluation_periods,
        "candidate_observations": observations,
        "forecast_coverage": forecast_coverage,
        "selection_coverage": selection_coverage,
        "all_causal_fields_resolved": not contains_marker(result.get("blogger_logic") or {}),
        "candidate_verdicts_resolved": not any(
            contains_marker(item) for item in result.get("candidate_theses") or []
        ),
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "finalized_at": utc_now(),
    }
    result["publication_gate"] = gate
    result["status"] = "publication_ready_for_conditional_recommendation" if gate["ready"] else "research_incomplete"
    result["quantitative_layer"] = {
        **(result.get("quantitative_layer") or {}),
        "backtest_metrics": backtest.get("metrics"),
        "backtest_period": period,
        "backtest_settings": settings,
    }
    result["finalization_warnings"] = list(dict.fromkeys(evidence_validation["warnings"] + warnings))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--evidence-pack", type=Path, required=True)
    parser.add_argument("--backtest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = finalize_brief(
        load_json(args.brief), load_json(args.forecast), load_json(args.selection),
        load_json(args.evidence_pack), load_json(args.backtest),
    )
    result["finalization_inputs"] = {
        "brief_sha256": sha256_file(args.brief),
        "forecast_sha256": sha256_file(args.forecast),
        "selection_sha256": sha256_file(args.selection),
        "evidence_pack_sha256": sha256_file(args.evidence_pack),
        "backtest_sha256": sha256_file(args.backtest),
    }
    atomic_write_json(args.output, result)
    gate = result["publication_gate"]
    print(f"ready={gate['ready']} errors={len(gate['errors'])} facts={gate['verified_fact_count']}")
    return 0 if gate["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
