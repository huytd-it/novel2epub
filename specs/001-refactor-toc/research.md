# Research: Refactor TOC

## Decision: Preserve original and displayed metadata in the manifest

**Rationale**: The current `Manifest` already stores original metadata (`title`, `author`,
`description`) and translated metadata (`title_vi`, `author_vi`, `description_vi`). This
matches the feature need to render Hán Việt/Vietnamese values while keeping source values
for traceability. Extending this shape with explicit source URL and missing-field/status
information is less risky than introducing a separate metadata store.

**Alternatives considered**: Store only translated values and discard originals. Rejected
because it violates traceability and makes refresh/override decisions unsafe. Store a
separate metadata JSON file. Rejected because it splits EPUB-critical state from the
manifest and complicates compatibility.

## Decision: Use compatibility-tolerant manifest loading

**Rationale**: Existing users may already have `manifest.json` without the new fields.
Dataclass defaults and defensive loading allow old manifests to remain usable while new
fields are populated on next TOC refresh.

**Alternatives considered**: Require a one-time migration command. Rejected because the
project is a local tool and can migrate lazily during normal load/save. Break old manifests
and require users to recrawl. Rejected because it violates cache preservation.

## Decision: Put sorting, filtering, and range selection in shared service logic

**Rationale**: The feature requires CLI and Web UI alignment. A shared chapter list helper
can accept sort, search, filter, and range inputs and return selected chapters plus a
summary, while routes and CLI commands remain thin adapters.

**Alternatives considered**: Implement list controls only in templates/routes. Rejected
because CLI behavior would drift. Implement only CLI range by numeric source index. Rejected
because the spec requires range selection by active visible sort/filter order.

## Decision: Reuse the existing ebook overview chapter table as the TOC table

**Rationale**: The current Web UI already centers chapter review in `GET /ebooks/{slug}`
and the user explicitly prefers using the existing `ebooks/default` table if possible.
Enhancing that table with metadata columns, row checkboxes, and row action buttons avoids
duplicating TOC state and keeps crawl/translate status visible in one place.

**Alternatives considered**: Create a separate `/toc` page. Rejected because it would split
chapter selection from existing ebook workflows. Replace the table with a pure client-side
widget. Rejected because server-rendered controls are sufficient and easier to test.

## Decision: Support both checked-row and visible-range targeting

**Rationale**: Ranges are efficient for contiguous chapter blocks, while checkboxes are
needed for non-contiguous repairs. The submitted targeting mode must be explicit when both
are present so users do not accidentally operate on the wrong chapters.

**Alternatives considered**: Only use checkboxes. Rejected because selecting hundreds of
contiguous chapters becomes slow. Only use range endpoints. Rejected because users need to
repair scattered failed chapters.

## Decision: Keep cache reuse default and make override an explicit boolean action

**Rationale**: The current pipeline already skips existing raw/translated files unless
`force` is passed. Preserving that default satisfies cost-control expectations. The Web UI
and CLI should expose override text consistently and log skipped/replaced outcomes.

**Alternatives considered**: Always replace selected chapters. Rejected because it risks
losing edited translations. Prompt interactively before every overwrite. Rejected because
it does not fit background Web UI jobs and batch CLI workflows.

## Decision: Treat missing metadata as non-blocking, visible status

**Rationale**: Many novel sites omit description or author. The user still benefits from
chapter import and can act on chapters. Missing-field indicators satisfy the constitution
without blocking normal work.

**Alternatives considered**: Fail TOC import unless all metadata is present. Rejected
because it would make common sources unusable. Silently leave fields empty. Rejected
because users need to know what was not found.

## Decision: Contract both CLI and Web UI interactions

**Rationale**: The project exposes both surfaces today. Contracts documented as command and
route/user-flow behavior are enough for planning and tests without requiring an external
OpenAPI contract.

**Alternatives considered**: Skip contracts because the feature is local. Rejected because
the plan must prevent behavior drift across CLI and Web UI. Generate formal OpenAPI only.
Rejected because not all behavior is HTTP-only.
