#!/usr/bin/env python3
"""Collect a reproducible A-share market breadth and limit-up snapshot.

The public market endpoints are auxiliary rather than official documented APIs.
Every response is cached and any failed component is reported explicitly.
"""

from __future__ import annotations

import argparse
import urllib.parse
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, FetchResult, atomic_write_json, provider, utc_now


ZT_UT = "7eea3edcaed734bea9cbfc24409ed989"


def _url(base: str, params: dict[str, Any]) -> str:
    return f"{base}?{urllib.parse.urlencode(params)}"


def _items(value: Any) -> list[dict]:
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _fetch_json_safe(
    client: CachedHttpClient,
    url: str,
    *,
    ttl: float,
    interval: float = 2.0,
) -> tuple[dict, FetchResult | None, str]:
    try:
        payload, fetched = client.get_json(
            url,
            ttl_seconds=ttl,
            min_interval_seconds=interval,
            headers={"Referer": "https://quote.eastmoney.com/"},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("top-level JSON is not an object")
        return payload, fetched, ""
    except Exception as exc:
        return {}, None, f"{type(exc).__name__}: {exc}"


def collect_snapshot(date: str, *, cache_dir: Path | None = None) -> dict:
    if len(date) != 8 or not date.isdigit():
        raise ValueError("date must be YYYYMMDD")
    client = CachedHttpClient(cache_dir, timeout=20, retries=3, default_min_interval=2.0)
    ttl = 300 if date == datetime.now().strftime("%Y%m%d") else 7 * 86400
    retrievals: list[dict] = []
    warnings: list[str] = []

    breadth_url = _url(
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        {
            "fltt": 2,
            "invt": 2,
            "fields": "f12,f14,f104,f105,f106",
            "secids": "1.000001,0.399001",
        },
    )
    breadth_payload, breadth_fetch, error = _fetch_json_safe(client, breadth_url, ttl=ttl)
    if error:
        warnings.append(f"breadth unavailable: {error}")
    if breadth_fetch:
        retrievals.append(breadth_fetch.metadata())
        if breadth_fetch.warning:
            warnings.append(breadth_fetch.warning)
    breadth_rows = _items((breadth_payload.get("data") or {}).get("diff"))
    advance_count = 0
    decline_count = 0
    flat_count = 0
    market_components: list[dict] = []
    for row in breadth_rows:
        try:
            advances = int(row.get("f104") or 0)
            declines = int(row.get("f105") or 0)
            flats = int(row.get("f106") or 0)
        except (TypeError, ValueError):
            continue
        advance_count += advances
        decline_count += declines
        flat_count += flats
        market_components.append(
            {
                "code": str(row.get("f12") or ""),
                "name": str(row.get("f14") or ""),
                "advance_count": advances,
                "decline_count": declines,
                "flat_count": flats,
            }
        )
    if market_components and len(market_components) != 2:
        warnings.append(f"expected 2 Shanghai/Shenzhen breadth components, got {len(market_components)}")

    pool_specs = {
        "limit_up": ("getTopicZTPool", "fbt:asc"),
        "broken_limit": ("getTopicZBPool", "fbt:asc"),
        "limit_down": ("getTopicDTPool", "fund:asc"),
        "yesterday_limit": ("getYesterdayZTPool", "zs:desc"),
    }
    pools: dict[str, list[dict]] = {}
    for name, (endpoint, sort) in pool_specs.items():
        pool_url = _url(
            f"https://push2ex.eastmoney.com/{endpoint}",
            {"ut": ZT_UT, "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 10000, "sort": sort, "date": date},
        )
        payload, fetched, error = _fetch_json_safe(client, pool_url, ttl=ttl)
        if error:
            warnings.append(f"{name} pool unavailable: {error}")
            pools[name] = []
        else:
            pools[name] = _items((payload.get("data") or {}).get("pool"))
        if fetched:
            retrievals.append(fetched.metadata())
            if fetched.warning:
                warnings.append(fetched.warning)

    limit_up = pools["limit_up"]
    heights = []
    ladder: Counter[int] = Counter()
    for row in limit_up:
        try:
            height = int(row.get("lbc") or 0)
        except (TypeError, ValueError):
            height = 0
        heights.append(height)
        if height > 0:
            ladder[height] += 1
    yesterday_returns = []
    for row in pools["yesterday_limit"]:
        try:
            yesterday_returns.append(float(row.get("zdp")))
        except (TypeError, ValueError):
            continue

    index_url = "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006"
    indices: list[dict] = []
    try:
        index_fetch = client.get(index_url, ttl_seconds=60 if ttl == 300 else ttl, min_interval_seconds=0.2)
        retrievals.append(index_fetch.metadata())
        text = index_fetch.body.decode("gbk", errors="replace")
        for line in text.split(";"):
            if '="' not in line:
                continue
            values = line.split('"', 2)[1].split("~")
            if len(values) <= 32:
                continue
            try:
                change_pct = float(values[32])
            except (TypeError, ValueError):
                continue
            indices.append({"name": values[1], "code": values[2], "change_pct": change_pct})
        if not indices:
            warnings.append("Tencent index response contained no parsable indices")
        if index_fetch.warning:
            warnings.append(index_fetch.warning)
    except Exception as exc:
        warnings.append(f"index momentum unavailable: {type(exc).__name__}: {exc}")

    zt_count = len(limit_up)
    broken_count = len(pools["broken_limit"])
    continuation_count = sum(value >= 9.8 for value in yesterday_returns)
    return {
        "schema": "market.snapshot/1",
        "market": "CN-A-SH-SZ",
        "date": date,
        "as_of": utc_now(),
        "providers": [
            provider("eastmoney-market", "Eastmoney", 0.62, 0.62),
            provider("tencent-market", "Tencent Finance", 0.65, 0.78),
        ],
        "breadth": {
            "advance_count": advance_count if market_components else None,
            "decline_count": decline_count if market_components else None,
            "flat_count": flat_count if market_components else None,
            "observed_count": advance_count + decline_count + flat_count if market_components else 0,
            "market_components": market_components,
            "method": "sum of Eastmoney Shanghai Composite and Shenzhen Component f104/f105/f106 market counts",
        },
        "limit_ecology": {
            "limit_up_count": zt_count if limit_up or not any("limit_up pool unavailable" in w for w in warnings) else None,
            "broken_limit_count": broken_count if pools["broken_limit"] or not any("broken_limit pool unavailable" in w for w in warnings) else None,
            "limit_down_count": len(pools["limit_down"]) if pools["limit_down"] or not any("limit_down pool unavailable" in w for w in warnings) else None,
            "break_rate_pct": round(100 * broken_count / (zt_count + broken_count), 3) if zt_count + broken_count else None,
            "max_limit_height": max(heights, default=None),
            "ladder": {str(key): value for key, value in sorted(ladder.items())},
            "yesterday_limit_count": len(yesterday_returns) if yesterday_returns else None,
            "continuation_count": continuation_count if yesterday_returns else None,
            "continuation_rate_pct": round(100 * continuation_count / len(yesterday_returns), 3) if yesterday_returns else None,
            "yesterday_pool_mean_return_pct": round(sum(yesterday_returns) / len(yesterday_returns), 3) if yesterday_returns else None,
        },
        "indices": indices,
        "retrievals": retrievals,
        "warnings": warnings,
        "notes": [
            "Public market endpoints are auxiliary and undocumented; retain cached raw responses.",
            "Breadth covers Shanghai and Shenzhen markets through index-level f104/f105/f106 counts; Beijing Stock Exchange is not included.",
            "Breadth and index quotes are latest available; the requested date is honored by the limit-up pools.",
            "The 9.8% continuation threshold is a broad-market approximation and does not encode every board/ST limit rule.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect_snapshot(args.date, cache_dir=args.cache_dir)
    atomic_write_json(args.output, result)
    print(f"wrote A-share snapshot to {args.output}; warnings={len(result['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
