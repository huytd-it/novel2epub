# Reader Search + TOC Sidebar

**Date:** 2026-07-23
**Status:** Approved (revised after design review)
**Author:** AI + User

## Overview

Add cross-chapter full-text search (with regex) and a fixed TOC sidebar to the
reader view. Replace is offered from the search bar but **delegates to the
existing find/replace stack** (`step_find_replace` + `/glossary/propagate`)
rather than introducing a parallel write path — so batch edits keep going
through the job queue and keep their one-level backup.

## Design review outcome

The first draft added three new endpoints in `reader.py`, including a
`search-replace` that wrote every chapter to disk synchronously in the request
handler. That was dropped because the codebase already has the canonical
find/replace-across-chapters system, and the synchronous version was unsafe:

- **Existing stack (reuse, don't duplicate):**
  - [`step_find_replace`](../../../novel2epub/pipeline.py) — batch literal
    replace across chapters; saves `meta['before_find_replace']` for undo.
  - [`/api/ebooks/{slug}/glossary/match-count`](../../../app/routes/glossary.py)
    — per-chapter + total match counting; documented as *the* replace preview
    ("số đếm này chính là preview của propagate — không có bước xem trước riêng").
  - [`/api/ebooks/{slug}/glossary/propagate`](../../../app/routes/glossary.py)
    — `scope=chapter` writes one chapter immediately, `scope=all` **enqueues a
    `translate`-category job** and returns 409 if another job is running.
- **Why the synchronous write path was rejected:** it bypassed `JobQueue` and
  could interleave with a running translate/automation job editing the same
  `translated/` files (lost writes); it discarded the `before_find_replace`
  backup; and it re-implemented logic that already exists.
- **The only genuinely new backend capability is regex**, since
  `step_find_replace` is literal-only (`content.replace`). That is added as a
  `regex=` flag on the existing function + endpoints, not a new endpoint.

## Goals

- Search all translated chapters from the reader UI (cross-chapter)
- Regex + case-sensitivity options for search
- Replace from the reader, reusing the safe existing propagate flow
- Add regex support to the existing find/replace stack
- Fixed TOC sidebar on the left for quick chapter navigation
- Keyboard shortcuts (`Ctrl+Shift+F` for search, `T` for TOC, `Esc` to close)

## Non-Goals

- Search indexing (YAGNI — on-demand scan is fast enough)
- Search in raw Chinese text (only translated Vietnamese)
- **Multi-level undo** — the existing `before_find_replace` meta backup already
  gives one-level undo per chapter; that is reused, not removed. (The first
  draft called undo a non-goal citing git history; the workspace data dir is not
  git-tracked, so that reasoning was wrong.)
- Hijacking the browser's native `Ctrl+F` (readers expect in-page find to keep
  working; cross-chapter search uses `Ctrl+Shift+F`).
- A separate diff-preview step for replace — consistent with the glossary flow,
  the match count *is* the preview.

## Architecture

### Approach: read-only search in the reader, replace delegated

Client-side UI in `reader.html`:

- **Search** calls one new read-only endpoint (`GET .../search`).
- **Replace** calls the **existing** `/glossary/match-count` (preview) and
  `/glossary/propagate` (apply) endpoints — extended with a `regex` flag.
- **TOC** uses `chapters_info`, already in the template context. No new API.

### Components

1. **TOC Sidebar** — fixed left panel, chapter list, highlights current chapter.
2. **Search/Replace Bar** — floating bar (`Ctrl+Shift+F`); search is read-only,
   replace delegates to the existing propagate flow.
3. **Backend** — one new read-only search endpoint + a `regex` flag added to
   `step_find_replace`, `/glossary/match-count`, and `/glossary/propagate`.

## Detailed Design

### 1. TOC Sidebar

**UI:**
- Fixed panel on left, width ~240px.
- Toggle with toolbar button (📑) or keyboard `T`.
- Chapter list from `chapters_info` (already in template context; the same data
  already backs the `#chapter-select` dropdown).
- Current chapter highlighted; chapters without a translation dimmed (reuse the
  `has_translated` flag already present per entry).
- Click chapter → navigate to `/ebooks/{slug}/read/{index}`.
- Mobile: collapsed by default, drawer overlay when opened.

**Layout:**
- TOC open on desktop → reader content gets `margin-left: 240px`.
- TOC closed → margin returns to auto. `transition: margin-left 0.2s`.

**CSS Classes:**
- `.toc-sidebar` / `.toc-sidebar.open`
- `.toc-chapter-item` / `.toc-chapter-item.active`
- `.reader-wrap.toc-open` (adds margin-left)

### 2. Search/Replace Bar

