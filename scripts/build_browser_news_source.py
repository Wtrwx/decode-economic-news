#!/usr/bin/env python3
"""Normalize browser-observed news pages into evidence.source/1."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, normalized_identifier, provider, sha256_bytes, sha256_file, utc_now


TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
    "spm",
}
VALID_METHODS = {"visible_original_page", "publisher_index", "search_result"}
VALID_ACCESS = {"open", "signed_in", "login_required", "paywalled", "unknown"}


def canonicalize_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("browser page URL must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("browser page URL must not contain user information")
    host = parsed.hostname.lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    query = []
    for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        query.append((key, item))
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, urllib.parse.urlencode(query), ""))


def _iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        return match.group(0) if match else ""


def _short_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def normalize_capture(capture: dict[str, Any], *, max_excerpt_chars: int = 800) -> dict[str, Any]:
    if capture.get("schema") != "browser.news.capture/1":
        raise ValueError("input must use browser.news.capture/1")
    if not 100 <= max_excerpt_chars <= 2000:
        raise ValueError("max_excerpt_chars must be between 100 and 2000")
    pages = capture.get("pages")
    if not isinstance(pages, list):
        raise ValueError("capture pages must be a list")
    captured_at = str(capture.get("captured_at") or utc_now())
    if not _iso_date(captured_at):
        raise ValueError("captured_at must be an ISO date or datetime")
    facts: list[dict[str, Any]] = []
    warnings = [
        "Browser observation records what was visible at capture time; it does not independently verify an article's claims.",
        "Only a short excerpt is retained. Cookies, storage, request headers and browser credentials must never enter a capture file.",
    ]
    seen: set[str] = set()
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            warnings.append(f"skipped non-object browser page at index {index}")
            continue
        raw_url = str(page.get("canonical_url") or page.get("url") or "")
        try:
            url = canonicalize_url(raw_url)
        except ValueError as exc:
            warnings.append(f"skipped browser page {index}: {exc}")
            continue
        if url in seen:
            continue
        title = _short_text(page.get("title"), 500)
        if not title:
            warnings.append(f"skipped browser page without title: {url}")
            continue
        method = str(page.get("capture_method") or "search_result")
        if method not in VALID_METHODS:
            warnings.append(f"browser page used unknown capture_method={method!r}; treated as search_result")
            method = "search_result"
        access = str(page.get("access_state") or "unknown")
        if access not in VALID_ACCESS:
            access = "unknown"
        publisher = _short_text(page.get("publisher"), 200) or urllib.parse.urlsplit(url).hostname or "Unknown publisher"
        published_at = str(page.get("published_at") or "")
        observed_at = str(page.get("observed_at") or captured_at)
        period = _iso_date(published_at) or _iso_date(observed_at)
        if not period:
            warnings.append(f"skipped browser page without usable date: {url}")
            continue
        visible_text = re.sub(r"\s+", " ", str(page.get("visible_text") or "")).strip()
        supplied_excerpt = page.get("excerpt") or page.get("snippet") or ""
        excerpt_source = visible_text or str(supplied_excerpt)
        excerpt = _short_text(excerpt_source, max_excerpt_chars)
        if method == "visible_original_page":
            role = "browser_observed_original"
            claim = f"A browser-observed page from {publisher} displayed the article title: {title}"
        elif method == "publisher_index":
            role = "publisher_index"
            claim = f"A publisher index from {publisher} listed: {title}"
        else:
            role = "discovery_lead"
            claim = f"Browser search results listed an article titled: {title}"
        fact = {
            "fact_id": f"BROWSER-{period}-{normalized_identifier(publisher)}-{sha256_bytes(url.encode('utf-8'))[:12]}",
            "claim": claim,
            "period": period,
            "publisher": publisher,
            "source_url": url,
            "retrieved_at": observed_at,
            "evidence_role": role,
            "observation_scope": "content_and_metadata" if visible_text and method == "visible_original_page" else "metadata_only",
            "content_observed": bool(visible_text and method == "visible_original_page"),
            "title": title,
            "byline": _short_text(page.get("byline"), 300),
            "published_at": published_at or None,
            "observed_at": observed_at,
            "date_basis": "published_at" if _iso_date(published_at) else "observed_at",
            "capture_method": method,
            "access_state": access,
            "excerpt": excerpt,
            "visible_text_sha256": sha256_bytes(visible_text.encode("utf-8")) if visible_text else None,
        }
        facts.append(fact)
        seen.add(url)
        if access in ("login_required", "paywalled"):
            warnings.append(f"content access was restricted; only visible metadata may be used: {url}")
    if not facts:
        raise RuntimeError("browser capture contained no usable pages")
    first_url = facts[0]["source_url"]
    return {
        "schema": "evidence.source/1",
        "provider": provider("browser-news", "Browser-observed news sources", 0.55, 0.60),
        "retrieval": {
            "status": "fresh",
            "retrieved_at": captured_at,
            "source_url": first_url,
            "raw_sha256": sha256_bytes(json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")),
            "capture_surface": _short_text(capture.get("browser_surface"), 100) or "browser",
        },
        "query": _short_text(capture.get("query"), 500),
        "facts": facts,
        "warnings": list(dict.fromkeys(warnings + [str(item) for item in capture.get("warnings") or []])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--max-excerpt-chars", type=int, default=800)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture = load_json(args.input)
    result = normalize_capture(capture, max_excerpt_chars=args.max_excerpt_chars)
    result["retrieval"]["capture_file_sha256"] = sha256_file(args.input)
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} browser-observed news facts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
