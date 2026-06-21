# Web UI Contract: Refactor TOC

## Ebook Overview

Route: `GET /ebooks/{slug}`

**Expected content**

- Novel metadata: source URL, original title, displayed title, original author, displayed
  author, original description, displayed description, and missing-field indicators.
- TOC controls: sort key, sort direction, search text, status filters, and missing-field filter.
- Shared chapter table: row checkbox, source index, visible title, source URL, crawl status,
  translation status, missing-field status, and per-row crawl/translate action buttons.
- Bulk controls: targeting mode (`checked` or `range`), visible range endpoints, checked-row
  count preview, crawl selected, translate selected, and explicit override checkbox.

## Fetch TOC Job

Route: `POST /ebooks/{slug}/jobs/fetch-toc`

**Expected behavior**

- Refreshes metadata and chapter list without downloading chapter body text.
- Does not overwrite curated metadata unless the request explicitly includes override.
- Redirects back to the ebook overview with job status/log visible.

## Chapter List Query

Route: `GET /ebooks/{slug}` with query parameters

```text
sort=<source|title|raw|translated>
direction=<asc|desc>
search=<text>
filter_raw=<any|yes|no>
filter_translated=<any|yes|no>
filter_missing=<any|yes|no>
```

**Expected behavior**

- Applies search and filters before range selection.
- Applies deterministic sorting to the visible result set.
- Keeps controls populated with the active query values after refresh.
- Renders checkboxes only for visible rows and keeps hidden filtered rows out of the current
  submitted selection.

## Bulk Chapter Action

Route: `POST /ebooks/{slug}/jobs/chapter-action`

**Form fields**

- `action`: `crawl` or `translate`.
- `sort`: active sort key.
- `direction`: active sort direction.
- `search`: active search text.
- `filter_raw`: active raw filter.
- `filter_translated`: active translation filter.
- `filter_missing`: active missing-field filter.
- `range_start`: visible range start chapter identifier.
- `range_end`: visible range end chapter identifier.
- `checked_indexes`: one or more visible checked chapter indexes.
- `targeting_mode`: `checked` or `range`.
- `override`: explicit replacement flag.

**Expected behavior**

- Resolves checked rows from the active visible list when `targeting_mode=checked`.
- Resolves the selected range from the active visible list when `targeting_mode=range`.
- Starts one background job if no other job is running.
- Reports selected count before action submission.
- Preserves old output when `override` is absent.
- Replaces old output only for selected chapters when `override` is present.

## Per-Chapter Action

Route: `POST /ebooks/{slug}/chapters/{index}/action`

**Form fields**

- `action`: `crawl` or `translate`.
- `override`: explicit replacement flag.

**Expected behavior**

- Targets only the requested chapter.
- Is exposed as a button in the shared chapter table row and may also appear on chapter detail.
- Uses the same skip/replacement semantics as bulk actions.
- Redirects back to the chapter detail or ebook overview with job status/log visible.