**Trigger:**
- `Ctrl+Shift+F` or toolbar button 🔍. `Esc` closes.
- `Ctrl+F` is left alone → native in-page find still works.

**UI Elements:**
- Search input (pattern)
- Checkbox: "Regex"
- Checkbox: "Phân biệt hoa/thường" (case sensitive)
- Button: "Tìm" → fetch results
- Results area: chapters with matches; click a result → navigate.
- Toggle: "Thay thế" → reveals replace input + buttons.
- Replace input (replacement text/pattern).
- Button: "Thay trong chương này" → propagate `scope=chapter`.
- Button: "Thay tất cả chương" → propagate `scope=all` (enqueues job).

**Search workflow (read-only):**
1. User enters pattern, clicks Tìm.
2. `GET /api/ebooks/{slug}/search?q={pattern}&regex=1&case=1`
3. Results grouped by chapter: "Chương X (5 khớp) — snippet…".
4. Click result → navigate to that chapter.

**Replace workflow (delegates to existing endpoints):**
1. User toggles "Thay thế", enters replacement.
2. On focus/entry, call `GET /glossary/match-count?find=…&regex=…` to show the
   counts (this *is* the preview — per-chapter count + total, matching the
   glossary flow). No separate diff endpoint.
3. "Thay trong chương này" → `POST /glossary/propagate` with
   `scope=chapter&chapter_index={current}` → writes immediately (with
   `before_find_replace` backup), reload the reader.
4. "Thay tất cả chương" → `POST /glossary/propagate` with `scope=all` →
   enqueues a `translate`-category job. On 409 ("Đang có job khác chạy"), show a
   toast and do not reload.

