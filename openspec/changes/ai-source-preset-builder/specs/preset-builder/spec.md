## ADDED Requirements

### Requirement: Preset builder endpoint generates a `SourcePreset` from a TOC URL
The preset builder endpoint SHALL accept a TOC URL plus an optional `novel_title` (default `"赤心巡天"`) and an optional preset name, and return a fully-populated `SourcePreset` candidate together with the list of chapters the candidate would extract, without writing to disk until the user explicitly confirms.

#### Scenario: Static HTML site
- **WHEN** a user submits `toc_url="https://www.aixdzs.com/novel/赤心巡天/"` to the preset builder
- **THEN** the engine heuristic picks `http`, AI CLI proposes a `content_selector`, `toc_selector`, `chapter_link_pattern`, `chapter_title_selector`, and other fields, the preview shows the full chapter list (one entry per `<a>` inside the chosen `toc_selector` whose `href` matches `chapter_link_pattern`), and the response payload contains the candidate `preset` and the `preview.chapters` array.

#### Scenario: JS-rendered site
- **WHEN** a user submits `toc_url="https://sto9.com/book/3352/index.html"` and the HTTP request returns a page whose `<a>` tags under the chosen `toc_selector` are empty (JS-rendered)
- **THEN** the engine heuristic retries with `crawl4ai` (setting `magic: true`, `headless: true`), the AI proposes the `crawl4ai`-only fields (`js_code` may be empty), and the preview is computed from the rendered DOM.

#### Scenario: AI CLI unavailable
- **WHEN** a user submits a TOC URL and the AI CLI (`opencode run` or configured equivalent) is not on PATH or returns a non-zero exit code
- **THEN** the preset builder returns HTTP 503 with a structured error explaining that the AI CLI is missing, and does not write to `sources.yaml`.

### Requirement: Pattern validation refuses too-broad or too-narrow regex
The preset builder SHALL validate the proposed `chapter_link_pattern` by counting how many links the regex matches inside the chosen `toc_selector` scope. The pattern SHALL be rejected as too broad when the match count exceeds a configurable upper bound (default `2000`) and as too narrow when the count is below a configurable lower bound (default `5`); in either case, the response includes a `validation: {too_broad|too_narrow, count, threshold}` field and the refined regex.

#### Scenario: Too-broad regex caught and refined
- **WHEN** the AI proposes `chapter_link_pattern: ".*"` and the matched count inside `toc_selector` is 7321
- **THEN** the preset builder marks the pattern as `too_broad`, asks the AI (with a feedback message that includes the count and a snippet of the matched URLs) to refine it, and the refined pattern (e.g. `/book/3352/\d+\.html`) brings the count under 2000.

#### Scenario: Too-narrow regex caught and refined
- **WHEN** the AI proposes `chapter_link_pattern: "/book/3352/0001\.html"` and the matched count is 1
- **THEN** the preset builder marks the pattern as `too_narrow`, asks the AI to generalize it, and the refined pattern brings the count into the [5, 2000] window.

#### Scenario: Refinement budget exhausted
- **WHEN** the pattern is still flagged as `too_broad` or `too_narrow` after the maximum number of refinement rounds (default 3)
- **THEN** the preset builder returns HTTP 422 with the latest candidate and a `validation` block, and the user is prompted to either accept manually or supply hints (e.g. "chapters are under `/read/`").

### Requirement: User can override the AI suggestion for any preset field
The preset builder SHALL accept per-field overrides in the request (e.g. `encoding`, `js_code`, `magic`, `headless`, `user_agent`, `delay_seconds`, `next_page_selector`, `next_page_url_pattern`). When overrides are provided, they replace the AI's value for that field in the candidate preset, and the override is logged in the response payload under `overrides_applied`.

#### Scenario: Override encoding for a GBK site
- **WHEN** a user submits `toc_url="https://example.com/book/12345/"` with override `encoding="gbk"`
- **THEN** the candidate preset's `encoding` field is `gbk` regardless of what the AI suggested, and the response lists `encoding` in `overrides_applied`.

#### Scenario: Override crawl4ai `js_code` for infinite-scroll TOC
- **WHEN** a user submits a TOC URL and override `js_code="window.scrollTo(0, document.body.scrollHeight); await new Promise(r => setTimeout(r, 1500));"`
- **THEN** the candidate preset's `js_code` is the override, the engine is forced to `crawl4ai`, and the preview re-runs the crawl with that `js_code` to compute the chapter list.

### Requirement: `toc-preview` runs a non-mutating verification of an existing preset against a URL
The system SHALL provide a non-mutating `toc-preview` operation (CLI subcommand and Web UI button on `/preset-builder`) that, given a TOC URL and a preset name, runs the existing `HttpCrawler` / `Crawl4AICrawler` configured by that preset, and returns the resulting chapter list with metadata.

