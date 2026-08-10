#!/usr/bin/env python3
"""Validate evidence packs and source documents without network access."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from evidence_core import load_json


def _valid_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_fact(fact: dict, seen: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    fact_id = str(fact.get("fact_id") or "")
    if not fact_id:
        errors.append("fact missing fact_id")
    elif fact_id in seen:
        errors.append(f"duplicate fact_id: {fact_id}")
    else:
        seen.add(fact_id)
    for field in ("claim", "publisher", "source_url", "retrieved_at", "period"):
        if fact.get(field) in (None, ""):
            errors.append(f"{fact_id or '<unknown>'} missing {field}")
    parsed = urlsplit(str(fact.get("source_url") or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors.append(f"{fact_id or '<unknown>'} has invalid source_url")
    if fact.get("retrieved_at") and not _valid_iso(fact.get("retrieved_at")):
        errors.append(f"{fact_id or '<unknown>'} has invalid retrieved_at")
    if "value" in fact and fact.get("unit") in (None, ""):
        errors.append(f"{fact_id or '<unknown>'} numeric fact missing unit")
    if "REDACTED" in str(fact.get("source_url") or ""):
        warnings.append(f"{fact_id or '<unknown>'} source URL contains redacted credentials")
    return errors, warnings


def validate_document(document: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = list(document.get("warnings") or [])
    schema = document.get("schema")
    if schema not in ("evidence.source/1", "evidence.pack/1"):
        errors.append(f"unsupported schema for evidence validation: {schema!r}")
    facts = document.get("facts")
    if not isinstance(facts, list):
        errors.append("facts must be a list")
        facts = []
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            errors.append("fact is not an object")
            continue
        fact_errors, fact_warnings = validate_fact(fact, seen)
        errors.extend(fact_errors)
        warnings.extend(fact_warnings)
    if schema == "evidence.pack/1" and not str(document.get("topic") or "").strip():
        errors.append("evidence pack missing topic")
    if not facts:
        warnings.append("document contains no verified facts")
    metadata_only = sum(
        item.get("evidence_role") in {"discovery_lead", "publisher_index"}
        or item.get("observation_scope") == "metadata_only"
        for item in facts if isinstance(item, dict)
    )
    if metadata_only:
        warnings.append(
            f"document contains {metadata_only} discovery or metadata-only facts; they do not count as substantive support"
        )
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(warnings), "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    report = validate_document(load_json(args.input))
    for error in report["errors"]:
        print(f"ERROR: {error}")
    for warning in report["warnings"]:
        print(f"WARN: {warning}")
    print(f"valid={report['valid']} errors={report['error_count']} warnings={report['warning_count']}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
