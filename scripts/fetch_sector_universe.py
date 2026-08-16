#!/usr/bin/env python3
"""Discover Eastmoney sector members with a dated preset seed fallback."""

from __future__ import annotations

import argparse
import urllib.parse
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, atomic_write_json, load_json, provider, utc_now


DEFAULT_PRESETS = Path(__file__).resolve().parent.parent / "references" / "sector-presets.json"


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    diff = ((payload.get("data") or {}).get("diff")) or []
    return list(diff.values()) if isinstance(diff, dict) else list(diff)


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value not in (-0.0, 0.0) else None
    except (TypeError, ValueError):
        return None


def _eastmoney_json(client: CachedHttpClient, params: dict[str, Any], ttl_seconds: float) -> tuple[dict[str, Any], Any]:
    errors = []
    query = urllib.parse.urlencode(params)
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        url = f"https://{host}/api/qt/clist/get?{query}"
        try:
            return client.get_json(url, ttl_seconds=ttl_seconds, min_interval_seconds=2.0)
        except Exception as exc:
            errors.append(f"{host}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def discover_boards(
    keywords: list[str], client: CachedHttpClient, ttl_seconds: float, max_boards: int
) -> tuple[list[dict[str, Any]], list[Any], list[str]]:
    boards: list[dict[str, Any]] = []
    retrievals = []
    warnings = []
    for board_type, fs in (("concept", "m:90+t:3"), ("industry", "m:90+t:2")):
        try:
            for page in range(1, 7):
                params = {
                    "pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fs": fs, "fields": "f12,f14,f3,f104,f105,f128,f140",
                }
                payload, fetched = _eastmoney_json(client, params, ttl_seconds)
                retrievals.append(fetched)
                page_items = _items(payload)
                for item in page_items:
                    name = str(item.get("f14") or "")
                    if name and any(keyword.lower() in name.lower() for keyword in keywords):
                        boards.append({
                            "code": str(item.get("f12") or ""),
                            "name": name,
                            "type": board_type,
                            "change_pct": _number(item.get("f3")),
                            "advance_count": item.get("f104"),
                            "decline_count": item.get("f105"),
                            "leader": item.get("f140") or item.get("f128"),
                        })
                total = int(((payload.get("data") or {}).get("total")) or 0)
                if not page_items or page * 100 >= total:
                    break
        except Exception as exc:
            warnings.append(f"{board_type} board discovery failed: {type(exc).__name__}: {exc}")
    unique = {item["code"]: item for item in boards if item["code"]}
    if not unique:
        warnings.append(f"no board name matched keywords: {keywords}")
    return list(unique.values())[:max_boards], retrievals, warnings


def fetch_members(
    boards: list[dict[str, Any]], client: CachedHttpClient, ttl_seconds: float
) -> tuple[list[dict[str, Any]], list[Any], list[str]]:
    members: dict[str, dict[str, Any]] = {}
    retrievals = []
    warnings = []
    for board in boards:
        params = {
            "pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fs": f"b:{board['code']}",
            "fields": "f12,f14,f2,f3,f8,f9,f20,f23",
        }
        try:
            payload, fetched = _eastmoney_json(client, params, ttl_seconds)
            retrievals.append(fetched)
            for item in _items(payload):
                code = str(item.get("f12") or "")
                name = str(item.get("f14") or "")
                if len(code) != 6 or "退" in name or "ST" in name.upper():
                    continue
                current = members.setdefault(code, {
                    "code": code,
                    "name": name,
                    "boards": [],
                    "price": _number(item.get("f2")),
                    "change_pct": _number(item.get("f3")),
                    "turnover_pct": _number(item.get("f8")),
                    "pe_ttm": _number(item.get("f9")),
                    "market_cap": _number(item.get("f20")),
                    "pb": _number(item.get("f23")),
                })
                current["boards"].append(board["name"])
        except Exception as exc:
            warnings.append(f"board {board['code']} members failed: {type(exc).__name__}: {exc}")
    return list(members.values()), retrievals, warnings


