# Data Model: Refactor TOC

## Novel Metadata

Represents a source novel and the metadata used for review and EPUB output.

**Fields**

- `slug`: Stable local identifier for the novel.
- `source_url`: URL used to import or refresh the TOC.
- `title`: Original source title.
- `title_vi`: Displayed Vietnamese/Hán Việt title.
- `author`: Original source author.
- `author_vi`: Displayed Vietnamese/Hán Việt author.
- `description`: Original source description.
- `description_vi`: Displayed Vietnamese description.
- `cover_url`: Source cover image URL when available.
- `cover_file`: Local cover file name when downloaded.
- `metadata_missing`: List or flags for missing title, description, author, or cover.
- `curated_fields`: Fields that were edited locally and must not be silently overwritten.
- `chapters`: Ordered list of Chapter records.

**Validation Rules**

- `slug` is required.
- `source_url` is required for source imports and refreshes.
- Missing `description`, `author`, or `cover_url` does not block import.
- Missing `title` is visible to the user and may fall back to configured local title.
- Refresh MUST NOT overwrite curated fields unless override is explicit.

**Relationships**

- One Novel Metadata record owns many Chapter records.

## Chapter

Represents a chapter discovered from the source TOC.

**Fields**

- `index`: Stable source-order index used for file stems and default ordering.
- `url`: Source chapter URL.
- `title_zh`: Original chapter title.
- `title_vi`: Displayed translated chapter title.
- `has_raw`: Derived state indicating raw chapter content exists.
- `has_translated`: Derived state indicating translated chapter content exists.
- `missing_fields`: List or flags for missing title or URL.
- `duplicate_of`: Optional reference when a duplicate URL/title is detected.
- `last_action_status`: Latest crawl/translate result for UI/log display.

**Validation Rules**

- `index` MUST be unique within a manifest.
- `url` SHOULD be present for crawlable chapters; missing or malformed URLs make the
  chapter ineligible for crawl until corrected.
- Duplicate URLs MUST be reported and handled deterministically.
- Existing `title_vi` MUST be preserved during TOC refresh unless override is explicit.

**State Transitions**

```text
discovered -> raw_available -> translated_available
discovered -> action_failed
raw_available -> translated_available
raw_available -> action_failed
translated_available -> replaced_raw (crawl override)
translated_available -> replaced_translation (translate override)
action_failed -> raw_available or translated_available after retry
```

## Chapter Selection

Represents the user's visible chapter set and selected range.

**Fields**

- `sort_key`: Active sort key, such as source order, title, crawl status, or translation status.
- `sort_direction`: Ascending or descending.
- `search`: Search text applied to visible title or source URL.
- `filters`: Status and missing-field filters.
- `range_start`: First selected chapter in the active visible order.
- `range_end`: Last selected chapter in the active visible order.
- `checked_indexes`: Source-order indexes explicitly selected by visible row checkboxes.
- `targeting_mode`: `checked` or `range`, used when submitting a bulk action.
- `selected_count`: Count of chapters targeted by the pending action.
- `selected_indexes`: Source-order indexes for selected chapters.

**Validation Rules**

- Range selection applies after sort/search/filter are applied.
- Reversed endpoints select the inclusive range between endpoints in visible order.
- Empty result sets produce no selected chapters and no action should run.
- Selected count and endpoints must be visible before bulk actions.
- Checked indexes must be intersected with the active visible result set before submission.
- If both checked rows and range endpoints are present, targeting mode must determine which
  set is used and the selected count must match that mode.

## Chapter Action Result

Represents outcomes for crawl or translate actions.

**Fields**

- `action`: `crawl` or `translate`.
- `override`: Whether existing content replacement was explicitly requested.
- `chapter_index`: Target chapter source-order index.
- `outcome`: `completed`, `skipped`, `failed`, or `replaced`.
- `message`: User-facing result message.
- `previous_content_existed`: Whether cached output existed before the action.
- `retryable`: Whether the user can retry the action.
- `targeting_mode`: `single`, `checked`, or `range`.

**Validation Rules**

- Existing raw/translated content is skipped when `override` is false.
- Existing raw/translated content may be replaced only when `override` is true.
- Failure for one chapter must not mark successful chapters as failed.
- Failed chapters must be identifiable for retry.
- Row action buttons must produce `single` targeting mode and affect only one chapter.
