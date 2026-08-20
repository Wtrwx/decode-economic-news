#!/usr/bin/env python3
"""Build a NewsNook-first coverage record with optional browser fallback.

The NewsNook collector records the primary API attempts. A browser plan and
capture are required only when that primary gate fails or the researcher gives
an explicit fallback reason. Browser-only mode remains available for backward
compatibility with existing artifacts.
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


def build_collection_coverage(
    newsnook: dict[str, Any],
    *,
    browser_plan: dict[str, Any] | None = None,
    browser_capture: dict[str, Any] | None = None,
    fallback_reasons: list[str] | None = None,
) -> dict[str, Any]:
    if newsnook.get("schema") != "evidence.source/1":
        raise ValueError("NewsNook input must use evidence.source/1")
    if ((newsnook.get("provider") or {}).get("id")) != "newsnook-api":
        raise ValueError("NewsNook input must come from provider.id=newsnook-api")
    collection = newsnook.get("collection") or {}
    if collection.get("schema") != "newsnook.api.collection/1":
        raise ValueError("NewsNook input is missing newsnook.api.collection/1 metadata")
    primary_gate = collection.get("gate") or {}
    reasons = [str(item).strip() for item in (fallback_reasons or []) if str(item).strip()]
    primary_outcomes_explicit = bool(primary_gate.get("all_source_outcomes_explicit"))
    if not primary_outcomes_explicit:
        reasons.append("not every selected NewsNook source has an explicit outcome")
    if not primary_gate.get("primary_sufficient"):
        reasons.extend(str(item) for item in primary_gate.get("fallback_reasons") or [])
    reasons = list(dict.fromkeys(reasons))
    fallback_required = bool(reasons)

    if (browser_plan is None) != (browser_capture is None):
        raise ValueError("browser plan and capture must be supplied together")
    browser_coverage = None
    if browser_plan is not None and browser_capture is not None:
        browser_coverage = build_coverage(browser_plan, browser_capture)
    browser_passed = bool(((browser_coverage or {}).get("gate") or {}).get("passed"))
    primary_sufficient = bool(primary_gate.get("primary_sufficient"))
    passed = primary_outcomes_explicit and (browser_passed if fallback_required else primary_sufficient)
    warnings = list(newsnook.get("warnings") or [])
    if browser_coverage:
        warnings.extend(browser_coverage.get("warnings") or [])
    if fallback_required and browser_coverage is None:
        warnings.append("Browser fallback is required but no browser plan/capture was supplied.")
    if fallback_required and browser_coverage is not None and not browser_passed:
        warnings.append("Browser fallback was attempted but its explicit coverage gate did not pass.")
    if not fallback_required and browser_coverage is None:
        warnings.append("NewsNook API coverage was sufficient; browser collection was intentionally skipped.")
    if fallback_required and browser_passed:
        status = "degraded"
    elif passed:
        status = "complete"
    else:
        status = "incomplete"
    return {
        "schema": "news.collection.coverage/2",
        "created_at": utc_now(),
        "topic": collection.get("query"),
        "primary": {
            "transport": "newsnook-api",
            "status": (newsnook.get("retrieval") or {}).get("status"),
            "attempts": collection.get("attempts") or [],
            "gate": primary_gate,
        },
        "browser_fallback": {
            "required": fallback_required,
            "reasons": reasons,
            "provided": browser_coverage is not None,
            "passed": browser_passed,
            "coverage": browser_coverage,
        },
        "gate": {
            "primary_api_sufficient": primary_sufficient,
            "all_primary_source_outcomes_explicit": primary_outcomes_explicit,
            "browser_fallback_required": fallback_required,
            "browser_fallback_provided": browser_coverage is not None,
            "browser_fallback_passed": browser_passed,
            "passed": passed,
        },
        "status": status,
        "warnings": list(dict.fromkeys(str(item) for item in warnings if str(item).strip())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newsnook", type=Path, help="evidence.source/1 from fetch_newsnook_news.py")
    parser.add_argument("--plan", type=Path, help="browser fallback plan, or browser-only plan")
    parser.add_argument("--capture", type=Path, help="browser fallback capture, or browser-only capture")
    parser.add_argument("--fallback-reason", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.newsnook:
        if (args.plan is None) != (args.capture is None):
            parser.error("--plan and --capture must be supplied together")
        result = build_collection_coverage(
            load_json(args.newsnook),
            browser_plan=load_json(args.plan) if args.plan else None,
            browser_capture=load_json(args.capture) if args.capture else None,
            fallback_reasons=args.fallback_reason,
        )
        result["inputs"] = {
            "newsnook_sha256": sha256_file(args.newsnook),
            "browser_plan_sha256": sha256_file(args.plan) if args.plan else None,
            "browser_capture_sha256": sha256_file(args.capture) if args.capture else None,
        }
    else:
        if args.plan is None or args.capture is None:
            parser.error("browser-only mode requires --plan and --capture; preferred mode uses --newsnook")
        result = build_coverage(load_json(args.plan), load_json(args.capture))
        result["inputs"] = {
            "plan_sha256": sha256_file(args.plan),
            "capture_sha256": sha256_file(args.capture),
        }
    atomic_write_json(args.output, result)
    gate = result["gate"]
    if result.get("schema") == "news.collection.coverage/2":
        print(
            f"status={result['status']} passed={gate['passed']} "
            f"primary={gate['primary_api_sufficient']} fallback_required={gate['browser_fallback_required']}"
        )
    else:
        print(
            f"status={result['status']} passed={gate['passed']} "
            f"accounted={gate['accounted_publishers']}/{gate['required_publishers']} "
            f"originals={gate['opened_original_pages']}"
        )
    return 0 if gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
