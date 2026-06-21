# Feature Specification: Refactor TOC

**Feature Branch**: `master`

**Created**: 2026-06-21

**Status**: Draft

**Input**: User description: "refactor toc: Cho phép lấy toàn bộ thông tin từ url gồm title, description, author (rule: dịch theo từ hán Việt), và list chapter (cho phép sort, chọn range theo sort, search, filter và mỗi chapter có các action translate, crawler (override old)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import full novel metadata from URL (Priority: P1)

A user provides a novel source URL and expects the system to collect the full novel
identity needed for an EPUB: title, description, author, source URL, and chapter list.
Title and author values from Chinese sources are presented using the project's Hán Việt
translation rule by default.

**Why this priority**: Complete metadata is the foundation for a usable EPUB and for all
later chapter-level actions. Without reliable metadata and chapter URLs, users cannot
confidently crawl, translate, or build the novel.

**Independent Test**: Use a source URL with known metadata and chapters, run the import,
and verify that title, description, author, source URL, ordered chapters, and per-chapter
URLs are visible and stored without requiring a full crawl or translation.

**Acceptance Scenarios**:

1. **Given** a source URL with title, description, author, and chapter links, **When** the
   user imports or refreshes TOC information, **Then** the novel record contains all
   available metadata and a chapter list with stable chapter titles and source URLs.
2. **Given** source metadata containing Chinese names, **When** the metadata is displayed
   or stored for Vietnamese output, **Then** title and author names use Hán Việt rendering
   by default while preserving the original source value for traceability.
3. **Given** an existing novel with curated metadata, **When** the user refreshes from the
   source URL without choosing override, **Then** curated values are not silently replaced.

---

### User Story 2 - Find and select chapters from the TOC (Priority: P2)

A user reviews the chapter list and needs to sort it, search within it, filter by status
or text, select chapters with checkboxes, and select a range based on the currently
visible sorted order. The table should reuse the existing ebook chapter table in
`ebooks/default`/ebook overview instead of creating a separate duplicate view.

**Why this priority**: Long novels often contain hundreds or thousands of chapters. Users
need precise list controls to work on the right chapters without accidental selection.

**Independent Test**: Import a novel with many chapters, apply sorting, search, and filter
controls, then select a range and verify that the selected chapters match the active
visible order.

**Acceptance Scenarios**:

1. **Given** a chapter list sorted by a selected order, **When** the user chooses a range
   from chapter A to chapter B, **Then** the selected range follows the active sorted order,
   not the original source order unless that is the active sort.
2. **Given** a search term or filter, **When** the user applies it, **Then** only matching
   chapters are visible and range selection operates on that visible result set.
3. **Given** filters are cleared, **When** the user returns to the full chapter list,
   **Then** all chapters are visible in a deterministic order.
4. **Given** a user checks individual chapter rows, **When** a bulk action is submitted,
   **Then** only checked rows are targeted unless a visible range is explicitly selected.

---

### User Story 3 - Run per-chapter crawl and translate actions (Priority: P3)

A user selects one or more chapters or acts on a single chapter and can run crawl or
translate for those chapters. If existing raw or translated output exists, the user can
explicitly choose to override old content.

**Why this priority**: Chapter-level actions let users repair failed chapters, refresh stale
content, and avoid paying to translate chapters that do not need work.

**Independent Test**: Choose a chapter with existing cached content, run crawl and translate
once without override and once with override, and verify that old content is preserved in
the first case and replaced in the second case with clear user feedback.

**Acceptance Scenarios**:

1. **Given** a chapter with no cached raw content, **When** the user runs crawl for that
   chapter, **Then** the chapter status changes to crawled and the raw content becomes
   available for review.
2. **Given** a chapter with existing raw or translated content, **When** the user runs the
   same action without override, **Then** the existing content is kept and the user is told
   that override is required to replace it.
3. **Given** a chapter with existing raw or translated content, **When** the user runs the
   action with override, **Then** the old output is replaced and the chapter status reflects
   the latest successful action.
4. **Given** a chapter row in the table, **When** the user clicks the row's crawl or
   translate action button, **Then** only that row's chapter is targeted.

---

### Edge Cases

- Source page provides title but no description or author: import succeeds, missing fields
  are marked as unavailable, and the user can still review and act on chapters.
- Source page has duplicate chapter links or titles: duplicates are identified clearly and
  the chapter list keeps a stable order without silently merging unrelated chapters.
- Chapter URL is malformed or unreachable: that chapter is marked as needing attention and
  does not block usable metadata or other chapters.
- Search or filter returns no chapters: the user sees an empty-result state and no range
  action is applied.
- Checked rows are hidden by a later search/filter change: hidden rows are not submitted
  unless they are still part of the active visible result set.
