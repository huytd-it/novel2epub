<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- PRINCIPLE_1_NAME placeholder -> I. Source Metadata Completeness
- PRINCIPLE_2_NAME placeholder -> II. Translation Fidelity and Glossary Discipline
- PRINCIPLE_3_NAME placeholder -> III. Idempotent Crawl/Translate/Build Pipeline
- PRINCIPLE_4_NAME placeholder -> IV. Chapter-Level User Control
- PRINCIPLE_5_NAME placeholder -> V. Independently Testable Delivery
Added sections:
- Product Constraints
- Development Workflow
Removed sections:
- Placeholder template guidance comments
Templates requiring updates:
- ✅ .specify/templates/plan-template.md
- ✅ .specify/templates/spec-template.md
- ✅ .specify/templates/tasks-template.md
- ⚠ .specify/templates/commands/*.md not present in this checkout
Follow-up TODOs: None
-->
# novel2epub Constitution

## Core Principles

### I. Source Metadata Completeness

Every feature that imports or refreshes a novel from a source URL MUST preserve the
complete source-level metadata needed to build an EPUB: title, description, author,
source URL, ordered chapter list, and per-chapter source URL. Metadata extraction MUST
be explicit about missing fields and MUST NOT silently overwrite curated values without
a user-visible override path. Rationale: EPUB quality and repeatable rebuilds depend on
stable metadata, not only chapter text.

### II. Translation Fidelity and Glossary Discipline

Chinese-to-Vietnamese translation features MUST follow traditional edit rules captured
in `docs/rule.md` and `docs/tool.md`: names and culturally significant proper nouns use
Sino-Vietnamese readings by default, glossary entries take precedence over model output,
and translated prose must be natural Vietnamese rather than literal machine output.
Changes that affect translation prompts, title translation, author rendering, or glossary
handling MUST include examples that demonstrate the expected rule. Rationale: consistent
Hán Việt naming and readable Vietnamese are the core product value.

### III. Idempotent Crawl/Translate/Build Pipeline

Crawler, translator, and EPUB builder operations MUST be resumable and idempotent across
CLI and Web UI entry points. Cached chapter files and manifests MUST be reused unless the
user explicitly requests an override, recrawl, or retranslate action. Failures MUST leave
completed chapters usable and MUST report which chapter or metadata item failed.
Rationale: long novels and paid translation calls require safe restarts and predictable
cost control.

### IV. Chapter-Level User Control

Users MUST be able to inspect and act on chapters independently. Features that expose a
chapter list MUST support deterministic ordering, search or filtering when the list can
grow large, range selection based on the active sort order, and per-chapter actions for
crawling and translating with explicit override behavior. Rationale: novel workflows are
iterative, and users need precise control over thousands of chapters.

### V. Independently Testable Delivery

Each user-facing story MUST be independently testable through CLI behavior, Web UI
behavior, service-level tests, or documented manual verification. Any change that touches
parsing, sorting, filtering, cache overwrite behavior, manifest schema, or EPUB output
MUST include automated tests unless the spec explicitly documents why manual verification
is the only practical option. Rationale: regressions in chapter ordering or cache behavior
can corrupt large outputs and are costly to discover late.

## Product Constraints

The project targets Python 3.10+ and stores novel state on disk under `data/<slug>/` using
manifest files plus `raw/` and `translated/` chapter files. Implementations MUST preserve
compatibility between CLI and Web UI workflows and MUST keep configuration-driven sources
usable through `config.yaml` or library entries. Network fetchers MUST respect the selected
engine (`http`, `crawl4ai`, or `firecrawl`) and MUST keep site-specific selectors and
patterns configurable. Features that crawl public websites MUST keep copyright and source
terms concerns visible in documentation or user guidance when behavior changes.

## Development Workflow

Plans MUST pass the Constitution Check before research and again after design. Specs MUST
define user stories that can be delivered and verified independently, especially for TOC,
metadata, chapter action, and translation workflows. Tasks MUST identify cache and override
semantics, manifest/schema effects, tests, and documentation updates. Reviews MUST verify
that CLI and Web UI behavior remain aligned when both surfaces are affected.

## Governance

This constitution supersedes conflicting process guidance for feature planning and review.
Amendments MUST update this file, include a Sync Impact Report, and propagate any changed
rules to affected Spec Kit templates and runtime guidance. Versioning follows semantic
versioning: MAJOR for incompatible principle removals or redefinitions, MINOR for added or
materially expanded principles or required sections, and PATCH for clarifications that do
not change obligations. Every feature plan MUST document Constitution Check results, and
every review MUST treat unresolved violations as blockers unless the plan records a justified
exception in Complexity Tracking.

**Version**: 1.0.0 | **Ratified**: 2026-06-21 | **Last Amended**: 2026-06-21
