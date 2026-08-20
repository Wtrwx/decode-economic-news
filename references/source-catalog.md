# Blogger-Logic Source Catalog

Use this catalog to choose the source layer before searching. Coverage means an implemented collector or a documented handoff, not guaranteed access to every historical document.

| Layer | Implemented source | Role | Important limit |
|---|---|---|---|
| Primary news transport | NewsNook public API (`/api/feed/{source_id}`) | Collect publisher-attributed feeds, market flashes and original links with explicit per-source outcomes | NewsNook is a reader/proxy, not the publisher; its API returns raw upstream payloads and can inherit upstream failures |
| Global discovery supplement | GDELT DOC 2.0 | Find additional original publisher URLs, languages and countries | Index coverage varies; discovery is not verification |
| Browser fallback | In-app Browser or connected browser | Fill a documented API gap, render JavaScript pages or use an existing lawful signed-in session | Use only after the API/HTTP path is insufficient or when the user explicitly requests it; never export session data or bypass access controls |
| Browser fallback registry | Reuters, Bloomberg, Financial Times plus 10 lower-frequency sites | Build targeted site-scoped fallback searches from corpus evidence | Citation frequency is not browsing history, authority or truth; see `blogger-news-sites.json` |
| Official press text | Fed, FDA and EIA RSS/Atom presets | Detect original releases before media interpretation | Feed item is an index; open the linked release for exact wording |
| U.S. company disclosure | SEC EDGAR submissions | Form, date, accession and primary-document URL | Filing metadata is not a summary of business impact |
| Drug pipeline | ClinicalTrials.gov API v2 | Status, phase, sponsor, condition and intervention | Sponsor-submitted registry data can lag and is not approval evidence |
| China company disclosure | CNINFO | Statutory A-share announcements | Endpoint is public but less stable than documented APIs |
| International macro | World Bank, FRED, Eurostat | Dated official time series and vintages | FRED requires a key; definitions differ across publishers |
| A-share price and mood | Tencent, Eastmoney and existing market scripts | Price history, breadth, limit ecology and screening | Public portal endpoints are auxiliary and may throttle |
| U.S./Korean peer prices | Yahoo Finance chart plus official ETF/issuer definitions | Same-sector relative returns and prior-close lead/lag research | Chart endpoint is undocumented auxiliary data; mappings are analogs, not causal proof |

## Covered through the companion `a-stock-data` skill

Use NewsNook as the default transport for current news feeds and market flashes. Use `a-stock-data` for A-share research reports, quotes, fundamentals, announcements, fund flow, margin financing, block trades, shareholder counts, financial statements, Dragon-Tiger list, limit-up ecology, interaction Q&A and popularity lists, and as an independent portal corroboration layer when needed. Do not refetch the same portal endpoint redundantly unless comparing transport health or corroborating a material claim. Convert material results into the evidence contract before causal analysis.

## Remaining gaps versus a professional news workflow

- Reuters, Bloomberg and Financial Times full text: retain lawful links and user-provided excerpts; do not bypass paywalls or republish protected articles. NewsNook/Google News/GDELT can surface links but do not replace licensed terminals.
- China official macro/policy releases: NBS, PBOC, MOF, MOFCOM, Customs, NDRC, MIIT and State Council do not expose one uniform, documented API. Prefer their original HTML/XLS/PDF releases, snapshot the raw file and add a source-specific adapter only after endpoint stability is measured.
- Exchange order books and institutional positioning: public daily data cannot reconstruct full intraday positioning. Use licensed tick/order-book data when the claim depends on microstructure.
- Expectations data: consensus forecasts, options-implied distributions and analyst estimate revisions often require licensed providers. Do not infer exact expected probability from one price move.
- Supply-chain and alternative data: shipping, customs microdata, app usage, card spending and satellite data need separate licensing and methodology checks.

## Collection order for blogger-style analysis

1. Route by event origin. Start with the official release for scheduled/statutory events. For unscheduled news, exclusives, rumors, stakeholder reactions or unexplained price moves, query the relevant NewsNook API preset first and retain every selected source outcome.
2. Use NewsNook items, GDELT or portal news to discover event leads and competing framings. Open the original or an authoritative corroborating source before treating a central claim as verified. Use a targeted browser fallback only when the primary API gate fails or lawful HTTP/API access cannot establish the needed observation.
3. Classify event direction and stage: rumor, proposal, draft, announced, approved, effective, enforced or result.
4. Compare pre-event positioning and 1/3/5-day relative reaction with `compute_news_reaction.py`.
5. Treat a direction/reaction contradiction as a research question: priced in, implementation doubt, weaker-than-expected detail, hidden constraint or liquidity reversal.
6. Verify the best explanation using a second independent source or a falsifiable next observation.

## Transcript-confirmed media priority

- Core: Reuters (26/186 transcript files), Bloomberg (26/186) and Financial Times (15/186).
- Secondary: Lianhe Zaobao (3 files), Xinhua (2) and Cailian Press (2).
- Occasional: The Wall Street Journal, The New York Times, Nikkei, Kyodo News, CCTV News, Yicai and Economic Daily News Taiwan (1 file each).

These are normalized literal citations in the supplied corpus. They show that the blogger cited a publisher at least once; they do not prove a direct subscription, habitual browsing, exclusive reliance or correctness. Use them to target a browser fallback after NewsNook/API collection identifies a gap, then open and record the original page.
