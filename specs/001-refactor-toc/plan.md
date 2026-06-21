# Implementation Plan: Refactor TOC

**Branch**: `` | **Date**: 2026-06-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-refactor-toc/spec.md`

## Summary

Refactor the TOC workflow so a source URL can populate complete novel metadata and a
chapter list, preserve original and displayed translated metadata, let users sort/search/
filter/select ranges from the active visible order, select rows with checkboxes, and run
per-row or bulk crawl/translate actions with explicit override semantics. The implementation
will extend the existing disk-backed manifest and reuse the current `ebooks/default` chapter
table/ebook overview surface instead of adding a separate TOC page.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: requests, beautifulsoup4, PyYAML, ebooklib, markdown,
FastAPI, Jinja2; optional crawl engines `crawl4ai` and `firecrawl-py`; translation via
existing translator backends.

**Storage**: Disk-backed `data/<slug>/manifest.json`, `raw/*.md`, `translated/*.md`,
and `translation_meta/*.json` managed by `novel2epub.storage.Storage`.

**Testing**: pytest with unit and route tests under `tests/`.

**Target Platform**: Local CLI and optional local Web UI on developer/user machines.

**Project Type**: Single Python application with CLI package (`novel2epub/`) and Web UI
package (`app/`).

**Performance Goals**: Users can inspect and operate on a 1,000-chapter table without
manual lag, select visible ranges or 20+ checked rows in under 30 seconds, and import a
500-chapter TOC in under 2 minutes for supported sources.

**Constraints**: Must preserve current cache/idempotency behavior by default; override
must be explicit; manifest changes must tolerate existing manifests; crawler selectors
and engine choices remain configuration-driven.

**Scale/Scope**: Feature covers one novel at a time, up to thousands of chapters per
manifest, across CLI and Web UI workflows.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Source metadata**: PASS. Plan tracks title, description, author, source URL,
  original/displayed values, ordered chapters, and per-chapter URLs. Missing metadata is
  represented as explicit indicators, not silent failure.
- **Translation rules**: PASS. Metadata display uses existing translation/glossary rules
  with Hán Việt defaults for title and author while preserving originals.
- **Pipeline safety**: PASS. Existing cache reuse remains default for crawl/translate;
  override is an explicit action scoped to selected metadata or chapters.
- **Chapter control**: PASS. Design covers deterministic table ordering, search/filter,
  row checkboxes, active-sort range selection, selected-count confirmation, per-row action
  buttons, and bulk actions from the same ebook overview table.
- **Independent verification**: PASS. Tests are required for metadata parsing, manifest
  compatibility, sort/filter/range selection, override behavior, route contracts, and
  CLI/Web UI alignment.

Post-design re-check: PASS. `research.md`, `data-model.md`, contracts, and
`quickstart.md` preserve all gate decisions without unresolved violations.

## Project Structure

### Documentation (this feature)

```text
specs/001-refactor-toc/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   └── web-ui.md
└── tasks.md             # Created by /speckit-tasks, not by this plan
```

### Source Code (repository root)

```text
novel2epub/
├── crawler.py           # TOC metadata extraction and chapter discovery
├── storage.py           # Manifest and chapter state model/serialization
├── pipeline.py          # Fetch TOC, crawl selected, translate selected actions
├── cli.py               # CLI commands/options for TOC and chapter actions
└── translator.py        # Existing translation backend and glossary behavior

app/
├── job.py               # Background job dispatch for TOC/chapter actions
├── routes/
│   ├── ebooks.py        # Ebook overview and shared TOC/chapter table rows
│   ├── jobs.py          # Web UI job/action endpoints
│   └── chapters.py      # Chapter detail/edit behavior
└── templates/
    ├── ebook.html       # Shared TOC table, row checkboxes, and action controls
    └── chapter.html     # Per-chapter review actions if needed

tests/
├── test_crawler_meta.py
├── test_pipeline_meta.py
├── test_storage.py
├── test_routes_glossary.py
└── test_refactor_toc.py # New focused coverage for this feature
```

**Structure Decision**: Keep the feature in the existing single-project layout. The
business logic belongs in `novel2epub/` so CLI and Web UI share the same behavior; Web UI
routes/templates should only adapt that behavior for interaction.

## Complexity Tracking

No constitution violations or complexity exceptions are required.
