#!/usr/bin/env python3
"""Compute interpretable Chinese finance text signals from a UTF-8 document."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from evidence_core import atomic_write_json, clamp, sha256_file, utc_now


METHOD_VERSION = "finance-text-signals/1.0"
LEXICONS = {
    "positive": ["增长", "改善", "突破", "上调", "回升", "盈利", "增持", "超预期", "创新高", "利好", "领先", "扩张"],
    "negative": ["下降", "恶化", "下调", "亏损", "减持", "违约", "风险", "暴跌", "低于预期", "收缩", "处罚", "危机"],
    "uncertainty": ["可能", "或许", "预计", "尚未", "不确定", "有待", "传闻", "据称", "无法确认", "存在变数", "取决于"],
    "urgency": ["突发", "紧急", "立即", "警告", "最后期限", "迫在眉睫", "史上首次", "创纪录"],
    "causal": ["因为", "所以", "导致", "意味着", "原因是", "本质上", "反过来", "从而", "取决于", "结果是"],
    "source_language": ["数据显示", "根据", "公告", "报告", "统计", "原文", "官方", "同比", "环比"],
}


def _count_phrases(text: str, phrases: list[str]) -> tuple[int, dict[str, int]]:
    detail = {phrase: text.count(phrase) for phrase in phrases if phrase in text}
    return sum(detail.values()), detail


def compute_text_signals(text: str) -> dict:
    comparison_text = re.sub(r"\s+", "", text)
    length = len(comparison_text)
    if length == 0:
        raise ValueError("text is empty")
    counts: dict[str, int] = {}
    matches: dict[str, dict[str, int]] = {}
    for category, phrases in LEXICONS.items():
        counts[category], matches[category] = _count_phrases(comparison_text, phrases)
    positive = counts["positive"]
    negative = counts["negative"]
    polarity = (positive - negative) / (positive + negative + 5)
    per_thousand = {key: 1000 * value / length for key, value in counts.items()}
    numbers = len(re.findall(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?%?", text))
    dates = len(re.findall(r"(?:20\d{2}[-年/.])?\d{1,2}[-月/.]\d{1,2}日?", text))
    evidence_density = 1000 * (counts["source_language"] + numbers + dates) / length
    return {
        "schema": "evidence.signal/1",
        "signal_type": "finance_text_signals",
        "method_version": METHOD_VERSION,
        "as_of": utc_now(),
        "values": {
            "polarity": round(polarity, 6),
            "polarity_0_100": round(clamp(50 + 50 * polarity), 3),
            "uncertainty_per_1000": round(per_thousand["uncertainty"], 3),
            "urgency_per_1000": round(per_thousand["urgency"], 3),
            "causal_density_per_1000": round(per_thousand["causal"], 3),
            "evidence_density_per_1000": round(evidence_density, 3),
            "number_count": numbers,
            "date_count": dates,
        },
        "coverage": 1.0,
        "inputs": {"characters": length, "lexicon_categories": sorted(LEXICONS)},
        "counts": counts,
        "matches": matches,
        "warnings": [
            "Dictionary signals do not resolve negation, sarcasm or target-specific stance.",
            "Polarity measures language, not the likely market impact of the event.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    text = args.input.read_text(encoding="utf-8")
    result = compute_text_signals(text)
    result["inputs"]["file"] = str(args.input.resolve())
    result["inputs"]["sha256"] = sha256_file(args.input)
    atomic_write_json(args.output, result)
    print(f"wrote text signals to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