**Note on the `/glossary/*` path:** these endpoints operate on the translated
files, not on glossary entries specifically (propagate's docstring: "Không tự
sửa mục glossary"). Reusing them from the reader is intentional; renaming them to
a neutral `find-replace` namespace is out of scope for this change.

**CSS Classes:**
- `.search-bar` / `.search-bar.hidden`
- `.search-results` / `.search-result-item`
- `.search-replace-controls`

### 3. Backend

#### NEW — `GET /api/ebooks/{slug}/search`  (read-only)

**File:** `app/routes/reader.py`

**Query params:**
- `q` (str, required) — search pattern
- `regex` (bool, default false) — treat pattern as regex
- `case` (bool, default false) — case sensitive

**Logic (single code path for count + snippets):**
1. Load manifest; iterate chapters where `storage.has_translated(ch)`.
2. Build a compiled pattern once:
   - regex: `re.compile(q, 0 if case else re.IGNORECASE)`
   - literal: `re.compile(re.escape(q), 0 if case else re.IGNORECASE)`
   - Invalid regex → `HTTPException(400, "Regex không hợp lệ: …")`.
3. `matches = list(pattern.finditer(text))`; skip chapter if none.
4. `count = len(matches)`; take up to N (e.g. 3) snippets: ~100 chars around
   each `match.start()`, ellipsis-trimmed.
5. Title via `ch.title or f"Chương {ch.index}"` (never hardcode a prefix).

**Response:**
```json
[
  {"chapter_index": 42, "title": "Chương 42 — …", "count": 5,
   "snippets": ["…cảnh quan đẹp đẽ…", "…quan sát kỹ…"]}
]
```

#### EXTEND — `step_find_replace(...)`  in `pipeline.py`

Add `regex: bool = False`. When set, compile `find` once and use
`pattern.subn(replace, content)` for both the count and the replacement
(replacing the literal `content.count(find)` / `content.replace(...)` path).
The `meta['before_find_replace']` backup and `also_raw` handling are unchanged.

#### EXTEND — `GET /api/ebooks/{slug}/glossary/match-count`

Add `regex: bool = False`. When set, count via `len(pattern.findall(content))`
with the same compile-once logic. Still returns
`{chapter_count, total_count, chapter_total}` — the replace preview.

#### EXTEND — `POST /api/ebooks/{slug}/glossary/propagate`

Add `regex: bool = Form(False)`. `scope=chapter` uses `pattern.subn` inline
(keeping the backup); `scope=all` forwards `regex=regex` into
`step_find_replace`. Job-queue + 409 behavior unchanged.

### 4. Keyboard Shortcuts

The reader has **two** `keydown` handlers today (the nav/bookmark handler and
the compare-mode handler); wire these into the nav handler, which already guards
against `INPUT`/`TEXTAREA`/`SELECT` focus:

- `Ctrl+Shift+F` / `Cmd+Shift+F` → open search bar (preventDefault). Plain
  `Ctrl+F` is **not** intercepted.
- `t` / `T` → toggle TOC sidebar.
- `Esc` → close search bar if open (must also fire when focus is inside the
  search input).

## Data Flow

### Search Flow (read-only)

```
User [Ctrl+Shift+F] → search bar opens
User enters "修煉" + checks Regex → clicks Tìm
→ GET /api/ebooks/{slug}/search?q=修煉&regex=1
→ backend scans translated files → [{chapter_index, title, count, snippets}]
→ UI lists results
User clicks "Chương 42 (5 khớp)" → navigate /ebooks/{slug}/read/42
```

### Replace Flow (delegated, safe)

```
User toggles "Thay thế", enters "tu luyện"
→ GET /glossary/match-count?find=修煉&replace=…&regex=1   (preview counts)
User clicks "Thay tất cả chương"
→ POST /glossary/propagate  scope=all  regex=1
→ enqueues translate-category job (step_find_replace, regex=True)
   • 200 → toast "Đã xếp hàng", job writes with before_find_replace backup
   • 409 → toast "Đang có job khác chạy" (no reload)
User clicks "Thay trong chương này"
→ POST /glossary/propagate  scope=chapter  chapter_index={current}  regex=1
→ writes immediately (+ backup) → reload reader
```

### TOC Flow

```
User clicks 📑 or presses T
→ .toc-sidebar gets .open ; .reader-wrap gets .toc-open (margin-left:240px)
User clicks "Chương 123" → navigate /ebooks/{slug}/read/123
```

## Concurrency & Safety

- All disk writes go through the existing propagate/step_find_replace path, so
  batch replace runs as a `translate`-category job and cannot race concurrent
  crawl/translate/automation jobs. `scope=all` returns 409 when a job is active.
- Each replaced chapter keeps `meta['before_find_replace']` (one-level undo),
  preserved for both literal and regex replaces.
- The new `/search` endpoint is read-only — no locking concerns.
- Regex is compiled once per request; invalid patterns fail fast with 400.

## Error Handling

- Invalid regex (search or replace) → toast/400 "Regex không hợp lệ: {error}".
- No search results → "Không tìm thấy kết quả".
- Replace-all while a job runs → 409 → toast "Đang có job khác chạy", no reload.
- Network error → "Lỗi kết nối, thử lại".

## Testing Strategy

- Unit: `step_find_replace(..., regex=True)` — count + `subn`, backup written.
- Unit: `/glossary/match-count?regex=1` and `/glossary/propagate?regex=1`.
- Unit: `GET /search` — literal, regex, case on/off; invalid regex → 400;
  snippet windows; title fallback for untitled chapters.
- Manual: search navigation; replace-current reloads; replace-all enqueues and
  409s correctly; TOC navigation + active highlight; mobile drawer.
- Manual: `Ctrl+F` still triggers native find; `Ctrl+Shift+F` opens the bar.

## UI/UX Details

### TOC Sidebar
- Matches existing dark/light theme; scrollable list; current chapter
  bold + highlighted; untranslated chapters dimmed. Icon 📑.

### Search Bar
- Fixed, `z-index: 50`, below nav; box shadow; results scrollable
  `max-height: 50vh`; snippets truncated ~100 chars with ellipsis; per-chapter
  match-count badge.

## Performance

- Search scans translated files in-memory (~1000 chapters × ~5KB ≈ 5MB,
  < 500ms). No indexing (YAGNI).
- Replace preview is just match counts (no diff generation, no I/O beyond read).
- Single-chapter replace is instant; batch replace is a background job.

## File Changes

### Modified Files

1. **`novel2epub/pipeline.py`** — add `regex: bool = False` to
   `step_find_replace`.
2. **`app/routes/glossary.py`** — add `regex` to `match-count` and `propagate`.
3. **`app/routes/reader.py`** — add read-only `GET /api/ebooks/{slug}/search`.
4. **`app/templates/reader.html`** — TOC sidebar + search/replace bar (replace
   delegates to `/glossary/*`), CSS, JS, keyboard shortcuts. `chapters_info`
   already in context.

### New Files
None.

## Success Criteria

- User can search across all chapters from the reader (literal + regex + case).
- Replace runs through the existing safe path: current-chapter immediate (with
  backup), all-chapters as a job (409-aware), regex supported end-to-end.
- TOC sidebar provides quick navigation with an accurate active highlight.
- `Ctrl+Shift+F` opens search; native `Ctrl+F` still works; `T`/`Esc` behave.
- Mobile responsive: TOC collapses, search bar adapts.

## Future Enhancements (Out of Scope)

- Search in raw Chinese text
- In-chapter match highlighting for the current chapter
- Search history / saved patterns
- Rename `/glossary/{match-count,propagate}` to a neutral `find-replace`
  namespace (they already operate on translations, not glossary entries)
- Multi-level / cross-chapter undo beyond the existing one-level backup
