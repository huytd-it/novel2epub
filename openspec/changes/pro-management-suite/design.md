## Context

The web UI (`app/`) is a FastAPI + Jinja2 app whose state lives entirely on disk under the workspace (novels in `data/`, presets, and a single unified `novel2epub.yaml`). Background work is run by `app/job.py:JobRunner`, which holds **two fixed slots** (`crawl`, `translate`); `build`/`run` occupy both. A second job in a busy category is rejected — routes turn that into HTTP 409. The frontend polls `GET /api/status` every 1.5 s and patches the library region via DOM replacement. The shell is a 23-line `base.html` with two nav links and a 209-line ad-hoc `style.css`.

This change is cross-cutting: it rewrites the job runner, adds new persistent state (queue history, automations, archived flags), introduces a scheduler thread, and reskins every page. It therefore warrants a design doc to lock decisions before coding.

Constraints: single-process, single-user, local-first; no database; Windows-friendly (paths, no POSIX-only assumptions); keep the existing pipeline/crawler/translator/epub modules untouched.

## Goals / Non-Goals

**Goals:**
- Replace reject-when-busy with a real FIFO queue while preserving the two-category parallelism (crawl ∥ translate) that `job.py` already documents.
- Provide a cohesive, themeable UI shell and component set without adopting a heavy frontend framework or build step.
- Add management surfaces (ebook/source/crawl/storage/automation) that operate on existing on-disk data via thin new modules.
- Keep all new persistence as human-readable files under the workspace; no migration of existing novel data.

**Non-Goals:**
- No multi-user auth, no remote/multi-process workers, no real database.
- No changes to crawl engines, translator backends, or the EPUB builder.
- No SPA rewrite; progressive enhancement over server-rendered HTML stays the model.

## Decisions

### D1 — Queue model: one worker thread per category, in-memory queue + persisted history
Keep the two execution categories (`crawl`, `translate`); `build`/`run` acquire both (modeled as a `both` job that needs both category locks). Each category gets a `queue.Queue`-backed worker thread that pulls `pending` jobs FIFO. Jobs are dataclasses with a UUID, state, params, and timestamps, held in an ordered registry behind the existing `JobRunner._lock`.
- *Why:* preserves current concurrency semantics and the cooperative `cancel_event` checkpoint pattern already in `job.py`/`pipeline.py`; minimal new concepts.
- *Alternatives:* a single global worker (loses crawl∥translate parallelism — rejected); `concurrent.futures` pool (harder to express the "build needs both slots" mutual exclusion and reordering — rejected).
- Reorder = mutate the pending list under the lock before the worker dequeues; the worker re-checks the head each iteration.
- History is a bounded deque persisted to `workspace/.n2e/queue_history.json` on each terminal transition so it survives restarts.

### D2 — Enqueue semantics & API (BREAKING)
Job-start routes change from "409 if busy" to "always enqueue, return the job id". Browser form posts keep redirecting (303) but with a toast-friendly flash; programmatic callers get the id. `GET /api/status` is superseded by `GET /api/queue` returning `{categories, running, pending, history}`; `/api/status` is kept as a thin compatibility shim during transition.
- *Why:* the whole UX premise is "fire many jobs and walk away".
- *Migration:* update `index.html`/`ebook.html` polling JS to the richer payload; keep `/api/status` mapping until templates are cut over, then remove.

### D3 — Persistence: a `.n2e/` sidecar dir, JSON for runtime state, YAML for user-authored config
New runtime/user state lives under `workspace/.n2e/`: `queue_history.json`, `automations.yaml`, and an `archived` list (in `automations.yaml` or a small `library_state.json`). Presets continue to use the existing sources file. Automations are user-authored → YAML (ruamel, consistent with the rest of the project); history is machine-written → JSON.
- *Why:* no DB dependency; matches the project's existing YAML-config idiom; easy to inspect/edit/back up.
- *Alternatives:* SQLite (overkill for single-user, adds a dep surface — rejected).