#### Scenario: Preview against an existing preset
- **WHEN** a user runs `novel2epub toc-preview https://www.aixdzs.com/novel/赤心巡天/ --preset aixdzs`
- **THEN** the command prints the resolved `title`, `author`, `description`, the chapter count, and the first/last 5 chapter titles with their URLs, and exits 0.

#### Scenario: Preview detects a broken pattern
- **WHEN** a preset's `chapter_link_pattern` is so broad that it matches 0 chapters for the supplied URL (e.g. preset for site A reused on site B)
- **THEN** the command prints a warning `Pattern matches 0 chapters` and exits non-zero, so the user is alerted before kicking off a full crawl.

### Requirement: `preset-build` CLI subcommand persists the candidate after confirmation
The system SHALL expose a `novel2epub preset-build <toc_url>` CLI subcommand. The command SHALL run the full preset-builder flow, print the candidate and preview, prompt the user for `y/N` confirmation, and on `y` call `save_presets()` to persist into `sources.yaml` (creating the file with the existing `sources:` root if absent) and on `N` exit without writing.

#### Scenario: User confirms
- **WHEN** the user types `y` at the confirmation prompt
- **THEN** the preset is written to `sources.yaml`, the new preset name is printed, and the command exits 0.

#### Scenario: User declines
- **WHEN** the user types `n` or presses Enter
- **THEN** no file is written, the command prints `Cancelled.`, and exits 0.

#### Scenario: Non-interactive `--yes` flag
- **WHEN** the user runs `novel2epub preset-build <toc_url> --name mypreset --yes`
- **THEN** the confirmation prompt is skipped, the preset is written immediately, and the command exits 0.

### Requirement: Web UI route `/preset-builder` renders a form, preview, and save button
The system SHALL expose `GET /preset-builder` rendering a form with a TOC URL input, an optional `novel_title` input (default `赤心巡天`), an optional preset name input, and an "Overrides" fieldset accepting the same per-field overrides as the API. Submitting the form SHALL post to `POST /preset-builder/preview`, which returns the candidate and preview, rendered into the same page with a "Save preset" button that posts to `POST /preset-builder/save`.

#### Scenario: Preview submission
- **WHEN** a user submits the form with a TOC URL
- **THEN** the response renders the AI's candidate preset (each field as a labeled `<input>`/`<select>` so the user can edit it), the chapter count, a paginated sample of the first 20 chapters, and a "Save preset" button.

#### Scenario: Save submission
- **WHEN** a user clicks "Save preset"
- **THEN** the server writes the (possibly edited) preset into `sources.yaml` via `save_presets()` and redirects to `/sources` (HTTP 303) with a flash message `Đã lưu preset <name>`.

### Requirement: `library._fetch_meta` suggests creating a preset when no match is found
The system SHALL extend `library._fetch_meta` so that, when `detect_preset(toc_url, presets)` returns `None`, the response payload includes `suggested_preset: null` and `suggest_url: "/preset-builder?toc_url=<url>"`. The `/library` page SHALL show a notice "Chưa có preset cho URL này — [Tạo preset]" linking to `suggest_url` when the user pastes a URL that does not match any existing preset.

#### Scenario: URL matches a preset
- **WHEN** a user pastes `https://sto9.com/book/3352/index.html` and the `sto9` preset exists
- **THEN** `_fetch_meta` returns `preset: "sto9"`, `suggested_preset: null`, no `suggest_url`, and the library form auto-selects the `sto9` preset.

#### Scenario: URL matches no preset
- **WHEN** a user pastes `https://example.com/novel/12345/` and no preset has a domain that matches `example.com`
- **THEN** `_fetch_meta` returns `preset: null`, `suggested_preset: null`, `suggest_url: "/preset-builder?toc_url=https%3A%2F%2Fexample.com%2Fnovel%2F12345%2F"`, and the library form shows the "Tạo preset" link.

### Requirement: Preset builder is offline-friendly
The preset builder SHALL not require network access beyond the TOC URL itself; it SHALL run the same way on Windows / macOS / Linux, and SHALL gracefully handle timeouts from the AI CLI (default `timeout_seconds: 120` for the suggestion call, configurable per request).

#### Scenario: AI CLI timeout
- **WHEN** the AI CLI takes longer than the configured timeout
- **THEN** the process is terminated, the response payload is `{"error": "AI CLI timeout after 120s"}` with HTTP 504, and no preset is written.

#### Scenario: Intermittent network failure
- **WHEN** fetching the TOC URL itself returns a non-2xx status
- **THEN** the preset builder returns HTTP 502 with the URL and the HTTP status in the error message, and the user can retry without side effects.
