# Browser News Fallback Workflow

The browser is a fallback after NewsNook API and ordinary official/API access. Do not run a broad browser radar merely because a topic is current. Use it when the NewsNook collection gate fails, no relevant API item exists, a selected original page requires JavaScript or a lawful signed-in session, a material claim still needs visible-page confirmation, or the user explicitly asks for browser collection.

## Collection procedure

1. Run `fetch_newsnook_news.py` and `build_news_coverage.py --newsnook ...` first. Read [newsnook-api-workflow.md](newsnook-api-workflow.md) for the primary path.
2. Identify the exact missing publisher, claim or page. Read `blogger-news-sites.json` or run `list_browser_news_sites.py` only to build the smallest relevant fallback plan.
3. Use the available Browser control skill and follow its browser-selection and setup instructions. If the user explicitly names a browser, keep that choice.
4. Search for discovery, then open the original publisher or official page. A search-engine snippet is not the article's claim. Every planned fallback publisher must end with `opened_original`, `no_relevant_result`, `paywalled`, `login_required`, `search_results_only`, or `failed`; never silently omit an attempted source.
5. Record only visible, task-relevant fields: canonical URL, title, publisher, byline, publication time, observation time, access state, capture method and a short excerpt.
6. Use `visible_original_page` only after opening the article page. Use `publisher_index` for a publisher's list page and `search_result` for unverified discovery results.
7. Never inspect or export cookies, local/session storage, passwords, authorization headers or browser profiles. Do not bypass a login, paywall, CAPTCHA, robots restriction or access control.
8. Save the observations and explicit attempts as `browser.news.capture/1`, normalize pages with `build_browser_news_source.py`, then rebuild `news.collection.coverage/2` with the original NewsNook file plus `--plan` and `--capture`.

## Fallback commands

```bash
python3 scripts/list_browser_news_sites.py --publisher 路透 \
  --topic 'AI 芯片出口限制' --output work/browser-search-plan.json

python3 scripts/build_browser_news_source.py work/browser-capture.json \
  --output work/browser-news.json

python3 scripts/build_news_coverage.py --newsnook work/newsnook-news.json \
  --plan work/browser-search-plan.json --capture work/browser-capture.json \
  --output work/news-coverage.json
```

Use `--tier core` only when the API gap genuinely spans all three core international publishers. A targeted one-publisher fallback is normally sufficient for a specific missing lead. The browser may use an already authorized session to view what the user can lawfully access, but the capture stores no session material and marks restricted pages explicitly.

## Capture contract

```json
{
  "schema": "browser.news.capture/1",
  "query": "semiconductor export controls",
  "captured_at": "2026-08-20T12:00:00+00:00",
  "browser_surface": "in-app-browser",
  "attempts": [
    {"site_id": "reuters", "outcome": "opened_original"}
  ],
  "pages": [
    {
      "url": "https://publisher.example/article",
      "canonical_url": "https://publisher.example/article",
      "title": "Article title",
      "publisher": "Publisher",
      "byline": "Author",
      "published_at": "2026-08-20T10:00:00+00:00",
      "observed_at": "2026-08-20T12:00:00+00:00",
      "capture_method": "visible_original_page",
      "access_state": "open",
      "visible_text": "Task-relevant visible text"
    }
  ],
  "warnings": []
}
```

The normalizer removes common tracking parameters, deduplicates canonical URLs, truncates excerpts and stores only a SHA-256 for the complete visible text. Browser observation establishes what was displayed, not whether the article's underlying claims are true.
