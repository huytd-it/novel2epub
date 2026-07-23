# Reader Search/Replace + TOC Sidebar

**Date:** 2026-07-23  
**Status:** Approved  
**Author:** AI + User

## Overview

Add advanced full-text search across all chapters with regex support and replace preview, plus a fixed TOC sidebar for quick chapter navigation in the reader view.

## Goals

- Search all translated chapters from reader UI (cross-chapter search)
- Replace with regex support (per-chapter or batch all)
- Preview diff before applying replace operations
- Fixed TOC sidebar on left for easy chapter navigation
- Keyboard shortcuts (Ctrl+F for search, T for TOC)

## Non-Goals

- Search indexing (YAGNI — on-demand scan is fast enough)
- Search in raw Chinese text (only translated Vietnamese)
- Undo/redo for replace (git history is sufficient)

## Architecture

### Approach: Pure Client-Side with API Support

Client-side UI in `reader.html` calls new backend APIs for search/replace. TOC data already available in template (`chapters_info`) — no additional API needed.

### Components

1. **TOC Sidebar** — Fixed left panel with chapter list, highlights current chapter
2. **Search/Replace Bar** — Floating bar (Ctrl+F), search input + options + results
3. **Backend APIs** — Search endpoint, preview endpoint, replace endpoint

## Detailed Design

### 1. TOC Sidebar

**UI:**
- Fixed panel on left, width ~240px
- Toggle with toolbar button (icon 📑) or keyboard shortcut `T`
- Chapter list from `chapters_info` (already in template context)
- Current chapter highlighted
- Click chapter → navigate to `/ebooks/{slug}/read/{index}`
- On mobile: collapse by default, drawer overlay when opened

**Layout:**
- When TOC open on desktop: reader content gets `margin-left: 240px`
- When TOC closed: margin-left returns to auto
- Smooth transition via CSS `transition: margin-left 0.2s`

**Data:**
```javascript
// Already available in template:
const chapters_info = {{ chapters_info | tojson }};
// [{index: 1, title: "...", has_translated: true}, ...]
```

**CSS Classes:**
- `.toc-sidebar` — fixed left panel
- `.toc-sidebar.open` — visible state
- `.toc-chapter-item` — chapter link
- `.toc-chapter-item.active` — current chapter
- `.reader-wrap.toc-open` — applied when TOC is open, adds margin-left

### 2. Search/Replace Bar

**Trigger:**
- Ctrl+F or toolbar button 🔍
- Esc to close

**UI Elements:**
- Search input (pattern)
- Checkbox: "Regex"
- Checkbox: "Case sensitive"
- Button: "Search" → fetch results
- Toggle: "Show Replace" → reveals replace input + buttons
- Replace input (replacement pattern)
- Button: "Replace in current chapter"
- Button: "Replace all chapters"
- Results area: list of chapters with matches, click to navigate

**Workflow:**
1. User enters pattern, clicks Search
2. Call `GET /api/ebooks/{slug}/search?q={pattern}&regex=1&case=1`
3. Display results grouped by chapter: "Chương X (5 matches) — snippet preview"
4. User toggles Replace, enters replacement pattern
5. Click "Replace all chapters" → call preview API
6. Display diff for each affected chapter (reuse `.diff-line.del/.ins` CSS)
7. User confirms → call replace API, show success toast, refresh reader if current chapter affected

**CSS Classes:**
- `.search-bar` — floating bar, fixed top below nav
- `.search-bar.hidden` — closed state
- `.search-results` — scrollable results list
- `.search-result-item` — chapter result card
- `.search-replace-controls` — replace input + buttons
- `.search-preview` — diff preview area

### 3. Backend APIs

#### `GET /api/ebooks/{slug}/search`

**Query params:**
- `q` (str, required) — search pattern
- `regex` (bool, default false) — treat pattern as regex
- `case` (bool, default false) — case sensitive

**Logic:**
1. Load manifest, iterate all chapters with `has_translated`
2. Read each translated file via `storage.read_translated(ch)`
3. If regex: `re.findall(pattern, text, flags)`, else `text.lower().count(pattern.lower())`
4. Collect matches: chapter index, title, count, snippet (first 100 chars around match)

**Response:**
```json
[
  {
    "chapter_index": 42,
    "title": "Chương 42 — Ngày đầu ở Thanh Vân",
    "count": 5,
    "snippets": ["...cảnh quan đẹp đẽ...", "...quan sát kỹ..."]
  }
]
```

**File:** `app/routes/reader.py` (add endpoint)

#### `POST /api/ebooks/{slug}/search-preview`

**Body (JSON):**
```json
{
  "pattern": "quan sát",
  "replacement": "nhìn ngắm",
  "regex": false,
  "case": false,
  "chapter_index": null  // null = all chapters, int = single chapter
}
```

**Logic:**
1. Load chapters (filtered by `chapter_index` if provided)
2. For each chapter: read translated, apply replacement in-memory
3. Generate diff via `difflib.unified_diff` or `difflib.HtmlDiff`
4. Return list of diffs

