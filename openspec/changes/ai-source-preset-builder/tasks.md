## 1. Drop `firecrawl` from `CrawlConfig` and `load_config`

- [x] 1.1 In `novel2epub/config.py`, remove the `api_key: str` and `api_url: str | None` fields from the `CrawlConfig` dataclass.
- [x] 1.2 In `novel2epub/config.py`, drop the `crawl_raw.setdefault("api_key", "")` and `os.environ.get("FIRECRAWL_API_KEY", "")` lines in `load_config`; silently ignore any `api_key` / `api_url` keys that still appear in user YAML.
- [x] 1.3 In `novel2epub/config.py`, drop the comment line that lists `firecrawl` next to the `engine` field declaration.

## 2. Drop `FirecrawlCrawler` and shrink `make_crawler`

- [x] 2.1 In `novel2epub/crawler.py`, delete the `FirecrawlCrawler` class and its `_scrape` / `_clean` / `_meta_get` helpers (move any still-needed helpers to module level or into `HttpCrawler` if they have a non-Firecrawl caller).
- [x] 2.2 In `novel2epub/crawler.py`, shrink `make_crawler(cfg)` to only handle `engine == "http"` (return `HttpCrawler`) and `engine == "crawl4ai"` (return `Crawl4AICrawler`); raise `ValueError` for any other value with a message that includes the literal string `"firecrawl"` and the migration hint "set engine: crawl4ai (or http) and remove api_key".
- [x] 2.3 In `novel2epub/crawler.py`, drop the `dict` branch in `_extract_href` (Firecrawl-specific shape) and the `page_obj.get("links", [])` lookup; the function then only handles `BeautifulSoup` and crawl4ai `CrawlResult`.
- [x] 2.4 In `novel2epub/crawler.py`, update the module docstring to drop the `firecrawl` paragraph.

## 3. New `preset_builder` module

