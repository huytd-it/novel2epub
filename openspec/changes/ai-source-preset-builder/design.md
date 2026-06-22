## Context

`novel2epub` already has a working crawl layer (`HttpCrawler`, `Crawl4AICrawler`, soon-to-be-removed `FirecrawlCrawler`) and a `SourcePreset` registry loaded from `sources.yaml`. Adding a new site today means a human reads the page HTML, guesses CSS selectors, hand-crafts a `chapter_link_pattern` regex, and writes a new YAML block. The painful part is the regex: a too-broad pattern (`.*`, `\.html$`) silently matches header / footer / tag links, returning thousands of bogus chapter URLs and breaking the pipeline downstream; a too-narrow pattern (`chapter1\.html` literal) yields one chapter. The natural-source list in `docs/source.md` has 30+ candidate sites; the manual workflow does not scale.

At the same time, `firecrawl-py` is paid and the `firecrawl` engine adds a third code path that the `http` + `crawl4ai` pair already covers for the in-repo use-cases. Simplifying down to those two engines removes a dep, shrinks `CrawlConfig`, and clears confusion in the Web UI.

Constraints: must run on Windows (existing dev machine), must not require `firecrawl-py`, must reuse the existing `cli_runner` + `presets.go` AI CLI infra, must preserve the byte-level `sources.yaml` round-trip (handled by `ruamel.yaml` in `novel2epub/sources.py`).

## Goals / Non-Goals

**Goals:**
- Drop-in `novel2epub preset-build <url>` flow that takes a TOC URL, returns a `SourcePreset` candidate + a previewed chapter list, and (after a single keystroke) persists it to `sources.yaml`.
- A non-mutating `toc-preview` flow that re-runs an existing preset against a URL so the user can verify a regex in seconds.
- Validation loop: AI's suggested `chapter_link_pattern` is checked by counting matches in the chosen `toc_selector`; too broad / too narrow triggers a refinement round (≤3).
- Per-field overrides for special cases (encoding, `js_code`, `magic`, `headless`, `user_agent`, pagination knobs).
- Web UI at `/preset-builder` mirroring the CLI, plus a "Tạo preset" link in the library add form when no preset matches the pasted URL.
- Drop `firecrawl` engine, `api_key` / `api_url` from `CrawlConfig`, and the related UI / docs / comments.

**Non-Goals:**
- No new runtime dependency. AI inference goes through the existing `cli_runner` (already wraps `opencode run` / `claude -p`).
- No changes to the existing `toc`, `crawl`, `translate`, `build` CLI subcommands — `preset-build` and `toc-preview` are strictly additive.
- No bulk-import wizard. The "drive from `docs/source.md`" angle is left to the user invoking the CLI per URL.
- No auto-save. Every write is gated by a confirmation step (`y/N` or `--yes`).
- No multi-tenant / cloud-mode concerns — this is a single-user local tool.

## Decisions

### D1 — New module `novel2epub/preset_builder.py` for the AI flow
The preset builder lives in a dedicated module rather than being bolted onto `sources.py` or `crawler.py`. `sources.py` stays a pure data layer (load/save/detect), `crawler.py` stays the engine runtime, and the AI orchestration — engine selection, prompt construction, validation loop, save prompt — sits in `preset_builder.py`. **Why:** keeps the data layer testable without a CLI, keeps the engine runtime free of LLM concerns, and lets the Web UI / CLI both import the same function. **Alternative considered:** put the flow inside `cli.py` — rejected because the Web UI also needs it.

### D2 — Engine heuristic: HTTP first, then `crawl4ai` on insufficiency
The builder runs `HttpCrawler` first, parses the page, picks the longest plausible `toc_selector` (the one whose `<a>` count is highest and >0), and counts how many of its links match the AI-suggested `chapter_link_pattern`. If the count is in `[5, 2000]` the engine stays `http`; if the count is 0 or the response looks JS-shell-only (no `<a>` in any common `toc_selector` candidate, or the page body is shorter than 2 KB), the heuristic re-runs with `Crawl4AICrawler` (`magic=True`, `headless=True`). **Why this order:** the `http` engine is free and fast, and most of `docs/source.md` is static. The `crawl4ai` fallback covers SPA / lazy-load sites. **Alternative considered:** always use `crawl4ai` — rejected as wasteful (5–10 s overhead per site) and harder to reason about for the simple static case.

