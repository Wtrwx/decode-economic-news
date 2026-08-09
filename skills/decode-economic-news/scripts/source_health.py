#!/usr/bin/env python3
"""Probe configured data sources and produce a machine-readable health report."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from evidence_core import CachedHttpClient, atomic_write_json, load_json, safe_url, utc_now


DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "references" / "source-registry.json"


def _expand_env(value: str) -> str:
    for key, env_value in os.environ.items():
        value = value.replace("${" + key + "}", env_value)
    return value


def _expanded_headers(source: dict) -> dict[str, str]:
    headers = source.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("source headers must be an object")
    return {str(key): _expand_env(str(value)) for key, value in headers.items()}


def check_sources(registry: dict, cache_dir: Path | None = None) -> dict:
    results = []
    client = CachedHttpClient(cache_dir, timeout=15, retries=2)
    for source in registry.get("sources") or []:
        required_env = str(source.get("required_env") or "")
        if required_env and not os.environ.get(required_env):
            results.append({"id": source.get("id"), "status": "skipped", "reason": f"missing environment variable {required_env}"})
            continue
        url = _expand_env(str(source.get("health_url") or ""))
        started = time.monotonic()
        try:
            fetched = client.get(
                url,
                headers=_expanded_headers(source),
                ttl_seconds=0,
                min_interval_seconds=float(source.get("min_interval_seconds") or 0.2),
                allow_stale=False,
            )
            if source.get("expect") == "json":
                json.loads(fetched.body.decode("utf-8-sig"))
            results.append(
                {
                    "id": source.get("id"),
                    "publisher": source.get("publisher"),
                    "status": "healthy",
                    "latency_ms": round(1000 * (time.monotonic() - started), 1),
                    "http_status": fetched.http_status,
                    "bytes": len(fetched.body),
                    "raw_sha256": fetched.raw_sha256,
                    "url": safe_url(url),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": source.get("id"),
                    "publisher": source.get("publisher"),
                    "status": "failed",
                    "latency_ms": round(1000 * (time.monotonic() - started), 1),
                    "url": safe_url(url),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "schema": "source.health/1",
        "checked_at": utc_now(),
        "summary": {
            "healthy": sum(item["status"] == "healthy" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
            "skipped": sum(item["status"] == "skipped" for item in results),
        },
        "sources": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check_sources(load_json(args.registry), args.cache_dir)
    atomic_write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
