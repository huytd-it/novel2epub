## 1. Extend configuration model

- [ ] 1.1 Add `next_page_selector: str = ""`,
      `next_page_url_pattern: str = ""`, and
      `max_pages_per_chapter: int = 10` to `CrawlConfig` in
      `novel2epub/config.py`
- [ ] 1.2 Add a `__post_init__` to `CrawlConfig` that raises `ValueError`
      if `next_page_url_pattern` is set and does not contain exactly one
      capturing group
- [ ] 1.3 Mirror the three fields on `SourcePreset` in
      `novel2epub/sources.py` and ensure they are part of
      `crawl_overrides()` and `_FIELD_NAMES` so YAML round-trip works
- [ ] 1.4 Add a unit test asserting that omitting the new fields keeps
      the existing defaults and that an invalid pattern raises
      `ValueError` at construction time

## 2. Implement pagination helper

- [ ] 2.1 Add `fetch_chapter_paginated(...)` in `novel2epub/crawler.py`
      that takes three closures: `fetch_html`, `extract_text`, and
      `next_page_url`
- [ ] 2.2 Implement stop conditions: missing link, already-visited URL,
      duplicate trimmed text, and `max_pages_per_chapter` reached
- [ ] 2.3 Implement the title-strip heuristic: drop the first
      non-blank line of a sub-page when it matches the first non-blank
      line of page 1
- [ ] 2.4 Implement the URL-pattern fallback: substitute the regex's
      capturing group with an incrementing suffix (`_2`, `_3`, ...)
      until the pattern fails to match

## 3. Wire the helper into the three crawlers

- [ ] 3.1 Update `HttpCrawler.fetch_chapter` to delegate to
      `fetch_chapter_paginated`, supplying closures that use
      `_get_soup`, `_extract_text`, and a `next_page_url` resolver
      that reads `cfg.next_page_selector` or applies
      `cfg.next_page_url_pattern`
- [ ] 3.2 Update `Crawl4AICrawler.fetch_chapter` with the same
      delegation, using `_arun` and `_markdown` + `_clean` as the
      extract closure
- [ ] 3.3 Update `FirecrawlCrawler.fetch_chapter` with the same
      delegation, using `_scrape`
- [ ] 3.4 Verify the existing `Crawler` protocol and the
      `pipeline.fetch_chapter` call site are unchanged

## 4. Ship the shuhaige preset

- [ ] 4.1 Add a `shuhaige:` entry to `novel2epub/sources.yaml` with
      `engine: http`, `content_selector: "#content"`, and
      `next_page_selector: "a#pager_next"`
- [ ] 4.2 Run `load_presets()` and confirm the new preset round-trips
      through YAML load and save without losing fields

## 5. Tests

- [ ] 5.1 Add `tests/test_chapter_pagination.py` with fixtures that
      simulate a three-page chapter using `next_page_selector`
- [ ] 5.2 Add a test for the URL-pattern fallback that monkey-patches
      `_get_soup` to return a known sequence of HTML responses
- [ ] 5.3 Add a test that asserts duplicate-content detection stops
      the loop after the first duplicate
- [ ] 5.4 Add a test that asserts `max_pages_per_chapter=3` caps the
      loop on a five-page fixture
- [ ] 5.5 Add a test that asserts the repeated title on the first
      line of a sub-page is stripped
- [ ] 5.6 Add a test that asserts `CrawlConfig` raises `ValueError` on
      a `next_page_url_pattern` with zero or two capturing groups
- [ ] 5.7 Run `pytest tests/ -v` and confirm the full suite still
      passes

## 6. Documentation and smoke test

- [ ] 6.1 Update `AGENTS.md` (or a new `docs/pagination.md`) with a
      short note explaining the three new fields and the shuhaige
      preset, plus a link to the shuhaige.net test URL the user
      originally reported
- [ ] 6.2 Run a manual smoke test against
      `https://www.shuhaige.net/17619/55331876.html` using the new
      preset and confirm the returned text covers all three sub-pages