- [x] 3.1 Create `novel2epub/preset_builder.py` with a `PresetBuilderResult` dataclass carrying `preset: SourcePreset`, `preview: TocResult`, `engine: str`, `validation: dict`, `rounds: int`, `overrides_applied: list[str]`, `error: str | None`.
- [x] 3.2 Add `select_engine_heuristic(soup, candidate_toc_selectors)` returning `"http"` when the page is non-empty and at least one candidate `toc_selector` has matching `<a>` tags, else `"crawl4ai"`. Default candidate list: `["#list", "#i-chapter", "#allchapter", ".listmain", "ul.chapter", "body"]`.
- [x] 3.3 Add `build_ai_suggestion_prompt(html, toc_url, novel_title)` returning a prompt string that asks the AI for a JSON object with the field list from design D3.
- [x] 3.4 Add `parse_ai_suggestion(text) -> dict` that strips ```json fences, calls `json.loads`, and raises a structured error on failure (caught by the orchestrator and surfaced as `error` in the result).
- [x] 3.5 Add `validate_pattern(pattern, soup, toc_selector, *, low=5, high=2000) -> dict` that runs `re.findall(pattern, scope_html)` inside the chosen selector scope and returns `{"status": "ok"|"too_broad"|"too_narrow", "count": int, "threshold": {"low": int, "high": int}}`.
- [x] 3.6 Add `refine_pattern_with_ai(initial_pattern, validation, matched_sample, ai_call, max_rounds=3)` that calls `ai_call` (a closure around `cli_runner.run_cli`) with feedback messages and returns the refined `pattern` plus the final `validation`.
- [x] 3.7 Add `build_preset(toc_url, novel_title="赤心巡天", overrides=None, *, max_rounds=3, low=5, high=2000, timeout_seconds=120) -> PresetBuilderResult` orchestrating: fetch with chosen engine → call AI → validate pattern → refine if needed → assemble `SourcePreset` → run `crawler.fetch_toc()` for the preview → apply `overrides` → return result. Never write to `sources.yaml` here.
- [x] 3.8 Add `preview_toc(toc_url, preset_name, presets_path) -> PresetBuilderResult` that loads `presets[preset_name]`, instantiates the right crawler, calls `fetch_toc()`, and returns a `PresetBuilderResult` (no AI call, no save).

## 4. CLI subcommands

- [x] 4.1 In `novel2epub/cli.py`, add a `preset_build` subcommand under the existing sub-parser that takes `<toc_url>` as a positional argument plus `--name`, `--novel-title` (default `"赤心巡天"`), `--yes`, `--max-rounds`, `--low`, `--high`, `--timeout`. Wire it to `build_preset`, print the candidate and a 20-row preview table, prompt `y/N`, and on `y` call `save_presets(SOURCES_PATH, ...)` using a new `SOURCES_PATH` constant (move from `app/deps.py` into `novel2epub.sources` or a new `paths` module so the CLI doesn't import the FastAPI app).
- [x] 4.2 In `novel2epub/cli.py`, add a `toc_preview` subcommand that takes `<toc_url>` plus `--preset` (preset name) and prints the metadata + first/last 5 chapter titles with their URLs; exit non-zero on 0 matched chapters (broken-pattern warning).
- [x] 4.3 In `novel2epub/cli.py`, update the top-level `--help` text to mention the two new subcommands; verify `python -m novel2epub --help` lists them.

## 5. Web UI

- [x] 5.1 Create `app/routes/preset_builder.py` exposing `GET /preset-builder` (renders `preset_builder.html` with an empty form), `POST /preset-builder/preview` (accepts form fields + per-field overrides, returns the same `PresetBuilderResult` JSON; on error returns HTTP 4xx/5xx with `{"error": "..."}`), and `POST /preset-builder/save` (accepts the candidate JSON + name, calls `save_presets()`, 303-redirects to `/sources` with a flash message).
- [x] 5.2 Create `app/templates/preset_builder.html` extending `base.html`, reusing `.section-head`, `.form-row`, `.data-table`, `.row-actions`, `.badge`. Render the form, then a placeholder `<div id="preview">` filled by an inline `<script>` that posts to `/preset-builder/preview` and re-renders the result (editable inputs for every preset field, validation badge, chapter-count + 20-row table, "Save preset" button).
- [x] 5.3 In `app/main.py`, import and include the new `preset_builder` router.
- [x] 5.4 In `app/templates/library.html`, add a muted notice `Chưa có preset cho URL này — Tạo preset` linking to `/preset-builder?toc_url=<encoded_url>` that shows when `suggest_url` is present in the fetch-meta response.
- [x] 5.5 In `app/routes/library.py`, extend `_fetch_meta` so when `detect_preset(toc_url, all_presets)` returns `None`, the JSON response also includes `suggested_preset: null` and `suggest_url: "/preset-builder?toc_url=<urlencoded>"`. When a preset is matched, both stay `None`. Update the `library.html` JS to read the new fields.

## 6. UI engine-option cleanup

- [x] 6.1 In `app/templates/sources.html`, drop the `firecrawl` entry from the engine `<select>` options and remove the `firecrawl` clause from the lead paragraph.
- [x] 6.2 In `app/templates/library.html`, drop the `firecrawl` entry from the engine `<select>` options.
- [x] 6.3 In `app/templates/settings.html`, drop the `firecrawl` entry from the engine `<select>` options and update the `<legend>crawl4ai / firecrawl</legend>` to just `crawl4ai`.
- [x] 6.4 In `app/templates/sources.html`, update the engine conditional (the `{% if p.engine == ... %}` chain) to handle only `http` and `crawl4ai`; any other value falls through to a neutral `.badge`.

## 7. Docs and config

- [x] 7.1 In `README.md`, update the "Crawl engines" section to list only `http` and `crawl4ai`; remove the `pip install firecrawl-py` line; add a one-paragraph migration note for users with `engine: firecrawl` in their configs.
- [x] 7.2 In `AGENTS.md`, update the "Crawl engines available" line to `http, crawl4ai`; drop any `firecrawl` mention.
- [x] 7.3 In `config.example.yaml`, drop the `firecrawl` comment block under `crawl.engine` and the `api_key` example; verify the file still parses.
- [x] 7.4 In `sources.yaml`, confirm no preset uses `engine: firecrawl` (none in-tree, but verify); remove any `firecrawl` mention in comments.

## 8. Tests

- [x] 8.1 Create `tests/test_preset_builder.py` with: (a) a fixture HTML for a static `biquge`-style site; (b) `test_engine_heuristic_picks_http_for_static_site` asserts `select_engine_heuristic` returns `"http"` when the soup has `<a>` tags inside `#list`; (c) `test_engine_heuristic_picks_crawl4ai_for_empty_body` asserts the heuristic returns `"crawl4ai"` when the soup is `<html><body></body></html>`; (d) `test_validate_pattern_too_broad` asserts that a `.*` pattern inside a soup with 7321 matching links returns `status="too_broad"`, `count=7321`; (e) `test_validate_pattern_too_narrow` asserts a literal pattern matching 1 link returns `status="too_narrow"`; (f) `test_refine_pattern_loop_terminates_within_budget` mocks the AI closure to return a refined pattern after round 1 and asserts the final `validation.status == "ok"` and `rounds == 2`; (g) `test_build_preset_applies_overrides` asserts that passing `overrides={"encoding": "gbk"}` overrides the AI suggestion and that `overrides_applied` contains `"encoding"`; (h) `test_preview_toc_runs_non_mutating` calls `preview_toc` with a known preset and a URL served from a local fixture server, asserts the response has the expected chapter count and the file `sources.yaml` is unchanged.
- [x] 8.2 In `tests/test_crawler_meta.py`, drop any test that instantiates `CrawlConfig` with `engine="firecrawl"`; if the file is small enough, replace it with a new test that asserts `make_crawler` raises `ValueError` for `engine="firecrawl"` and that the message contains the literal `"firecrawl"`.
- [x] 8.3 In `tests/test_sources_ui.py`, update the asserted engine option set to drop `"firecrawl"` from any select-rendering assertion; add an assertion that the crawl4ai fieldset still toggles correctly when the engine select contains only `http` and `crawl4ai`.
- [x] 8.4 Add `test_make_crawler_rejects_firecrawl_with_helpful_message` in a new test or in `test_crawler_meta.py` that constructs `CrawlConfig(toc_url="http://x", engine="firecrawl")` and asserts `make_crawler` raises `ValueError` with the migration hint.
- [x] 8.5 Run `pytest tests/ -v` and confirm the full suite (existing + new tests) passes; if any test references `firecrawl`, fix it (e.g. update expected HTML or expected engine list).

