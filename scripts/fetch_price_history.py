#!/usr/bin/env python3
"""Fetch cached Tencent forward-adjusted daily price histories."""

from __future__ import annotations

import argparse
import json
import urllib.parse
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, atomic_write_json, load_json, provider, utc_now


def market_prefix(code: str) -> str:
    raw = code.strip().upper()
    if raw.startswith(("SH", "SZ", "BJ")):
        return raw[:2].lower()
    code = raw[-6:]
    if code in {"000016", "000300", "000688", "000852", "000905"}:
        return "sh"
    if code.startswith(("5", "6", "9")):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


def normalize_code(code: str) -> str:
    digits = "".join(character for character in str(code) if character.isdigit())
    if len(digits) < 6:
        raise ValueError(f"invalid security code: {code}")
    return digits[-6:]


def parse_tencent_payload(payload: dict[str, Any], prefixed: str, adjustment: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    node = (payload.get("data") or {}).get(prefixed) or {}
    key = "qfqday" if adjustment == "qfq" else "day"
    raw_bars = node.get(key) or node.get("day") or []
    bars = []
    for raw in raw_bars:
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        try:
            bars.append({
                "date": str(raw[0])[:10],
                "open": float(raw[1]),
                "close": float(raw[2]),
                "high": float(raw[3]),
                "low": float(raw[4]),
                "volume": float(raw[5]),
            })
        except (TypeError, ValueError):
            continue
    qt = node.get("qt") or {}
    quote_values = qt.get(prefixed) or []
    name = str(quote_values[1]) if len(quote_values) > 1 else ""

    def qfloat(index: int) -> float | None:
        try:
            value = float(quote_values[index])
            return value if value != 0 else None
        except (IndexError, TypeError, ValueError):
            return None

    quote = {
        "price": qfloat(3),
        "change_pct": qfloat(32),
        "turnover_pct": qfloat(38),
        "pe_ttm": qfloat(39),
        "market_cap_yi": qfloat(44),
        "pb": qfloat(46),
    }
    return name, quote, sorted(bars, key=lambda item: item["date"])


def fetch_one(code: str, days: int, adjustment: str, client: CachedHttpClient, ttl_seconds: float) -> dict[str, Any]:
    raw_code = code
    code = normalize_code(code)
    prefixed = market_prefix(raw_code) + code
    param = f"{prefixed},day,,,{days},{adjustment}"
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urllib.parse.urlencode({"param": param})
    payload, fetched = client.get_json(url, ttl_seconds=ttl_seconds, min_interval_seconds=0.25)
    if payload.get("code") not in (0, "0"):
        raise RuntimeError(f"Tencent API error for {code}: {payload.get('msg')}")
    name, quote, bars = parse_tencent_payload(payload, prefixed, adjustment)
    if len(bars) < 20:
        raise RuntimeError(f"insufficient price history for {code}: {len(bars)} bars")
    return {
        "code": code,
        "name": name,
        "market_id": prefixed,
        "adjustment": adjustment,
        "quote": quote,
        "retrieval": fetched.metadata(),
        "bars": bars,
    }


def codes_from_universe(document: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in ("members", "stocks", "candidates", "securities"):
        for item in document.get(key) or []:
            raw = item.get("code") if isinstance(item, dict) else item
            if raw:
                try:
                    codes.append(normalize_code(str(raw)))
                except ValueError:
                    pass
    for key in ("benchmark", "market_benchmark"):
        item = document.get(key) or {}
        if isinstance(item, dict) and item.get("code"):
            codes.append(normalize_code(str(item["code"])))
    return list(dict.fromkeys(codes))


def build_history(
    codes: list[str], days: int, adjustment: str, client: CachedHttpClient, ttl_seconds: float
) -> dict[str, Any]:
    series = []
    warnings = []
    for code in dict.fromkeys(codes):
        try:
            series.append(fetch_one(code, days, adjustment, client, ttl_seconds))
        except Exception as exc:
            warnings.append(f"{code} unavailable: {type(exc).__name__}: {exc}")
    requested = len(list(dict.fromkeys(codes)))
    return {
        "schema": "market.history/1",
        "provider": provider("tencent-kline", "Tencent Finance", 0.65, 0.80),
        "as_of": max((item["bars"][-1]["date"] for item in series), default=None),
        "requested_count": requested,
        "series_count": len(series),
        "coverage": round(len(series) / requested, 3) if requested else 0.0,
        "series": series,
        "created_at": utc_now(),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", action="append", default=[])
    parser.add_argument("--universe", type=Path)
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--adjustment", choices=("qfq", "none"), default="qfq")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/decode-economic-news/prices"))
    parser.add_argument("--ttl-hours", type=float, default=6)
    parser.add_argument("--max-codes", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    codes = [normalize_code(code) for code in args.code]
    universe_document = None
    if args.universe:
        universe_document = load_json(args.universe)
        codes.extend(codes_from_universe(universe_document))
    codes = list(dict.fromkeys(codes))[: max(1, args.max_codes)]
    if not codes:
        parser.error("provide --code or --universe")
    client = CachedHttpClient(args.cache_dir, timeout=20, retries=3, default_min_interval=0.25)
    result = build_history(codes, max(80, args.days), args.adjustment, client, max(0, args.ttl_hours) * 3600)
    if universe_document:
        result["universe_context"] = {
            "sector": universe_document.get("sector"),
            "benchmark": universe_document.get("benchmark"),
            "market_benchmark": universe_document.get("market_benchmark"),
            "discovery_status": universe_document.get("discovery_status"),
            "seed_as_of": universe_document.get("seed_as_of"),
        }
    atomic_write_json(args.output, result)
    print(f"wrote {result['series_count']}/{result['requested_count']} histories; coverage={result['coverage']:.0%}")
    return 0 if result["series_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
