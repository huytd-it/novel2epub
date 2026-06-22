## Context

The `/sources` Web UI (`app/routes/sources.py` + `app/templates/sources.html`) manages `SourcePreset` entries persisted to `novel2epub/sources.yaml`. It is the only pixel surface in the app still rendered with a bare `<table>` and ungrouped inline `<label>` inputs (see `sources.html:8-64`), while sibling pages — `index.html`, `ebook.html`, `library.html` — already adopted shared CSS conventions (`.table-wrap`/`.data-table`, `.form-row`, `.actions`, `.badge`, `fieldset legend`) defined in `app/static/style.css`. The `library.html` add-ebook form further demonstrates the in-repo pattern for engine-conditional selection and JS-assisted UX (`library.html:36-72`).

Presets are *baked* into each ebook's `configs/<slug>.yaml` at scaffold time (`config_writer.scaffold_config_file` → `_deep_merge` of `preset.crawl_overrides()`), so the preset name is not stored on the ebook. The "Used by" indicator therefore must be computed by comparing an ebook's resolved crawl config against each preset's `crawl_overrides()` output at render time — a read-only, render-time concern inside `sources_page`.

Routes and form fields of the existing endpoints (`GET /sources`, `POST /sources`, `POST /sources/{name}/delete`) are stable. `tests/test_crawler_meta.py` and other existing tests must keep passing.

## Goals / Non-Goals

**Goals:**
- Bring `/sources` to the same visual/interaction standard as `/library` and `/ebooks/{slug}` without introducing new dependencies.
- Surface preset-to-ebook impact so deletion is a deliberate action.
- Reduce form noise by hiding crawl4ai-only fields when `engine != crawl4ai`.
- Reuse existing CSS classes; only add to `style.css` if a needed utility is genuinely absent.

**Non-Goals:**
- No new route, no new POST field, no schema change to `sources.yaml` or `SourcePreset`.
- No rename/relocation of `sources_page`, `save_source_preset`, `delete_source_preset`.
- No persistence of "preset name" on ebooks — usage detection stays a render-time comparison.
- No dark mode, i18n, or multi-language overhaul of the rest of the Web UI.
- No JS framework, build step, or external CSS.

## Decisions

### D1 — Adopt `.table-wrap` + `.data-table` for the preset list
Reuse the exact convention from the ebook overview (`index.html` / `ebook.html`). Add engine badges via the existing `.badge` class (e.g. `.badge.ok` for `http`, `.badge.run` for `crawl4ai`, neutral for `firecrawl`) so engine is scannable at a glance. Wrap in `<div class="table-wrap">` for horizontal scroll on narrow viewports. **Alternative considered:** a responsive card grid — rejected as inconsistent with sibling list pages.

### D2 — Add a render-time `usage` map keyed by preset name
`sources_page` extends itself by reading `deps.library()` and, for each ebook, loading the resolved `CrawlConfig` (via `deps.resolved_cfg(slug)`) and comparing its non-default crawl fields against each preset's `crawl_overrides()`. A preset is considered "used by `<slug>`" when **all** key/value pairs in `crawl_overrides()` are equal to the corresponding fields on the resolved crawl config. The result is `usage: dict[str, list[str]]`, passed to the template. **Why key-by-field comparison instead of storing a preset name:** the data model already bakes preset values into config and several legacy configs predate the preset feature — a name field would lie for those. Comparison gracefully degrades to "unused" for hand-edited configs. **Alternative considered:** store the preset name alongside `LibraryEntry` — rejected as a schema change requiring migration.

### D3 — Restyle add/edit form with `fieldset` + `.form-row`
Group fields into four `<fieldset>` blocks mirroring the library page: `Basic` (name, engine, delay_seconds, encoding), `Selectors` (content/toc/chapter_title/title/author/desc/cover), `crawl4ai options` (headless, magic, js_code), `Network` (user_agent). Use `.form-row` for horizontal label alignment that wraps on narrow screens. Keep POST field names and the single-form action `/sources` unchanged so `save_source_preset` stays byte-identical.

### D4 — Engine-conditional crawl4ai fieldset
Render the crawl4ai fieldset always (for no-JS users and edit mode of existing crawl4ai presets), but add `style="display:none"` server-side when `edit.engine != "crawl4ai"` AND in "add" mode. A small inline `<script>` toggles `display` on the `change` event of the `engine` `<select>`. **Why always-render + toggle, not `template {% if %}` drop:** removing the fieldset server-side breaks editing existing crawl4ai presets after a transient frontend toggle or if JS is disabled — the no-JS path must still let users submit `headless`/`magic`/`js_code` for crawl4ai. Keeping fields present also means `save_source_preset` never needs a defaulting branch.

### D5 — Button row replacing inline text links
Move preset row actions (`Sửa` / `Xóa`) into `<div class="row-actions">` (already defined in `style.css:79`) using `.actions a.button` for edit and `<button>` for delete, matching the library page's delete form. We avoid `.actions` (flex with wrap) at row level in favor of the more compact `.row-actions` already present for tables. **Alternative considered:** a sticky `.bulk-bar` — rejected, there is no bulk action on this page.

### D6 — Empty-state and header copy
Replace the bare `<p class="muted">Chưa có preset nào.</p>` with a short, action-oriented empty-state line consistent with `library.html:26`, and add a header `muted` paragraph identical in tone to `library.html:5`. No new copy guidelines introduced.

## Risks / Trade-offs

- **[Risk] Usage detection false negatives for hand-edited configs** → Mitigation: comparison is purely informational (rendering only); a `—` is shown instead of a count, never blocking deletion. Documented in the empty state.
- **[Risk] `deps.resolved_cfg` is heavier than `load_config`** → Mitigation: `/sources` already enumerates presets once per render and is an admin-only, low-traffic page; resolved_cfg reuses the same library iteration already happening elsewhere. No caching needed at expected scale (< 100 ebooks).
- **[Risk] JS toggle could confuse users if `engine` flips to `crawl4ai` mid-edit and they already typed selectors** → Mitigation: toggle only hides the crawl4ai block, never clears submitted values; the form still POSTs all fields regardless of visibility, and `save_source_preset` ignores crawl4ai fields for non-crawl4ai engines via `SourcePreset` defaults.
- **[Risk] New CSS class introduced if `.row-actions` styling falls short** → Mitigation: prefer reusing `.row-actions` (already used in ebook table); only extend `style.css` if a gap is found during implementation, and keep additions minimal and document them in tasks.