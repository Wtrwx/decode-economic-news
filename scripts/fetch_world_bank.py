#!/usr/bin/env python3
"""Fetch an official World Bank indicator with provenance and cache metadata."""

from __future__ import annotations

import argparse
import re
import urllib.parse
from pathlib import Path

from evidence_core import CachedHttpClient, atomic_write_json, normalized_identifier, provider, warnings_from_fetches


def _indicator_unit(metadata: dict, override: str) -> str:
    if override:
        return override
    explicit = str(metadata.get("unit") or "").strip()
    if explicit:
        return explicit
    name = str(metadata.get("name") or "")
    parenthetical = re.search(r"\(([^()]*)\)\s*$", name)
    hint = parenthetical.group(1) if parenthetical else ""
    if "%" in hint:
        return "%"
    return hint or "source-defined"


def fetch_indicator(
    country: str,
    indicator: str,
    start: int,
    end: int,
    *,
    unit_override: str = "",
    cache_dir: Path | None = None,
) -> dict:
    country = country.upper().strip()
    indicator = indicator.upper().strip()
    if not country.replace(";", "").isalnum():
        raise ValueError("country must contain ISO-like codes separated by semicolons")
    if not all(part.replace("_", "").isalnum() for part in indicator.split(".")):
        raise ValueError("invalid World Bank indicator code")
    if start > end:
        raise ValueError("start year must not exceed end year")

    client = CachedHttpClient(cache_dir)
    base = "https://api.worldbank.org/v2"
    data_url = (
        f"{base}/country/{urllib.parse.quote(country, safe=';')}/indicator/"
        f"{urllib.parse.quote(indicator)}?format=json&date={start}:{end}&per_page=20000"
    )
    meta_url = f"{base}/indicator/{urllib.parse.quote(indicator)}?format=json"
    payload, data_fetch = client.get_json(data_url, ttl_seconds=86400)
    metadata_payload, meta_fetch = client.get_json(meta_url, ttl_seconds=30 * 86400)
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise RuntimeError("World Bank response does not contain an observation list")
    metadata_rows = metadata_payload[1] if isinstance(metadata_payload, list) and len(metadata_payload) > 1 else []
    metadata = metadata_rows[0] if metadata_rows else {}
    name = str(metadata.get("name") or indicator)
    unit = _indicator_unit(metadata, unit_override)
    facts = []
    for row in sorted(payload[1], key=lambda item: str(item.get("date") or "")):
        value = row.get("value")
        if value is None:
            continue
        period = str(row.get("date") or "")
        economy = str((row.get("country") or {}).get("value") or country)
        facts.append(
            {
                "fact_id": f"WB-{normalized_identifier(indicator)}-{normalized_identifier(country)}-{period}",
                "claim": f"{economy} {name} in {period}: {value} {unit}",
                "value": value,
                "unit": unit,
                "period": period,
                "economy": economy,
                "indicator": indicator,
                "publisher": "World Bank",
                "source_url": data_fetch.source_url,
                "retrieved_at": data_fetch.retrieved_at,
                "source_note": metadata.get("sourceNote", ""),
                "source_organization": metadata.get("sourceOrganization", ""),
            }
        )
    if not facts:
        raise RuntimeError("World Bank returned no non-null observations")
    fetches = [data_fetch, meta_fetch]
    return {
        "schema": "evidence.source/1",
        "provider": provider("world-bank", "World Bank", 0.98, 0.97),
        "retrieval": data_fetch.metadata(),
        "supporting_retrievals": [item.metadata() for item in fetches[1:]],
        "series": {"country": country, "indicator": indicator, "name": name, "unit": unit},
        "facts": facts,
        "warnings": warnings_from_fetches(fetches),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True)
    parser.add_argument("--indicator", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--unit", default="")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch_indicator(args.country, args.indicator, args.start, args.end, unit_override=args.unit, cache_dir=args.cache_dir)
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} facts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