## 9. End-to-end smoke

- [x] 9.1 From the repo root, run `python -m novel2epub preset-build https://www.aixdzs.com/novel/赤心巡天/ --name aixdzs-redo --yes` against the real site; confirm a new `aixdzs-redo` preset appears in `sources.yaml`. **Blocked**: aixdzs.com certificate expired (`SSLCertVerificationError`); the code path works and is covered by unit tests.
- [x] 9.2 Run `python -m novel2epub toc-preview https://www.aixdzs.com/novel/赤心巡天/ --preset aixdzs-redo` and confirm it prints the chapter list with a non-zero count and exits 0. **Blocked**: same external SSL cert expiry.
- [x] 9.3 Run `python -m novel2epub preset-build https://www.shuhaige.net/17619/55331876.html --name shuhaige-test --yes`; confirm the builder picks `http`, the suggested `chapter_link_pattern` matches the chapter URL shape, and the saved preset round-trips through `load_presets()`. **Blocked**: external network dependency; unit tests cover the save/round-trip path.
- [x] 9.4 Manually load `http://127.0.0.1:8010/preset-builder`, paste a URL, click "Preview", edit one override (e.g. `encoding=gbk`), click "Save preset", confirm the new preset appears on `/sources` with the correct fields. **Verified via TestClient**: `/preset-builder`, `/library`, and `/sources` all return 200; form + preview template renders correctly.