### D3 — AI suggestion via a single structured prompt, not a chain
The prompt asks the AI to return a JSON object with keys `toc_selector`, `content_selector`, `chapter_link_pattern`, `chapter_title_selector`, `title_selector`, `author_selector`, `desc_selector`, `cover_selector`, `engine` (`http` | `crawl4ai`), `headless` (bool), `magic` (bool), `js_code` (string), `encoding` (string), `delay_seconds` (number), and a one-line `reasoning`. The CLI is called with the raw HTML (truncated to `ai_fallback_max_html` from the existing config), the URL, the host (so the AI can see the slug pattern), and the `novel_title` (default `赤心巡天`). **Why a single prompt rather than a chain of one-shot calls:** fewer round-trips, fewer rate-limit issues, and the AI can reason about the page holistically. **Alternative considered:** a multi-step `select_engine → select_toc → select_pattern` chain — rejected as over-engineered for the page sizes here (most are < 200 KB).

### D4 — Pattern validation with explicit bounds
Validation counts `len(re.findall(chapter_link_pattern, soup.select_one(toc_selector).decode() if toc_selector else soup.decode()))` for the chosen selector scope. Bounds: `low=5`, `high=2000`, both configurable via request parameters. `too_broad` and `too_narrow` triggers a refinement prompt that includes the count and a sample of the matched URLs (first 20). **Why explicit bounds rather than ratios:** a "ratio of matched links to total" depends on knowing the total number of chapters, which is exactly what we are trying to discover. A fixed window around the expected chapter count of a typical novel is more robust. **Alternative considered:** an unbounded refinement — rejected, runaway AI cost.

### D5 — Overrides are first-class request fields, not post-hoc edits
`build_preset(toc_url, overrides={"encoding": "gbk", "js_code": "..."})` passes overrides into the candidate before preview. The overrides are recorded in the response under `overrides_applied` so the user can audit what the AI would have done vs. what actually went into the preset. **Why:** sites like `shuhaige` need `encoding` defaulted by the user (HTML is GBK) and sites with infinite-scroll TOCs need `js_code` set; baking these into "post-edit" steps would hide them from the audit trail. **Alternative considered:** mutate `preset.*` in the UI after the response — rejected because the preview then needs to be re-run, doubling the cost.

### D6 — Non-mutating `toc-preview` reuses the same path, skips the AI
`toc-preview <url> --preset <name>` instantiates the saved preset, runs `make_crawler`, calls `crawler.fetch_toc()`, and prints the metadata + chapter list (first/last 5 with titles, full count). No AI call. **Why separate command:** it is the cheap, post-hoc verification path; mixing it into `preset-build` would mean the user pays the AI cost every time they want to check a regex. **Alternative considered:** a `--verify-only` flag on `preset-build` — rejected because the same logic is also a button on the Web UI, so a dedicated endpoint is cleaner.

### D7 — Drop `firecrawl` engine and `api_key` / `api_url`
`make_crawler` now raises `ValueError` for anything other than `http` / `crawl4ai`; the error message explicitly mentions `firecrawl` and the migration (`set engine: crawl4ai (or http) and remove api_key`). `CrawlConfig.__init__` no longer accepts `api_key` / `api_url`; `load_config` silently ignores those keys in YAML. `FirecrawlCrawler` and any helper that has no other caller (`_scrape`, `_meta_get` if orphaned) are deleted. **Why this is the right time:** the AI-preset-builder is itself a proof that `crawl4ai` + the `ai_fallback` HTML-to-text path cover the same jobs that `firecrawl` did.

### D8 — Web UI uses the existing CSS conventions, not a new layout
The `/preset-builder` page reuses `.section-head`, `.form-row`, `.data-table`, `.row-actions`, and `.badge` from `app/static/style.css`. The form posts JSON to `/preset-builder/preview` (returns the same `PresetBuilderResult` as the CLI), which the page then renders into an editable candidate + preview table. The save button posts the edited JSON to `/preset-builder/save`, which calls `save_presets()` and 303-redirects to `/sources` with a flash. **Why mirror the CLI's payload:** the JS-side rendering is a thin wrapper around the same data, and the same payload can be served to a future mobile / desktop client.

