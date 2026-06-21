# Quickstart: Refactor TOC

## Prerequisites

- Python dependencies installed from `requirements.txt`.
- A `config.yaml` or library entry with a valid `crawl.toc_url` and chapter link pattern.
- Optional Web UI dependencies installed when validating browser flows.

## CLI Validation

### 1. Fetch TOC metadata only

```bash
python -m novel2epub -c config.yaml toc
```

**Expected outcome**

- Manifest exists under `data/<slug>/manifest.json`.
- Metadata includes source URL, title, description, author, and chapter list when available.
- Missing title, description, author, or chapter URL values are visible in output/logs.
- No `raw/*.md` chapter body files are required to be created by this step.

### 2. Translate metadata using project rules

```bash
python -m novel2epub -c config.yaml meta
```

**Expected outcome**

- Displayed title and author use the configured Hán Việt/glossary translation behavior.
- Original source title and author remain available in the manifest.
- Running the command again without force does not replace existing displayed metadata.

### 3. Review chapter list controls

```bash
python -m novel2epub -c config.yaml chapters --sort title --search "章" --filter raw:no
```

**Expected outcome**

- Output contains only matching visible chapters.
- Rows include source index, visible title, URL, raw status, translated status, and missing status.
- Re-running with the same options produces deterministic order.

### 4. Crawl a selected visible range without override

```bash
python -m novel2epub -c config.yaml crawl --sort title --search "章" --range 1:3
```

**Expected outcome**

- The range is resolved from the active sorted/searched list.
- Existing raw files are skipped.
- Result output identifies completed, skipped, and failed chapters.

### 5. Crawl or translate with explicit override

```bash
python -m novel2epub -c config.yaml crawl --sort source --range 1:1 --force
python -m novel2epub -c config.yaml translate --sort source --range 1:1 --force
```

**Expected outcome**

- Only the selected chapter is replaced.
- Result output identifies the replacement.
- Untargeted cached raw and translated files remain unchanged.

## Web UI Validation

### 1. Start the UI

```bash
uvicorn app.main:app --reload --port 8010
```

Open `http://127.0.0.1:8010` and select an ebook.

### 2. Fetch and review TOC

**Expected outcome**

- The ebook page shows source URL, original/displayed metadata, missing-field indicators,
  and chapter count.
- Fetching TOC does not require a full crawl.

### 3. Sort, search, filter, and select range

**Expected outcome**

- Chapter rows update according to active controls.
- Range selection uses the visible sorted/filtered order.
- Selected count and endpoints are visible before submitting an action.
- Each visible row has a checkbox plus crawl and translate action buttons.

### 3b. Select non-contiguous rows with checkboxes

**Expected outcome**

- Checking multiple visible rows updates the checked-row count.
- Bulk action with targeting mode `checked` targets only checked visible rows.
- Changing search/filter hides rows and hidden rows are not submitted as checked targets.

### 4. Run per-chapter and bulk actions

**Expected outcome**

- Per-chapter crawl/translate targets only that chapter.
- Per-row crawl/translate buttons in the shared ebook table target only that row.
- Bulk crawl/translate targets only the selected visible range.
- Bulk checked-row actions target only visible checked rows.
- Existing content is skipped unless override is checked.
- Job log reports completed, skipped, failed, and replaced chapters.

## Test Commands

```bash
pytest tests/test_crawler_meta.py tests/test_pipeline_meta.py tests/test_storage.py
pytest tests/test_refactor_toc.py
```

**Expected outcome**

- Tests cover metadata extraction, manifest compatibility, list controls, range selection,
  override behavior, and CLI/Web UI action alignment.

**Observed validation**

- `python -m pytest` passes with the full test suite.
- Existing manifests without new TOC fields load with default empty values and are rewritten
  with new fields on the next save.
