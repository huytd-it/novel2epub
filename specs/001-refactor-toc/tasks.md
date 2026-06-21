---

description: "Task list for Refactor TOC implementation"
---

# Tasks: Refactor TOC

**Input**: Design documents from `/specs/001-refactor-toc/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required by constitution for metadata parsing, manifest compatibility, sort/filter/range selection, cache override behavior, route contracts, and CLI/Web UI alignment.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- All task descriptions include exact file paths

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare focused test coverage and shared terminology before feature work.

- [X] T001 Create focused Refactor TOC test module in tests/test_refactor_toc.py
- [X] T002 [P] Add CLI contract references for TOC commands as comments or fixtures in tests/test_refactor_toc.py
- [X] T003 [P] Add Web UI contract references for TOC routes as comments or fixtures in tests/test_refactor_toc.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared manifest and chapter-list foundations that all user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 Extend Manifest and Chapter dataclasses with source_url, missing-field, duplicate, and action-status fields in novel2epub/storage.py
- [X] T005 Update manifest serialization and compatibility-tolerant loading for old manifest.json files in novel2epub/storage.py
- [X] T006 Add manifest compatibility tests for old and new fields in tests/test_storage.py
- [X] T007 Create shared TOC/chapter list helper functions for status rows, sort, search, filter, visible range selection, and selected-count summaries in novel2epub/toc.py
- [X] T008 Add shared TOC helper unit tests for deterministic sorting, filtering, searching, reversed ranges, and empty results in tests/test_refactor_toc.py
- [X] T009 Update pipeline imports and call sites to use shared TOC selection helpers without changing default source-order behavior in novel2epub/pipeline.py
- [X] T010 Add regression tests proving existing source-order crawl/translate range behavior still works with no sort/search/filter options in tests/test_refactor_toc.py

**Checkpoint**: Manifest compatibility and shared chapter-list behavior are ready for all stories.

---

## Phase 3: User Story 1 - Import full novel metadata from URL (Priority: P1) MVP

**Goal**: A user can import or refresh source metadata and chapter list from a URL without full chapter crawl, with original and displayed metadata preserved.

**Independent Test**: Use a source URL fixture with known metadata and chapters, run TOC import, and verify title, description, author, source URL, ordered chapters, per-chapter URLs, missing-field indicators, and preserved curated values.

### Tests for User Story 1

- [X] T011 [P] [US1] Add crawler fixture tests for title, author, description, cover, source URL, chapter URL, missing metadata, and duplicate chapter handling in tests/test_refactor_toc.py
- [X] T012 [P] [US1] Add pipeline tests for TOC refresh preserving curated title_vi, author_vi, description_vi, and chapter title_vi without override in tests/test_refactor_toc.py
- [X] T013 [P] [US1] Add CLI tests for `toc` and `meta --force` metadata behavior in tests/test_refactor_toc.py

### Implementation for User Story 1

- [X] T014 [US1] Extend TocResult and HttpCrawler metadata extraction to include source_url and missing-field indicators in novel2epub/crawler.py
- [X] T015 [US1] Extend FirecrawlCrawler metadata extraction to include source_url and missing-field indicators in novel2epub/crawler.py
- [X] T016 [US1] Implement deterministic duplicate chapter reporting while preserving stable chapter order in novel2epub/crawler.py
- [X] T017 [US1] Update _refresh_manifest to persist source_url, missing-field indicators, duplicate info, and curated-field preservation in novel2epub/pipeline.py
- [X] T018 [US1] Add explicit metadata refresh override support to step_fetch_toc and metadata translation paths in novel2epub/pipeline.py
- [X] T019 [US1] Add `toc` command and `meta --force` option wiring in novel2epub/cli.py
- [X] T020 [US1] Update ebook overview metadata rows for original/displayed metadata and missing-field indicators in app/routes/ebooks.py
- [X] T021 [US1] Update ebook overview template to display source URL, original/displayed title, author, description, chapter count, and missing-field indicators in app/templates/ebook.html

**Checkpoint**: User Story 1 is independently functional and can ship as MVP.

---

## Phase 4: User Story 2 - Find and select chapters from the TOC (Priority: P2)

**Goal**: A user can sort, search, filter, and select an inclusive range from the active visible chapter list.

**Independent Test**: Import a many-chapter manifest, apply list controls, select a range, and verify selected chapters match the active sorted/filtered visible order.

### Tests for User Story 2

- [X] T022 [P] [US2] Add CLI tests for `chapters --sort --search --filter` output and deterministic row order in tests/test_refactor_toc.py
- [X] T023 [P] [US2] Add route tests for GET /ebooks/{slug} query controls preserving sort, direction, search, and filters in tests/test_refactor_toc.py
- [X] T024 [P] [US2] Add range-selection tests proving selected endpoints use visible sorted/filtered order in tests/test_refactor_toc.py

### Implementation for User Story 2

- [X] T025 [US2] Add `chapters` CLI command with --sort, --desc, --search, and --filter options in novel2epub/cli.py
- [X] T026 [US2] Render chapter list rows from shared TOC helper including raw, translated, and missing statuses in app/routes/ebooks.py
- [X] T027 [US2] Accept and preserve sort, direction, search, filter_raw, filter_translated, and filter_missing query parameters in app/routes/ebooks.py
- [X] T028 [US2] Add TOC controls, empty-result state, visible selected-count preview, and range endpoint inputs in app/templates/ebook.html
- [X] T029 [US2] Add source URL, visible title, raw status, translated status, and missing status columns to chapter table in app/templates/ebook.html

**Checkpoint**: User Story 2 is independently functional after Story 1 metadata exists.

---

## Phase 5: User Story 3 - Run per-chapter crawl and translate actions (Priority: P3)

**Goal**: A user can crawl or translate one chapter or a visible selected range, preserving cached output by default and replacing only when override is explicit.

**Independent Test**: Choose chapters with existing cached raw/translated content, run crawl/translate without override and with override, and verify skipped/replaced outcomes and per-chapter result reporting.

### Tests for User Story 3

- [X] T030 [P] [US3] Add pipeline tests for selected crawl preserving raw by default and replacing only with force in tests/test_refactor_toc.py
- [X] T031 [P] [US3] Add pipeline tests for selected translate preserving translated output by default and replacing only with force in tests/test_refactor_toc.py
- [X] T032 [P] [US3] Add route tests for POST /ebooks/{slug}/jobs/chapter-action resolving visible range and override semantics in tests/test_refactor_toc.py
- [X] T033 [P] [US3] Add route tests for POST /ebooks/{slug}/chapters/{index}/action targeting only one chapter in tests/test_refactor_toc.py

### Implementation for User Story 3

- [X] T034 [US3] Add selected chapter action result summaries with completed, skipped, failed, and replaced outcomes in novel2epub/pipeline.py
- [X] T035 [US3] Extend step_crawl_selected to accept selected chapter indexes from shared visible-list selection while preserving start/end compatibility in novel2epub/pipeline.py
- [X] T036 [US3] Extend step_translate_selected to accept selected chapter indexes from shared visible-list selection while preserving chapter/from/to compatibility in novel2epub/pipeline.py
- [X] T037 [US3] Add CLI --sort, --desc, --search, --filter, and --range option handling to crawl and translate commands in novel2epub/cli.py
- [X] T038 [US3] Register custom background jobs for bulk chapter actions and per-chapter actions in app/routes/jobs.py
- [X] T039 [US3] Add per-chapter action route for crawl/translate with override in app/routes/chapters.py
- [X] T040 [US3] Add crawl/translate selected controls with explicit override checkbox in app/templates/ebook.html
- [X] T041 [US3] Add per-chapter crawl/translate controls with explicit override checkbox in app/templates/chapter.html
- [X] T042 [US3] Update JobRunner labels/log handling for chapter-action outcomes in app/job.py

**Checkpoint**: User Story 3 is independently functional and aligned across CLI and Web UI.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, validation, and cleanup across all stories.

- [X] T043 Update README usage examples for `toc`, `chapters`, active-list range selection, and override behavior in README.md
- [X] T044 Update quickstart validation notes after implementation if command names or flags changed in specs/001-refactor-toc/quickstart.md
- [X] T045 Run pytest tests/test_refactor_toc.py tests/test_crawler_meta.py tests/test_pipeline_meta.py tests/test_storage.py
- [X] T046 Run pytest tests/test_routes_glossary.py and any route tests added for TOC workflows
- [X] T047 Review manifest output from a sample import and document any compatibility caveats in specs/001-refactor-toc/quickstart.md
- [X] T048 Verify CLI and Web UI behavior remain aligned for source metadata, list controls, range selection, and override semantics using specs/001-refactor-toc/contracts/cli.md and specs/001-refactor-toc/contracts/web-ui.md
- [X] T049 [US2] Add row checkboxes and checked-row count preview to the shared ebook chapter table in app/templates/ebook.html
- [X] T050 [US3] Add explicit targeting_mode and checked_indexes handling for bulk chapter actions in app/routes/jobs.py
- [X] T051 [US3] Add crawl and translate action buttons directly inside each shared chapter table row in app/templates/ebook.html
- [X] T052 [P] [US2] Add route test proving visible table rows render checkboxes and row action buttons in tests/test_refactor_toc.py
- [X] T053 [P] [US3] Add route test proving checked targeting intersects checked indexes with the active visible result set in tests/test_refactor_toc.py
- [X] T054 Update README and quickstart notes for checkbox selection and shared ebook table row actions in README.md and specs/001-refactor-toc/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; MVP scope.
- **User Story 2 (Phase 4)**: Depends on Foundational and benefits from US1 metadata, but list helper tests can be implemented independently.
- **User Story 3 (Phase 5)**: Depends on Foundational and should use US2 active visible-list selection for bulk actions.
- **Polish (Phase 6)**: Depends on completed target stories.

### User Story Dependencies

- **US1**: Independent after Foundational; provides metadata and TOC import MVP.
- **US2**: Requires imported or fixture manifest data; independent of chapter action implementation.
- **US3**: Requires shared selection helpers and imported/fixture manifest data; uses US2-style active-list selection for bulk workflows.

### Within Each User Story

- Tests for that story should be written first and fail before implementation.
- Storage/crawler/pipeline changes should precede CLI and Web UI adapters.
- Shared behavior belongs in `novel2epub/`; routes/templates adapt shared behavior only.
- Story complete before moving to the next priority unless parallel work is isolated by file.

---

## Parallel Opportunities

- T002 and T003 can run in parallel after T001.
- T011, T012, and T013 can run in parallel because they target different US1 test scopes.
- T022, T023, and T024 can run in parallel because they target CLI, route, and selection tests.
- T030, T031, T032, and T033 can run in parallel because they target distinct action behaviors.
- T043 and T044 can run in parallel after command names are stable.
- T052 and T053 can run in parallel because they validate separate Web UI table behaviors.

## Parallel Example: User Story 1

```text
Task: "T011 [P] [US1] Add crawler fixture tests for title, author, description, cover, source URL, chapter URL, missing metadata, and duplicate chapter handling in tests/test_refactor_toc.py"
Task: "T012 [P] [US1] Add pipeline tests for TOC refresh preserving curated title_vi, author_vi, description_vi, and chapter title_vi without override in tests/test_refactor_toc.py"
Task: "T013 [P] [US1] Add CLI tests for `toc` and `meta --force` metadata behavior in tests/test_refactor_toc.py"
```

## Parallel Example: User Story 2

```text
Task: "T022 [P] [US2] Add CLI tests for `chapters --sort --search --filter` output and deterministic row order in tests/test_refactor_toc.py"
Task: "T023 [P] [US2] Add route tests for GET /ebooks/{slug} query controls preserving sort, direction, search, and filters in tests/test_refactor_toc.py"
Task: "T024 [P] [US2] Add range-selection tests proving selected endpoints use visible sorted/filtered order in tests/test_refactor_toc.py"
```

## Parallel Example: User Story 3

```text
Task: "T030 [P] [US3] Add pipeline tests for selected crawl preserving raw by default and replacing only with force in tests/test_refactor_toc.py"
Task: "T031 [P] [US3] Add pipeline tests for selected translate preserving translated output by default and replacing only with force in tests/test_refactor_toc.py"
Task: "T032 [P] [US3] Add route tests for POST /ebooks/{slug}/jobs/chapter-action resolving visible range and override semantics in tests/test_refactor_toc.py"
Task: "T033 [P] [US3] Add route tests for POST /ebooks/{slug}/chapters/{index}/action targeting only one chapter in tests/test_refactor_toc.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 for metadata import, metadata translation, manifest compatibility, and overview display.
3. Validate US1 independently with TOC import and metadata tests.
4. Stop and confirm source metadata behavior before adding list controls or chapter actions.

### Incremental Delivery

1. Deliver US1 to make complete URL metadata and TOC import reliable.
2. Deliver US2 to add chapter list control and visible range selection.
3. Deliver US3 to add crawl/translate actions over one chapter or selected visible ranges.
4. Complete Phase 6 documentation and full validation.

### Notes

- Keep existing default commands working when new sort/search/filter/range options are omitted.
- Do not silently overwrite curated metadata or cached raw/translated chapter output.
- Keep CLI and Web UI behavior backed by shared `novel2epub/` logic wherever possible.