**Response:**
```json
[
  {
    "chapter_index": 42,
    "title": "Chương 42",
    "replacements": 5,
    "diff_lines": [
      {"type": "del", "text": "quan sát cảnh"},
      {"type": "ins", "text": "nhìn ngắm cảnh"},
      {"type": "eq", "text": "vật xung quanh"}
    ]
  }
]
```

**File:** `app/routes/reader.py`

#### `POST /api/ebooks/{slug}/search-replace`

**Body:** Same as preview

**Logic:**
1. Load chapters
2. For each chapter: read translated, apply replacement, **write back to disk**
3. Use `re.sub(pattern, replacement, text)` if regex, else `text.replace(pattern, replacement)`
4. Return count of chapters updated + total replacements

**Response:**
```json
{
  "chapters_updated": 12,
  "total_replacements": 47
}
```

**File:** `app/routes/reader.py`

### 4. Keyboard Shortcuts

Add to existing keydown handler in reader.html:

- `Ctrl+F` / `Cmd+F` → open search bar (prevent default browser search)
- `t` / `T` → toggle TOC sidebar
- `Esc` → close search bar if open

## Data Flow

### Search Flow

```
User [Ctrl+F] → Search Bar opens
User enters "修煉" + checks Regex
User clicks Search
→ GET /api/ebooks/{slug}/search?q=修煉&regex=1
→ Backend scans all translated files
→ Returns [{chapter_index, title, count, snippets}]
→ UI displays results
User clicks "Chương 42 (5 matches)"
→ Navigate to /ebooks/{slug}/read/42
```

### Replace Flow

```
User in Search Bar, toggle "Show Replace"
User enters replacement "tu luyện"
User clicks "Replace all chapters"
→ POST /api/ebooks/{slug}/search-preview
→ Backend generates diffs without writing
→ Returns [{chapter_index, title, diff_lines}]
→ UI displays diff preview
User clicks "Confirm Replace"
→ POST /api/ebooks/{slug}/search-replace
→ Backend writes to disk
→ Returns {chapters_updated, total_replacements}
→ UI shows toast, reloads reader if current chapter affected
```

### TOC Flow

```
User clicks 📑 button or presses T
→ `.toc-sidebar` gets class `open`
→ `.reader-wrap` gets class `toc-open` (margin-left: 240px)
→ TOC panel slides in from left
User clicks "Chương 123"
→ Navigate to /ebooks/{slug}/read/123
```

## Error Handling

- Invalid regex pattern → show toast "Regex không hợp lệ: {error}"
- No search results → display "Không tìm thấy kết quả"
- Replace API error → show toast, don't reload page
- Network error → generic "Lỗi kết nối, thử lại"

## Testing Strategy

- Manual testing: search with plain text, regex, case options
- Replace preview: verify diff display matches expected changes
- Replace apply: verify files written correctly, reload shows changes
- TOC: verify navigation works, highlight updates, mobile responsive
- Keyboard shortcuts: Ctrl+F intercepts browser default, Esc closes

## UI/UX Details

### TOC Sidebar Style
- Matches existing dark/light theme
- Scrollable chapter list if many chapters
- Current chapter bold + background highlight
- Icon: 📑 or ☰

### Search Bar Style
- Fixed position, `z-index: 50`, below nav bar
- Box shadow for elevation
- Results scrollable, max-height 50vh
- Snippet preview truncated to 100 chars with ellipsis
- Match count badge per chapter result

### Diff Preview Style
- Reuse existing `.diff-line`, `.diff-line.del`, `.diff-line.ins` classes
- Display in collapsible sections per chapter
- Green background for additions, red for deletions

## Performance

- Search scans all translated files in-memory: ~1000 chapters × 5KB avg = 5MB, scan time < 500ms
- No indexing needed (YAGNI)
- Replace preview generates diffs without I/O until user confirms
- Single-chapter operations are instant

## File Changes

### New Files
None (all changes in existing files)

### Modified Files

1. **`app/routes/reader.py`**
   - Add `@router.get("/api/ebooks/{slug}/search")`
   - Add `@router.post("/api/ebooks/{slug}/search-preview")`
   - Add `@router.post("/api/ebooks/{slug}/search-replace")`

2. **`app/templates/reader.html`**
   - Add TOC sidebar HTML structure
   - Add search/replace bar HTML structure
   - Add CSS for `.toc-sidebar`, `.search-bar`, `.search-results`, `.search-preview`
   - Add JavaScript for search/replace logic, TOC toggle, keyboard shortcuts
   - Inject `chapters_info` into JS context (already in template)

## Success Criteria

- User can search across all chapters from reader UI
- Regex search works correctly
- Replace preview shows accurate diffs
- Replace applies changes and updates visible chapter
- TOC sidebar provides quick chapter navigation
- Keyboard shortcuts work as specified
- Mobile responsive: TOC collapses, search bar adapts

## Future Enhancements (Out of Scope)

- Search in raw Chinese text
- Search highlighting within chapter text (current chapter only)
- Search history / saved patterns
- Export search results to file
- Fuzzy search / typo tolerance
