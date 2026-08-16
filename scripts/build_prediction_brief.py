#!/usr/bin/env python3
"""Build a blogger-logic causal research scaffold from forecast and selection signals."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now

DEFAULT_PRESETS = Path(__file__).resolve().parent.parent / "references" / "sector-presets.json"


def _contradiction(forecast: dict[str, Any]) -> str:
    horizons = (((forecast.get("values") or {}).get("forecasts")) or {})
    short = horizons.get("5d") or {}
    swing = horizons.get("20d") or {}
    if short.get("regime") != swing.get("regime"):
        return (
            f"5日信号为{short.get('regime')}（{short.get('score')}），但20日信号为"
            f"{swing.get('regime')}（{swing.get('score')}）：短期价格与中期结构为何分化？"
        )
    return (
        f"5日与20日信号均为{short.get('regime')}，但价格重定价是否有基本面兑现、"
        "资金持续性和产业链传导支持？"
    )


def build_brief(
    topic: str,
    preset: str,
    forecast: dict[str, Any],
    selection: dict[str, Any],
    evidence_pack: dict[str, Any] | None = None,
    backtest: dict[str, Any] | None = None,
    presets: dict[str, Any] | None = None,
    cross_market: dict[str, Any] | None = None,
    news_coverage: dict[str, Any] | None = None,
    signal_backtest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    presets = presets or load_json(DEFAULT_PRESETS)
    preset_config = ((presets.get("presets") or {}).get(preset) or {})
    profile_key = preset_config.get("research_profile") or presets.get("default_research_profile") or "generic-industry"
    profile = ((presets.get("research_profiles") or {}).get(profile_key) or {})
    candidates = (((selection.get("values") or {}).get("candidates")) or [])
    facts = (evidence_pack or {}).get("facts") or []
    substantive_facts = [
        item for item in facts
        if item.get("evidence_role") not in {"discovery_lead", "publisher_index"}
        and item.get("observation_scope") != "metadata_only"
    ]
    warnings = list(forecast.get("warnings") or []) + list(selection.get("warnings") or [])
    if backtest:
        warnings.extend(backtest.get("warnings") or [])
    if evidence_pack:
        warnings.extend(evidence_pack.get("warnings") or [])
    if cross_market:
        warnings.extend(cross_market.get("warnings") or [])
    if news_coverage:
        warnings.extend(news_coverage.get("warnings") or [])
    if signal_backtest:
        warnings.extend(signal_backtest.get("warnings") or [])
    actor_rows = [
        {
            "actor": actor,
            "goal": "research_required",
            "constraint": "research_required",
            "observable_evidence": [],
        }
        for actor in profile.get("actors") or ["政策制定者", "产业链公司", "客户", "资本提供者"]
    ]
    candidate_theses = []
    for item in candidates:
        candidate_theses.append({
            "rank": item.get("rank"),
            "code": item.get("code"),
            "name": item.get("name"),
            "quantitative_evidence": {
                "score": item.get("score"),
                "strengths": item.get("strengths"),
                "risks": item.get("risks"),
            },
            "role_in_industry_chain": "research_required",
            "expectation_gap": "research_required",
            "catalyst": "research_required",
            "who_benefits_and_why": "research_required",
            "fundamental_confirmation": "research_required",
            "supporting_fact_ids": [],
            "fundamental_verdict": "research_required",
            "valuation_verdict": "research_required",
            "catalyst_status": "research_required",
            "risk_level": "research_required",
            "competing_explanation": "research_required",
            "second_order_effect": "research_required",
            "invalidation_signal": "research_required",
        })
    research_questions = [
        "当前价格上涨/下跌究竟在交易什么预期，市场共识是什么？",
        "哪个数据或行为与表面叙事矛盾，形成真正的预期差？",
        "政策、供给、需求、成本、融资五类约束中，哪个是主导变量？",
        "谁掌握资源和定价权，谁承担成本，谁拥有更好的退出选项？",
        "催化剂如何传导到订单、收入、利润、现金流或估值？量级足够吗？",
        "如果竞争解释成立，应观察到什么不同数据？",
        "哪个下一期数据、公告或事件会证伪这条链？",
    ]
    research_questions.extend(profile.get("questions") or [])
    research_questions.extend(
        [
            "美股和韩股同板块的变化来自共同风险偏好，还是可传导的订单、价格、库存或资本开支变量？",
            "A股相对外盘是确认、拒绝还是逆势走强？本地政策、估值和资金结构如何解释差异？",
        ]
    )
    cross_values = (cross_market or {}).get("values") or {}
    return {
        "schema": "prediction.brief/1",
        "topic": topic,
        "preset": preset,
        "sector_research_profile": {
            "key": profile_key,
            "valuation_framework": profile.get("valuation_framework"),
            "display_name": preset_config.get("display_name") or topic,
        },
        "created_at": utc_now(),
        "as_of": forecast.get("as_of") or selection.get("as_of"),
        "status": "research_scaffold_not_publication_ready",
        "blogger_logic": {
            "contradiction": _contradiction(forecast),
            "verified_fact_ids": [item.get("fact_id") for item in substantive_facts if item.get("fact_id")],
            "actor_matrix": actor_rows,
            "surface_explanation": "research_required",
            "structural_cause": "research_required",
            "causal_chain": [
                "trigger", "constraint", "actor_decision", "industry_transmission",
                "earnings_or_cashflow_effect", "valuation_response", "feedback_or_reversal",
            ],
            "competing_explanation": "research_required",
            "second_order_effect": "research_required",
            "conditional_conclusion": "research_required",
        },
        "quantitative_layer": {
            "forecast": (forecast.get("values") or {}).get("forecasts"),
            "selection_as_of": selection.get("as_of"),
            "candidate_count": len(candidates),
            "backtest_metrics": (backtest or {}).get("metrics"),
            "backtest_period": (backtest or {}).get("period"),
            "backtest_settings": (backtest or {}).get("settings"),
            "cross_market_overlay": {
                "provided": bool(cross_market),
                "as_of": (cross_market or {}).get("as_of"),
                "acceptance": cross_values.get("a_share_acceptance"),
                "foreign_impulse_5d_pct": cross_values.get("foreign_impulse_5d_pct"),
                "market_impulses": cross_values.get("market_impulses"),
                "transmission_variables": cross_values.get("transmission_variables"),
                "coverage": (cross_market or {}).get("coverage"),
            },
            "sector_signal_validation": {
                "provided": bool(signal_backtest),
                "current_score": (signal_backtest or {}).get("current_score"),
                "current_bucket": (signal_backtest or {}).get("current_bucket"),
                "gate": (signal_backtest or {}).get("gate"),
            },
            "news_coverage": {
                "provided": bool(news_coverage),
                "status": (news_coverage or {}).get("status"),
                "gate": (news_coverage or {}).get("gate"),
            },
        },
        "candidate_theses": candidate_theses,
        "research_questions": research_questions,
        "publication_gate": {
            "has_evidence_pack": bool(evidence_pack),
            "verified_fact_count": len(substantive_facts),
            "total_fact_count": len(facts),
            "has_walk_forward_backtest": bool(backtest),
            "has_cross_market_overlay": bool(cross_market),
            "news_coverage_complete": bool(((news_coverage or {}).get("gate") or {}).get("passed")),
            "sector_signal_usable": ((signal_backtest or {}).get("gate") or {}).get("status") == "usable",
            "all_causal_fields_resolved": False,
            "candidate_verdicts_resolved": False,
            "ready": False,
        },
        "warnings": list(dict.fromkeys(warnings + [
            "Quantitative ranking is evidence for attention allocation, not a substitute for causal research.",
            "Do not publish candidate names as recommendations until research_required fields are resolved.",
        ])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--preset", default="custom")
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--evidence-pack", type=Path)
    parser.add_argument("--backtest", type=Path)
    parser.add_argument("--cross-market-signal", type=Path)
    parser.add_argument("--news-coverage", type=Path)
    parser.add_argument("--signal-backtest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    forecast = load_json(args.forecast)
    selection = load_json(args.selection)
    presets = load_json(args.presets)
    if args.preset != "custom" and args.preset not in (presets.get("presets") or {}):
        parser.error(f"unknown preset {args.preset!r}; use fetch_sector_universe.py --list-presets")
    evidence_pack = load_json(args.evidence_pack) if args.evidence_pack else None
    backtest = load_json(args.backtest) if args.backtest else None
    cross_market = load_json(args.cross_market_signal) if args.cross_market_signal else None
    news_coverage = load_json(args.news_coverage) if args.news_coverage else None
    signal_backtest = load_json(args.signal_backtest) if args.signal_backtest else None
    result = build_brief(
        args.topic, args.preset, forecast, selection, evidence_pack, backtest, presets, cross_market,
        news_coverage, signal_backtest,
    )
    result["inputs"] = {
        "forecast_sha256": sha256_file(args.forecast),
        "selection_sha256": sha256_file(args.selection),
        "evidence_pack_sha256": sha256_file(args.evidence_pack) if args.evidence_pack else None,
        "backtest_sha256": sha256_file(args.backtest) if args.backtest else None,
        "cross_market_signal_sha256": sha256_file(args.cross_market_signal) if args.cross_market_signal else None,
        "news_coverage_sha256": sha256_file(args.news_coverage) if args.news_coverage else None,
        "signal_backtest_sha256": sha256_file(args.signal_backtest) if args.signal_backtest else None,
    }
    atomic_write_json(args.output, result)
    print(
        f"brief candidates={len(result['candidate_theses'])} facts={result['publication_gate']['verified_fact_count']} "
        f"ready={result['publication_gate']['ready']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
