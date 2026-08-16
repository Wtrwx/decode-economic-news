#!/usr/bin/env python3
"""Fetch cached U.S. and Korean peer histories for an A-share sector."""

from __future__ import annotations

import argparse
import os
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from evidence_core import CachedHttpClient, atomic_write_json, load_json, provider, safe_proxy_url, utc_now


DEFAULT_PRESETS = Path(__file__).resolve().parent.parent / "references" / "cross-market-presets.json"
VALID_MARKETS = ("us", "kr")


def normalize_proxy_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme.lower() not in ("http", "https", "socks5", "socks5h") or not parsed.hostname:
        raise ValueError("CROSS_MARKET_PROXY_URL must use http, https, socks5 or socks5h")
    scheme = "socks5h" if parsed.scheme.lower() == "socks5" else parsed.scheme.lower()
    return urllib.parse.urlunsplit((scheme, parsed.netloc, parsed.path or "/", "", ""))


def _range_for_days(days: int) -> str:
    if days <= 120:
        return "6mo"
    if days <= 260:
        return "1y"
    if days <= 520:
        return "2y"
    return "5y"


def parse_chart(payload: dict[str, Any], requested_symbol: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"Yahoo chart error for {requested_symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo chart returned no result for {requested_symbol}")
    result = results[0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    adjusted = ((indicators.get("adjclose") or [{}])[0].get("adjclose") or [])
    timezone_name = str(meta.get("exchangeTimezoneName") or "UTC")
    try:
        exchange_tz = ZoneInfo(timezone_name)
    except Exception:
        exchange_tz = timezone.utc
    bars = []
    for index, stamp in enumerate(timestamps):
        def number(values: list[Any]) -> float | None:
            try:
                value = values[index]
                return float(value) if value is not None else None
            except (IndexError, TypeError, ValueError):
                return None

        raw_close = number(quote.get("close") or [])
        close = number(adjusted) or raw_close
        if close is None or close <= 0:
            continue
        date = datetime.fromtimestamp(int(stamp), timezone.utc).astimezone(exchange_tz).date().isoformat()
        bars.append(
            {
                "date": date,
                "open": number(quote.get("open") or []),
                "close": close,
                "high": number(quote.get("high") or []),
                "low": number(quote.get("low") or []),
                "volume": number(quote.get("volume") or []),
                "raw_close": raw_close,
            }
        )
    bars = sorted({item["date"]: item for item in bars}.values(), key=lambda item: item["date"])
    return meta, bars


def fetch_one(
    asset: dict[str, Any], market: str, days: int, client: CachedHttpClient, ttl_seconds: float, proxy_url: str | None
) -> dict[str, Any]:
    symbol = str(asset["symbol"])
    query = urllib.parse.urlencode(
        {"range": _range_for_days(days), "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"}
    )
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='.') }?{query}"
    payload, fetched = client.get_json(
        url,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 decode-economic-news/1.0"},
        ttl_seconds=ttl_seconds,
        min_interval_seconds=0.7,
        proxy_url=proxy_url,
    )
    meta, bars = parse_chart(payload, symbol)
    if len(bars) < 20:
        raise RuntimeError(f"insufficient price history for {symbol}: {len(bars)} bars")
    return {
        "code": symbol,
        "symbol": symbol,
        "name": asset.get("name") or meta.get("longName") or meta.get("shortName") or symbol,
        "market": market,
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "timezone": meta.get("exchangeTimezoneName"),
        "role": asset.get("role"),
        "mapping_strength": asset.get("mapping_strength"),
        "adjustment": "vendor_adjusted_close",
        "retrieval": fetched.metadata(),
        "bars": bars[-max(20, days):],
    }


def planned_assets(config: dict[str, Any], preset: str, markets: list[str]) -> list[tuple[str, dict[str, Any]]]:
    preset_config = ((config.get("presets") or {}).get(preset) or {})
    if not preset_config:
        raise ValueError(f"unknown cross-market preset: {preset}")
    assets: list[tuple[str, dict[str, Any]]] = []
    benchmarks = config.get("market_benchmarks") or {}
    for market in markets:
        benchmark = dict(benchmarks.get(market) or {})
        if benchmark:
            benchmark.update({"role": "market_benchmark", "mapping_strength": 1.0})
            assets.append((market, benchmark))
        assets.extend((market, dict(item)) for item in preset_config.get(market) or [])
    seen: set[str] = set()
    return [(market, asset) for market, asset in assets if not (asset["symbol"] in seen or seen.add(asset["symbol"]))]


def build_history(
    config: dict[str, Any], preset: str, markets: list[str], days: int, client: CachedHttpClient,
    ttl_seconds: float, proxy_url: str | None = None
) -> dict[str, Any]:
    assets = planned_assets(config, preset, markets)
    series = []
    warnings = []
    for market, asset in assets:
        try:
            series.append(fetch_one(asset, market, days, client, ttl_seconds, proxy_url))
        except Exception as exc:
            warnings.append(f"{asset['symbol']} unavailable: {type(exc).__name__}: {exc}")
    preset_config = (config.get("presets") or {})[preset]
    if proxy_url:
        warnings.append(f"cross-market transport used runtime proxy {safe_proxy_url(proxy_url)}; routing does not change source authority")
    warnings.extend(
        [
            "Yahoo Finance chart is an undocumented public-market auxiliary endpoint; corroborate material prices with an exchange or licensed source.",
            "Daily Korean closes are not same-morning leading data for A-shares; lead tests use only prior foreign closes.",
        ]
    )
    requested = len(assets)
    return {
        "schema": "market.history/1",
        "provider": provider("yahoo-finance-chart", "Yahoo Finance", 0.62, 0.55),
        "market": "CROSS-US-KR",
        "as_of": max((item["bars"][-1]["date"] for item in series), default=None),
        "requested_count": requested,
        "series_count": len(series),
        "coverage": round(len(series) / requested, 3) if requested else 0.0,
        "series": series,
        "created_at": utc_now(),
        "universe_context": {
            "preset": preset,
            "markets": markets,
            "market_benchmarks": config.get("market_benchmarks"),
            "transmission_variables": preset_config.get("transmission_variables"),
            "event_leaders": preset_config.get("event_leaders"),
            "caveat": preset_config.get("caveat"),
            "mapping_as_of": config.get("as_of"),
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", required=False)
    parser.add_argument("--presets", type=Path, default=DEFAULT_PRESETS)
    parser.add_argument("--market", action="append", choices=VALID_MARKETS)
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--ttl-hours", type=float, default=6)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/decode-economic-news/cross-market"))
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_json(args.presets)
    if args.list_presets:
        for key, item in (config.get("presets") or {}).items():
            print(f"{key}\tUS={len(item.get('us') or [])}\tKR={len(item.get('kr') or [])}")
        return 0
    if not args.preset or not args.output:
        parser.error("--preset and --output are required unless --list-presets is used")
    markets = list(dict.fromkeys(args.market or VALID_MARKETS))
    proxy_raw = os.environ.get("CROSS_MARKET_PROXY_URL", "").strip()
    proxy_url = normalize_proxy_url(proxy_raw) if proxy_raw else None
    client = CachedHttpClient(args.cache_dir, timeout=20, retries=3, default_min_interval=0.7)
    result = build_history(
        config, args.preset, markets, max(80, args.days), client, max(0, args.ttl_hours) * 3600, proxy_url
    )
    atomic_write_json(args.output, result)
    print(f"wrote {result['series_count']}/{result['requested_count']} cross-market histories; coverage={result['coverage']:.0%}")
    return 0 if result["series_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
