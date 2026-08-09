#!/usr/bin/env python3
"""Fetch a FRED series with observation dates, vintages and provenance."""

from __future__ import annotations

import argparse
import os
import urllib.parse
from pathlib import Path

from evidence_core import CachedHttpClient, atomic_write_json, normalized_identifier, provider, warnings_from_fetches


def fetch_series(
    series_id: str,
    start: str,
    end: str,
    *,
    api_key: str,
    cache_dir: Path | None = None,
) -> dict:
    if not api_key:
        raise RuntimeError("FRED_API_KEY is required")
    series_id = series_id.upper().strip()
    if not series_id.replace("_", "").isalnum():
        raise ValueError("invalid FRED series ID")
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    if end:
        params["observation_end"] = end
    base = "https://api.stlouisfed.org/fred"
    observations_url = f"{base}/series/observations?{urllib.parse.urlencode(params)}"
    metadata_url = f"{base}/series?{urllib.parse.urlencode({'series_id': series_id, 'api_key': api_key, 'file_type': 'json'})}"
    client = CachedHttpClient(cache_dir)
    observations_payload, observations_fetch = client.get_json(observations_url, ttl_seconds=3600)
    metadata_payload, metadata_fetch = client.get_json(metadata_url, ttl_seconds=7 * 86400)
    observations = observations_payload.get("observations") if isinstance(observations_payload, dict) else None
    series_rows = metadata_payload.get("seriess") if isinstance(metadata_payload, dict) else None
    if not isinstance(observations, list):
        raise RuntimeError("FRED response does not contain observations")
    metadata = series_rows[0] if isinstance(series_rows, list) and series_rows else {}
    title = str(metadata.get("title") or series_id)
    units = str(metadata.get("units") or "source-defined")
    facts = []
    for row in observations:
        raw_value = row.get("value")
        if raw_value in (None, ".", ""):
            continue
        try:
            value: float | str = float(raw_value)
        except (TypeError, ValueError):
            value = str(raw_value)
        period = str(row.get("date") or "")
        facts.append(
            {
                "fact_id": f"FRED-{normalized_identifier(series_id)}-{period}",
                "claim": f"{title} on {period}: {value} {units}",
                "value": value,
                "unit": units,
                "period": period,
                "indicator": series_id,
                "publisher": "Federal Reserve Bank of St. Louis",
                "source_url": observations_fetch.source_url,
                "retrieved_at": observations_fetch.retrieved_at,
                "vintage": {
                    "realtime_start": row.get("realtime_start"),
                    "realtime_end": row.get("realtime_end"),
                },
            }
        )
    if not facts:
        raise RuntimeError("FRED returned no non-missing observations")
    fetches = [observations_fetch, metadata_fetch]
    return {
        "schema": "evidence.source/1",
        "provider": provider("fred", "Federal Reserve Bank of St. Louis", 0.98, 0.98),
        "retrieval": observations_fetch.metadata(),
        "supporting_retrievals": [metadata_fetch.metadata()],
        "series": {"series_id": series_id, "title": title, "units": units, "frequency": metadata.get("frequency")},
        "facts": facts,
        "warnings": warnings_from_fetches(fetches),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default="")
    parser.add_argument("--api-key", default=os.environ.get("FRED_API_KEY", ""))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch_series(args.series_id, args.start, args.end, api_key=args.api_key, cache_dir=args.cache_dir)
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} facts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
