#!/usr/bin/env python3
"""Fetch and normalize official ClinicalTrials.gov API v2 study records."""

from __future__ import annotations

import argparse
import urllib.parse
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, atomic_write_json, normalized_identifier, provider, warnings_from_fetches


BASE_URL = "https://clinicaltrials.gov/api/v2/studies"


def _module(study: dict[str, Any], name: str) -> dict[str, Any]:
    value = (study.get("protocolSection") or {}).get(name)
    return value if isinstance(value, dict) else {}


def normalize_studies(studies: Any, retrieved_at: str) -> list[dict[str, Any]]:
    if not isinstance(studies, list):
        raise RuntimeError("ClinicalTrials.gov response does not contain studies")
    facts: list[dict[str, Any]] = []
    for study in studies:
        if not isinstance(study, dict):
            continue
        identification = _module(study, "identificationModule")
        status = _module(study, "statusModule")
        sponsor = _module(study, "sponsorCollaboratorsModule")
        conditions = _module(study, "conditionsModule")
        design = _module(study, "designModule")
        interventions = _module(study, "armsInterventionsModule")
        nct_id = str(identification.get("nctId") or "").strip()
        title = str(identification.get("briefTitle") or identification.get("officialTitle") or "").strip()
        if not nct_id or not title:
            continue
        overall_status = str(status.get("overallStatus") or "UNKNOWN")
        last_update = str((status.get("lastUpdatePostDateStruct") or {}).get("date") or status.get("statusVerifiedDate") or "")
        period = last_update or retrieved_at[:10]
        lead_sponsor = str((sponsor.get("leadSponsor") or {}).get("name") or "")
        intervention_names = [
            str(item.get("name"))
            for item in interventions.get("interventions") or []
            if isinstance(item, dict) and item.get("name")
        ]
        facts.append(
            {
                "fact_id": f"CTGOV-{normalized_identifier(nct_id)}-{normalized_identifier(period)}",
                "claim": f"ClinicalTrials.gov lists {nct_id} ({title}) with status {overall_status}",
                "period": period,
                "publisher": "U.S. National Library of Medicine / ClinicalTrials.gov",
                "source_url": f"https://clinicaltrials.gov/study/{urllib.parse.quote(nct_id)}",
                "retrieved_at": retrieved_at,
                "nct_id": nct_id,
                "title": title,
                "official_title": identification.get("officialTitle"),
                "overall_status": overall_status,
                "last_known_status": status.get("lastKnownStatus"),
                "status_verified_date": status.get("statusVerifiedDate"),
                "last_update_posted": last_update,
                "start_date": (status.get("startDateStruct") or {}).get("date"),
                "primary_completion_date": (status.get("primaryCompletionDateStruct") or {}).get("date"),
                "completion_date": (status.get("completionDateStruct") or {}).get("date"),
                "lead_sponsor": lead_sponsor,
                "conditions": conditions.get("conditions") or [],
                "phases": design.get("phases") or [],
                "study_type": design.get("studyType"),
                "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
                "interventions": intervention_names,
                "has_results": bool(study.get("hasResults")),
            }
        )
    return facts


def fetch_trials(
    *,
    term: str = "",
    condition: str = "",
    intervention: str = "",
    status: str = "",
    page_size: int = 100,
    max_pages: int = 1,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if not any((term.strip(), condition.strip(), intervention.strip())):
        raise ValueError("at least one of term, condition or intervention is required")
    if not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and 1000")
    if not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be between 1 and 20")
    params = {"format": "json", "pageSize": str(page_size)}
    if term.strip():
        params["query.term"] = term.strip()
    if condition.strip():
        params["query.cond"] = condition.strip()
    if intervention.strip():
        params["query.intr"] = intervention.strip()
    if status.strip():
        params["filter.overallStatus"] = status.strip().upper()
    client = CachedHttpClient(cache_dir, default_min_interval=0.25)
    fetches = []
    all_facts: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(max_pages):
        page_params = dict(params)
        if page_token:
            page_params["pageToken"] = page_token
        url = f"{BASE_URL}?{urllib.parse.urlencode(page_params)}"
        payload, fetched = client.get_json(url, ttl_seconds=3600, min_interval_seconds=0.25)
        fetches.append(fetched)
        if not isinstance(payload, dict):
            raise RuntimeError("ClinicalTrials.gov response is not an object")
        all_facts.extend(normalize_studies(payload.get("studies"), fetched.retrieved_at))
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            break
    if not all_facts:
        raise RuntimeError("ClinicalTrials.gov returned no usable studies")
    warnings = warnings_from_fetches(fetches)
    warnings.extend(
        [
            "Registry status and dates are submitted by study sponsors and may lag real-world developments.",
            "Trial registration or completion does not imply efficacy, approval, commercial success or investment merit.",
        ]
    )
    return {
        "schema": "evidence.source/1",
        "provider": provider("clinicaltrials-gov", "ClinicalTrials.gov", 0.97, 0.96),
        "retrieval": fetches[0].metadata(),
        "supporting_retrievals": [item.metadata() for item in fetches[1:]],
        "query": {**params, "maxPages": max_pages},
        "facts": all_facts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", default="")
    parser.add_argument("--condition", default="")
    parser.add_argument("--intervention", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch_trials(
        term=args.term,
        condition=args.condition,
        intervention=args.intervention,
        status=args.status,
        page_size=args.page_size,
        max_pages=args.max_pages,
        cache_dir=args.cache_dir,
    )
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} trial facts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
