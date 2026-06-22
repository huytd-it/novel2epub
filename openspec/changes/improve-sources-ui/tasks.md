## 1. Route data: preset usage map

- [x] 1.1 In `app/routes/sources.py`, extend `sources_page` to compute a `usage: dict[str, list[str]]` mapping each preset name to the list of library ebook slugs whose resolved `CrawlConfig` matches all of that preset's `crawl_overrides()` pairs (empty list when none match). Use `deps.library().ebooks`, `deps.resolved_cfg(slug)`, and `SourcePreset.crawl_overrides()`.
- [x] 1.2 Pass `usage` into the `TemplateResponse` context alongside the existing `presets`/`edit`/`sources_path`/`job` keys. Do not change `save_source_preset` or `delete_source_preset` form signatures.

## 2. Template: preset list table

- [x] 2.1 In `app/templates/sources.html`, replace the bare `<table>` with `<div class="table-wrap"><table class="data-table">…</table></div>`.
- [x] 2.2 Add a "Used by" header column; for each preset row render the matching slugs as links to `/ebooks/{slug}` (from `usage[name]`), or a muted `—` when the list is empty.
- [x] 2.3 Render the engine column as a `.badge` (e.g. `badge ok` for `http`, `badge run` for `crawl4ai`, neutral `.badge` for `firecrawl`).
- [x] 2.4 Replace the inline `Sửa`/`Xóa` text links with a `<div class="row-actions">` containing `<a class="button" href="/sources?edit={{ name }}">Sửa</a>` and the existing delete `<button>` form (keep the `confirm()` prompt).
- [x] 2.5 Replace the "no presets" empty state with an action-oriented muted message consistent with `library.html:26`; ensure no `<table>` is rendered in that branch.

## 3. Template: grouped add/edit form

- [x] 3.1 Wrap the heading copy into a `.section-head` with a `p.muted` lead paragraph describing presets and listing `{{ sources_path }}`, mirroring `library.html:5`.
- [x] 3.2 Reorganize the `<form method="post" action="/sources">` into four `<fieldset>` blocks: Basic (`name`, `engine`, `delay_seconds`, `encoding`), Selectors (the seven CSS selector inputs), crawl4ai options (`headless`, `magic`, `js_code`; see D4), Network (`user_agent`). Use `.form-row` for horizontal label grouping inside each fieldset.
- [x] 3.3 Keep all existing `name="..."` field attributes, default values, and the `required` logic on `name` (add mode only) unchanged so `save_source_preset` works unmodified.
- [x] 3.4 Update the submit button label to `Cập nhật` in edit mode and `Thêm` in add mode (preserve existing wording, just relocate into the form's `.form-row` actions).

## 4. Engine-conditional crawl4ai fieldset

- [x] 4.1 Add an `id` to the crawl4ai fieldset (e.g. `crawl4ai-options`) and to the `engine` `<select>` (e.g. `engine-select`).
- [x] 4.2 Server-side: render the crawl4ai fieldset with `style="display:none"` when there is **no** `edit` preset OR `edit.engine != "crawl4ai"`. When editing an existing crawl4ai preset, render it visible.
- [x] 4.3 Add an inline `<script>` (in `{% block scripts %}` of `sources.html`) that listens to the `change` event on `#engine-select` and toggles `display` between `''` and `none` on `#crawl4ai-options` based on the selected value. Never clear input values on hide.

## 5. Tests & verification

- [x] 5.1 Add/extend a test under `tests/` that hits `GET /sources` with at least one preset and one library ebook using that preset, and asserts the response HTML contains a `data-table` row with the matching `/ebooks/<slug>` link in the "Used by" column. Reuse the existing FastAPI test client fixture pattern from `tests/test_crawler_meta.py`.
- [x] 5.2 Add a test asserting the empty preset state renders the muted empty-state message and contains no `<table>` element.
- [x] 5.3 Add a test asserting the crawl4ai fieldset is hidden by default in add mode (contains `display:none` or equivalent hidden attribute) and visible when `edit` targets a crawl4ai preset.
- [x] 5.4 Run `pytest tests/ -v` and confirm the full suite (existing + new tests) passes. Update any snapshot/HTML-assertion tests that match the old markup.
- [x] 5.5 Manually load `http://127.0.0.1:8010/sources`, verify: badge colors, zebra striping, horizontal scroll, engine toggle shows/hides the crawl4ai fieldset live, editing a crawl4ai preset keeps the fieldset visible without JS, and the delete confirm flow still deletes the preset and redirects to `/sources`.