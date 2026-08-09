#!/usr/bin/env python3
"""Combine source and signal documents into a provenance-preserving evidence pack."""

from __future__ import annotations

import argparse
from pathlib import Path

from evidence_core import atomic_write_json, load_json, sha256_file, utc_now
from validate_evidence import validate_document


def build_pack(topic: str, source_paths: list[Path], signal_paths: list[Path]) -> dict:
    if not topic.strip():
        raise ValueError("topic is required")
    facts: list[dict] = []
    signals: list[dict] = []
    artifacts: list[dict] = []
    warnings: list[str] = []
    manifest: list[dict] = []
    for path in source_paths:
        document = load_json(path)
        manifest.append({"role": "source", "path": str(path.resolve()), "sha256": sha256_file(path), "schema": document.get("schema")})
        if document.get("schema") == "evidence.source/1":
            facts.extend(document.get("facts") or [])
        else:
            artifacts.append({"path": str(path.resolve()), "schema": document.get("schema"), "content": document})
        warnings.extend(document.get("warnings") or [])
    for path in signal_paths:
        document = load_json(path)
        if document.get("schema") != "evidence.signal/1":
            raise ValueError(f"signal file is not evidence.signal/1: {path}")
        manifest.append({"role": "signal", "path": str(path.resolve()), "sha256": sha256_file(path), "schema": document.get("schema")})
        signals.append(document)
        warnings.extend(document.get("warnings") or [])
    pack = {
        "schema": "evidence.pack/1",
        "topic": topic.strip(),
        "created_at": utc_now(),
        "facts": facts,
        "signals": signals,
        "artifacts": artifacts,
        "warnings": list(dict.fromkeys(str(item) for item in warnings if str(item).strip())),
        "missing_evidence": [],
        "manifest": manifest,
    }
    report = validate_document(pack)
    pack["validation"] = report
    if report["errors"]:
        raise RuntimeError("invalid evidence pack: " + "; ".join(report["errors"][:5]))
    return pack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--source", action="append", default=[], type=Path)
    parser.add_argument("--signal", action="append", default=[], type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pack = build_pack(args.topic, args.source, args.signal)
    atomic_write_json(args.output, pack)
    print(f"wrote evidence pack: facts={len(pack['facts'])} signals={len(pack['signals'])} warnings={len(pack['warnings'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