- Range endpoints are reversed in the active sort order: the system selects the inclusive
  range between the two endpoints in the visible order.
- A crawl or translate action partially fails across a selected range: successful chapters
  remain completed, failed chapters are reported individually, and retry can target only
  failed chapters.
- User refreshes TOC after local edits: source-derived fields do not replace curated local
  values unless the user explicitly chooses override.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow a user to import or refresh a novel TOC from a source URL.
- **FR-002**: System MUST capture source URL, title, description, author, ordered chapter
  list, and per-chapter source URL when available from the source.
- **FR-003**: System MUST preserve original source metadata values separately from displayed
  translated values when translation or normalization changes title or author text.
- **FR-004**: System MUST render Chinese title and author names using Hán Việt rules by
  default for Vietnamese output and review.
- **FR-005**: System MUST show missing title, description, author, chapter title, or chapter
  URL fields explicitly instead of failing silently.
- **FR-006**: System MUST prevent source refresh from silently overwriting curated metadata
  or chapter state unless the user chooses an explicit override action.
- **FR-007**: Users MUST be able to sort the chapter list by at least source order, title,
  crawl status, and translation status.
- **FR-008**: Users MUST be able to search chapters by visible chapter title and source URL.
- **FR-009**: Users MUST be able to filter chapters by crawl status, translation status,
  and whether the chapter has missing or invalid source information.
- **FR-010**: Users MUST be able to select an inclusive chapter range based on the active
  sorted and filtered list.
- **FR-011**: System MUST make selected chapter counts and range endpoints visible before a
  bulk action is applied.
- **FR-011A**: Users MUST be able to select individual visible chapter rows with checkboxes.
- **FR-011B**: If both checked rows and range endpoints are provided, system MUST make the
  chosen targeting mode explicit before submitting the action.
- **FR-012**: Users MUST be able to run crawl for a single chapter or selected chapters.
- **FR-013**: Users MUST be able to run translate for a single chapter or selected chapters.
- **FR-013A**: Each visible chapter row MUST expose crawl and translate actions that target
  only that row.
- **FR-014**: Crawl and translate actions MUST reuse existing cached output by default.
- **FR-015**: Crawl and translate actions MUST offer an explicit override option that
  replaces old raw or translated output only for the targeted chapters.
- **FR-016**: System MUST report per-chapter success, skipped, and failed statuses after
  crawl or translate actions.
- **FR-017**: System MUST allow retrying failed chapter actions without repeating successful
  chapters unless override is selected.
- **FR-018**: System MUST keep CLI and Web UI behavior aligned for source metadata, chapter
  list controls, selection, and override semantics.

### Key Entities *(include if feature involves data)*

- **Novel Metadata**: Represents a source novel with source URL, original title, displayed
  title, original description, displayed description, original author, displayed author,
  and user-curated overrides.
- **Chapter**: Represents one chapter with stable source order, visible title, source URL,
  crawl status, translation status, missing-field indicators, and eligibility for override.
- **Chapter Selection**: Represents the visible sorted and filtered chapter set, selected
  range endpoints, checked row indexes, selected count, targeting mode, and target action.
- **Chapter Action Result**: Represents per-chapter outcome for crawl or translate actions,
  including completed, skipped, failed, and replaced states.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can import metadata and a 500-chapter TOC from a supported source and
  verify the collected title, description, author, and chapter count in under 2 minutes.
- **SC-002**: At least 95% of chapters from a supported source retain stable source order
  and valid source URLs after import; any exceptions are individually visible to the user.
- **SC-003**: Users can search, filter, sort, and select a chapter range from a 1,000-chapter
  list in under 30 seconds during manual validation.
- **SC-003A**: Users can select at least 20 non-contiguous visible chapters with row
  checkboxes and confirm the selected count before running a bulk action.
- **SC-004**: In validation with existing cached chapters, 100% of crawl and translate
  actions preserve old output unless the user selects override.
- **SC-005**: After a partial action failure, users can identify failed chapters and retry
  only those chapters without repeating successful chapters.
- **SC-006**: Hán Việt rendering of imported Chinese title and author values matches the
  project's translation rules in all reviewed sample imports.

## Assumptions

- The primary users are existing novel2epub users who manage novels through CLI or Web UI.
- Source pages may not expose every metadata field; missing description or author does not
  block chapter import.
- The source order remains the default chapter order unless the user selects another sort.
- Search and filter operate on the imported chapter list, not on full chapter body text.
- Override applies only to targeted metadata or chapters, not to unrelated cached content.
- This feature covers TOC and chapter action workflow; EPUB build behavior changes only as
  needed to consume the improved metadata.
