#!/usr/bin/env python3
"""Collect publisher-attributed news through the NewsNook public API."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from evidence_core import (
    CachedHttpClient,
    atomic_write_json,
    load_json,
    normalized_identifier,
    provider,
    sha256_bytes,
    utc_now,
)


DEFAULT_SOURCES = Path(__file__).resolve().parent.parent / "references" / "newsnook-api-sources.json"
TRACKING_KEYS = {"at_campaign", "at_medium", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "spm"}
QUERY_SPLIT = re.compile(r"[\s,，;；|/]+")


def validate_api_base(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip().rstrip("/"))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("NewsNook API base must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("NewsNook API base must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("NewsNook API base must not contain a query or fragment")
    host = parsed.hostname.lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/"), "", ""))


def feed_endpoint(api_base: str, source_id: str, page: int = 0) -> str:
    endpoint = f"{validate_api_base(api_base)}/api/feed/{urllib.parse.quote(source_id, safe='')}"
    return endpoint if page <= 0 else f"{endpoint}?page={page}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _clean_text(value: Any, limit: int = 4000) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _canonical_url(value: Any) -> str:
    raw = html.unescape(str(value or "")).strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    host = parsed.hostname.lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    scheme = parsed.scheme.lower()
    if scheme == "http" and any(
        parsed.hostname.lower().endswith(suffix)
        for suffix in ("eastmoney.com", "wallstreetcn.com", "163.com", "netease.com")
    ):
        scheme = "https"
    query = []
    for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        query.append((key, item))
    return urllib.parse.urlunsplit(
        (scheme, host, re.sub(r"/{2,}", "/", parsed.path or "/"), urllib.parse.urlencode(query), "")
    )


def _timezone(name: str) -> timezone | ZoneInfo:
    if name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _published_at(raw: Any, timezone_name: str, retrieved_at: str) -> tuple[str, str]:
    fallback = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    parsed: datetime | None = None
    if isinstance(raw, (int, float)) and raw > 0:
        timestamp = float(raw) / 1000 if float(raw) > 10_000_000_000 else float(raw)
        parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    text = str(raw or "").strip()
    if parsed is None and text.isdigit() and len(text) >= 10:
        timestamp = float(text) / 1000 if len(text) >= 13 else float(text)
        parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if parsed is None and text:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            parsed = None
    if parsed is None and text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None and text:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y%m%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        parsed = fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone(timezone_name))
    return parsed.isoformat(timespec="seconds"), parsed.date().isoformat()


def _child_text(node: ET.Element, names: set[str]) -> str:
    for child in node:
        if _local_name(child.tag) in names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _entry_link(node: ET.Element) -> str:
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


def _parse_json_feed(data: dict[str, Any], source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    articles = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), 500)
        url = _canonical_url(item.get("url") or item.get("external_url") or item.get("id"))
        if not title or not url:
            continue
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": _clean_text(item.get("content_text") or item.get("summary") or item.get("content_html")),
                "published_at_raw": item.get("date_published") or item.get("date_modified"),
                "publisher": source["publisher"],
            }
        )
        if len(articles) >= limit:
            break
    return articles


def parse_feed_payload(payload: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    stripped = payload.lstrip()
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return _parse_json_feed(data, source, limit)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid RSS/Atom/JSON Feed payload: {exc}") from exc
    entries = [node for node in root.iter() if _local_name(node.tag) in ("item", "entry")]
    articles = []
    for node in entries:
        title = _clean_text(_child_text(node, {"title"}), 500)
        url = _canonical_url(_entry_link(node))
        if not title or not url:
            continue
        publisher = _clean_text(_child_text(node, {"source"}), 200) or source["publisher"]
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": _clean_text(_child_text(node, {"description", "summary", "content", "encoded"})),
                "published_at_raw": _child_text(node, {"pubdate", "published", "updated", "date"}),
                "publisher": publisher,
            }
        )
        if len(articles) >= limit:
            break
    return articles


def parse_eastmoney_kx(payload: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    match = re.search(r"var\s+ajaxResult\s*=\s*(\{[\s\S]*\})\s*;?\s*$", payload)
    if not match:
        raise RuntimeError("Eastmoney KX payload is not expected JSONP")
    data = json.loads(match.group(1))
    articles = []
    for item in data.get("LivesList") or []:
        if not isinstance(item, dict):
            continue
        news_id = str(item.get("newsid") or item.get("id") or "").strip()
        title = _clean_text(item.get("title"), 500)
        url = _canonical_url(item.get("url_unique") or item.get("url_w") or item.get("url_m"))
        if not url and news_id:
            url = f"https://finance.eastmoney.com/a/{news_id}.html"
        if not title or not url:
            continue
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": _clean_text(item.get("digest") or item.get("simdigest") or title),
                "published_at_raw": item.get("showtime") or item.get("ordertime"),
                "publisher": source["publisher"],
            }
        )
        if len(articles) >= limit:
            break
    return articles


def parse_eastmoney_news(payload: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = json.loads(payload)
    if str(data.get("code")) != "1":
        raise RuntimeError(f"Eastmoney news returned code={data.get('code')!r}")
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    articles = []
    for item in body.get("list") or []:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), 500)
        url = _canonical_url(item.get("url") or item.get("articleUrl") or item.get("code_url"))
        if not title or not url:
            continue
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": _clean_text(item.get("summary") or item.get("digest")),
                "published_at_raw": item.get("showTime") or item.get("publishTime") or item.get("showtime"),
                "publisher": source["publisher"],
            }
        )
        if len(articles) >= limit:
            break
    return articles


def parse_wscn_live(payload: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = json.loads(payload)
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    articles = []
    for item in body.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        summary = _clean_text(item.get("content_text") or item.get("content"))
        title = _clean_text(item.get("title"), 500)
        if not title:
            bracket = re.match(r"^【([^】]+)】", summary)
            title = (bracket.group(1) if bracket else summary[:120]).strip()
        url = _canonical_url(item.get("uri")) or (f"https://wallstreetcn.com/livenews/{item_id}" if item_id else "")
        if not title or not url:
            continue
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "published_at_raw": item.get("display_time") or item.get("created_at"),
                "publisher": source["publisher"],
            }
        )
        if len(articles) >= limit:
            break
    return articles


def parse_cls(payload: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = json.loads(payload)
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    articles = []
    for item in body.get("roll_data") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        summary = _clean_text(item.get("content") or item.get("brief"))
        title = _clean_text(item.get("brief"), 500)
        if not title:
            bracket = re.match(r"^【([^】]+)】", summary)
            title = (bracket.group(1) if bracket else summary[:120]).strip()
        if not item_id or not title:
            continue
        articles.append(
            {
                "title": title,
                "url": f"https://www.cls.cn/telegraph/{item_id}",
                "summary": summary,
                "published_at_raw": item.get("ctime"),
                "publisher": source["publisher"],
            }
        )
        if len(articles) >= limit:
            break
    return articles


def parse_netease(payload: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("NetEase payload is not an object")
    entries = data.get("list") if isinstance(data.get("list"), list) else next(
        (value for value in data.values() if isinstance(value, list)), []
    )
    articles = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), 500)
        doc_id = str(item.get("docid") or item.get("postid") or "").strip()
        url = _canonical_url(item.get("url_3w") or item.get("url") or item.get("docurl"))
        if not url and doc_id:
            url = f"https://www.163.com/dy/article/{doc_id}.html"
        if not title or not url:
            continue
        articles.append(
            {
                "title": title,
                "url": url,
                "summary": _clean_text(item.get("digest") or item.get("description") or title),
                "published_at_raw": item.get("ptime"),
                "publisher": source["publisher"],
            }
        )
        if len(articles) >= limit:
            break
    return articles


PARSERS = {
    "feed": parse_feed_payload,
    "google-news": parse_feed_payload,
    "eastmoney-kx": parse_eastmoney_kx,
    "eastmoney-news": parse_eastmoney_news,
    "wscn-live": parse_wscn_live,
    "cls": parse_cls,
    "netease": parse_netease,
}


def parse_payload(payload: bytes, source: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    parser_name = str(source.get("parser") or "")
    parser = PARSERS.get(parser_name)
    if parser is None:
        raise ValueError(f"unsupported NewsNook parser: {parser_name or '<missing>'}")
    text = payload.decode("utf-8-sig", errors="replace")
    articles = parser(text, source, limit)
    if not articles:
        raise RuntimeError(f"NewsNook source returned no usable items for parser={parser_name}")
    return articles


def _query_terms(query: str) -> list[str]:
    return list(dict.fromkeys(part.casefold() for part in QUERY_SPLIT.split(query.strip()) if part.strip()))


def _matches(article: dict[str, Any], terms: list[str], match_mode: str) -> bool:
    if not terms:
        return True
    haystack = " ".join(
        str(article.get(field) or "") for field in ("title", "summary", "publisher")
    ).casefold()
    checks = [term in haystack for term in terms]
    return all(checks) if match_mode == "all" else any(checks)


def _fact(
    source_id: str,
    source: dict[str, Any],
    article: dict[str, Any],
    *,
    endpoint: str,
    retrieved_at: str,
) -> dict[str, Any]:
    title = _clean_text(article.get("title"), 500)
    url = _canonical_url(article.get("url"))
    summary = _clean_text(article.get("summary"))
    publisher_name = _clean_text(article.get("publisher"), 200) or str(source["publisher"])
    published_at, period = _published_at(
        article.get("published_at_raw"), str(source.get("timezone") or "UTC"), retrieved_at
    )
    parser_name = str(source.get("parser") or "")
    if parser_name == "google-news":
        role = "discovery_lead"
        scope = "metadata_only"
        observed = False
        claim = f"NewsNook API indexed a Google News item attributed to {publisher_name}: {title}"
    elif summary:
        role = "api_observed_news_item"
        scope = "content_and_metadata"
        observed = True
        claim = f"NewsNook API returned an item attributed to {publisher_name}: {title}"
    else:
        role = "publisher_index"
        scope = "metadata_only"
        observed = False
        claim = f"NewsNook API listed an item attributed to {publisher_name}: {title}"
    return {
        "fact_id": f"NEWSNOOK-{period}-{normalized_identifier(source_id)}-{sha256_bytes(url.encode('utf-8'))[:12]}",
        "claim": claim,
        "period": period,
        "publisher": publisher_name,
        "source_url": url,
        "retrieved_at": retrieved_at,
        "title": title,
        "published_at": published_at,
        "excerpt": summary,
        "evidence_role": role,
        "observation_scope": scope,
        "content_observed": observed,
        "retrieved_via": endpoint,
        "api_source_id": source_id,
        "source_role": source.get("role"),
        "source_authority_score": source.get("authority_score"),
        "api_endpoint_stability": source.get("endpoint_stability"),
    }


def _selected_sources(config: dict[str, Any], preset: str, explicit: list[str]) -> list[str]:
    sources = config.get("sources") or {}
    if explicit:
        selected = list(dict.fromkeys(explicit))
    else:
        presets = config.get("presets") or {}
        if preset not in presets:
            raise ValueError(f"unknown NewsNook preset {preset!r}; available: {', '.join(sorted(presets))}")
        selected = list(dict.fromkeys(str(item) for item in presets[preset]))
    unknown = [item for item in selected if item not in sources]
    if unknown:
        raise ValueError(f"unknown NewsNook source IDs: {', '.join(unknown)}")
    if not selected:
        raise ValueError("at least one NewsNook source is required")
    return selected


def collect_newsnook_news(
    *,
    config: dict[str, Any],
    preset: str = "finance",
    explicit_sources: list[str] | None = None,
    query: str = "",
    match_mode: str = "any",
    api_base: str | None = None,
    cache_dir: Path | None = None,
    max_items_per_source: int = 50,
    max_facts: int = 200,
    min_success_sources: int = 2,
    min_facts: int = 1,
    ttl_seconds: float = 300,
    allow_stale: bool = True,
    client: CachedHttpClient | None = None,
) -> dict[str, Any]:
    if config.get("schema") != "newsnook.api.sources/1":
        raise ValueError("invalid NewsNook source registry")
    if match_mode not in ("any", "all"):
        raise ValueError("match_mode must be any or all")
    if not 1 <= max_items_per_source <= 500:
        raise ValueError("max_items_per_source must be between 1 and 500")
    if not 1 <= max_facts <= 2000:
        raise ValueError("max_facts must be between 1 and 2000")
    selected = _selected_sources(config, preset, explicit_sources or [])
    base = validate_api_base(api_base or os.environ.get("NEWSNOOK_API_BASE") or str(config["api_base"]))
    terms = _query_terms(query)
    http = client or CachedHttpClient(
        cache_dir,
        timeout=20,
        retries=3,
        user_agent="decode-economic-news/1.0 NewsNook-API-client",
        default_min_interval=0.35,
    )
    attempts: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for source_id in selected:
        source = dict(config["sources"][source_id])
        endpoint = feed_endpoint(base, source_id)
        try:
            fetched = http.get(
                endpoint,
                headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json, text/html, */*"},
                ttl_seconds=ttl_seconds,
                min_interval_seconds=0.35,
                allow_stale=allow_stale,
            )
            articles = parse_payload(fetched.body, source, limit=max_items_per_source)
            matched = [item for item in articles if _matches(item, terms, match_mode)]
            attempts.append(
                {
                    "source_id": source_id,
                    "publisher": source["publisher"],
                    "parser": source["parser"],
                    "endpoint": endpoint,
                    "outcome": "success",
                    "retrieval_status": fetched.status,
                    "http_status": fetched.http_status,
                    "content_type": fetched.content_type,
                    "raw_sha256": fetched.raw_sha256,
                    "item_count": len(articles),
                    "matched_item_count": len(matched),
                    "warning": fetched.warning or None,
                }
            )
            for article in matched:
                fact = _fact(
                    source_id,
                    source,
                    article,
                    endpoint=endpoint,
                    retrieved_at=fetched.retrieved_at,
                )
                if not fact["source_url"] or fact["source_url"] in seen_urls:
                    continue
                facts.append(fact)
                seen_urls.add(fact["source_url"])
        except Exception as exc:
            attempts.append(
                {
                    "source_id": source_id,
                    "publisher": source["publisher"],
                    "parser": source["parser"],
                    "endpoint": endpoint,
                    "outcome": "failed",
                    "item_count": 0,
                    "matched_item_count": 0,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
    facts.sort(key=lambda item: (str(item.get("published_at") or ""), item["fact_id"]), reverse=True)
    facts = facts[:max_facts]
    successes = [item for item in attempts if item["outcome"] == "success"]
    failures = [item for item in attempts if item["outcome"] == "failed"]
    stale = [item for item in successes if item.get("retrieval_status") == "stale"]
    required_successes = min(max(1, min_success_sources), len(selected))
    reasons = []
    if len(successes) < required_successes:
        reasons.append(f"only {len(successes)}/{required_successes} required NewsNook sources succeeded")
    if len(facts) < max(1, min_facts):
        reasons.append(f"only {len(facts)}/{max(1, min_facts)} required relevant items were found")
    primary_sufficient = not reasons
    if not successes:
        status = "failed"
    elif failures or stale:
        status = "degraded"
    elif all(item.get("retrieval_status") == "cached" for item in successes):
        status = "cached"
    else:
        status = "fresh"
    warnings = [
        "NewsNook is the API transport, not the publisher; retain the attributed upstream publisher and original URL.",
        "A feed/API item records the observed title and excerpt. Corroborate central, surprising or numerical claims with an original or independent source.",
        "Use the browser only when this primary API gate fails or a material claim cannot be checked through lawful API/HTTP access.",
    ]
    warnings.extend(
        f"NewsNook source failed: {item['source_id']}: {item['error']}" for item in failures
    )
    warnings.extend(
        f"NewsNook source used stale cache: {item['source_id']}" for item in stale
    )
    if terms and not facts:
        warnings.append(f"NewsNook sources returned no items matching query: {query}")
    combined_hash = sha256_bytes(
        json.dumps(
            [{"source_id": item["source_id"], "raw_sha256": item.get("raw_sha256"), "outcome": item["outcome"]} for item in attempts],
            sort_keys=True,
        ).encode("utf-8")
    )
    return {
        "schema": "evidence.source/1",
        "provider": provider("newsnook-api", "NewsNook API", 0.50, 0.65),
        "retrieval": {
            "status": status,
            "retrieved_at": utc_now(),
            "source_url": base,
            "raw_sha256": combined_hash,
            "api_transport": "NewsNook /api/feed/{source_id}",
        },
        "collection": {
            "schema": "newsnook.api.collection/1",
            "repository": config.get("repository"),
            "registry_commit": config.get("registry_commit"),
            "api_base": base,
            "preset": None if explicit_sources else preset,
            "query": query,
            "query_terms": terms,
            "match_mode": match_mode,
            "selected_sources": selected,
            "attempts": attempts,
            "gate": {
                "requested_sources": len(selected),
                "attempted_sources": len(attempts),
                "successful_sources": len(successes),
                "failed_sources": [item["source_id"] for item in failures],
                "stale_sources": [item["source_id"] for item in stale],
                "raw_item_count": sum(int(item.get("item_count") or 0) for item in attempts),
                "relevant_fact_count": len(facts),
                "all_source_outcomes_explicit": len(attempts) == len(selected),
                "primary_sufficient": primary_sufficient,
                "passed": primary_sufficient,
                "browser_fallback_recommended": not primary_sufficient,
                "fallback_reasons": reasons,
            },
        },
        "facts": facts,
        "warnings": list(dict.fromkeys(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", default="finance")
    parser.add_argument("--source", action="append", default=[], help="Replace the preset with explicit NewsNook source IDs")
    parser.add_argument("--query", default="", help="Filter title, excerpt and attributed publisher")
    parser.add_argument("--match", choices=("any", "all"), default="any")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/decode-economic-news/newsnook"))
    parser.add_argument("--ttl-seconds", type=float, default=300)
    parser.add_argument("--max-items-per-source", type=int, default=50)
    parser.add_argument("--max-facts", type=int, default=200)
    parser.add_argument("--min-success-sources", type=int, default=2)
    parser.add_argument("--min-facts", type=int, default=1)
    parser.add_argument("--no-stale", action="store_true")
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_json(args.sources)
    if args.list_presets:
        for name, source_ids in sorted((config.get("presets") or {}).items()):
            print(f"{name}\t{','.join(source_ids)}")
        return 0
    if args.list_sources:
        for source_id, item in sorted((config.get("sources") or {}).items()):
            print(f"{source_id}\t{item['publisher']}\t{item['parser']}\t{item['role']}")
        return 0
    if args.output is None:
        parser.error("--output is required unless --list-presets or --list-sources is used")
    result = collect_newsnook_news(
        config=config,
        preset=args.preset,
        explicit_sources=args.source,
        query=args.query,
        match_mode=args.match,
        api_base=args.api_base or None,
        cache_dir=args.cache_dir,
        max_items_per_source=args.max_items_per_source,
        max_facts=args.max_facts,
        min_success_sources=args.min_success_sources,
        min_facts=args.min_facts,
        ttl_seconds=args.ttl_seconds,
        allow_stale=not args.no_stale,
    )
    atomic_write_json(args.output, result)
    gate = result["collection"]["gate"]
    print(
        f"status={result['retrieval']['status']} passed={gate['passed']} "
        f"sources={gate['successful_sources']}/{gate['requested_sources']} facts={gate['relevant_fact_count']}"
    )
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
