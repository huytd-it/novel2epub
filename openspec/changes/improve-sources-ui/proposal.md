## Why

The `/sources` page is the least polished screen in the Web UI: its preset table is a raw HTML `<table>` with no scroll/badges, the add/edit form is a long vertical stack of inline labels that wraps awkwardly, the crawl4ai-only fields (`headless`, `magic`, `js_code`) are shown for every engine, and there is no visible link between a preset and the ebooks actively using it. As more site presets get added (sto9, aixdzs, qidian, 69shuba, shuqi …) the page becomes hard to scan and edit. This change makes the page consistent with the rest of the UI (library/ebook pages already use `.form-row`, `.data-table`, `.actions`, badges) and gives the user quick orientation when managing crawl configurations.

## What Changes

- Replace the raw `<table>` in `sources.html` with the `.table-wrap` + `.data-table` pattern used by the ebook overview, including a header background, zebra striping, horizontal scroll on overflow, and engine badges.
- Add a "Used by" column listing the ebook slugs whose `preset` resolves to this preset (or a muted `—` when unused), so users see impact before deleting.
- Restyle the add/edit form using `.form-row` groupings (Basic, Selectors, crawl4ai options, Network) so labels align horizontally and wrap on narrow screens.
- Conditionally render the `crawl4ai` fieldset only when `engine == crawl4ai` (and toggle it via JS when the engine `<select>` changes), removing noise for `http`/`firecrawl`.
- Replace the inline text-link actions (`Sửa` / `Xóa`) with the `.actions` button row used elsewhere (`.actions a.button`, `.actions button`) and present the delete button inside a confirm-on-submit form as today.
- Add an "engine → preset hint" header note and a small legend explaining the saved path (`{{ sources_path }}`) consistently with the library page's `<p class="muted">…</p>`.
- No **BREAKING** changes to routes or form fields; all existing POST fields and the `/sources/{name}/delete` endpoint stay identical.

## Capabilities

### New Capabilities
- `sources-ui`: Visual layout and interaction behavior of the `/sources` page — preset table presentation, add/edit form grouping, engine-conditional fields, preset-usage display, and action-button styling.

### Modified Capabilities
<!-- None. There are no existing specs under openspec/specs/, and the route/contract behavior (POST fields, delete endpoint) is unchanged. -->

## Impact

- **Code**: `app/templates/sources.html` (full rewrite of content block), `app/routes/sources.py` (`sources_page` needs to pass a `usage` mapping of preset name → list of ebook slugs), `app/static/style.css` (only if a new utility class is needed — expected to reuse existing classes).
- **Data**: `app/routes/library.py` reads `library.ebooks` to compute usage; no storage format changes.
- **APIs**: No public API or form-field changes. `GET /sources` gains a non-breaking `usage` template variable.
- **Tests**: Existing route tests for `/sources` continue to pass; add a lightweight test asserting `usage` is rendered and the crawl4ai fieldset is hidden when `engine != crawl4ai`.
- **Dependencies**: No new Python or JS dependencies — vanilla JS as already used on the library page.