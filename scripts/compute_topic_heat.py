#!/usr/bin/env python3
"""Measure topic attention velocity and source diversity from news JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, clamp, sha256_file, utc_now


METHOD_VERSION = "topic-heat/1.0"


def _parse_time(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _title_key(title: str) -> str:
    normalized = re.sub(r"[^\w\u3400-\u9fff]+", "", title).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_topic_heat(articles: list[dict[str, Any]], keywords: list[str], now: datetime | None = None) -> dict:
    if not keywords:
        raise ValueError("at least one keyword is required")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    matched: list[tuple[datetime, dict[str, Any]]] = []
    malformed = 0
    for article in articles:
        haystack = f"{article.get('title', '')}\n{article.get('content', '')}".lower()
        if not all(keyword.lower() in haystack for keyword in keywords):
            continue
        try:
            published = _parse_time(str(article.get("published_at") or ""))
        except (TypeError, ValueError):
            malformed += 1
            continue
        if published > now + timedelta(minutes=5) or published < now - timedelta(days=7):
            continue
        matched.append((published, article))
    unique: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for published, article in sorted(matched, key=lambda item: item[0], reverse=True):
        key = _title_key(str(article.get("title") or article.get("content") or ""))
        unique.setdefault(key, (published, article))
    deduplicated = list(unique.values())
    last_hour = [item for item in deduplicated if item[0] >= now - timedelta(hours=1)]
    last_24h = [item for item in deduplicated if item[0] >= now - timedelta(hours=24)]
    prior = [item for item in deduplicated if now - timedelta(days=7) <= item[0] < now - timedelta(hours=24)]
    prior_daily_average = len(prior) / 6
    velocity_ratio = (len(last_24h) + 1) / (prior_daily_average + 1)
    attention_score = clamp(50 + 20 * math.log2(velocity_ratio))
    sources = {str(article.get("source") or "unknown") for _, article in last_24h}
    diversity_score = clamp(20 * len(sources))
    recency_score = clamp(100 * len(last_hour) / max(1, len(last_24h)))
    heat_score = 0.60 * attention_score + 0.25 * diversity_score + 0.15 * recency_score
    duplicate_ratio = 1 - len(deduplicated) / len(matched) if matched else 0.0
    warnings = []
    if malformed:
        warnings.append(f"ignored {malformed} matched articles with invalid published_at")
    if len(sources) <= 1 and last_24h:
        warnings.append("last-24-hour attention comes from one source only")
    return {
        "schema": "evidence.signal/1",
        "signal_type": "topic_heat",
        "method_version": METHOD_VERSION,
        "as_of": now.isoformat(timespec="seconds"),
        "values": {
            "score": round(heat_score, 3),
            "attention_velocity_score": round(attention_score, 3),
            "source_diversity_score": round(diversity_score, 3),
            "recency_score": round(recency_score, 3),
            "last_hour_count": len(last_hour),
            "last_24h_count": len(last_24h),
            "prior_six_day_count": len(prior),
            "velocity_ratio": round(velocity_ratio, 6),
            "duplicate_ratio": round(duplicate_ratio, 6),
        },
        "coverage": 1.0 if matched else 0.0,
        "inputs": {"keywords": keywords, "input_articles": len(articles), "matched_articles": len(matched)},
        "warnings": warnings + ["Attention is separate from positive/negative sentiment and fundamental importance."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL with title, content, source, published_at")
    parser.add_argument("--keyword", action="append", required=True)
    parser.add_argument("--now", default="", help="ISO-8601 override for reproducible runs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    articles = []
    for line_number, line in enumerate(args.input.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        articles.append(value)
    now = _parse_time(args.now) if args.now else None
    result = compute_topic_heat(articles, args.keyword, now=now)
    result["inputs"]["file"] = str(args.input.resolve())
    result["inputs"]["sha256"] = sha256_file(args.input)
    atomic_write_json(args.output, result)
    print(f"topic heat={result['values']['score']:.1f}; matched={result['inputs']['matched_articles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
