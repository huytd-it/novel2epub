## ADDED Requirements

### Requirement: Multi-page chapter detection by CSS selector

The crawler MUST support detecting a "next page" link via a CSS selector
configured on `CrawlConfig.next_page_selector`. When the selector is set
and the rendered page contains a matching `<a>` element with a non-empty
`href`, the crawler MUST fetch that URL, extract its content, and
concatenate it with the current chapter text in document order. The
process repeats until the selector no longer matches, the link is
absent, or the page-count cap is reached.

#### Scenario: Three-page chapter follows selector
- **WHEN** `CrawlConfig.next_page_selector` is `"a#pager_next"` and a
  chapter URL serves page 1 with a link `<a id="pager_next" href="..._2.html">`,
  page 2 with `..._3.html`, and page 3 with no matching link
- **THEN** `fetch_chapter` returns the concatenation of pages 1, 2, and 3
  in order, separated by a blank line

#### Scenario: Single-page chapter with selector configured
- **WHEN** `CrawlConfig.next_page_selector` is `"a.next"` but the rendered
  page has no element matching that selector
- **THEN** `fetch_chapter` returns the text of the single page unchanged
  and performs exactly one HTTP request

#### Scenario: Selector points to anchor with no href
- **WHEN** `CrawlConfig.next_page_selector` matches an `<a>` element whose
  `href` is empty, missing, or a `javascript:` pseudo-URL
- **THEN** `fetch_chapter` stops paginating and returns the text already
  collected

### Requirement: Multi-page chapter detection by URL pattern

The crawler MUST support a regex-based fallback configured on
`CrawlConfig.next_page_url_pattern`. The pattern MUST contain exactly one
capturing group; the crawler substitutes that group's value with an
incrementing suffix (`_2`, `_3`, ...) starting at `2` and re-fetches
until the pattern no longer matches the current URL, the resulting URL
returns a non-200 response, or the page-count cap is reached.

#### Scenario: Pattern with numeric suffix
- **WHEN** `CrawlConfig.next_page_url_pattern` is `"(\d+)\.html$"` and the
  current chapter URL is `https://example.com/book/12345.html`
- **THEN** the crawler tries `.../12345_2.html`, `.../12345_3.html`, ...
  in order, treating the first URL that does not match the pattern or
  fails to respond as the end of the chapter

#### Scenario: Pattern with no capturing group
- **WHEN** `CrawlConfig.next_page_url_pattern` is set but contains zero
  capturing groups
- **THEN** the crawler MUST raise a `ValueError` at construction time
  (`CrawlConfig.__post_init__`) with a message that names the offending
  field

### Requirement: Stop paginating on duplicate content

To prevent infinite loops when a "next" link is misconfigured (e.g.
points to the same page), the crawler MUST stop paginating as soon as the
trimmed text of the newly fetched page is identical to the trimmed text
of any page already collected for the current chapter.

#### Scenario: Last page repeats first page
- **WHEN** pages 1, 2, and 3 each return text `["A", "B", "B"]`
- **THEN** the crawler returns `"A\n\nB"` and stops after the duplicate,
  without issuing a fourth request

#### Scenario: Identical link points to the same URL
- **WHEN** the "next page" link on page 2 has the same `href` as the
  URL that produced page 2
- **THEN** the crawler stops paginating and returns the text collected
  through page 2

### Requirement: Page-count safety cap

The crawler MUST honour `CrawlConfig.max_pages_per_chapter` (default
`10`). Once the number of pages fetched for a single chapter reaches
this cap, the crawler MUST stop paginating and return the concatenated
text it has, even if a "next" link is still present.

#### Scenario: Cap prevents runaway pagination
- **WHEN** `CrawlConfig.max_pages_per_chapter` is `3` and a chapter has
  five sub-pages
- **THEN** the crawler fetches exactly three pages and returns the
  concatenation of those three

#### Scenario: Default cap is ten
- **WHEN** `CrawlConfig` is instantiated without specifying
  `max_pages_per_chapter`
- **THEN** the field's value is `10`

### Requirement: Repeated chapter title is removed

Most paginated sites repeat the chapter title at the top of every
sub-page. The crawler MUST detect a repeated title at the start of a
sub-page and strip it before concatenation, so the resulting text does
not contain the title twice.

#### Scenario: Sub-page starts with the chapter title
- **WHEN** page 1 ends with `"...kết thúc trang 1."` and page 2 begins
  with `"第N章 章名\n\nNội dung tiếp..."` where `章名` is identical to
  the first non-blank line of page 1
- **THEN** the concatenated text begins with the title exactly once and
  continues directly with the body of page 2

#### Scenario: Sub-page has no title prefix
- **WHEN** page 2 begins with body text that does not match the first
  line of page 1
- **THEN** the crawler concatenates without modification

### Requirement: All engines share the same pagination contract

The pagination behaviour described above MUST be implemented for every
concrete crawler (`HttpCrawler`, `Crawl4AICrawler`, `FirecrawlCrawler`).
The configuration surface is shared via `CrawlConfig`; the engines MUST
NOT introduce their own pagination-specific fields.

#### Scenario: Crawl4AI engine follows the same selector
- **WHEN** `CrawlConfig.engine` is `"crawl4ai"` and
  `CrawlConfig.next_page_selector` is `"a.next"`
- **THEN** `Crawl4AICrawler.fetch_chapter` follows the same sub-page
  protocol as `HttpCrawler.fetch_chapter`

#### Scenario: Firecrawl engine follows the same pattern
- **WHEN** `CrawlConfig.engine` is `"firecrawl"` and
  `CrawlConfig.next_page_url_pattern` is `"(\d+)\.html$"`
- **THEN** `FirecrawlCrawler.fetch_chapter` follows the same sub-page
  protocol as `HttpCrawler.fetch_chapter`

### Requirement: Source presets round-trip pagination fields

`SourcePreset` and the YAML loader at `novel2epub/sources.py` MUST
preserve `next_page_selector`, `next_page_url_pattern`, and
`max_pages_per_chapter` when reading and writing
`novel2epub/sources.yaml`, so a preset can be created, saved, and
re-loaded without losing pagination configuration.

#### Scenario: Preset saves and reloads the selector
- **WHEN** a user adds a new preset with
  `next_page_selector: "a#pager_next"` to `sources.yaml` and reloads
  it via `load_presets()`
- **THEN** the resulting `SourcePreset` has
  `next_page_selector == "a#pager_next"`

#### Scenario: Preset defaults match CrawlConfig defaults
- **WHEN** a preset omits the pagination fields entirely
- **THEN** `SourcePreset.next_page_selector` is `""`,
  `next_page_url_pattern` is `""`, and `max_pages_per_chapter` is `10`
