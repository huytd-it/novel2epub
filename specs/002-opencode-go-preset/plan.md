# Implementation Plan: OpenCode Go Translation & AI Preset

**Branch**: `` | **Date**: 2026-06-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-opencode-go-preset/spec.md`

## Summary

Add a built-in `go` preset to `novel2epub` that activates OpenCode Go as the translation backend via a single `translate.preset: go` config field. The preset sets `translate.cli.command` to `opencode run`, provides a sensible default Go model (`opencode-go/qwen3.7-plus`), ships Go-optimized prompt templates, and applies consistently across chapter translation, metadata translation, glossary AI, rewrite, and evaluation features — all without changes to `translator.py` or `cli_runner.py`. Optionally add `crawl.ai_fallback` for AI-powered chapter extraction when standard selectors fail (P3).

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: PyYAML, ruamel.yaml (existing); CLI: `opencode` CLI with Go subscription (user-installed)

**Storage**: Config values live in YAML config files (config.yaml, library.yaml) and `sources.yaml`; preset definitions are compiled into `config.py` or loaded from a data file.

**Testing**: pytest with unit tests for preset resolution/merge logic and integration tests with a mock CLI translator.

**Target Platform**: Local CLI and optional local Web UI (same as existing project).

**Project Type**: Single Python CLI package (`novel2epub/`) with Web UI (`app/`).

**Performance Goals**: Preset resolution completes in <100ms at config load time; translation throughput is identical to manual CLI configuration (no overhead from preset layer).

**Constraints**: Must preserve backward compatibility with existing configs that do not set `translate.preset`. Must not change `translator.py` or `cli_runner.py` code. Must allow explicit per-field overrides to take precedence over preset values.

**Scale/Scope**: Single-user desktop; one novel at a time. Preset definitions are static and maintained in the project repository.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Source metadata**: N/A — feature does not touch metadata extraction or TOC parsing.
- **Translation rules**: PASS. Go preset prompt templates must preserve Hán Việt naming, glossary precedence, and natural Vietnamese output. The spec provides Go-optimized templates that align with these rules.
- **Pipeline safety**: PASS. The preset layer only changes default CLI config values. Cache reuse, resume behavior, failure reporting, and override semantics are unchanged.
- **Chapter control**: N/A — feature does not touch chapter listing, ordering, or selection.
- **Independent verification**: PASS. Config loading tests verify preset resolution, field override precedence, and prompt template selection. Integration tests verify end-to-end translation with mock CLI.

Post-design re-check: PASS. Research, contracts, and quickstart preserve all gate decisions without unresolved violations.

## Project Structure

### Documentation (this feature)

```text
specs/002-opencode-go-preset/
├── plan.md              # This file
├── research.md          # Phase 0: unknowns resolved
├── data-model.md        # Phase 1: preset data structures
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   └── cli.md           # CLI config contract (preset field + merge rules)
└── tasks.md             # Created by /speckit-tasks, not by this plan
```

### Source Code (repository root)

```text
novel2epub/
├── config.py            # Add GoPreset dataclass + preset resolution in load_config()
├── crawler.py           # Optional: add ai_fallback logic to HttpCrawler/Crawl4AICrawler
└── presets/
    └── go.py            # Go preset definitions (command, model, prompts, fallback cfg)

tests/
├── test_config.py       # Extended: preset resolution, field override, validation
└── test_crawler_meta.py # Extended: ai_fallback behavior if P3 is implemented
```

**Structure Decision**: Keep preset definitions in a dedicated `novel2epub/presets/go.py` module rather than hardcoding in `config.py`, so future presets (e.g. `preset: claude`, `preset: ollama`) can follow the same pattern without bloating the config loader.

## Complexity Tracking

No constitution violations or complexity exceptions are required.
