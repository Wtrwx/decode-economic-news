# Browser News Workflow

Use browser collection only after checking whether a purpose-built connector, official API or CLI can perform the same operation. Prefer the browser when a page needs JavaScript rendering, site search, pagination, an existing signed-in session or visual inspection.

## Collection procedure

1. Read `blogger-news-sites.json` or run `python3 scripts/list_browser_news_sites.py`. The registry separates transcript-confirmed core, secondary and occasional sources; it does not claim access to the blogger's browsing history.
2. Use the available Browser control skill and follow its browser-selection and setup instructions. If the user explicitly names a browser, keep that choice.
3. Search for discovery, then open the original publisher or official page. Do not treat a search-engine snippet as the article's claim.
   Start with Reuters, Bloomberg and Financial Times for international stories because they are the three most frequently cited media in the 186-file corpus. Add the relevant official source and at least one independent source when the claim is material.
4. Record only visible, task-relevant fields: canonical URL, title, publisher, byline, publication time, observation time, access state, capture method and a short excerpt.
5. Use `visible_original_page` only after opening the article page. Use `publisher_index` for a publisher's list page and `search_result` for unverified discovery results.
6. Never inspect or export cookies, local/session storage, passwords, authorization headers or browser profiles.
7. Do not bypass a login, paywall, CAPTCHA, robots restriction or access control. When authentication blocks an explicitly selected browser, ask the user to sign in there.
8. Save the observations as `browser.news.capture/1`, then normalize them with `build_browser_news_source.py` and validate the output before adding it to an evidence pack.

## Corpus-backed site plan

```bash
# Inspect sites explicitly cited in the blogger corpus
python3 scripts/list_browser_news_sites.py

# Build browser discovery queries for the three high-frequency international sources
python3 scripts/list_browser_news_sites.py --tier core --topic 'AI 芯片出口限制' \
  --output work/browser-search-plan.json

# Resolve either English publisher names or Chinese aliases
python3 scripts/list_browser_news_sites.py --publisher 路透 --topic '创新药 FDA'
```

Core means 15 or more transcript files; secondary means repeated citations in at least two files; occasional means one-file evidence. The browser may use an already authorized session to view what the user can lawfully access, but the capture still stores no session material and must mark restricted pages as `login_required` or `paywalled`.

## Capture contract

```json
{
  "schema": "browser.news.capture/1",
  "query": "semiconductor export controls",
  "captured_at": "2026-08-08T12:00:00+00:00",
  "browser_surface": "in-app-browser",
  "pages": [
    {
      "url": "https://publisher.example/article",
      "canonical_url": "https://publisher.example/article",
      "title": "Article title",
      "publisher": "Publisher",
      "byline": "Author",
      "published_at": "2026-08-08T10:00:00+00:00",
      "observed_at": "2026-08-08T12:00:00+00:00",
      "capture_method": "visible_original_page",
      "access_state": "open",
      "visible_text": "Task-relevant visible text"
    }
  ],
  "warnings": []
}
```

The normalizer removes common tracking parameters, deduplicates canonical URLs, truncates excerpts and stores only a SHA-256 for the complete visible text. Browser observation establishes what was displayed, not whether the article's underlying claims are true.
