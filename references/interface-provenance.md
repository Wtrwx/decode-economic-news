# Interface Implementation Provenance

Research date: 2026-08-08. GitHub counts are snapshots and will change.

## Local problem profile

The skill already had reproducible macro, A-share price/mood, forecasting and recommendation code. The missing layer was original-event discovery and normalization: global publisher links, U.S. filings, drug-pipeline records, official release feeds and a deterministic way to compare source direction with market reaction. The implementation must remain standard-library-first, cached, rate-limited and compatible with `evidence.source/1` or `evidence.signal/1`.

## GitHub search path and candidates

Searches used repository, code and issue search for `gdelt-doc-api`, `sec-edgar-downloader`, `clinicaltrials.gov api v2`, `feedparser`, the exact endpoint strings and rate-limit/User-Agent issues.

| Candidate | Snapshot | Evidence inspected | Decision |
|---|---:|---|---|
| [alex9smith/gdelt-doc-api](https://github.com/alex9smith/gdelt-doc-api) | 225 stars, 48 forks, MIT, pushed 2025-04-22 | API client modes, JSON/content-type checks and [error-handling issue #64](https://github.com/alex9smith/gdelt-doc-api/issues/64) | Adapt parameter and error patterns; keep a zero-dependency collector and stricter 5.2-second pacing |
| [jadchaar/sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader) | 712 stars, 165 forks, MIT, pushed 2026-06-22 | submissions/ticker endpoints, 10-request/sec constant, rate-limit tests, [limiter issue #46](https://github.com/jadchaar/sec-edgar-downloader/issues/46) and [official access issue #113](https://github.com/jadchaar/sec-edgar-downloader/issues/113) | Adapt endpoint, CIK and pacing patterns; require an explicit contact User-Agent; fetch metadata rather than bulk documents |
| [akfamily/akshare](https://github.com/akfamily/akshare) | 21,864 stars, 3,425 forks, MIT, pushed 2026-08-07 | Repository scope and Chinese financial endpoint coverage | Avoid adding as a dependency because `a-stock-data` already covers the overlapping A-share portals; use it only as a future endpoint-discovery reference |
| [kurtmckee/feedparser](https://github.com/kurtmckee/feedparser) | 2,408 stars, 370 forks, active 2026-08-03 | Mature general feed parser scope | Avoid a large dependency for five controlled official feeds; implement a narrow RSS/Atom parser with `ElementTree` |
| ClinicalTrials v2 wrappers and skills | Mostly 0–5 stars; several lacked a declared license | Endpoint strings, search parameter examples and simple normalization patterns | Avoid copying young wrappers; implement against the official OpenAPI/data model and test the exact fields used |

No third-party source file was copied into the skill. The collectors reimplement only the narrow request/normalization behavior required by the evidence contract.

## Verification evidence

- Offline unit tests cover GDELT discovery semantics, SEC ticker/filing normalization, ClinicalTrials fields, RSS parsing and positive-news/negative-price contradiction logic.
- Live smoke tests returned fresh ClinicalTrials.gov records and fresh Fed/FDA/EIA feed entries.
- GDELT returned HTTP 429 during the smoke test. The collector surfaced failure rather than returning an empty success; GDELT therefore remains an optional discovery source and never a publication gate.
- SEC live smoke is intentionally not run without a real `SEC_USER_AGENT` containing the caller's contact information.
- Cross-market mapping was checked against official iShares, State Street, Global X, Invesco and Samsung/KODEX product pages on 2026-08-08. Yahoo `query1` returned HTTP 429, while the `query2` chart host returned JSON histories for both `SOXX` and Korean `091160.KS` with a browser User-Agent. The adapter therefore uses `query2`, conservative pacing, cache and explicit low stability.

## Confidence

- High: SEC metadata normalization, official feed parsing and ClinicalTrials v2 core fields.
- Medium: GDELT availability because the public endpoint is heavily throttled even with conservative pacing.
- Low by design: any market-intent inference from one article or one price window; the reaction signal only creates falsifiable research prompts.
- Medium-low: Yahoo chart availability because it is undocumented and may throttle. High: the point-in-time rule that foreign close dates must be strictly earlier than the A-share date in lead tests.
