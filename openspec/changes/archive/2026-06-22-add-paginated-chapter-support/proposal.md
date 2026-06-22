## Why

A number of Chinese novel sites (e.g. `shuhaige.net`, `69shuba.com`) split
long chapters into multiple sub-pages that the reader has to navigate with a
"next page" / `>` link. Today the crawler treats each chapter URL as a single
page — the result is a truncated chapter that ends mid-sentence, then the
pipeline still ships a "complete" book to the EPUB. This change teaches the
crawler to detect, fetch, and stitch together every sub-page of a chapter
before it hands the text to the translator.

## What Changes

- Add three new optional fields to `CrawlConfig` (and `SourcePreset`):
  - `next_page_selector` — CSS selector for the explicit "next page" link
    (e.g. `a#pager_next`, `a.next`, `.bottem1 a.next`).
  - `next_page_url_pattern` — regex fallback for sites that load the next
    page via JavaScript and don't expose a navigable `<a>` tag. The regex
    must contain one capturing group; the crawler substitutes the group
    with a counter (`_2`, `_3`, ...) and re-fetches until the pattern no
    longer matches.
  - `max_pages_per_chapter` — safety cap to prevent infinite loops
    (default `10`).
- Teach `HttpCrawler.fetch_chapter` and `Crawl4AICrawler.fetch_chapter`
  to follow sub-pages and concatenate their text in order, removing the
  repeated chapter title that most sites render at the top of every page.
- Add a new `shuhaige` site preset in `novel2epub/sources.yaml`
  demonstrating `next_page_selector: "a#pager_next"` so users have a
  working example.
- Add a `_MD_LINK`-aware dedupe step so we don't accidentally re-fetch a
  page we've already pulled (e.g. when "next" points back to itself).
- **BREAKING** for anyone reading `CrawlConfig` programmatically: three
  new fields are appended. YAML configs that omit them continue to work
  (defaults), but code that instantiates `CrawlConfig(...)` positionally
  must switch to keyword arguments.

## Capabilities

### New Capabilities

- `chapter-pagination`: The crawler MUST be able to detect, fetch, and
  concatenate multi-page chapters using either a CSS selector for the
  next-page link or a URL-pattern fallback. Stops on missing link,
  duplicate content, or page-count cap. All three engines (`http`,
  `crawl4ai`, `firecrawl`) expose the same configuration surface.

### Modified Capabilities

_None._ No existing spec is being changed; this is a pure addition. The
Crawler protocol and `CrawlConfig` gain new optional fields, but their
**existing** requirements (return text, return `TocResult`, etc.) are
unchanged.

## Impact

- `novel2epub/config.py` — three new optional fields on `CrawlConfig`.
- `novel2epub/sources.py` — mirror the three fields on `SourcePreset` so
  the Web UI / YAML preset loader round-trips them.
- `novel2epub/crawler.py` — new helper `_fetch_chapter_with_pagination`
  used by `HttpCrawler.fetch_chapter` and `Crawl4AICrawler.fetch_chapter`.
  `FirecrawlCrawler.fetch_chapter` gets the same treatment (the API
  already returns the rendered page, so the helper is shared).
- `novel2epub/sources.yaml` — new `shuhaige` preset.
- `tests/test_crawler_meta.py` (or new `tests/test_chapter_pagination.py`)
  — fixture-based tests covering: no pagination, CSS-selector pagination,
  URL-pattern pagination, dedupe of repeated title, max-pages cap, and
  stop-on-duplicate.
- `configs/novel.yaml` consumers — no change required; new fields are
  optional.
