# NewsNook API Workflow

Use NewsNook's public production API as the default news transport. NewsNook is a reader and proxy, not the publisher: preserve the upstream publisher and original article URL on every fact, and grade authority by the upstream publisher rather than by NewsNook.

## Endpoints and configuration

- Default base URL: `https://news.aizeek.com`
- Feed endpoint: `GET /api/feed/{source_id}`; optional `?page=N` is supported for sources with upstream paging.
- Page proxy: `GET /api/page?url={encoded_original_url}`. Use it only for a specific original page selected from the feed results; it returns raw upstream HTML or JSON, not a verified summary.
- Source registry and implementation: [t59688/newsnook](https://github.com/t59688/newsnook), Apache-2.0.

Set `NEWSNOOK_API_BASE` at runtime to use a reviewed self-hosted deployment. The base URL must be HTTP(S), must not contain credentials, and must not be written with secrets into evidence artifacts.

## Default collection

```bash
python3 scripts/fetch_newsnook_news.py --list-presets
python3 scripts/fetch_newsnook_news.py --preset finance \
  --query 'semiconductor export controls' \
  --output work/newsnook-news.json
python3 scripts/build_news_coverage.py --newsnook work/newsnook-news.json \
  --output work/news-coverage.json
```

Use `--source` repeatedly when a request needs an explicit source set. If any `--source` is supplied, it replaces the preset. The collector stores an outcome for every selected source, raw-response checksums, original links, parser type, matched-item count and failures. A nonzero exit means the primary gate found no usable relevant item or no successful source; the output file still records the failure and should drive the fallback.

## Preset routing

- `finance`: default mixed China/international market scan.
- `china-finance`: A-share, domestic business and China market events.
- `international-business`: macro, trade, geopolitics and overseas company events.
- `technology`: technology and semiconductor industry stories.
- `ai`: AI labs, projects and specialist media.

Read [newsnook-api-sources.json](newsnook-api-sources.json) when choosing or adding source IDs. It is a reviewed snapshot, not a promise that every upstream remains available. Unknown or structurally changed responses must fail explicitly; do not silently reinterpret HTML error pages as news.

## Evidence semantics

- A NewsNook feed/API item proves that the attributed publisher endpoint returned the observed title and excerpt at retrieval time.
- Google News entries remain `discovery_lead` until the original publisher or an independent authoritative source is opened.
- Items with no usable excerpt are metadata-only and do not count as substantive support.
- Media reports can support attributed statements, but central, surprising or numerical claims still require the original release or a second independent source.
- NewsNook's `/api/page` is an API transport fallback before browser use; raw HTML still needs careful extraction and source attribution.

## Browser fallback conditions

Use the browser only when at least one of these applies:

1. The NewsNook collection gate fails because the API is unavailable, selected sources fail, or no relevant item is found.
2. The selected API item points to a JavaScript-only, access-controlled or malformed original page that cannot be checked through lawful API/HTTP access.
3. A material claim requires visible-page confirmation that the feed excerpt and available official sources cannot provide.
4. The user explicitly requests browser collection or asks to use an existing signed-in browser session.

When fallback is needed, read [browser-news-workflow.md](browser-news-workflow.md), record explicit publisher outcomes, and rebuild coverage with both `--newsnook` and the browser plan/capture. Do not run a broad browser radar merely because the topic is current.
