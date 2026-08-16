#!/usr/bin/env python3
"""Fetch configured official RSS/Atom releases without third-party packages."""

from __future__ import annotations

import argparse
import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, atomic_write_json, load_json, normalized_identifier, provider, sha256_bytes


DEFAULT_PRESETS = Path(__file__).resolve().parent.parent / "references" / "official-feed-presets.json"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in node:
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _link(node: ET.Element) -> str:
    for child in node:
        if _local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        rel = str(child.attrib.get("rel") or "alternate")
        if href and rel in ("", "alternate"):
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def _period(raw: str, fallback: str) -> str:
    text = raw.strip()
    if not text:
        return fallback[:10]
    try:
        parsed = email.utils.parsedate_to_datetime(text)
        return parsed.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        return match.group(0) if match else fallback[:10]


def parse_feed(payload: bytes, *, publisher: str, retrieved_at: str, limit: int) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid RSS/Atom XML: {exc}") from exc
    entries = [node for node in root.iter() if _local_name(node.tag) in ("item", "entry")]
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in entries:
        title = _child_text(node, {"title"})
        url = _link(node)
        if not title or not url or url in seen:
            continue
        seen.add(url)
        raw_date = _child_text(node, {"pubdate", "published", "updated", "date"})
        period = _period(raw_date, retrieved_at)
        summary = _child_text(node, {"description", "summary", "content"})
        facts.append(
            {
                "fact_id": f"FEED-{period}-{normalized_identifier(publisher)}-{sha256_bytes(url.encode('utf-8'))[:12]}",
                "claim": f"{publisher} published: {title}",
                "period": period,
                "publisher": publisher,
                "source_url": url,
                "retrieved_at": retrieved_at,
                "title": title,
                "published_at_raw": raw_date,
                "summary": re.sub(r"<[^>]+>", " ", summary).strip()[:2000],
                "evidence_role": "official_release_index",
            }
        )
        if len(facts) >= limit:
            break
    return facts


def fetch_feed(
    preset_name: str,
    *,
    limit: int = 50,
    presets_path: Path = DEFAULT_PRESETS,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    config = load_json(presets_path)
    preset = (config.get("presets") or {}).get(preset_name)
    if not isinstance(preset, dict):
        available = ", ".join(sorted((config.get("presets") or {}).keys()))
        raise ValueError(f"unknown feed preset {preset_name!r}; available: {available}")
    client = CachedHttpClient(cache_dir)
    fetched = client.get(str(preset["url"]), ttl_seconds=900, min_interval_seconds=0.5)
    facts = parse_feed(
        fetched.body,
        publisher=str(preset["publisher"]),
        retrieved_at=fetched.retrieved_at,
        limit=limit,
    )
    if not facts:
        raise RuntimeError("official feed returned no usable entries")
    warnings = [
        "Feed entries prove publication and provide original links; verify the linked release text before quoting detailed claims."
    ]
    if fetched.warning:
        warnings.append(fetched.warning)
    return {
        "schema": "evidence.source/1",
        "provider": provider(
            str(preset["id"]),
            str(preset["publisher"]),
            float(preset["authority_score"]),
            float(preset["endpoint_stability"]),
        ),
        "retrieval": fetched.metadata(),
        "feed": {"preset": preset_name, "category": preset.get("category"), "url": preset["url"]},
        "facts": facts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--preset", default="")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_json(args.presets)
    if args.list_presets:
        for key, item in sorted((config.get("presets") or {}).items()):
            print(f"{key}\t{item['publisher']}\t{item['category']}")
        return 0
    if not args.preset or args.output is None:
        parser.error("--preset and --output are required unless --list-presets is used")
    result = fetch_feed(args.preset, limit=args.limit, presets_path=args.presets, cache_dir=args.cache_dir)
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} official release links to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
