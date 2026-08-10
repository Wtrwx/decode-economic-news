# Blogger-Logic Source Catalog

Use this catalog to choose the source layer before searching. Coverage means an implemented collector or a documented handoff, not guaranteed access to every historical document.

| Layer | Implemented source | Role | Important limit |
|---|---|---|---|
| Global news discovery | GDELT DOC 2.0 | Find original publisher URLs, languages and countries | Index coverage varies; discovery is not verification |
| Browser-observed news | In-app Browser or connected browser | Render JavaScript pages, use site search and existing signed-in sessions | Observation is not verification; never export session data or bypass access controls |
| Blogger-cited media registry | Reuters, Bloomberg, Financial Times plus 10 lower-frequency sites | Build site-scoped browser searches from corpus evidence | Citation frequency is not browsing history, authority or truth; see `blogger-news-sites.json` |
| Official press text | Fed, FDA and EIA RSS/Atom presets | Detect original releases before media interpretation | Feed item is an index; open the linked release for exact wording |
| U.S. company disclosure | SEC EDGAR submissions | Form, date, accession and primary-document URL | Filing metadata is not a summary of business impact |
| Drug pipeline | ClinicalTrials.gov API v2 | Status, phase, sponsor, condition and intervention | Sponsor-submitted registry data can lag and is not approval evidence |
| China company disclosure | CNINFO | Statutory A-share announcements | Endpoint is public but less stable than documented APIs |
| International macro | World Bank, FRED, Eurostat | Dated official time series and vintages | FRED requires a key; definitions differ across publishers |
| A-share price and mood | Tencent, Eastmoney and existing market scripts | Price history, breadth, limit ecology and screening | Public portal endpoints are auxiliary and may throttle |
| U.S./Korean peer prices | Yahoo Finance chart plus official ETF/issuer definitions | Same-sector relative returns and prior-close lead/lag research | Chart endpoint is undocumented auxiliary data; mappings are analogs, not causal proof |

## Covered through the companion `a-stock-data` skill

Do not duplicate its Eastmoney, Tonghuashun, Tencent, CNINFO, iwencai, mootdx and Sina adapters. Use it for A-share research reports, portal news, 7x24 news, fund flow, margin financing, block trades, shareholder counts, financial statements, Dragon-Tiger list, limit-up ecology, interaction Q&A and popularity lists. Convert material results into the evidence contract before causal analysis.

## Remaining gaps versus a professional news workflow

- Reuters, Bloomberg and Financial Times full text: retain lawful links and user-provided excerpts; do not bypass paywalls or republish protected articles. GDELT can help discover some original URLs but is not a replacement for licensed terminals.
- China official macro/policy releases: NBS, PBOC, MOF, MOFCOM, Customs, NDRC, MIIT and State Council do not expose one uniform, documented API. Prefer their original HTML/XLS/PDF releases, snapshot the raw file and add a source-specific adapter only after endpoint stability is measured.
- Exchange order books and institutional positioning: public daily data cannot reconstruct full intraday positioning. Use licensed tick/order-book data when the claim depends on microstructure.
- Expectations data: consensus forecasts, options-implied distributions and analyst estimate revisions often require licensed providers. Do not infer exact expected probability from one price move.
- Supply-chain and alternative data: shipping, customs microdata, app usage, card spending and satellite data need separate licensing and methodology checks.

## Collection order for blogger-style analysis

1. Route by event origin. Start with the official release for scheduled/statutory events; start with Reuters/Bloomberg/FT for exclusives, rumors, stakeholder reactions or unexplained price moves, then seek official corroboration.
2. Use GDELT, portal news or browser search to discover both event leads and competing framings. Open the original page before upgrading a browser result to an observation, and record an explicit outcome for every planned core publisher.
3. Classify event direction and stage: rumor, proposal, draft, announced, approved, effective, enforced or result.
4. Compare pre-event positioning and 1/3/5-day relative reaction with `compute_news_reaction.py`.
5. Treat a direction/reaction contradiction as a research question: priced in, implementation doubt, weaker-than-expected detail, hidden constraint or liquidity reversal.
6. Verify the best explanation using a second independent source or a falsifiable next observation.

## Transcript-confirmed media priority

- Core: Reuters (26/186 transcript files), Bloomberg (26/186) and Financial Times (15/186).
- Secondary: Lianhe Zaobao (3 files), Xinhua (2) and Cailian Press (2).
- Occasional: The Wall Street Journal, The New York Times, Nikkei, Kyodo News, CCTV News, Yicai and Economic Daily News Taiwan (1 file each).

These are normalized literal citations in the supplied corpus. They show that the blogger cited a publisher at least once; they do not prove a direct subscription, habitual browsing, exclusive reliance or correctness. Use `list_browser_news_sites.py` to produce site-scoped discovery queries, then open and record the original page.
