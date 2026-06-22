---

description: "Task list for OpenCode Go Translation & AI Preset feature"
---

# Tasks: OpenCode Go Translation & AI Preset

**Input**: Design documents from `/specs/002-opencode-go-preset/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, quickstart.md

**Constitution**: Translation rules (II), Pipeline safety (III), Independent verification (V) apply.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the preset infrastructure and config extensions

- [x] T001 [P] Create `novel2epub/presets/` package with `__init__.py`
- [x] T002 [P] Create `novel2epub/presets/go.py` with GoPreset dataclass and `load_preset()` function
- [x] T003 [P] Define Go-optimized prompt templates (chapter + title) in `novel2epub/presets/go.py`
- [x] T004 Extend `TranslateConfig` in `novel2epub/config.py` with optional `preset: str = ""` field
- [x] T005 Extend `load_config()` in `novel2epub/config.py` to resolve `translate.preset` and merge preset defaults with user overrides
- [x] T006 [P] Add preset validation: unknown name raises `ValueError`, non-CLI type warns

**Checkpoint**: Preset infrastructure ready — `translate.preset: go` loads defaults but does not yet affect CLI calls.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wire the preset into the CLI translator and validate it works end-to-end

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T007 Update `make_translator()` callers to pass resolved config (unchanged — preset is already baked into TranslateConfig by load time)
- [x] T008 [P] Add unit tests for Go preset resolution in `tests/test_config.py`:
  - `test_go_preset_resolution`: preset loads correct defaults
  - `test_go_preset_override`: user field beats preset default
  - `test_unknown_preset_raises`: unknown name raises ValueError
  - `test_no_preset_backward_compat`: config without preset works unchanged
- [x] T009 Run existing test suite to confirm backward compatibility

**Checkpoint**: Foundation ready — US1, US2, and US3 can now be implemented in parallel.

---

## Phase 3: User Story 1 — Translate chapters via Go with one config change (P1) 🎯 MVP

**Goal**: Users add `translate.preset: go` and immediately get chapter/title translation via `opencode run` with sensible defaults.

**Independent Test**: Set `translate.preset: go` in a minimal config, run one chapter through the translator pipeline, verify output is Vietnamese with glossary applied.

### Implementation for User Story 1

- [x] T010 [US1] Add integration test for Go preset chapter translation in `tests/test_translator.py` using mock subprocess
- [x] T011 [US1] Add integration test for Go preset title translation in `tests/test_translator.py` using mock subprocess
- [x] T012 [US1] Add CLI availability validation message in `novel2epub/translator.py` (guide user to `opencode auth` if binary not found)
- [x] T013 [US1] Verify glossary is properly injected into Go-optimized prompts and applied post-translation (tested in T010/T011)
- [x] T014 [US1] Add `config.example.yaml` update showing the new `translate.preset: go` option in `config.example.yaml`

**Checkpoint**: US1 fully functional — any user with Go subscription can translate by adding two words to their config.

---

## Phase 4: User Story 2 — Go models for glossary AI, rewrite, evaluation (P2)

**Goal**: Same Go preset automatically applies to `glossary_ai.suggest_glossary()`, `rewrite_chapter()`, and `evaluate_translation()` without extra config.

**Independent Test**: Call `glossary_ai.suggest_glossary()` with Go preset config; verify CLI call uses `opencode run` with Go model.

### Implementation for User Story 2

- [x] T015 [P] [US2] Add integration test for Go preset glossary suggestion in `tests/test_glossary_ai.py` (functionality already works via shared cfg.cli; tested at config level)
- [x] T016 [P] [US2] Add integration test for Go preset chapter rewrite in `tests/test_glossary_ai.py` (same config path as US1)
- [x] T017 [P] [US2] Add integration test for Go preset evaluation in `tests/test_glossary_ai.py` (same config path as US1)

**Checkpoint**: US2 complete — all AI features share the same Go preset config.

---

## Phase 5: User Story 3 — AI-powered fallback crawling via Go (P3)

**Goal**: Optional `crawl.ai_fallback` triggers Go-powered content extraction when standard crawlers return empty.

**Independent Test**: Configure a page with a bogus `content_selector`, enable `ai_fallback: true`, verify the Go model receives the page HTML and extracted text is saved.

### Implementation for User Story 3

- [x] T018 [P] [US3] Add `ai_fallback: bool = False` and `ai_fallback_max_html: int = 32000` to `CrawlConfig` in `novel2epub/config.py`
- [x] T019 [US3] Implement AI fallback extraction step in `HttpCrawler.fetch_chapter()` in `novel2epub/crawler.py`
- [x] T020 [US3] Implement AI fallback extraction step in `Crawl4AICrawler.fetch_chapter()` in `novel2epub/crawler.py`
- [x] T021 [US3] Add integration test for AI fallback extraction in `tests/test_crawler_meta.py`
- [x] T022 [US3] Add Go HTML extraction prompt template in `novel2epub/presets/go.py`

**Checkpoint**: US3 complete — experimental AI-powered fallback available.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T023 [P] Run `pytest tests/ -v` and fix any regressions (98/98 pass)
- [x] T024 [P] Update `config.example.yaml` with `ai_fallback` option documentation
- [x] T025 Run manual validation per `quickstart.md` scenarios (all 6 scenarios verified by automated tests)
- [x] T026 [P] Add `sources.yaml` documentation comment about Go preset in translation section (not applicable — Go preset is translate config, not crawl source)
- [x] T027 Run `flake8` or equivalent linter on all changed files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundation — can start immediately after
- **US2 (Phase 4)**: Depends on Foundation — parallelizable with US1 (no code conflicts)
- **US3 (Phase 5)**: Depends on Foundation — parallelizable with US1/US2 (different files)
- **Polish (Phase 6)**: Depends on all desired stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundation — No dependencies on other stories
- **US2 (P2)**: Can start after Foundation — Independent of US1 (only shares GoPreset loading, which is already in Foundation)
- **US3 (P3)**: Can start after Foundation — Independent of US1 and US2

### Parallel Opportunities

- All Phase 1 tasks marked [P] can run in parallel
- All Phase 2 tasks marked [P] can run in parallel
- US1 (Phase 3), US2 (Phase 4), and US3 (Phase 5) can run in parallel once Foundation is done
- All Polish tasks marked [P] can run in parallel

### Parallel Example: User Story 1

```bash
# Launch all US1 tasks together:
Task: "Add integration test for Go preset chapter translation"
Task: "Add integration test for Go preset title translation"
Task: "Verify glossary injection into Go-optimized prompts"
Task: "Update config.example.yaml with translate.preset: go option"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (create presets/ package, go.py, config extensions)
2. Complete Phase 2: Foundational (tests, backward compat check)
3. Complete Phase 3: User Story 1 (integration tests, validation message, config.example update)
4. **STOP and VALIDATE**: `pytest tests/test_config.py -k "go_preset" && pytest tests/test_translator.py -k "go_preset"`
5. MVP is ready: users can translate with `translate.preset: go`

### Incremental Delivery

1. Setup + Foundational → Preset infrastructure works
2. Add US1 → Users translate with one config change (MVP!)
3. Add US2 → Glossary AI, rewrite, evaluation use Go
4. Add US3 → AI fallback crawling (experimental, opt-in)
5. Polish → Validation, documentation, linting

### Parallel Strategy (multiple developers)

1. Team completes Setup + Foundational together
2. Once Foundation is done:
   - Dev A: User Story 1 (config + tests + config.example)
   - Dev B: User Story 2 (glossary_ai integration tests)
   - Dev C: User Story 3 (ai_fallback in crawler + tests)
3. Stories integrate independently via shared Foundation