def build_universe(
    preset_key: str | None,
    keywords: list[str],
    presets: dict[str, Any],
    client: CachedHttpClient,
    ttl_seconds: float,
    max_boards: int,
    max_members: int,
    seed_only: bool = False,
    benchmark_code: str | None = None,
    benchmark_name: str | None = None,
    market_benchmark_code: str | None = None,
) -> dict[str, Any]:
    preset = ((presets.get("presets") or {}).get(preset_key) or {}) if preset_key else {}
    search_terms = list(dict.fromkeys(keywords + list(preset.get("aliases") or [])))
    if not search_terms:
        raise ValueError("provide --preset or at least one --keyword")
    if seed_only:
        boards, retrievals, warnings, members = [], [], ["seed-only mode requested; dynamic discovery skipped"], []
    else:
        boards, retrievals, warnings = discover_boards(search_terms, client, ttl_seconds, max_boards)
        members, member_retrievals, member_warnings = fetch_members(boards, client, ttl_seconds)
        retrievals.extend(member_retrievals)
        warnings.extend(member_warnings)
    dynamic_count = len(members)
    discovery_status = "dynamic"
    if not members and preset.get("seed_universe"):
        members = [dict(item, boards=[preset.get("display_name")]) for item in preset["seed_universe"]]
        discovery_status = "seed_fallback"
        warnings.append(
            f"dynamic sector discovery unavailable; using dated seed universe as of {preset.get('seed_as_of')}"
        )
    elif not members:
        warnings.append("no sector members discovered and no seed universe is configured")
    members.sort(key=lambda item: (float(item.get("market_cap") or 0), item.get("code", "")), reverse=True)
    members = members[:max_members]
    benchmark = preset.get("benchmark")
    if benchmark_code:
        benchmark = {"code": benchmark_code, "name": benchmark_name or benchmark_code}
    market_benchmark = preset.get("market_benchmark") or {"code": "000300", "name": "沪深300"}
    if market_benchmark_code:
        market_benchmark = {"code": market_benchmark_code, "name": market_benchmark_code}
    if not benchmark:
        warnings.append("no tradable benchmark configured; pass --benchmark-code before forecasting")
    return {
        "schema": "sector.universe/1",
        "sector": {"preset": preset_key, "name": preset.get("display_name") or "/".join(keywords)},
        "search_terms": search_terms,
        "benchmark": benchmark,
        "market_benchmark": market_benchmark,
        "reference_index": preset.get("reference_index"),
        "discovery_status": discovery_status,
        "seed_as_of": preset.get("seed_as_of") if discovery_status == "seed_fallback" else None,
        "matched_boards": boards,
        "dynamic_member_count": dynamic_count,
        "members": members,
        "provider": provider("eastmoney-sector", "Eastmoney", 0.62, 0.60),
        "retrievals": [item.metadata() for item in retrievals],
        "as_of": utc_now(),
        "coverage": round(len(members) / max(1, max_members), 3),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--benchmark-code", help="tradable ETF/index proxy for a custom sector")
    parser.add_argument("--benchmark-name")
    parser.add_argument("--market-benchmark-code", default=None)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/decode-economic-news/sectors"))
    parser.add_argument("--ttl-hours", type=float, default=6)
    parser.add_argument("--max-boards", type=int, default=8)
    parser.add_argument("--max-members", type=int, default=80)
    parser.add_argument("--seed-only", action="store_true", help="skip portal discovery and use the dated preset seed")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    presets = load_json(args.presets)
    available = presets.get("presets") or {}
    if args.list_presets:
        for key, value in available.items():
            benchmark = (value.get("benchmark") or {}).get("code") or "-"
            print(f"{key}\t{value.get('display_name') or key}\t{benchmark}")
        return 0
    if args.preset and args.preset not in available:
        parser.error(f"unknown preset {args.preset!r}; use --list-presets or --keyword")
    if not args.output:
        parser.error("--output is required unless --list-presets is used")
    client = CachedHttpClient(args.cache_dir, timeout=20, retries=3, default_min_interval=2.0)
    result = build_universe(
        args.preset, args.keyword, presets, client,
        max(0, args.ttl_hours) * 3600, max(1, args.max_boards), max(1, args.max_members), args.seed_only,
        args.benchmark_code, args.benchmark_name, args.market_benchmark_code,
    )
    atomic_write_json(args.output, result)
    print(
        f"sector={result['sector']['name']} members={len(result['members'])} "
        f"status={result['discovery_status']} warnings={len(result['warnings'])}"
    )
    return 0 if result["members"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
