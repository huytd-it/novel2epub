## 1. Job queue core (job-queue)

- [x] 1.1 Add `app/queue.py` with a `Job` dataclass (uuid, ebook, step, params, state, enqueue/start/end timestamps, error) and a `JobQueue` holding per-category FIFO pending lists + a bounded history deque, all guarded by one lock
- [x] 1.2 Implement a configurable pool of N daemon worker threads per category (`crawl`, `translate`) that dequeue FIFO; model `build`/`run` as a `both` job that acquires exclusive access to the categories it spans before running
- [x] 1.3 Implement lifecycle transitions (`pending`→`running`→`done`/`failed`/`cancelled`) reusing the existing `cancel_event` checkpoint pattern from `pipeline.py`
- [x] 1.4 Implement `enqueue`, `cancel(job_id)`, `retry(job_id)` (clones params into a new job), and `reorder(job_id, before_id)` for pending jobs
- [x] 1.5 Persist history to `workspace/.n2e/queue_history.json` on each terminal transition; load it on startup
- [x] 1.6 Refactor `JobRunner` to delegate to `JobQueue`, keeping `start`/`start_custom`/`request_cancel`/`status` working as thin shims
- [x] 1.7 Unit tests: second-job-enqueues, auto-start-on-free, crawl∥translate parallelism, N-worker concurrency within a category, both-slot mutual exclusion, cancel pending/running, retry, reorder, history cap

## 2. Queue API & enqueue semantics (job-queue)

- [x] 2.1 Add `GET /api/queue` returning `{categories, running, pending (with position), history}`
- [x] 2.2 Add control endpoints: cancel job, retry job, reorder pending job
- [x] 2.3 Change job-start routes in `app/routes/jobs.py` to always enqueue and return the new job id (303 redirect for forms, id in body/header for fetch); remove 409-on-busy
- [x] 2.4 Keep `GET /api/status` as a compatibility shim mapping the new payload to the old shape

## 3. UI shell & design system (ui-design-system)

- [x] 3.1 Rewrite `app/templates/base.html` into a shell with persistent sidebar/topbar nav (Library, Sources, Storage, Automation) and active-link marking
- [x] 3.2 Add design tokens (color/spacing/typography/radius) as CSS custom properties on `:root` with a `[data-theme="light|dark"]` override in `app/static/style.css`
- [x] 3.3 Add reusable component styles: card, table, badge, button, form-control, modal, toast
- [x] 3.4 Add theme toggle persisted to `localStorage` with a pre-paint inline head script to avoid FOUC; default to OS `prefers-color-scheme`
- [x] 3.5 Add `app/static/app.js` with toast helper and a shared queue indicator that polls `/api/queue` and renders running+pending count in the shell
- [x] 3.6 Use a fluid full-width layout for management/data views; cap chapter prose at a readable max-width; collapse nav on narrow viewports
- [x] 3.7 Verify existing pages (index, ebook, chapter, sources, settings, glossary, preset_builder) render correctly under the new shell

## 4. Ebook management (ebook-management)

- [x] 4.1 Rebuild `index.html` library as progress cards (title/author/cover, crawled C/N, translated T/N, EPUB present) with quick actions (open, settings, crawl/translate/build, download, remove-with-confirm)
- [x] 4.2 Add bulk selection + bulk action route that enqueues the chosen job per selected ebook
- [x] 4.3 Add archive/unarchive: store archived slugs in `workspace/.n2e/library_state.json`; hide archived by default with a "show archived" toggle; routes for archive/unarchive
- [x] 4.4 Add config export (download effective ebook config) and import (create ebook from uploaded config) endpoints + UI

## 5. Source management (source-management)

- [x] 5.1 Add clone-preset action and surface using-ebooks before delete confirmation in `app/routes/sources.py` + `sources.html`
- [x] 5.2 Add a preset dry-run test (reuse `make_crawler`+`fetch_toc`+one `fetch_chapter`, write nothing) run as a short background job; report title, chapter count, sample content, or failure reason
- [x] 5.3 Add export-presets (download) and import-presets (upload, merge-by-name with overwrite/rename on collision) endpoints + UI
- [x] 5.4 Show last-validation outcome per preset alongside existing usage list

## 6. Crawl management (crawl-management)

