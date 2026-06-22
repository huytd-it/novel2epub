## ADDED Requirements

### Requirement: Preset list renders as a responsive data table
The `/sources` page SHALL render the preset list using the shared `.table-wrap` + `.data-table` conventions (header background, zebra striping, horizontal scroll on overflow) and SHALL show the engine of each preset as a color-coded `.badge`.

#### Scenario: Preset list displayed
- **WHEN** a user requests `GET /sources` and at least one preset exists
- **THEN** the response HTML wraps the preset table in a `div.table-wrap` containing a `table.data-table`, each row shows the preset name, engine as a badge, `content_selector`, and `chapter_link_pattern`, and the table scrolls horizontally instead of overflowing the page on viewports narrower than the table.

#### Scenario: Empty state
- **WHEN** a user requests `GET /sources` and no presets exist
- **THEN** the response HTML shows an action-oriented muted empty-state message in place of the table (no `<table>` is rendered).

### Requirement: Preset usage indicator
The `/sources` page SHALL, for every preset, display which library ebooks currently resolve to that preset's crawl overrides, computed read-only at render time. When no ebook matches, a muted `—` SHALL be shown.

#### Scenario: Preset used by one or more ebooks
- **WHEN** a preset's `crawl_overrides()` key/value pairs all equal the corresponding resolved crawl configuration fields of one or more library ebooks
- **THEN** the preset's row shows the list of matching ebook slugs as links to `/ebooks/{slug}`.

#### Scenario: Preset unused
- **WHEN** no library ebook's resolved crawl configuration matches all of a preset's `crawl_overrides()` pairs
- **THEN** the preset's row shows a muted `—` in the "Used by" column.

#### Scenario: Usage is non-blocking on deletion
- **WHEN** a user submits the delete form for a preset that is currently in use by one or more ebooks
- **THEN** the system deletes the preset (the existing semantics are unchanged); the usage indicator is informational only and imposes no confirmation beyond the existing `confirm()` JavaScript.

### Requirement: Grouped add/edit form
The add/edit preset form SHALL group its fields into `<fieldset>` blocks (Basic, Selectors, crawl4ai options, Network) and SHALL use the `.form-row` layout so labels align horizontally and wrap on narrow screens. The form MUST post to `/sources` with the same field names already accepted by `save_source_preset`; no field names or the POST endpoint SHALL change.

#### Scenario: Rendering the add form
- **WHEN** a user requests `GET /sources` without an `edit` query parameter
- **THEN** the form renders four fieldsets, the Basic fieldset's `name` input is `required`, and submitting the form posts the existing set of fields (`name`, `engine`, `chapter_link_pattern`, `content_selector`, `toc_selector`, `chapter_title_selector`, `title_selector`, `author_selector`, `desc_selector`, `cover_selector`, `encoding`, `user_agent`, `headless`, `magic`, `js_code`, `delay_seconds`) to `POST /sources`.

#### Scenario: Rendering the edit form
- **WHEN** a user requests `GET /sources?edit=<preset_name>` for an existing preset
- **THEN** the form is pre-populated with that preset's values, the submit button is labeled "Cập nhật", and the heading reflects the preset being edited.

### Requirement: Engine-conditional crawl4ai fields
The crawl4ai options fieldset SHALL be visually hidden whenever `engine` is not `crawl4ai`, both on initial render (based on the preset being edited or "add" mode) and whenever the user changes the `engine` select. The fieldset SHALL remain present in the DOM and its inputs SHALL still be submitted with the form, so users without JavaScript can still edit crawl4ai presets.

#### Scenario: Initial render with non-crawl4ai engine
- **WHEN** the form is rendered and the active engine is `http` or `firecrawl` (or unset in add mode)
- **THEN** the crawl4ai fieldset has `style="display:none"` (or an equivalent hidden state) and is not visible to the user.

#### Scenario: User switches engine to crawl4ai
- **WHEN** the user changes the `engine` select to `crawl4ai`
- **THEN** the crawl4ai fieldset becomes visible without reloading the page.

#### Scenario: User switches engine away from crawl4ai
- **WHEN** the crawl4ai fieldset is visible and the user changes `engine` back to `http` or `firecrawl`
- **THEN** the crawl4ai fieldset is hidden again, and any previously typed values in `headless`, `magic`, or `js_code` are preserved in the DOM (not cleared) so a subsequent switch back to `crawl4ai` restores them.

#### Scenario: No-JS user editing a crawl4ai preset
- **WHEN** JavaScript is disabled and the user opens the edit form for a preset whose `engine == crawl4ai`
- **THEN** the crawl4ai fieldset is visible (not server-side hidden) and the user can submit updated `headless`, `magic`, and `js_code` values.

### Requirement: Consistent row action buttons
Each preset row SHALL expose Edit and Delete actions using the shared `.row-actions` / `.actions a.button` / `.actions button` styling conventions so they match actions elsewhere in the app. The Delete action SHALL remain a `POST /sources/{name}/delete` form with an inline `confirm()` prompt, identical to today's behavior.

#### Scenario: Edit action
- **WHEN** a user clicks the Edit control on a preset row
- **THEN** the browser navigates to `GET /sources?edit=<preset_name>` and the edit form is rendered.

#### Scenario: Delete action with confirmation
- **WHEN** a user clicks the Delete control on a preset row and confirms the browser `confirm()` prompt
- **THEN** the form submits `POST /sources/{name}/delete`, the preset is removed from `sources.yaml`, and the user is redirected to `/sources` (HTTP 303).

#### Scenario: Delete action cancelled
- **WHEN** a user clicks the Delete control on a preset row and dismisses the `confirm()` prompt
- **THEN** no request is made and the preset remains unchanged.

### Requirement: Header and storage path messaging
`/sources` SHALL display a muted header paragraph describing what a preset is and where it is stored (`{{ sources_path }}`) using the same tone as the library page's lead paragraph, plus an engine-to-preset hint that helps users pick the right `engine` value.

#### Scenario: Header copy visible
- **WHEN** a user requests `GET /sources`
- **THEN** the response HTML contains a `p.muted` lead paragraph mentioning `sources_path` and a short hint connecting `engine` choices to the appropriate crawl backends.