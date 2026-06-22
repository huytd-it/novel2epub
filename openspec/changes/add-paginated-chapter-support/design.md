## Context

Today every concrete crawler (`HttpCrawler`, `Crawl4AICrawler`,
`FirecrawlCrawler`) implements `fetch_chapter(ch: Chapter) -> str` as a
single HTTP request. The chapter text is then handed straight to the
translator, which has no idea that the site actually split the chapter
into N sub-pages. The result on sites like `shuhaige.net` is an EPUB
where every "long" chapter is truncated to whatever the site put on page
1.

The crawler already has all the wiring needed to fetch a URL and extract
text from a CSS-selected node; the only missing piece is **looping**
through a chain of URLs and **stitching** their bodies into a single
string. The site preset system (`SourcePreset` + `sources.yaml`) and
`CrawlConfig` are the two natural extension points for configuration.

Stakeholders: end users (a complete, non-truncated EPUB), maintainers
(site presets become more expressive, fewer one-off bug reports), and the
pipeline (no API change — it still calls `fetch_chapter` once per
`Chapter`).

## Goals / Non-Goals

**Goals:**

- Add `next_page_selector` (CSS), `next_page_url_pattern` (regex), and
  `max_pages_per_chapter` (int) to `CrawlConfig` and `SourcePreset`.
- Provide a single, shared helper that the three concrete crawlers
  delegate to. The helper owns the loop, the dedupe check, the title
  strip, and the cap.
- All three engines behave identically for the same configuration.
- Ship a working `shuhaige` preset so the feature has a real-world
  example on day one.
- New tests cover the loop, the dedupe, the cap, the title strip, and
  the regex-fallback path.

**Non-Goals:**

- Generalised "infinite scroll" or JS-driven pagination that requires
  clicking a button to reveal more content. That is a different problem
  (it needs `js_code` execution, not URL following) and is out of
  scope.
- Re-translating already-translated sub-pages — translation caching
  belongs to the translator, not the crawler.
- Changing the public `Crawler` protocol. The existing
  `fetch_chapter(ch) -> str` signature is preserved.
- Backfilling `Pipeline` or the Web UI. They already treat
  `fetch_chapter` as a black box; the change is invisible to them.

## Decisions

### Decision 1: One helper, three thin wrappers

Add a module-level function in `novel2epub/crawler.py`:

```python
def fetch_chapter_paginated(
    crawler: "Crawler",
    ch: Chapter,
    *,
    fetch_html,        # (url) -> (soup_or_None, html_text) — engine-specific
    extract_text,      # (soup) -> str
    next_page_url,     # (current_url, html_text) -> str | None
) -> str:
    ...
```

Each engine supplies a 5-line closure that knows how to turn a URL into
its native response object and how to call the engine's own
`_extract_text` / `_clean` / `_get_soup` helpers. The pagination loop
itself lives in one place and is unit-testable without hitting the
network.

**Why not just put the loop in each crawler?** Three copies of the same
state machine (URL queue, dedupe set, page counter, duplicate-content
detector) is a maintenance hazard. The duplication would have made the
"all engines share the same pagination contract" spec requirement
fragile.

**Why a function, not a mixin or a base class?** The three crawlers
share very little besides the protocol; a base class would force
artificial inheritance. A free function that takes the three
engine-specific closures is the smallest change that still keeps the
behaviour unified.

### Decision 2: Stop conditions

The loop terminates on **any** of:

1. `next_page_url(current_url, html)` returns `None` — selector did not
   match, or pattern did not apply, or the link points to a
   `javascript:` URL.
2. The next URL has already been visited in this chapter.
3. The newly fetched page's trimmed text is identical (after title
   stripping) to one of the previously fetched pages.
4. The page count reaches `max_pages_per_chapter`.

Conditions 2 and 3 are belt-and-braces: 2 catches the dumb bug where
`a.next` points back at the same page, 3 catches a site that re-renders
the same content on every URL even when the URL changes (some CMS
behaviours). Either alone would be enough; having both means a
misconfigured preset fails fast without spamming the server.

### Decision 3: Title strip heuristic

