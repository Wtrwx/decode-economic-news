#!/usr/bin/env python3
"""Save, retrieve, compare and review reproducible research runs."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from evidence_core import (
    atomic_write_bytes,
    atomic_write_json,
    load_json,
    normalized_identifier,
    sha256_bytes,
    sha256_file,
    utc_now,
)


RUN_SCHEMA = "research.journal-run/1"
REVIEW_SCHEMA = "research.journal-review/1"
DEFAULT_ARCHIVE_ENV = "DECODE_ECONOMIC_NEWS_ARCHIVE"
SAFE_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".csv", ".tsv", ".pdf"}
STANCE_CHOICES = ("bullish", "bearish", "neutral", "mixed", "abstain", "not_applicable")
CONFIDENCE_CHOICES = ("low", "medium", "high", "unrated")
THESIS_STATUS_CHOICES = ("confirmed", "partially_confirmed", "refuted", "unresolved")
DECISION_QUALITY_CHOICES = ("good", "mixed", "poor", "unrated")


def default_archive() -> Path:
    configured = os.environ.get(DEFAULT_ARCHIVE_ENV)
    return Path(configured).expanduser() if configured else Path("work/research-journal")


def _archive_root(path: Path) -> Path:
    return path.expanduser().resolve()


def _clean_list(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(" ".join(str(item).split()) for item in values if str(item).strip()))


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _require_date(value: str, label: str) -> str:
    cleaned = value.strip()
    try:
        date.fromisoformat(cleaned[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must start with an ISO date: {value}") from exc
    return cleaned


def parse_artifact_spec(value: str) -> tuple[str, Path]:
    role, separator, raw_path = value.partition("=")
    if not separator or not role.strip() or not raw_path.strip():
        raise ValueError("artifact must use ROLE=PATH")
    return normalized_identifier(role), Path(raw_path).expanduser()


def _json_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema": document.get("schema"),
        "method_version": document.get("method_version"),
        "as_of": document.get("as_of"),
        "status": document.get("status"),
        "warning_count": len(document.get("warnings") or []),
    }
    gate = document.get("publication_gate") or document.get("gate") or {}
    if isinstance(gate, dict):
        snapshot["gate"] = {
            key: gate.get(key)
            for key in (
                "ready", "passed", "status", "sector_signal_usable",
                "selector_backtest_usable", "news_coverage_complete",
            )
            if key in gate
        }
    metrics = document.get("metrics") or {}
    if isinstance(metrics, dict):
        snapshot["metrics"] = {
            key: metrics.get(key)
            for key in (
                "hit_rate", "excess_hit_rate", "mean_net_return_pct",
                "median_net_return_pct", "mean_excess_return_pct",
            )
            if key in metrics
        }
    recommendations = document.get("recommendations") or []
    if isinstance(recommendations, list) and recommendations:
        snapshot["action_counts"] = dict(Counter(
            str(item.get("action") or "unknown")
            for item in recommendations if isinstance(item, dict)
        ))
        snapshot["recommendation_codes"] = [
            str(item.get("code")) for item in recommendations
            if isinstance(item, dict) and item.get("code")
        ]
    for key in ("current_score", "current_bucket"):
        if key in document:
            snapshot[key] = document.get(key)
    return {key: value for key, value in snapshot.items() if value not in (None, {}, [])}


def _artifact_record(archive: Path, role: str, source: Path) -> dict[str, Any]:
    source = source.resolve()
    if not source.is_file():
        raise ValueError(f"artifact is not a file: {source}")
    if source.name == ".env" or source.suffix.casefold() in {".secret", ".secrets"}:
        raise ValueError(f"refusing to archive a likely secret file: {source.name}")
    payload = source.read_bytes()
    digest = sha256_bytes(payload)
    suffix = source.suffix.casefold() if source.suffix.casefold() in SAFE_SUFFIXES else ".bin"
    relative = Path("objects") / digest[:2] / digest
    target = archive / relative
    if target.exists():
        if sha256_file(target) != digest:
            raise ValueError(f"content-addressed object is corrupt: {target}")
    else:
        atomic_write_bytes(target, payload)
    media_type = "application/octet-stream"
    snapshot: dict[str, Any] = {}
    if suffix in {".json", ".jsonl"}:
        media_type = "application/json" if suffix == ".json" else "application/x-ndjson"
        if suffix == ".json":
            try:
                document = json.loads(payload.decode("utf-8"))
                if isinstance(document, dict):
                    snapshot = _json_snapshot(document)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
    elif suffix in {".md", ".txt"}:
        media_type = "text/markdown" if suffix == ".md" else "text/plain"
    elif suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix in {".csv", ".tsv"}:
        media_type = "text/csv" if suffix == ".csv" else "text/tab-separated-values"
    return {
        "role": normalized_identifier(role),
        "source_name": source.name,
        "object_path": relative.as_posix(),
        "sha256": digest,
        "size_bytes": len(payload),
        "media_type": media_type,
        "snapshot": snapshot,
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def _stored_object_path(archive: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or candidate.parts[0] != "objects" or ".." in candidate.parts:
        raise ValueError(f"invalid object path: {relative}")
    return archive / candidate


def _run_identity(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic": run.get("topic"),
        "as_of": run.get("as_of"),
        "horizon": run.get("horizon"),
        "instruments": run.get("instruments") or [],
        "tags": run.get("tags") or [],
        "summary": run.get("summary") or {},
        "artifacts": [
            {"role": item.get("role"), "sha256": item.get("sha256")}
            for item in run.get("artifacts") or []
        ],
    }


def _review_identity(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": review.get("run_id"),
        "observed_at": review.get("observed_at"),
        "thesis_status": review.get("thesis_status"),
        "realized_return_pct": review.get("realized_return_pct"),
        "benchmark_return_pct": review.get("benchmark_return_pct"),
        "excess_return_pct": review.get("excess_return_pct"),
        "decision_quality": review.get("decision_quality"),
        "note": review.get("note"),
        "tags": review.get("tags") or [],
        "artifacts": [
            {"role": item.get("role"), "sha256": item.get("sha256")}
            for item in review.get("artifacts") or []
        ],
    }


def _manifest_path(archive: Path, run_id: str) -> Path:
    matches = list((archive / "runs").glob(f"*/*/{run_id}/manifest.json"))
    if not matches:
        raise FileNotFoundError(f"research run not found: {run_id}")
    if len(matches) > 1:
        raise ValueError(f"duplicate research run id: {run_id}")
    return matches[0]


def load_run(archive: Path, run_id: str) -> tuple[dict[str, Any], Path]:
    path = _manifest_path(_archive_root(archive), run_id)
    document = load_json(path)
    if document.get("schema") != RUN_SCHEMA:
        raise ValueError(f"invalid research run schema: {path}")
    return document, path


def load_reviews(manifest_path: Path) -> list[dict[str, Any]]:
    reviews = []
    for path in sorted((manifest_path.parent / "reviews").glob("*.json")):
        document = load_json(path)
        if document.get("schema") == REVIEW_SCHEMA:
            reviews.append(document)
    return sorted(reviews, key=lambda item: (str(item.get("observed_at") or ""), str(item.get("created_at") or "")))


def save_run(
    archive: Path,
    *,
    topic: str,
    as_of: str,
    horizon: str,
    conclusion: Path,
    artifacts: list[tuple[str, Path]] | None = None,
    instruments: list[str] | None = None,
    tags: list[str] | None = None,
    stance: str = "not_applicable",
    decision: str = "",
    confidence: str = "unrated",
    thesis: str = "",
    review_date: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    archive = _archive_root(archive)
    if stance not in STANCE_CHOICES:
        raise ValueError(f"invalid stance: {stance}")
    if confidence not in CONFIDENCE_CHOICES:
        raise ValueError(f"invalid confidence: {confidence}")
    topic = " ".join(topic.split())
    if not topic or not as_of.strip() or not horizon.strip():
        raise ValueError("topic, as_of and horizon are required")
    as_of = _require_date(as_of, "as_of")
    if review_date:
        review_date = _require_date(review_date, "review_date")
    artifact_specs = [("conclusion", conclusion), *(artifacts or [])]
    records = []
    seen = set()
    for role, path in artifact_specs:
        record = _artifact_record(archive, role, path)
        key = (record["role"], record["sha256"])
        if key not in seen:
            records.append(record)
            seen.add(key)
    conclusion_record = records[0]
    summary = {
        "stance": stance,
        "decision": " ".join(decision.split()),
        "confidence": confidence,
        "thesis": " ".join(thesis.split()),
        "review_date": review_date.strip() or None,
    }
    identity = {
        "topic": topic,
        "as_of": as_of,
        "horizon": horizon.strip(),
        "instruments": _clean_list(instruments or []),
        "tags": _clean_list(tags or []),
        "summary": summary,
        "artifacts": [{"role": item["role"], "sha256": item["sha256"]} for item in records],
    }
    content_fingerprint = _fingerprint(identity)
    if run_id:
        run_id = normalized_identifier(run_id)
    else:
        date_key = "".join(character for character in as_of[:10] if character.isdigit()) or "undated"
        run_id = f"{date_key}-{normalized_identifier(topic)[:40]}-{content_fingerprint[:10]}"
    year = as_of[:4] if len(as_of) >= 4 and as_of[:4].isdigit() else utc_now()[:4]
    month = as_of[5:7] if len(as_of) >= 7 and as_of[5:7].isdigit() else utc_now()[5:7]
    manifest_path = archive / "runs" / year / month / run_id / "manifest.json"
    if manifest_path.exists():
        existing = load_json(manifest_path)
        if existing.get("content_fingerprint") == content_fingerprint:
            return existing
        raise ValueError(f"run id already exists with different content: {run_id}")
    schemas = Counter(
        str((item.get("snapshot") or {}).get("schema"))
        for item in records if (item.get("snapshot") or {}).get("schema")
    )
    manifest = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "created_at": utc_now(),
        "content_fingerprint": content_fingerprint,
        "topic": topic,
        "as_of": as_of,
        "horizon": horizon.strip(),
        "instruments": identity["instruments"],
        "tags": identity["tags"],
        "summary": summary,
        "conclusion": conclusion_record,
        "artifacts": records,
        "artifact_schema_counts": dict(schemas),
        "review_policy": {
            "review_date": summary["review_date"],
            "reviews_are_append_only": True,
            "original_run_is_immutable": True,
        },
        "warnings": [
            "The journal preserves research provenance; it does not make a forecast correct.",
            "Do not archive credentials, cookies, authorization headers or proxy secrets.",
        ],
    }
    atomic_write_json(manifest_path, manifest)
    return manifest


def _matches(
    run: dict[str, Any], *, query: str = "", instrument: str = "", tag: str = "",
    stance: str = "", decision: str = "", date_from: str = "", date_to: str = "",
) -> bool:
    if date_from and str(run.get("as_of") or "") < date_from:
        return False
    if date_to and str(run.get("as_of") or "") > date_to:
        return False
    if instrument and instrument.casefold() not in " ".join(run.get("instruments") or []).casefold():
        return False
    if tag and tag.casefold() not in {str(item).casefold() for item in run.get("tags") or []}:
        return False
    summary = run.get("summary") or {}
    if stance and summary.get("stance") != stance:
        return False
    if decision and decision.casefold() not in str(summary.get("decision") or "").casefold():
        return False
    haystack = " ".join([
        str(run.get("topic") or ""), " ".join(run.get("instruments") or []),
        " ".join(run.get("tags") or []), str(summary.get("thesis") or ""),
    ]).casefold()
    return not query or query.casefold() in haystack


def list_runs(archive: Path, *, limit: int = 50, **filters: str) -> list[dict[str, Any]]:
    archive = _archive_root(archive)
    runs = []
    for path in (archive / "runs").glob("*/*/*/manifest.json"):
        try:
            document = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("schema") == RUN_SCHEMA and _matches(document, **filters):
            runs.append(document)
    runs.sort(key=lambda item: (str(item.get("as_of") or ""), str(item.get("created_at") or "")), reverse=True)
    return runs[: max(1, limit)]


def review_queue(
    archive: Path,
    *,
    as_of: str = "",
    days_ahead: int = 0,
    include_reviewed: bool = False,
    include_unscheduled: bool = False,
    **filters: str,
) -> dict[str, Any]:
    """Return due/overdue research runs with conclusion context attached."""
    archive = _archive_root(archive)
    reference_date = date.fromisoformat(_require_date(as_of, "as_of")[:10]) if as_of else date.today()
    window_end = reference_date + timedelta(days=max(0, days_ahead))
    items = []
    for run in list_runs(archive, limit=1_000_000, **filters):
        _, manifest_path = load_run(archive, str(run["run_id"]))
        reviews = load_reviews(manifest_path)
        summary = run.get("summary") or {}
        raw_review_date = str(summary.get("review_date") or "")
        if not raw_review_date:
            if not include_unscheduled:
                continue
            status = "unscheduled"
            review_day = None
            days_until_review = None
        else:
            review_day = date.fromisoformat(_require_date(raw_review_date, "review_date")[:10])
            reviewed_through = max(
                (date.fromisoformat(str(item.get("observed_at"))[:10]) for item in reviews if item.get("observed_at")),
                default=None,
            )
            if reviewed_through is not None and reviewed_through >= review_day:
                status = "reviewed"
            elif review_day < reference_date:
                status = "overdue"
            elif review_day == reference_date:
                status = "due"
            elif review_day <= window_end:
                status = "upcoming"
            else:
                continue
            days_until_review = (review_day - reference_date).days
        if status == "reviewed" and not include_reviewed:
            continue
        conclusion = run.get("conclusion") or {}
        items.append({
            "run_id": run.get("run_id"),
            "topic": run.get("topic"),
            "as_of": run.get("as_of"),
            "horizon": run.get("horizon"),
            "instruments": run.get("instruments") or [],
            "tags": run.get("tags") or [],
            "review_date": raw_review_date or None,
            "days_until_review": days_until_review,
            "review_status": status,
            "review_count": len(reviews),
            "summary": summary,
            "conclusion": {
                "source_name": conclusion.get("source_name"),
                "sha256": conclusion.get("sha256"),
                "snapshot": conclusion.get("snapshot") or {},
            },
            "artifact_snapshots": {
                str(item.get("role")): item.get("snapshot") or {}
                for item in run.get("artifacts") or []
            },
        })
    priority = {"overdue": 0, "due": 1, "upcoming": 2, "unscheduled": 3, "reviewed": 4}
    items.sort(key=lambda item: (
        priority.get(str(item.get("review_status")), 9),
        str(item.get("review_date") or "9999-12-31"),
        str(item.get("run_id") or ""),
    ))
    return {
        "schema": "research.journal-review-queue/1",
        "created_at": utc_now(),
        "as_of": reference_date.isoformat(),
        "days_ahead": max(0, days_ahead),
        "counts": dict(Counter(str(item["review_status"]) for item in items)),
        "items": items,
    }


def add_review(
    archive: Path,
    run_id: str,
    *,
    observed_at: str,
    thesis_status: str,
    realized_return_pct: float | None = None,
    benchmark_return_pct: float | None = None,
    decision_quality: str = "unrated",
    note: str = "",
    artifacts: list[tuple[str, Path]] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    archive = _archive_root(archive)
    if thesis_status not in THESIS_STATUS_CHOICES:
        raise ValueError(f"invalid thesis status: {thesis_status}")
    if decision_quality not in DECISION_QUALITY_CHOICES:
        raise ValueError(f"invalid decision quality: {decision_quality}")
    observed_at = _require_date(observed_at, "observed_at")
    for label, value in (
        ("realized_return_pct", realized_return_pct),
        ("benchmark_return_pct", benchmark_return_pct),
    ):
        if value is not None and _finite_number(value) is None:
            raise ValueError(f"{label} must be finite")
    run, manifest_path = load_run(archive, run_id)
    artifact_records = [_artifact_record(archive, role, path) for role, path in (artifacts or [])]
    excess = None
    if realized_return_pct is not None and benchmark_return_pct is not None:
        excess = round(realized_return_pct - benchmark_return_pct, 6)
    review_body = {
        "run_id": run_id,
        "observed_at": observed_at,
        "thesis_status": thesis_status,
        "realized_return_pct": realized_return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "excess_return_pct": excess,
        "decision_quality": decision_quality,
        "note": " ".join(note.split()),
        "tags": _clean_list(tags or []),
        "artifacts": [{"role": item["role"], "sha256": item["sha256"]} for item in artifact_records],
    }
    fingerprint = _fingerprint(review_body)
    review_id = f"{''.join(character for character in observed_at[:10] if character.isdigit()) or 'undated'}-{fingerprint[:10]}"
    review_path = manifest_path.parent / "reviews" / f"{review_id}.json"
    if review_path.exists():
        return load_json(review_path)
    review = {
        "schema": REVIEW_SCHEMA,
        "review_id": review_id,
        "created_at": utc_now(),
        "content_fingerprint": fingerprint,
        "run_id": run_id,
        "run_content_fingerprint": run.get("content_fingerprint"),
        **review_body,
        "artifacts": artifact_records,
    }
    atomic_write_json(review_path, review)
    return review


def compare_runs(archive: Path, run_ids: list[str]) -> dict[str, Any]:
    rows = []
    for run_id in run_ids:
        run, path = load_run(archive, run_id)
        reviews = load_reviews(path)
        latest = reviews[-1] if reviews else {}
        snapshots = {
            str(item.get("role")): item.get("snapshot")
            for item in run.get("artifacts") or [] if item.get("snapshot")
        }
        rows.append({
            "run_id": run_id,
            "as_of": run.get("as_of"),
            "horizon": run.get("horizon"),
            "instruments": run.get("instruments"),
            **(run.get("summary") or {}),
            "artifact_schema_counts": run.get("artifact_schema_counts"),
            "artifact_snapshots": snapshots,
            "latest_review": {
                key: latest.get(key) for key in (
                    "observed_at", "thesis_status", "realized_return_pct",
                    "benchmark_return_pct", "excess_return_pct", "decision_quality",
                ) if key in latest
            },
        })
    return {"schema": "research.journal-comparison/1", "created_at": utc_now(), "runs": rows}


def journal_stats(archive: Path, *, group_by: str = "none", **filters: str) -> dict[str, Any]:
    runs = list_runs(archive, limit=1_000_000, **filters)
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for run in runs:
        _, path = load_run(archive, str(run["run_id"]))
        reviews = load_reviews(path)
        latest = reviews[-1] if reviews else {}
        summary = run.get("summary") or {}
        if group_by == "horizon":
            keys = [str(run.get("horizon") or "unknown")]
        elif group_by == "stance":
            keys = [str(summary.get("stance") or "unknown")]
        elif group_by == "decision":
            keys = [str(summary.get("decision") or "unknown")]
        elif group_by == "instrument":
            keys = run.get("instruments") or ["unknown"]
        elif group_by == "tag":
            keys = run.get("tags") or ["untagged"]
        else:
            keys = ["all"]
        for key in keys:
            groups.setdefault(str(key), []).append((run, latest))

    def summarize(items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
        reviewed = [review for _, review in items if review]
        realized = [
            number for number in (_finite_number(item.get("realized_return_pct")) for item in reviewed)
            if number is not None
        ]
        excess = [
            number for number in (_finite_number(item.get("excess_return_pct")) for item in reviewed)
            if number is not None
        ]
        return {
            "runs": len(items),
            "reviewed_runs": len(reviewed),
            "review_coverage": round(len(reviewed) / len(items), 4) if items else 0.0,
            "thesis_status_counts": dict(Counter(str(item.get("thesis_status")) for item in reviewed)),
            "decision_quality_counts": dict(Counter(str(item.get("decision_quality")) for item in reviewed)),
            "mean_realized_return_pct": round(statistics.fmean(realized), 6) if realized else None,
            "mean_excess_return_pct": round(statistics.fmean(excess), 6) if excess else None,
        }

    return {
        "schema": "research.journal-stats/1",
        "created_at": utc_now(),
        "group_by": group_by,
        "groups": {key: summarize(items) for key, items in sorted(groups.items())},
    }


def verify_archive(archive: Path) -> dict[str, Any]:
    archive = _archive_root(archive)
    errors = []
    checked_objects: set[str] = set()
    run_count = review_count = 0
    for manifest_path in (archive / "runs").glob("*/*/*/manifest.json"):
        try:
            run = load_json(manifest_path)
        except Exception as exc:
            errors.append(f"{manifest_path}: {type(exc).__name__}: {exc}")
            continue
        if run.get("schema") != RUN_SCHEMA:
            errors.append(f"{manifest_path}: invalid run schema")
            continue
        run_count += 1
        if _fingerprint(_run_identity(run)) != run.get("content_fingerprint"):
            errors.append(f"{manifest_path}: run content fingerprint mismatch")
        for item in run.get("artifacts") or []:
            relative = str(item.get("object_path") or "")
            expected = str(item.get("sha256") or "")
            if not relative or not expected:
                errors.append(f"{manifest_path}: incomplete artifact record")
                continue
            try:
                target = _stored_object_path(archive, relative)
            except ValueError as exc:
                errors.append(f"{manifest_path}: {exc}")
                continue
            if not target.is_file():
                errors.append(f"{manifest_path}: missing object {relative}")
            elif relative not in checked_objects and sha256_file(target) != expected:
                errors.append(f"{manifest_path}: checksum mismatch {relative}")
            checked_objects.add(relative)
        for review_path in sorted((manifest_path.parent / "reviews").glob("*.json")):
            review_count += 1
            try:
                review = load_json(review_path)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{review_path}: {type(exc).__name__}: {exc}")
                continue
            if review.get("schema") != REVIEW_SCHEMA or review.get("run_id") != run.get("run_id"):
                errors.append(f"{review_path}: invalid review link")
            if review.get("run_content_fingerprint") != run.get("content_fingerprint"):
                errors.append(f"{review_path}: run fingerprint mismatch")
            if _fingerprint(_review_identity(review)) != review.get("content_fingerprint"):
                errors.append(f"{review_path}: review content fingerprint mismatch")
            for item in review.get("artifacts") or []:
                relative = str(item.get("object_path") or "")
                try:
                    target = _stored_object_path(archive, relative)
                except ValueError as exc:
                    errors.append(f"{review_path}: {exc}")
                    continue
                if not target.is_file() or sha256_file(target) != item.get("sha256"):
                    errors.append(f"{review_path}: missing or corrupt review artifact")
                checked_objects.add(relative)
    return {
        "schema": "research.journal-verification/1",
        "verified_at": utc_now(),
        "archive": str(archive),
        "valid": not errors,
        "runs": run_count,
        "reviews": review_count,
        "objects_checked": len(checked_objects),
        "errors": errors,
    }


def _filters(args: argparse.Namespace) -> dict[str, str]:
    return {
        "query": getattr(args, "query", "") or "",
        "instrument": getattr(args, "instrument", "") or "",
        "tag": getattr(args, "tag", "") or "",
        "stance": getattr(args, "stance", "") or "",
        "decision": getattr(args, "decision", "") or "",
        "date_from": getattr(args, "date_from", "") or "",
        "date_to": getattr(args, "date_to", "") or "",
    }


def _add_archive(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--archive", type=Path, default=default_archive())


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query")
    parser.add_argument("--instrument")
    parser.add_argument("--tag")
    parser.add_argument("--stance", choices=STANCE_CHOICES)
    parser.add_argument("--decision")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")


def _print_run_table(runs: list[dict[str, Any]]) -> None:
    print("RUN_ID\tAS_OF\tHORIZON\tSTANCE\tDECISION\tTOPIC")
    for run in runs:
        summary = run.get("summary") or {}
        print("\t".join([
            str(run.get("run_id") or ""), str(run.get("as_of") or ""),
            str(run.get("horizon") or ""), str(summary.get("stance") or ""),
            str(summary.get("decision") or ""), str(run.get("topic") or ""),
        ]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    save_parser = subparsers.add_parser("save", help="save an immutable research run")
    _add_archive(save_parser)
    save_parser.add_argument("--topic", required=True)
    save_parser.add_argument("--as-of", required=True)
    save_parser.add_argument("--horizon", required=True)
    save_parser.add_argument("--conclusion", type=Path, required=True)
    save_parser.add_argument("--artifact", action="append", default=[], metavar="ROLE=PATH")
    save_parser.add_argument("--instrument", action="append", default=[])
    save_parser.add_argument("--tag", action="append", default=[])
    save_parser.add_argument("--stance", choices=STANCE_CHOICES, default="not_applicable")
    save_parser.add_argument("--decision", default="")
    save_parser.add_argument("--confidence", choices=CONFIDENCE_CHOICES, default="unrated")
    save_parser.add_argument("--thesis", default="")
    save_parser.add_argument("--review-date", default="")
    save_parser.add_argument("--run-id")

    list_parser = subparsers.add_parser("list", help="search saved research runs")
    _add_archive(list_parser)
    _add_filters(list_parser)
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--json", action="store_true")

    show_parser = subparsers.add_parser("show", help="show one run and its reviews")
    _add_archive(show_parser)
    show_parser.add_argument("run_id")
    show_parser.add_argument("--artifact-role")
    show_parser.add_argument("--json", action="store_true")

    compare_parser = subparsers.add_parser("compare", help="compare saved conclusions and outcomes")
    _add_archive(compare_parser)
    compare_parser.add_argument("run_ids", nargs="+")
    compare_parser.add_argument("--json", action="store_true")

    review_parser = subparsers.add_parser("review", help="append an outcome review")
    _add_archive(review_parser)
    review_parser.add_argument("run_id")
    review_parser.add_argument("--observed-at", required=True)
    review_parser.add_argument("--thesis-status", choices=THESIS_STATUS_CHOICES, required=True)
    review_parser.add_argument("--realized-return-pct", type=float)
    review_parser.add_argument("--benchmark-return-pct", type=float)
    review_parser.add_argument("--decision-quality", choices=DECISION_QUALITY_CHOICES, default="unrated")
    review_parser.add_argument("--note", default="")
    review_parser.add_argument("--artifact", action="append", default=[], metavar="ROLE=PATH")
    review_parser.add_argument("--tag", action="append", default=[])

    due_parser = subparsers.add_parser("due", help="list conclusions due for outcome review")
    _add_archive(due_parser)
    _add_filters(due_parser)
    due_parser.add_argument("--as-of", default="")
    due_parser.add_argument("--days-ahead", type=int, default=0)
    due_parser.add_argument("--include-reviewed", action="store_true")
    due_parser.add_argument("--include-unscheduled", action="store_true")
    due_parser.add_argument("--output", type=Path)
    due_parser.add_argument("--json", action="store_true")

    stats_parser = subparsers.add_parser("stats", help="summarize reviewed outcomes")
    _add_archive(stats_parser)
    _add_filters(stats_parser)
    stats_parser.add_argument("--group-by", choices=("none", "horizon", "stance", "decision", "instrument", "tag"), default="none")
    stats_parser.add_argument("--json", action="store_true")

    verify_parser = subparsers.add_parser("verify", help="verify manifests and object checksums")
    _add_archive(verify_parser)
    verify_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "save":
            result = save_run(
                args.archive, topic=args.topic, as_of=args.as_of, horizon=args.horizon,
                conclusion=args.conclusion,
                artifacts=[parse_artifact_spec(item) for item in args.artifact],
                instruments=args.instrument, tags=args.tag, stance=args.stance,
                decision=args.decision, confidence=args.confidence, thesis=args.thesis,
                review_date=args.review_date, run_id=args.run_id,
            )
            print(result["run_id"])
            return 0
        if args.command == "list":
            results = list_runs(args.archive, limit=args.limit, **_filters(args))
            print(json.dumps(results, ensure_ascii=False, indent=2) if args.json else "", end="" if args.json else "")
            if not args.json:
                _print_run_table(results)
            elif results:
                print()
            return 0
        if args.command == "show":
            run, path = load_run(args.archive, args.run_id)
            if args.artifact_role:
                match = next((item for item in run.get("artifacts") or [] if item.get("role") == args.artifact_role), None)
                if not match:
                    raise ValueError(f"artifact role not found: {args.artifact_role}")
                print(str(_stored_object_path(_archive_root(args.archive), str(match["object_path"]))))
            else:
                document = {**run, "reviews": load_reviews(path)}
                if args.json:
                    print(json.dumps(document, ensure_ascii=False, indent=2))
                else:
                    _print_run_table([run])
                    print("ARTIFACTS")
                    for item in run.get("artifacts") or []:
                        print(f"{item['role']}\t{item.get('snapshot', {}).get('schema', '-')}\t{item['sha256'][:12]}\t{item['source_name']}")
                    print(f"REVIEWS\t{len(document['reviews'])}")
            return 0
        if args.command == "compare":
            result = compare_runs(args.archive, args.run_ids)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("RUN_ID\tAS_OF\tHORIZON\tSTANCE\tDECISION\tTHESIS_STATUS\tEXCESS_RETURN")
                for item in result["runs"]:
                    latest = item.get("latest_review") or {}
                    print("\t".join(str(value if value is not None else "") for value in (
                        item.get("run_id"), item.get("as_of"), item.get("horizon"), item.get("stance"),
                        item.get("decision"), latest.get("thesis_status"), latest.get("excess_return_pct"),
                    )))
            return 0
        if args.command == "review":
            result = add_review(
                args.archive, args.run_id, observed_at=args.observed_at,
                thesis_status=args.thesis_status, realized_return_pct=args.realized_return_pct,
                benchmark_return_pct=args.benchmark_return_pct, decision_quality=args.decision_quality,
                note=args.note, artifacts=[parse_artifact_spec(item) for item in args.artifact], tags=args.tag,
            )
            print(result["review_id"])
            return 0
        if args.command == "due":
            result = review_queue(
                args.archive, as_of=args.as_of, days_ahead=args.days_ahead,
                include_reviewed=args.include_reviewed,
                include_unscheduled=args.include_unscheduled,
                **_filters(args),
            )
            if args.output:
                atomic_write_json(args.output, result)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("STATUS\tREVIEW_DATE\tRUN_ID\tSTANCE\tDECISION\tTOPIC")
                for item in result["items"]:
                    summary = item.get("summary") or {}
                    print("\t".join(str(value or "") for value in (
                        item.get("review_status"), item.get("review_date"), item.get("run_id"),
                        summary.get("stance"), summary.get("decision"), item.get("topic"),
                    )))
            return 0
        if args.command == "stats":
            result = journal_stats(args.archive, group_by=args.group_by, **_filters(args))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("GROUP\tRUNS\tREVIEWED\tCOVERAGE\tMEAN_RETURN\tMEAN_EXCESS")
                for key, item in result["groups"].items():
                    print("\t".join(str(value if value is not None else "") for value in (
                        key, item["runs"], item["reviewed_runs"], item["review_coverage"],
                        item["mean_realized_return_pct"], item["mean_excess_return_pct"],
                    )))
            return 0
        result = verify_archive(args.archive)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"valid={result['valid']} runs={result['runs']} reviews={result['reviews']} objects={result['objects_checked']} errors={len(result['errors'])}")
        return 0 if result["valid"] else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