- [x] 6.1 Add a crawl console section to `ebook.html` showing per-chapter status: not-fetched / fetched / fetched-but-empty (empty = raw below minimal threshold)
- [x] 6.2 Compute and surface gaps (missing chapters within crawled range) and the failed/empty set as one actionable list
- [x] 6.3 Add "retry failed" action that enqueues a crawl job whose `selected_indexes` are exactly the failed/empty/missing chapters
- [x] 6.4 Surface engine/delay/retry/force as first-class per-run controls that override stored defaults for that run only (build on existing `crawl-range` route)
- [x] 6.5 Add a per-source concurrency cap to `SourcePreset`/`CrawlConfig` with mode-aware defaults (high for `fetcher`, low for `stealthy`/`dynamic`); wire it into `_crawl_chapters_parallel`
- [x] 6.6 Add a per-domain token-bucket rate limiter with jittered delay shared across a job's crawl workers
- [x] 6.7 Add an adaptive controller that reduces effective concurrency on a burst of 429/anti-bot responses and recovers gradually; keep existing exponential backoff + `Retry-After`
- [x] 6.8 Unit tests: per-source cap never exceeded, backoff reduces concurrency on 429 burst, Retry-After honored

## 6b. Translation concurrency (moxhimt-translator)

- [x] 6b.1 Add `inter_threads`/`intra_threads` to `MoxhiMTConfig` with defaults derived from `os.cpu_count()` so `inter × intra ≤ physical cores`; pass them to the CTranslate2 `Translator`
- [x] 6b.2 Refactor `MoxhiMTTranslator` to translate chunks via `translate_batch` (batched), preserving order, paragraph structure, chunk fallback, and glossary post-processing
- [x] 6b.3 Ensure moxhimt translate jobs rely on CT2 batching/threads rather than `translate.max_workers` thread-per-chapter fan-out; keep `max_workers` fan-out for `cli`/`google`
- [x] 6b.4 Tests: batched result equals sequential result; inter/intra defaults respect core count; cli/google still honor `max_workers`

## 6c. EPUB metadata (ebook-metadata)

- [x] 6c.1 Extend `NovelConfig` with `publisher`, `pubdate`, `date_added` (auto on create), `subjects` (list), `series`, `series_index`, `identifier` (auto `urn:uuid` when empty, persisted) plus existing `description`/`language`
- [x] 6c.2 Update config load/write (`config.py`, `config_writer.py`) and the ebook settings form to read/edit the new fields
- [x] 6c.3 Update `epub_builder.py`: emit `dc:identifier` as `urn:uuid:…` (replace hardcoded `novel2epub-{slug}`), `dc:publisher`, `dc:date`, one `dc:subject` per subject, and Calibre `series`/`series_index`/`timestamp` meta; omit empty fields
- [x] 6c.4 Display derived EPUB file size in the ebook/storage views (not an editable field)
- [x] 6c.5 Tests: populated fields appear in the built EPUB; identifier stable across rebuilds; empty fields omitted

## 7. Storage management (storage-management)

- [x] 7.1 Add `app/storage_report.py` that walks each ebook's raw/translated_mt/translated dirs + epub path and sums sizes by category and overall
- [x] 7.2 Add `GET /storage` page + route showing per-ebook breakdown and aggregate total
- [x] 7.3 Add confirmed cleanup actions (purge raw, purge MT snapshots, remove EPUB) that never touch edited translations; routes name what will be deleted
- [x] 7.4 Add full-ebook archive bundle (config + artifact dirs) via stdlib `zipfile` as a single download

## 8. Automation & scheduling (automation-scheduling)

- [x] 8.1 Define automation model (ebook, ordered steps from {fetch-toc, crawl-new, translate-pending, build}, schedule = daily@HH:MM | manual, enabled, last_run time+outcome) persisted to `workspace/.n2e/automations.yaml`
- [x] 8.2 Add CRUD routes + `/automation` page to create/edit/enable/disable/delete automations and view last-run status
- [x] 8.3 Add `app/scheduler.py` daemon thread that polls due automations and enqueues their steps in order **through the job queue**; start it from `app/main.py` lifespan
- [x] 8.4 Add run-now endpoint; derive and persist last-run outcome (success/failure/partial) from the terminal states of the enqueued steps

## 9. Cutover & cleanup

- [ ] 9.1 Update `index.html`/`ebook.html` polling JS from `/api/status` to `/api/queue` (queue panel: positions, progress, cancel/retry/reorder)
- [ ] 9.2 Remove the `/api/status` shim and dead/ad-hoc CSS once all templates use the new shell and queue payload
- [x] 9.3 Manual verification pass with `uvicorn app.main:app --reload --port 8010`: enqueue multiple jobs, cancel/retry/reorder, run a source test, view storage, create+run an automation
- [x] 9.4 Update `CLAUDE.md` Architecture/Technical Notes with the queue, scheduler, `.n2e/` sidecar, and new pages