We strip the first non-blank line of a sub-page **iff** it equals the
first non-blank line of page 1 (case-sensitive, whitespace-trimmed).
That is enough for the sites we have seen (`shuhaige`, `69shuba`,
generic WordPress paginated posts) and avoids pulling in a fuzzy
comparison that would be slow and hard to test.

### Decision 4: URL-pattern fallback

The regex must contain exactly one capturing group. We validate this in
`CrawlConfig.__post_init__` and raise `ValueError` early — the spec
requires this so a misconfigured preset fails at load time, not at
runtime during a 5 000-chapter crawl.

We start the counter at `2` (not `1`) because the input URL **is** page
1. We never re-fetch page 1.

### Decision 5: Where the configuration lives

`CrawlConfig` gets the three new fields. `SourcePreset` mirrors them so
the Web UI / YAML preset loader keeps working. `novel2epub/config.py`'s
`load_config` needs no change — it uses `CrawlConfig(**crawl_raw)` and
the new fields default to safe values.

### Decision 6: shuhaige preset

Add to `novel2epub/sources.yaml`:

```yaml
  shuhaige:
    name: 书海阁 (shuhaige.net)
    domains: shuhaige.net
    engine: http
    content_selector: "#content"
    next_page_selector: "a#pager_next"
    delay_seconds: 1.0
```

This is the smallest possible config that exercises the new code path
and matches the example URL the user reported. It also serves as
living documentation.

## Risks / Trade-offs

- **[Risk] Loop hangs the pipeline on a site that always renders a
  "next" link even on the last page.** → Mitigated by
  `max_pages_per_chapter` (default 10) and the duplicate-content stop
  condition. A misbehaving site can never request more than 10 pages
  per chapter.
- **[Risk] URL pattern matches URLs we should not crawl** (e.g. the
  pattern `(\d+)\.html$` matches the TOC, not just chapters). → The
  pattern is applied starting from the chapter URL `ch.url`, not from
  the TOC, and the result must be reachable from that starting point
  (URL host matches). Out of scope for v1: hostname validation. We
  document this in the field's docstring.
- **[Risk] Title-strip heuristic removes legitimate body text** when a
  page happens to start with the same string as the title. → Low
  probability in practice; if it happens, the user can disable the
  behaviour by leaving the title line outside the `content_selector`
  scope, or by setting `max_pages_per_chapter: 1` as an emergency brake.
- **[Risk] Three new fields on `CrawlConfig` is a breaking change for
  positional callers.** → The constructor is keyword-friendly, and the
  only positional caller in the codebase is `_coerce` in
  `novel2epub/sources.py`, which we update in the same patch. External
  callers passing positionals will get a `TypeError`; we document this
  in `CHANGELOG` (out of scope for this change, but called out in
  the proposal as **BREAKING**).
- **[Trade-off] We do not parallelise sub-page fetches.** Pagination is
  sequential because (a) sites rate-limit sequential requests harder
  than parallel ones, (b) dedupe is cheaper when pages arrive in
  order, and (c) the typical chapter is 2–4 pages so the latency win
  is small.

## Migration Plan

No data migration. The feature is purely additive:

1. Add the three fields to `CrawlConfig` (defaults match the new
   behaviour) and `SourcePreset`.
2. Add `fetch_chapter_paginated` helper and wire it into the three
   crawlers.
3. Add the `shuhaige` preset.
4. Ship tests.
5. Existing users see no change — every `CrawlConfig` they already have
   on disk loads successfully with the default values.

Rollback: revert the commit. No persistent state depends on the new
fields.

## Open Questions

- Should the helper also detect a "previous page" link on the **first**
  page (some sites render the pager on every page and a `pre` link
  appears only on page ≥ 2)? For v1: no. The crawler starts at
  `ch.url` and only walks forward. If a future site preset needs
  bi-directional pagination, that becomes a separate capability.
- Should we expose a "stop when next URL is the same as the previous
  one" shortcut as well as the duplicate-text check? For v1: the
  same-URL check is already in stop condition #2, and we do not need a
  third near-duplicate check.
