# Source and Stability Policy

## Two-axis grading

Grade publisher authority and endpoint stability separately.

| Source kind | Authority | Endpoint stability | Use |
|---|---:|---:|---|
| Official documented API | 0.9–1.0 | 0.9–1.0 | Primary quantitative evidence |
| Official release, filing, XLS/PDF | 0.9–1.0 | 0.6–0.9 | Primary evidence; snapshot raw file |
| Exchange or statutory disclosure platform | 0.9–1.0 | 0.7–0.9 | Company and market disclosure |
| Public market portal | 0.5–0.8 | 0.4–0.8 | Real-time/auxiliary data; corroborate |
| Media report | 0.4–0.8 | 0.6–0.9 | Discovery and attributed reporting |
| Social/anonymous claim | 0.0–0.3 | variable | Lead only; never sole evidence |

## Preferred sources

- International macro: FRED/ALFRED, World Bank, Eurostat, OECD and the publishing central bank/statistics agency.
- China macro: National Bureau of Statistics, People's Bank of China, Ministry of Finance, Ministry of Commerce and General Administration of Customs releases.
- Listed companies: exchange filings and CNINFO before portals or media.
- A-share real time: use the public market adapters as auxiliary sources; retain endpoint warnings and cached snapshots.
- U.S./Korean peer prices: use official exchange/issuer definitions for what a proxy represents. The bundled Yahoo chart adapter is auxiliary and undocumented; cache it, disclose 429/gaps and corroborate material prices.

## Fetch rules

- Set a finite timeout and retry only connection failures, 429 and 5xx responses.
- Do not retry ordinary 4xx errors except 408/429.
- Apply per-host spacing and never concurrently hammer rate-limited portals.
- Cache raw bytes before normalization.
- Store retrieval timestamp, safe URL, HTTP metadata and SHA-256.
- Mark cache fallback as `stale`, not `fresh`.
- Validate schema and minimum row count. An empty list is not automatically valid.
- Preserve data vintages when the source supports revisions.
- Inject proxy credentials through environment variables or a secret manager. Never write proxy URLs with user information to source files, command-line arguments, cache metadata or evidence documents.
- A proxy changes network routing, not source authority. Do not use it to bypass authentication, paywalls, access controls or publisher terms.
- Prefer an API or connector for structured official facts. Independently run the browser core-media radar for current international/cross-market outlooks, exclusives, rumors, stakeholder reactions and unexplained price moves; it is complementary evidence, not a fallback. Record explicit negative and access-restricted outcomes.
- Never export cookies, browser storage, passwords, authorization headers or profiles. A browser-visible page proves only what was displayed at capture time.

## Corroboration

Require a second independent source when a fact is surprising, central to the conclusion, or inconsistent with historical scale. Do not count syndicated copies as independent sources.

## Failure behavior

Return `fresh`, `cached`, `stale`, `degraded`, `failed`, or `skipped`. Include a warning that a writer can quote directly. Never silently substitute a different indicator or unit.