### D4 — Scheduler: one daemon thread polling due automations
A `scheduler.py` daemon wakes on a coarse interval (e.g. 30 s), evaluates each enabled automation's next-due time, and enqueues its steps **through the queue** (satisfying the automation-scheduling spec's "honor the queue" requirement). Schedules are stored as a simple recurrence (daily at HH:MM, or manual). Last-run outcome is derived from the terminal states of the jobs it enqueued.
- *Why:* `sched`/cron libs add deps and process assumptions; a poll loop is trivial and robust to sleep/wake.
- *Risk handled:* missed ticks while the app was down simply run at next due time (no catch-up storms).

### D5 — Frontend: server-rendered shell + small vanilla JS, CSS custom properties for theming
Introduce design tokens as CSS custom properties on `:root` with a `[data-theme]` override; theme choice stored in `localStorage` and applied pre-paint by a tiny inline script. Components are plain CSS classes (cards, badges, table, btn, modal, toast). One shared `app.js` provides toast + queue-poll helpers; `log-panel.js` is reused. No bundler.
- *Why:* keeps the zero-build, progressive-enhancement model; theming via custom properties is the lightest robust option.
- *Alternatives:* Tailwind/Bootstrap/htmx (build step or new dep, larger churn — rejected for now; htmx could be a later enhancement).

### D6 — Source test = dry-run over the existing crawler
Preset validation reuses `make_crawler` + `fetch_toc` (as `_fetch_meta` in `library.py` already does) plus a single `fetch_chapter` on the first TOC entry, writing nothing to `Storage`. Runs as a short-lived background job so blocking/anti-bot waits don't hang the request.
- *Why:* reuses proven crawl paths; "no chapter files written" is satisfied by simply not calling Storage writers.

### D7 — Storage report & cleanup operate on `Storage` paths directly
A `storage_report.py` walks each ebook's `raw/`, `translated_mt/`, `translated/`, and the epub path, summing sizes by category. Cleanup deletes within those category dirs only; archive bundles config + dirs via stdlib `zipfile`.
- *Why:* stdlib only, mirrors the directory contract documented in CLAUDE.md (MT snapshot vs edited copy).

### D8 — Crawl concurrency: per-source pool + adaptive anti-block throttle
The parallel path already exists (`_crawl_chapters_parallel`, one crawler per worker thread). This change makes it first-class and **safe**: concurrency is capped **per source** (preset field), not globally, because the binding constraint is the target site, not the 20-core CPU. Add a per-domain token-bucket rate limiter with jittered delay shared across the worker threads of a job, and an **adaptive controller** that halves effective concurrency on a burst of 429/anti-bot errors and recovers slowly. Existing exponential backoff + `Retry-After` handling is retained.
- *Hardware reality:* `fetcher` (HTTP+TLS impersonate) is light → tens of concurrent workers are fine; `stealthy`/`dynamic` spin a browser each (~300–600 MB) → cap at ~4–6 given ~8 GB free RAM. Defaults are mode-aware.
- *Why per-source:* one global number either blocks aggressive sites or throttles tolerant ones; the cap belongs with the preset that knows the site.
- *Alternatives:* a fixed global `max_workers` (current) — kept as a fallback default but overridable per source.

