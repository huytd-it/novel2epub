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
- `translator.py` — 4 backends: `openai` (OpenAI-Compatible HTTP API via `openai_client.py` — OpenAI, OpenRouter, Ollama, LM Studio, vLLM, llama.cpp server...), `google`, `moxhimt` (local NMT, CTranslate2 — runs offline, no API), `none`. Vietnamese-source novels (no translation needed): `translate.source_language: vi` forces `NoopTranslator` regardless of `type` — translate step copies raw verbatim into `translated/`+`translated_mt/` (so build/editor still work), title paths (Dịch TOC / dịch lại tiêu đề) are skipped via `pipeline._translate_is_noop`; UI option "Việt (không cần dịch)" in Settings→Dịch.
- `config.py` — YAML config with dataclass models, preset merging, validation
- `pipeline.py` — Orchestrates crawl → translate → build + AI actions (review/suggest/rewrite/evaluate)
- `epub_builder.py` — EPUB via ebooklib with glossary footnotes
- `bulk_transfer.py` — pure helpers for bulk AI-editing/translation round-trip, Markdown-based (better for AI parsing + can be saved/uploaded as `.md`): `build_export` (chapters as `## idx:N` headings + existing glossary as one flat `- Hán = Việt` list, prepended with either `EDIT_PROMPT` — biên tập bản dịch, distilled from `docs/rule.md` — or `TRANSLATE_PROMPT` — dịch từ raw, principles mirrored from `config.DEFAULT_PROMPT` so manual web-chat translation stays consistent with the in-app AI backend), `parse_import` (split edited/translated text back to `(index, title, content)` — title is the part after `## idx:N:`, `""` if absent; N is the MANIFEST index/position, which may differ from the chapter number inside the title itself; marker uses `idx:N` rather than `Chương N` specifically so the AI doesn't confuse this position index with the real chapter number that often appears inside the title text itself (e.g. `第1338章`); also recognizes legacy `## Chương N` and `===== CHƯƠNG N =====` markers for back-compat), `parse_glossary` (collect AI-emitted `## GLOSSARY` section into ONE flat dict — names/vietphrase classification is gone; legacy `### NAMES`/`### VIETPHRASE` subheadings in old exports still parse, everything lands in the single canonical list `names.txt`; old `vietphrase.txt` data is read merged and lazily consolidated into names.txt on web-Glossary save/import), `validate_import` (matched/missing/extra/unknown vs manifest). `POST .../batch/export` (manual "Xuất RAW" preview) and `POST .../batch/translate` (auto Xuất RAW → AI → Nhập job) both build the export through the same `build_export`/`chapter_marker`, so the preview always matches exactly what the job sends. `batch/export` takes `source=translated|raw` (translated = biên tập existing `translated/`; raw = dịch `raw/` for chapters never translated or to retranslate); confirm-import backfills `translated_mt/` only when a chapter has none yet (first translation via this round-trip), otherwise preserves it untouched (editing pass). `POST .../batch/translate` additionally overwrites manifest chapter `title` from the AI-translated heading title (backfills `title_zh` with the old title when empty; matches by marker N = manifest index only; `ensure_title_number` re-prefixes the REAL chapter number from the ZH title — `第M章/卷/回` → `Chương/Quyển/Hồi M:` — because AI often drops it or echoes the position index instead); manual `batch/import` does NOT touch titles. Web routes in `app/routes/chapters.py` do the I/O; `app/templates/ebook.html` opens export/import in a separate browser window (not a `<dialog>` — Pico CSS v2 requires `<dialog>` content wrapped in `<article>` or it renders as a blank full-viewport flex container) with copy/download-`.md`/upload-file affordances.
- `cli.py` — Argparse CLI with subcommands, range selection, sort/filter/search
- `app/` — FastAPI web UI (Jinja2 templates); chapter page is a 3-column editor (ZH source · VI machine-translation snapshot · editable "Biên tập" column with AI-edit button). Glossary edit flow v2: mọi chỗ sửa glossary (bảng Glossary, popover bôi đen trên trang chương) dùng chung pattern "sửa → đếm khớp (`glossary/match-count`) → chọn phạm vi lan truyền (`glossary/propagate`, scope=chapter đồng bộ / scope=all qua job step_find_replace)"; trang Glossary có bulk delete + tab Nghi vấn (`glossary/suspects` từ `novel2epub/glossary_review.py` thuần + `conflicts/resolve` persist); modal "Áp dụng lại" và 2 route reapply đã bỏ.
- `app/queue.py` — `JobQueue`: FIFO + configurable N worker threads per category (`crawl`, `translate`); `build`/`run` enqueue as a `both`-category job that waits for crawl+translate to go idle then blocks new crawl/translate starts until done. `app/job.py`'s `JobRunner` is a thin backwards-compatible shim over it.
- `app/scheduler.py` — `AutomationScheduler`: daemon thread polling automations (DB) every ~30s, enqueues due automations' steps (sequential, as one `both`-category job) through `JobQueue`. Lịch = cron 5 trường (croniter), due-check stateless từ `last_run_at`/`created_at` — lỡ mốc chạy bù tối đa 1 lần; legacy `daily@HH:MM`/`continuous@N` được `load_automations` tự migrate sang cron; `_tick` bọc try/except từng automation (1 cái hỏng không giết vòng poll).
- `novel2epub/service.py` — CLI `python -m novel2epub service install|uninstall|status`: đăng ký web server chạy nền khi khởi động máy (Windows Task Scheduler ONLOGON qua `start_server.cmd`, Linux systemd user service); phần sinh nội dung là hàm thuần để test không đụng OS.
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
- Config: unified SQLite DB with 3 layers — `settings` table (`defaults`, shared base), `sources` (site presets), `ebooks` (per-ebook overrides, incl. `translate_overrides_json`/`ai_overrides_json`). Effective ebook config = `deep_merge(defaults, ebooks[slug])` for ALL sections — `translate` (AI dịch) and `ai` (AI biên tập) are per-ebook like everything else; `defaults` is only the fallback for ebooks with no override and the value restored by the Settings "↺ Reset về config chung" buttons (crawl reset returns to source preset instead, keeping `toc_url`). Web Settings tabs save via `config_writer.update_ebook`; only the Reader connection block (url/service_key/timeout/batch_size, `READER_GLOBAL_FIELDS`) stays global via `update_defaults`. Default translate backend: `openai` @ `http://localhost:20128/v1`, model `free-stack`, timeout_seconds 120000; `reader.slug` defaults to the ebook slug at load. Run a given ebook via `-e <slug>` / web `resolved_cfg(slug)`.
- `NovelConfig` carries EPUB publishing metadata: `publisher`, `pubdate`, `date_added` (auto-set once on ebook creation), `subjects` (list), `series`/`series_index`, `identifier` (auto-generated `urn:uuid:...` on first load if empty, then persisted — stable across rebuilds). `epub_builder.build_epub(..., metadata=cfg.novel)` maps these to Dublin Core + Calibre `meta name="calibre:..."` tags; empty fields are omitted.
- Workspace sidecar dir `workspace/.n2e/` (next to the unified YAML, gitignored) holds runtime/user state: `queue_history.json` (job queue history, JSON), `automations.yaml` (user-authored, ruamel round-trip), `library_state.json` (archived ebook slugs).
- ENV override: `NOVEL2EPUB_FILE` (path to the unified file; falls back to `NOVEL2EPUB_CONFIG`)
- One-off migration from the old multi-file layout: `python scripts/migrate_to_single_yaml.py`

## Tech Stack

Python 3.10+, FastAPI, ebooklib, requests+BS4, crawl4ai, deep-translator, PyYAML+ruamel, pytest
