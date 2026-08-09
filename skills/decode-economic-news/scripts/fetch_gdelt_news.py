#!/usr/bin/env python3
"""Discover global news links through GDELT DOC 2.0 with provenance."""

from __future__ import annotations

import argparse
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, atomic_write_json, normalized_identifier, provider, sha256_bytes


BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def normalize_proxy_url(proxy_url: str) -> str:
    """Resolve GDELT hostnames through SOCKS to avoid proxy route mismatches."""
    value = proxy_url.strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() == "socks5":
        return urllib.parse.urlunsplit(("socks5h", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return value


def _seen_date(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    match = re.match(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return fallback[:10]


def normalize_articles(payload: Any, retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("GDELT response does not contain an article list")
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        domain = str(row.get("domain") or urllib.parse.urlsplit(url).netloc)
        period = _seen_date(row.get("seendate"), str(retrieval["retrieved_at"]))
        facts.append(
            {
                "fact_id": f"GDELT-{period}-{normalized_identifier(domain)}-{sha256_bytes(url.encode('utf-8'))[:12]}",
                "claim": f"GDELT indexed an article titled: {title}",
                "period": period,
                "publisher": domain or "Original publisher indexed by GDELT",
                "source_url": url,
                "retrieved_at": retrieval["retrieved_at"],
                "evidence_role": "discovery_lead",
                "title": title,
                "domain": domain,
                "language": row.get("language"),
                "source_country": row.get("sourcecountry"),
                "seen_at": row.get("seendate"),
                "social_image": row.get("socialimage"),
                "gdelt_query_url": retrieval["source_url"],
            }
        )
    return facts


def fetch_news(
    query: str,
    *,
    max_records: int = 50,
    timespan: str = "7d",
    start_datetime: str = "",
    end_datetime: str = "",
    cache_dir: Path | None = None,
    proxy_url: str = "",
) -> dict[str, Any]:
    query = query.strip()
    proxy_url = normalize_proxy_url(proxy_url)
    if not query:
        raise ValueError("query is required")
    if not 1 <= max_records <= 250:
        raise ValueError("max_records must be between 1 and 250")
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max_records),
        "sort": "datedesc",
    }
    if start_datetime or end_datetime:
        if not (start_datetime and end_datetime):
            raise ValueError("start_datetime and end_datetime must be supplied together")
        params["startdatetime"] = start_datetime
        params["enddatetime"] = end_datetime
    else:
        params["timespan"] = timespan
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    client = CachedHttpClient(cache_dir, timeout=40, retries=2)
    payload, fetched = client.get_json(
        url,
        ttl_seconds=900,
        min_interval_seconds=5.2,
        proxy_url=proxy_url or None,
    )
    facts = normalize_articles(payload, fetched.metadata())
    if not facts:
        raise RuntimeError("GDELT returned no usable article links")
    warnings = [
        "GDELT is a discovery index, not the publisher of the underlying claims; open and verify the original URL before citing content.",
        "Article availability, translation and indexing coverage vary by publisher and country.",
    ]
    if fetched.warning:
        warnings.append(fetched.warning)
    return {
        "schema": "evidence.source/1",
        "provider": provider("gdelt-doc", "GDELT Project", 0.70, 0.55),
        "retrieval": fetched.metadata(),
        "query": params,
        "network": {
            "proxy_used": bool(proxy_url),
            "proxy_scheme": urllib.parse.urlsplit(proxy_url).scheme if proxy_url else None,
        },
        "facts": facts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-records", type=int, default=50)
    parser.add_argument("--timespan", default="7d")
    parser.add_argument("--start-datetime", default="", help="GDELT YYYYMMDDhhmmss")
    parser.add_argument("--end-datetime", default="", help="GDELT YYYYMMDDhhmmss")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch_news(
        args.query,
        max_records=args.max_records,
        timespan=args.timespan,
        start_datetime=args.start_datetime,
        end_datetime=args.end_datetime,
        cache_dir=args.cache_dir,
        proxy_url=os.environ.get("GDELT_PROXY_URL", ""),
    )
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} discovery leads to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
