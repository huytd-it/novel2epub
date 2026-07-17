# Web UI Performance — Ebook/Chapter List

Date: 2026-07-15  
Status: Approved

## Problem

`GET /ebooks/{slug}` with 1500+ chapters:

- `chapter_rows()` executes N+1 SQL queries (1 SELECT per chapter)
- Each `_chapter_row()` SELECT fetches full `raw_text` + `translated_text` just to check boolean flags
- Result: ~3000–5000ms server-side, 500KB+ HTML with 1500 rows for the browser to parse

## Solution: A + B Combined

### Part A — Bulk SQL query (fix N+1)

Add `Storage.bulk_chapter_stats(slug)` returning `dict[int, dict]` via a single SQL query:

```sql
SELECT idx,
       CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 ELSE 0 END AS has_raw,
       CASE WHEN translated_text IS NOT NULL AND translated_text != '' THEN 1 ELSE 0 END AS has_translated_raw,
       meta_json,
       LENGTH(translated_text) AS translated_len,
       LENGTH(raw_text) AS raw_len
FROM chapters WHERE ebook_slug = ?
```

Update `chapter_rows()` to accept optional `stats_map: dict[int, dict] | None`. When provided, use pre-fetched stats instead of calling `_chapter_row()` per chapter. Backward compatible — callers that don't pass `stats_map` continue to work unchanged.

`word_count` and `zh_char_count` are estimated from `LENGTH` (bytes):
- `word_count ≈ translated_len // 5` (sufficient for sort/display)
- `zh_char_count ≈ raw_len // 3` (Han chars are ~3 bytes in UTF-8)

`has_translated` respects the `complete` flag in `meta_json` (same logic as current `Storage.has_translated()`).

`bientap` / `bientap_tooltip` are derived from `meta_json` in the same loop — no additional queries.

### Part B — Client-side table rendering

Instead of rendering 1500 `<tr>` rows in Jinja2, the server passes `chapters_json` (already computed) as `window.CHAPTERS_DATA` in a `<script>` tag and renders an empty `<tbody id="chapter-tbody">`.

JS in `ebook.html`:
1. Reads `window.CHAPTERS_DATA`
2. Builds `<tr>` rows (same columns as current template)
3. Calls `initDataTable` on the table

Filter/sort controls become client-side only — no server round-trip needed. The existing `compact-toolbar` form can remain for bookmarkable URLs but is no longer required for the table to render.

Checkbox "select all" and all bulk-action forms continue to work — JS attaches event listeners after building rows, same as currently done.

## Files Changed

| File | Change |
|------|--------|
| `novel2epub/storage.py` | Add `bulk_chapter_stats()` method |
| `novel2epub/toc.py` | `chapter_rows()` accepts optional `stats_map` |
| `app/routes/ebooks.py` | `_chapter_rows()` uses bulk stats; `ebook_home` passes `chapters_json` |
| `app/templates/ebook.html` | Remove Jinja loop, add JS row builder |

## Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| SQL queries / request | ~3000+ | 2–3 |
| Server response time | ~3–5 s | ~50–100 ms |
| HTML payload | ~500 KB+ | ~20 KB |
| Browser parse time | ~500 ms+ | ~10 ms |
| Filter/sort | full page reload | instant client-side |

## Out of Scope

- Pagination (not needed once client-side render is in place)
- Caching layer (bulk SQL is fast enough)
- Other pages (dashboard, reader) — separate improvement if needed
