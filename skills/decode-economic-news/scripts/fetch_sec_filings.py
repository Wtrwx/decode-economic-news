#!/usr/bin/env python3
"""Fetch recent company filings from the official SEC submissions API."""

from __future__ import annotations

import argparse
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from evidence_core import CachedHttpClient, atomic_write_json, normalized_identifier, provider, warnings_from_fetches


TICKER_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def normalize_cik(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if not digits or len(digits) > 10:
        raise ValueError("CIK must contain 1 to 10 digits")
    return digits.zfill(10)


def resolve_ticker(payload: Any, ticker: str) -> str:
    target = ticker.upper().strip()
    if not target:
        raise ValueError("ticker is required")
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        fields = payload.get("fields") or []
        try:
            ticker_index = fields.index("ticker")
            cik_index = fields.index("cik")
        except ValueError as exc:
            raise RuntimeError("SEC ticker mapping fields changed") from exc
        for row in payload["data"]:
            if str(row[ticker_index]).upper() == target:
                return normalize_cik(str(row[cik_index]))
    if isinstance(payload, dict):
        for row in payload.values():
            if isinstance(row, dict) and str(row.get("ticker") or "").upper() == target:
                return normalize_cik(str(row.get("cik_str") or row.get("cik") or ""))
    raise ValueError(f"ticker not found in SEC mapping: {ticker}")


def normalize_filings(
    payload: Any,
    *,
    forms: set[str],
    limit: int,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError("SEC submissions response is not an object")
    recent = (payload.get("filings") or {}).get("recent")
    if not isinstance(recent, dict):
        raise RuntimeError("SEC submissions response does not contain recent filings")
    accessions = recent.get("accessionNumber") or []
    facts: list[dict[str, Any]] = []
    cik_plain = str(payload.get("cik") or "").lstrip("0")
    company = str(payload.get("name") or f"CIK {cik_plain}")

    def column(name: str, index: int, default: Any = None) -> Any:
        values = recent.get(name)
        return values[index] if isinstance(values, list) and index < len(values) else default

    for index, accession in enumerate(accessions):
        form = str(column("form", index, ""))
        if forms and form.upper() not in forms:
            continue
        filing_date = str(column("filingDate", index, ""))
        primary_document = str(column("primaryDocument", index, ""))
        if not form or not filing_date or not primary_document:
            continue
        accession_no_dash = str(accession).replace("-", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/"
            f"{accession_no_dash}/{urllib.parse.quote(primary_document)}"
        )
        fact = {
            "fact_id": f"SEC-{normalized_identifier(str(accession))}",
            "claim": f"{company} filed {form} with the SEC on {filing_date}",
            "period": filing_date,
            "publisher": "U.S. Securities and Exchange Commission",
            "source_url": filing_url,
            "retrieved_at": retrieved_at,
            "company": company,
            "cik": normalize_cik(str(payload.get("cik") or "")),
            "ticker": payload.get("tickers"),
            "exchange": payload.get("exchanges"),
            "form": form,
            "accession_number": accession,
            "report_date": column("reportDate", index),
            "acceptance_datetime": column("acceptanceDateTime", index),
            "primary_document": primary_document,
            "primary_doc_description": column("primaryDocDescription", index),
        }
        facts.append(fact)
        if len(facts) >= limit:
            break
    return facts


def fetch_filings(
    *,
    cik: str = "",
    ticker: str = "",
    forms: list[str] | None = None,
    limit: int = 30,
    user_agent: str,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if not user_agent.strip() or "@" not in user_agent:
        raise RuntimeError("SEC_USER_AGENT is required and should identify an organization plus contact email")
    if bool(cik) == bool(ticker):
        raise ValueError("supply exactly one of cik or ticker")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    client = CachedHttpClient(cache_dir, user_agent=user_agent, default_min_interval=0.12)
    fetches = []
    if ticker:
        mapping, mapping_fetch = client.get_json(TICKER_URL, ttl_seconds=7 * 86400, min_interval_seconds=0.12)
        cik = resolve_ticker(mapping, ticker)
        fetches.append(mapping_fetch)
    cik = normalize_cik(cik)
    submissions_url = SUBMISSIONS_URL.format(cik=cik)
    payload, submissions_fetch = client.get_json(
        submissions_url,
        headers={"Accept-Encoding": "gzip, deflate"},
        ttl_seconds=900,
        min_interval_seconds=0.12,
    )
    fetches.insert(0, submissions_fetch)
    normalized_forms = {item.strip().upper() for item in (forms or []) if item.strip()}
    facts = normalize_filings(
        payload,
        forms=normalized_forms,
        limit=limit,
        retrieved_at=submissions_fetch.retrieved_at,
    )
    if not facts:
        raise RuntimeError("SEC returned no recent filings matching the requested forms")
    warnings = warnings_from_fetches(fetches)
    warnings.append("A filing record proves submission and form metadata; interpret the filing text separately before inferring business impact.")
    return {
        "schema": "evidence.source/1",
        "provider": provider("sec-edgar", "U.S. Securities and Exchange Commission", 0.99, 0.98),
        "retrieval": submissions_fetch.metadata(),
        "supporting_retrievals": [item.metadata() for item in fetches[1:]],
        "query": {"cik": cik, "ticker": ticker.upper(), "forms": sorted(normalized_forms), "limit": limit},
        "facts": facts,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cik", default="")
    group.add_argument("--ticker", default="")
    parser.add_argument("--form", action="append", default=[])
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT", ""))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = fetch_filings(
        cik=args.cik,
        ticker=args.ticker,
        forms=args.form,
        limit=args.limit,
        user_agent=args.user_agent,
        cache_dir=args.cache_dir,
    )
    atomic_write_json(args.output, result)
    print(f"wrote {len(result['facts'])} SEC filing facts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
