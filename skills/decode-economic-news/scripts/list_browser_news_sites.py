#!/usr/bin/env python3
"""List corpus-backed news sites and build browser discovery queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, utc_now


REGISTRY_PATH = Path(__file__).resolve().parent.parent / "references" / "blogger-news-sites.json"
VALID_TIERS = ("core", "secondary", "occasional")


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "browser.news.sites/1" or not isinstance(payload.get("sites"), list):
        raise ValueError("invalid browser news-site registry")
    return payload


def select_sites(
    payload: dict[str, Any], *, tiers: set[str] | None = None, region: str | None = None, publisher: str | None = None
) -> list[dict[str, Any]]:
    selected = []
    needle = (publisher or "").casefold().strip()
    for site in payload["sites"]:
        if tiers and site.get("tier") not in tiers:
            continue
        if region and site.get("region") != region:
            continue
        names = [site.get("id", ""), site.get("publisher", ""), *(site.get("aliases") or [])]
        if needle and not any(needle in str(name).casefold() for name in names):
            continue
        selected.append(site)
    order = {tier: index for index, tier in enumerate(VALID_TIERS)}
    return sorted(selected, key=lambda item: (order.get(item.get("tier"), 99), -int(item.get("corpus_files", 0)), item["id"]))


def build_plan(sites: list[dict[str, Any]], topic: str) -> dict[str, Any]:
    clean_topic = " ".join(topic.split())
    if not clean_topic:
        raise ValueError("topic must not be empty")
    queries = []
    for site in sites:
        for domain in site.get("domains") or []:
            queries.append(
                {
                    "site_id": site["id"],
                    "publisher": site["publisher"],
                    "tier": site["tier"],
                    "query": f"site:{domain} {clean_topic}",
                    "homepage": site["homepage"],
                    "access_model": site["access_model"],
                    "result_policy": "Open the original result before capture; a search snippet remains a discovery lead.",
                }
            )
    return {
        "schema": "browser.news.search-plan/1",
        "created_at": utc_now(),
        "topic": clean_topic,
        "queries": queries,
        "warnings": [
            "Publisher inclusion is inferred from explicit citations in the local transcript corpus, not browsing history.",
            "Do not bypass login, subscription, CAPTCHA or other access controls.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", action="append", choices=VALID_TIERS)
    parser.add_argument("--region")
    parser.add_argument("--publisher", help="Match publisher id, display name or Chinese alias")
    parser.add_argument("--topic", help="Build site-scoped browser queries for this topic")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = load_registry()
    sites = select_sites(
        registry,
        tiers=set(args.tier) if args.tier else None,
        region=args.region,
        publisher=args.publisher,
    )
    result: dict[str, Any]
    if args.topic:
        result = build_plan(sites, args.topic)
    else:
        result = {
            "schema": registry["schema"],
            "corpus_basis": registry["corpus_basis"],
            "sites": sites,
        }
    if args.output:
        atomic_write_json(args.output, result)
        print(f"wrote {len(result.get('queries', result.get('sites', [])))} entries to {args.output}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
