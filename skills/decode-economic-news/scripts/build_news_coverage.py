#!/usr/bin/env python3
"""Build and validate an explicit browser-news coverage record.

The search plan says what should be checked. The capture must say what actually
happened, including negative outcomes. This prevents a planned Reuters search
from being silently treated as completed research.
"""

from __future__ import annotations

import argparse
import urllib.parse
from pathlib import Path
from typing import Any

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now


VALID_OUTCOMES = {
    "opened_original",
    "no_relevant_result",
    "paywalled",
    "login_required",
    "search_results_only",
    "failed",
}
ACCOUNTED_OUTCOMES = VALID_OUTCOMES - {"failed"}
COMPLETED_OUTCOMES = ACCOUNTED_OUTCOMES - {"search_results_only"}


def _publisher_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _site_for_page(page: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any] | None:
    publisher = _publisher_key(page.get("publisher"))
    raw_url = str(page.get("canonical_url") or page.get("url") or "")
    hostname = (urllib.parse.urlsplit(raw_url).hostname or "").casefold()
    for query in queries:
        if publisher and publisher == _publisher_key(query.get("publisher")):
            return query
        domain = str(query.get("domain") or "").casefold()
        if domain and (hostname == domain or hostname.endswith(f".{domain}")):
            return query
    return None


def _page_outcome(page: dict[str, Any]) -> str:
    access = str(page.get("access_state") or "unknown")
    method = str(page.get("capture_method") or "search_result")
    if access == "paywalled":
        return "paywalled"
    if access == "login_required":
        return "login_required"
    if method == "visible_original_page" and access in {"open", "signed_in"}:
        return "opened_original"
    return "search_results_only"


def build_coverage(plan: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    if plan.get("schema") != "browser.news.search-plan/1":
        raise ValueError("plan must use browser.news.search-plan/1")
    if capture.get("schema") != "browser.news.capture/1":
        raise ValueError("capture must use browser.news.capture/1")
    queries = plan.get("queries") or []
    required = [item for item in queries if item.get("must_attempt", True)]
    records: dict[str, dict[str, Any]] = {}
    for item in required:
        site_id = str(item.get("site_id") or "")
        if not site_id:
            continue
        records[site_id] = {
            "site_id": site_id,
            "publisher": item.get("publisher"),
            "query": item.get("query"),
            "role": item.get("role"),
            "outcome": None,
            "original_pages": 0,
            "observed_pages": 0,
            "notes": [],
        }

    warnings: list[str] = []
    for attempt in capture.get("attempts") or []:
        if not isinstance(attempt, dict):
            warnings.append("ignored a non-object browser attempt")
            continue
        site_id = str(attempt.get("site_id") or "")
        record = records.get(site_id)
        if not record:
            warnings.append(f"capture attempt is not in the required plan: {site_id or '<missing>'}")
            continue
        outcome = str(attempt.get("outcome") or "")
        if outcome not in VALID_OUTCOMES:
            warnings.append(f"invalid outcome for {site_id}: {outcome or '<missing>'}")
            continue
        record["outcome"] = outcome
        note = " ".join(str(attempt.get("note") or "").split())
        if note:
            record["notes"].append(note[:500])

    for page in capture.get("pages") or []:
        if not isinstance(page, dict):
            continue
        matched = _site_for_page(page, required)
        if not matched:
            continue
        record = records[str(matched["site_id"])]
        outcome = _page_outcome(page)
        record["observed_pages"] += 1
        if outcome == "opened_original":
            record["original_pages"] += 1
            record["outcome"] = "opened_original"
        elif record["outcome"] != "opened_original":
            record["outcome"] = outcome

    attempts = list(records.values())
    missing = [item["site_id"] for item in attempts if item["outcome"] is None]
    failed = [item["site_id"] for item in attempts if item["outcome"] == "failed"]
    unresolved = [item["site_id"] for item in attempts if item["outcome"] == "search_results_only"]
    accounted = [item for item in attempts if item["outcome"] in ACCOUNTED_OUTCOMES]
    completed = [item for item in attempts if item["outcome"] in COMPLETED_OUTCOMES]
    originals = sum(int(item["original_pages"]) for item in attempts)
    reuters = records.get("reuters")
    gate = {
        "required_publishers": len(attempts),
        "accounted_publishers": len(accounted),
        "all_required_publishers_accounted_for": not missing and not failed and len(accounted) == len(attempts),
        "all_required_publishers_completed": not missing and not failed and not unresolved and len(completed) == len(attempts),
        "reuters_attempted": bool(reuters and reuters["outcome"] in ACCOUNTED_OUTCOMES),
        "opened_original_pages": originals,
        "missing_publishers": missing,
        "failed_publishers": failed,
        "unresolved_publishers": unresolved,
    }
    gate["passed"] = bool(
        gate["all_required_publishers_completed"]
        and (gate["reuters_attempted"] or "reuters" not in records)
    )
    if originals == 0:
        warnings.append(
            "No core-media original page was opened; coverage may pass only because every publisher has an explicit negative or restricted outcome."
        )
    if missing:
        warnings.append(f"required publishers were silently skipped: {', '.join(missing)}")
    if failed:
        warnings.append(f"publisher checks failed and need retry or explicit degraded handling: {', '.join(failed)}")
    if unresolved:
        warnings.append(f"search results were not resolved to an original/access/no-result outcome: {', '.join(unresolved)}")
    return {
        "schema": "browser.news.coverage/1",
        "created_at": utc_now(),
        "topic": plan.get("topic") or capture.get("query"),
        "attempts": attempts,
        "gate": gate,
        "status": "complete" if gate["passed"] and originals else ("degraded" if gate["passed"] else "incomplete"),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_coverage(load_json(args.plan), load_json(args.capture))
    result["inputs"] = {
        "plan_sha256": sha256_file(args.plan),
        "capture_sha256": sha256_file(args.capture),
    }
    atomic_write_json(args.output, result)
    gate = result["gate"]
    print(
        f"status={result['status']} passed={gate['passed']} "
        f"accounted={gate['accounted_publishers']}/{gate['required_publishers']} "
        f"originals={gate['opened_original_pages']}"
    )
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
