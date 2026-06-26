## Why

The web UI grew feature-by-feature into a functional but ad-hoc tool: a bare two-link header, a flat ebook table, inline `<details>` log blocks, and a job runner that **rejects** any second job with a 409 instead of queueing it. There is no way to schedule recurring updates, see disk usage, retry failed chapters in bulk, or test a source preset before using it. This change consolidates the experience into a professional, cohesive management console so a user can run many novels end-to-end without babysitting one job at a time.

## What Changes

- **Shared UI shell & design system**: a real sidebar/topbar navigation, a small reusable component/token set (cards, tables, badges, buttons, toasts, modals), consistent spacing/typography, and a dark/light theme. Replaces the minimal `base.html` header and the 209-line ad-hoc CSS.
- **Job queue with concurrent workers**: replace the "reject if busy" two-slot model with a real FIFO queue per category (pending → running → done/failed) backed by a **configurable pool of N concurrent workers per category**, with a queue panel showing position, live progress, cancel/retry, reorder, and a recent-history list. **BREAKING**: `POST /jobs/*` and `/ebooks/{slug}/jobs/*` now enqueue (return 202/redirect with a job id) instead of returning 409 when busy.
- **High-throughput crawl with anti-block control**: surface and extend the existing parallel-crawl support (`crawl.max_workers`) so a user can crawl many chapters at once (light `fetcher` mode scales to tens; browser modes stay low), with a **per-source concurrency cap**, per-domain jittered rate limiting, and **adaptive backoff that auto-reduces concurrency** on 429/anti-bot responses.
- **Parallel local translation tuned to the CPU**: drive concurrent translation through CTranslate2 batching plus configurable `inter_threads`/`intra_threads` (this machine has no CUDA GPU; moxhimt runs on CPU), instead of naive thread-per-chapter fan-out, with sensible defaults derived from physical core count.
- **Ebook management**: dashboard cards with progress bars (crawled/translated/built), quick actions, bulk operations across ebooks, archive/unarchive, and config export/import.
- **Source management**: a richer sources page — test/validate a preset against a sample URL (dry-run TOC + one chapter), clone a preset, import/export presets, and per-source health/usage indicators.
- **Crawl management**: a crawl console per ebook — per-chapter crawl status, gap/missing detection, one-click retry of failed/empty chapters, and engine/delay/retry overrides surfaced as first-class controls.
- **Storage management**: a storage overview (disk usage per ebook split by raw/mt/translated/epub), cleanup actions (purge raw, purge MT snapshots, remove built EPUB), and full-ebook archive to a compressed bundle.
- **Automation & scheduling**: define recurring or one-off automated pipelines (e.g. "every night: fetch new TOC entries → crawl new → translate → build") with enable/disable, last-run status, and run-now.
- **Rich EPUB metadata**: capture and package the full publishing metadata set — publisher, publication date, date added, language, subjects/topics, a proper `urn:uuid` identifier, series + series index, and description — so generated `.epub` files have complete, reader/Calibre-friendly metadata.
- **Wider, fluid layout**: the current UI is too narrow; the new shell uses a responsive fluid width with sensible max-width content columns and dense data tables that use the available screen real estate.

## Capabilities

### New Capabilities
- `ui-design-system`: Shared application shell (navigation, layout) plus reusable UI components, design tokens, and theming used across all pages.
- `job-queue`: FIFO background-job queue with lifecycle states, position/progress reporting, cancel/retry/reorder, and run history — replacing the reject-when-busy slot model.
- `ebook-management`: Library dashboard for ebooks — status/progress overview, per-ebook and bulk actions, archive/unarchive, and config import/export.
- `source-management`: Manage site presets — create/edit/clone/delete, validate/test against a live URL, import/export, and usage/health reporting.
- `crawl-management`: Per-ebook crawl console — chapter-level status, gap/failure detection, bulk retry, and surfaced engine/delay/retry controls.
- `storage-management`: Disk-usage reporting and cleanup/archive actions over the on-disk artifacts (raw/MT/translated/EPUB) of each ebook.
- `automation-scheduling`: Define, enable/disable, and run scheduled or recurring pipeline automations with run-now and last-run status.
- `ebook-metadata`: Capture and package the full EPUB publishing metadata set (publisher, dates, language, subjects, urn:uuid identifier, series + index, description) into the built `.epub`.

### Modified Capabilities
- `moxhimt-translator`: Add batch translation and CPU thread-pool tuning (`inter_threads`/`intra_threads`, batched `translate_batch`) so many chapters can be translated concurrently on CPU without naive thread-per-chapter oversubscription.
<!-- chapter-pagination and chapter-three-column-editor are reused as-is (no requirement changes). -->

## Impact

- **Code**: `app/job.py` (queue rewrite), `app/main.py` (router wiring, app.state for queue/scheduler), all `app/routes/*` (enqueue semantics, new routes for storage/automation/crawl-console), `app/templates/*` + `app/static/*` (new shell, components, CSS/JS), new modules likely under `app/` (e.g. `queue.py`, `scheduler.py`, `storage_report.py`).
- **APIs**: `GET /api/status` extended/replaced by a queue status endpoint; new endpoints for queue control, storage report/cleanup, source test, and automation CRUD/run. Job-start endpoints change from 409-on-busy to enqueue.
- **Persistence**: queue history, automation definitions, and ebook archived-state need lightweight on-disk storage (JSON/YAML under the workspace); no schema migration of existing novel data required.
- **Config model**: extend `NovelConfig` with publishing metadata fields (publisher, pubdate, date_added, subjects, series, series_index, identifier/uuid, description); `epub_builder.py` consumes them (replacing the hardcoded `novel2epub-{slug}` identifier with a stable `urn:uuid`). Extend `MoxhiMTConfig`/`TranslateConfig` with `inter_threads`/`intra_threads`/batch settings; extend `CrawlConfig`/`SourcePreset` with per-source concurrency cap + adaptive-throttle settings.
- **Dependencies**: no new hard runtime deps required for core (stdlib threading/sched + existing FastAPI/Jinja); optional packaging for archive bundles uses stdlib `zipfile`/`tarfile`.
- **Non-goals**: no change to the crawl engines, translator backends, or EPUB builder internals; no multi-user auth.
