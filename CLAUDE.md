<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/002-opencode-go-preset/plan.md
<!-- SPECKIT END -->

# novel2epub

Crawl Chinese web novels → translate to Vietnamese → build EPUB.

## Pipeline

```
TOC fetch -> crawl raw/*.md -> translate -> translated/*.md -> build -> .epub
```

## Key Commands

```sh
python -m novel2epub crawl          # crawl chapters
python -m novel2epub translate      # translate crawled chapters
python -m novel2epub build          # build EPUB
python -m novel2epub run            # crawl + translate + build

uvicorn app.main:app --reload --port 8010   # Web UI
pytest tests/ -v                             # run tests
```

## Architecture

- `crawler.py` — 3 engines: `http` (requests+BS4), `crawl4ai` (Playwright), `firecrawl` (API)
- `translator.py` — 4 backends: `openai` (OpenAI-Compatible HTTP API via `openai_client.py` — OpenAI, OpenRouter, Ollama, LM Studio, vLLM, llama.cpp server...), `google`, `moxhimt` (local NMT, CTranslate2 — runs offline, no API), `none`
- `config.py` — YAML config with dataclass models, preset merging, validation
- `pipeline.py` — Orchestrates crawl → translate → build + AI actions (review/suggest/rewrite/evaluate)
- `epub_builder.py` — EPUB via ebooklib with glossary footnotes
- `cli.py` — Argparse CLI with subcommands, range selection, sort/filter/search
- `app/` — FastAPI web UI (Jinja2 templates); chapter page is a 3-column editor (ZH source · VI machine-translation snapshot · editable "Biên tập" column with AI-edit button)
- `app/queue.py` — `JobQueue`: FIFO + configurable N worker threads per category (`crawl`, `translate`); `build`/`run` enqueue as a `both`-category job that waits for crawl+translate to go idle then blocks new crawl/translate starts until done. `app/job.py`'s `JobRunner` is a thin backwards-compatible shim over it.
- `app/scheduler.py` — `AutomationScheduler`: daemon thread polling `workspace/.n2e/automations.yaml` every ~30s, enqueues due automations' steps (sequential, as one `both`-category job) through `JobQueue`.
- `app/routes/storage.py` + `app/storage_report.py` — `/storage` page: per-ebook disk usage by raw/MT/translated/EPUB, purge actions, full-ebook `.zip` archive.
- `app/routes/automation.py` + `novel2epub/automation.py` — `/automation` page: CRUD automations (ebook, ordered steps from `fetch-toc`/`crawl-new`/`translate-pending`/`build`, `manual`|`daily@HH:MM` schedule), run-now.
- `app/library_state.py` — archived-ebook flags (`workspace/.n2e/library_state.json`), hides archived ebooks from `/` by default.
- `novel2epub/crawl_throttle.py` — `DomainRateLimiter` (jittered per-domain spacing) + `AdaptiveConcurrency` (backs off on 429/anti-bot bursts, recovers gradually); wired into `_crawl_chapters_parallel` in `pipeline.py`.

## Technical Notes

- `moxhimt` backend: `translate.type: moxhimt` runs `DanVP/MoxhiMT-60` (or compatible SentencePiece+CTranslate2 Marian model via `translate.moxhimt.model_id`) locally — NOT the HF Space demo. Lazy-downloads from HF Hub on first use. Optional deps: `ctranslate2 sentencepiece huggingface_hub`. Defaults are the best-quality config; default chunking is paragraph-level (falls back to sentence/char split when a paragraph exceeds the 512-token budget). CPU-only by design (no CUDA path) — parallelism comes from CTranslate2 `inter_threads`/`intra_threads` (default derived from `os.cpu_count()`) + batched `translate_batch` across a whole chapter in one call, NOT thread-per-chapter fan-out (`translate.max_workers` is forced to 1 for this backend; `openai`/`google` still honor it).
- Machine-translation snapshot: translating writes both `translated_mt/` (immutable MT snapshot, the "VI" column) and `translated/` (the edited copy, what build/EPUB reads). Old chapters without a snapshot degrade-fall-back to `translated` in the VI column.

- Crawl4AI 0.9.0: `magic` param goes inside `CrawlerRunConfig`, see `Crawl4AICrawler._run_cfg` in `crawler.py`
- Pagination: `crawl.next_page_selector` (CSS) or `crawl.next_page_url_pattern` (regex with 1 capture group)
- Crawl concurrency: `crawl.max_workers` requests N parallel threads but is capped per-source by `crawl.concurrency_cap` (0 = mode-aware default: 20 for `http`/scrapling `fetcher`, 5 for `crawl4ai`/scrapling `stealthy`/`dynamic` — see `CrawlConfig.effective_workers`). `SourcePreset.concurrency_cap` carries the same cap into site presets.
- Translation presets: `translate.preset: go` activates Go-optimized prompts via `presets/go.py`
- Config: single file `novel2epub.yaml` (gitignored) with 3 blocks — `defaults` (shared base), `sources` (site presets), `ebooks` (per-ebook overrides). Effective ebook config = `deep_merge(defaults, ebooks[slug])`. Committed template: `novel2epub.example.yaml`. Run a given ebook via `-e <slug>` / web `resolved_cfg(slug)`.
- `NovelConfig` carries EPUB publishing metadata: `publisher`, `pubdate`, `date_added` (auto-set once on ebook creation), `subjects` (list), `series`/`series_index`, `identifier` (auto-generated `urn:uuid:...` on first load if empty, then persisted — stable across rebuilds). `epub_builder.build_epub(..., metadata=cfg.novel)` maps these to Dublin Core + Calibre `meta name="calibre:..."` tags; empty fields are omitted.
- Workspace sidecar dir `workspace/.n2e/` (next to the unified YAML, gitignored) holds runtime/user state: `queue_history.json` (job queue history, JSON), `automations.yaml` (user-authored, ruamel round-trip), `library_state.json` (archived ebook slugs).
- ENV override: `NOVEL2EPUB_FILE` (path to the unified file; falls back to `NOVEL2EPUB_CONFIG`)
- One-off migration from the old multi-file layout: `python scripts/migrate_to_single_yaml.py`

## Tech Stack

Python 3.10+, FastAPI, ebooklib, requests+BS4, crawl4ai, deep-translator, PyYAML+ruamel, pytest