### D9 — Translation concurrency: CTranslate2 batching on CPU, not thread-per-chapter
**No CUDA GPU on this machine** (Intel UHD only) → moxhimt runs on CPU; `device` stays `cpu`. The `translate.max_workers` thread fan-out is fine for `cli`/`google` (I/O-bound subprocess/HTTP) but counter-productive for moxhimt on CPU (oversubscription). For moxhimt, parallelism is expressed via CTranslate2's own scheduler: `intra_threads` (cores per translation) and `inter_threads` (parallel translations), with paragraphs/sentences fed through `translate_batch`. Constraint surfaced to the user: keep `inter_threads × intra_threads ≤ physical cores`. Defaults derive from `os.cpu_count()` (e.g. `inter=4, intra=4` on a 20-core box).
- *Why:* matches CTranslate2's threading model; avoids Python-thread contention; batching is where CT2 throughput actually comes from.
- *Interaction with queue:* a single moxhimt translate **job** internally batches/threads; the queue still serializes translate jobs per category so two jobs don't both try to saturate all cores. (`cli`/`google` jobs may still use `translate.max_workers` thread fan-out.)
- *Alternatives:* many parallel translate jobs each on a thread (rejected — they'd fight for the same cores and RAM-resident model replicas).

### D10 — Layout: fluid width with max-width content columns
Root cause of "too narrow" is the default centered narrow `main`. The shell uses a fluid app width (sidebar + flexible content), data-dense tables span the full content width, and only long-form reading columns (chapter editor prose) keep a comfortable max-width. Breakpoints collapse the sidebar on small screens.
- *Why:* management screens (queue, library, storage) benefit from horizontal space; only prose needs a measure cap.

### D11 — EPUB metadata: extend `NovelConfig`, emit Dublin Core + Calibre meta, stable urn:uuid
Add publishing fields to `NovelConfig` and map them in `epub_builder.py`:

| UI field | Stored field | EPUB/OPF mapping |
|---|---|---|
| Định danh (urn:uuid) | `identifier` (auto `uuid4` if empty) | `dc:identifier` `urn:uuid:…` (replaces hardcoded `novel2epub-{slug}`) |
| Nhà xuất bản | `publisher` | `dc:publisher` |
| Xuất bản (ngày) | `pubdate` | `dc:date` / `dcterms:issued` |
| Đã thêm | `date_added` (auto on create) | `meta name="calibre:timestamp"` |
| Ngôn ngữ | `language` (exists) | `dc:language` |
| Chủ đề | `subjects` (list) | one `dc:subject` per entry |
| Bộ sách | `series` | `meta name="calibre:series"` (+ EPUB3 `belongs-to-collection`) |
| Số thứ tự | `series_index` | `meta name="calibre:series_index"` |
| Miêu tả | `description` (exists) | `dc:description` |
| Kích thước | — (computed) | not stored; displayed from the built file's byte size |

- *Why urn:uuid:* a stable, globally-unique identifier is what readers/Calibre expect; the current `novel2epub-{slug}` collides if slugs are reused and isn't a real URN. UUID is generated once and persisted so rebuilds keep the same identity.
- *"Kích thước" is derived,* not user input — shown in the storage/ebook views from the EPUB file size.

## Risks / Trade-offs

- **In-memory queue lost on restart** → Persist history and accept that *pending* (never-started) jobs are dropped on restart; surface this clearly. Re-enqueue is one click via history retry.
- **Cancel only at checkpoints** → Long single-chapter operations can't be interrupted mid-step; documented existing behavior of `cancel_event`, unchanged.
- **Concurrency bugs in reorder/both-slot acquisition** → Keep all queue mutations under the single existing `JobRunner._lock`; add focused unit tests for enqueue/dequeue/reorder/both-slot ordering.
- **Scheduler firing during heavy manual use** → Steps queue normally behind manual jobs (per spec); no preemption.
- **Big-bang reskin breaks pages** → Migrate the shell first, keep existing classes working, convert pages incrementally; each page verified in the preview before the next.
- **Theme flash (FOUC)** → Apply `data-theme` from `localStorage` via an inline head script before first paint.

## Migration Plan

1. Land `queue.py` (new) behind `JobRunner`, keeping the current public methods (`start`, `start_custom`, `request_cancel`, `status`) working; add queue methods alongside. Unit-test.
2. Add `GET /api/queue`; keep `/api/status` as a shim. Switch route handlers to enqueue.
3. Reskin `base.html` + tokens/components CSS + `app.js`; verify existing pages render.
4. Build new surfaces page-by-page (ebook dashboard → sources test → crawl console → storage → automations), each reusing the queue.
5. Add `scheduler.py`, start it from `app.main` lifespan.
6. Remove the `/api/status` shim and dead CSS once all templates are cut over.

Rollback: each step is additive until step 6; reverting the templates and leaving `job.py`'s legacy methods restores prior behavior.

## Open Questions

- Should `pending` jobs be persisted (best-effort) across restart, or is history-retry enough? (Leaning: history-retry only for v1.)
- Automation recurrence scope for v1: daily-at-time + manual only, or also interval/weekly? (Leaning: daily + manual, extend later.)
- Where to store the workspace sidecar when running the bundled/default config with no library — reuse `output.data_dir`'s parent? (Resolve during step 1.)