### D9 — `library._fetch_meta` extension stays backward compatible
The function gains two new optional keys in its JSON response: `suggested_preset: null` and `suggest_url: null`. Existing callers (`library.html` JS) ignore unknown keys, so the change is additive. The library template shows a single line of muted text + link only when `suggest_url` is set. **Why a new flag rather than reusing `preset`:** the existing `preset` field semantically means "preset the user should auto-select", and conflating "no preset exists" with "use this preset" would be confusing.

### D10 — Refinement budget is configurable per request, default 3
`refinement_rounds: int = 3` is a request field. The 3-round default covers the bulk of sites in `docs/source.md` (sto9, aixdzs, qidian, 69shuba) while bounding worst-case cost. The Web UI exposes this as an "Advanced" field; the CLI flags it as `--max-rounds N`.

## Risks / Trade-offs

- **[Risk] AI suggestion quality varies by model / page complexity** → Mitigation: the validation loop with `[5, 2000]` bounds catches the worst failures (over-broad / over-narrow). The "User can override" requirement (D5) means a failure is never blocking — the user can paste their own regex.
- **[Risk] `crawl4ai` is heavy (5–10 s per site) and requires a Chromium install** → Mitigation: `http` is tried first, so simple sites skip the browser entirely. The CLI is open about the engine it picked and the time spent, so the user can opt out.
- **[Risk] AI CLI call adds 20–60 s of latency per round** → Mitigation: the Web UI shows a spinner with the current round number; the CLI prints `[round 2/3]` progress. `timeout_seconds` is set to 120 by default and surfaced in the response.
- **[Risk] Removing `firecrawl` breaks any user who set `engine: firecrawl`** → Mitigation: `make_crawler` raises an explicit `ValueError` with a migration hint. README documents the change. The spec for `firecrawl-removal` lists the migration path.
- **[Risk] YAML round-trip with `ruamel.yaml` may not preserve formatting of `sources.yaml` after a `save_presets()` call that adds a new preset** → Mitigation: `save_presets()` already merges with the existing `CommentedMap`, so existing comments / key order are kept. The builder writes only the new preset and lets `save_presets()` merge it in.
- **[Risk] AI might output an invalid `chapter_link_pattern` that `re.compile` rejects** → Mitigation: `CrawlConfig.__post_init__` already validates the pattern and raises a `ValueError`; the builder catches that and routes the error back through the AI refinement loop.
- **[Risk] Race when two presets for the same host are saved** → Mitigation: `save_presets()` reads-modifies-writes inside the process; the Web UI and the CLI both run as single-user local tools, so concurrency is not a concern in the in-repo deployment.

## Migration Plan

1. Land the code changes (preset builder module, CLI subcommand, Web UI route, `firecrawl` removal in crawler / config / templates / docs).
2. Update `sources.yaml` if any preset is set to `engine: firecrawl` (none in-tree; documented in README for downstream users).
3. Update `README.md` "Crawl engines" section to list only `http` and `crawl4ai`, plus a one-paragraph migration note for `firecrawl` users.
4. Run `pytest tests/ -v` and confirm the new tests pass and the existing `test_crawler_meta.py` / `test_sources_ui.py` still pass after the engine-list updates.
5. Roll out to the local dev environment, run `novel2epub preset-build https://www.aixdzs.com/novel/赤心巡天/` end-to-end, confirm the resulting preset is committed to `sources.yaml` and the saved preset round-trips through `load_presets()`.
6. Rollback: revert the commits. No data migration is needed because `sources.yaml` is the single source of truth and the schema is unchanged for the remaining fields.

## Open Questions

- Should the Web UI's "Save preset" button also write a `library.ebooks` entry, or strictly the preset? Current plan: strictly the preset (D8) — the user clicks through to `/library/ebooks` to scaffold a new ebook after the preset exists. Confirm with product before implementation.
- Should `crawl4ai` fallback be triggered by content length, by absence of `<a>` tags, or both? Current heuristic uses both (`page_body < 2 KB OR no <a> in any candidate toc_selector`); could be tunable per request. Defer to implementation.
- Do we want to surface a per-URL "engine telemetry" log (HTTP 200 vs 403, content-length, number of redirects) for debugging? Current plan: no — keep the Web UI focused on the preview, put telemetry under a `verbose` flag in the CLI.
