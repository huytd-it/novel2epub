# Glossary Pending Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show pending AI glossary suggestions and conflicts at the top of the main glossary table, with editable per-row and bulk approval actions.

**Architecture:** Keep paginated approved entries in the existing `ROWS` state and load pending/conflict snapshots in parallel into separate arrays. Add one server-side bulk conflict endpoint so overwrite and conflict removal happen in the correct order; reuse the existing pending APIs and main-entry CRUD APIs.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, browser JavaScript, Tailwind utility classes, pytest, FastAPI TestClient

## Global Constraints

- Pending suggestions and conflicts remain excluded from translation prompts until approval writes them into the SQLite-backed `names.txt` glossary.
- Search, sort, and pagination continue to apply only to approved glossary entries.
- Pending suggestions and conflicts always render before approved entries.
- Bulk requests carry explicit client snapshots so suggestions created concurrently remain queued.
- Preserve the existing `Nghi vấn` tab and its single-conflict resolve flow.
- Do not add a frontend framework or external dependency.

---

## File Structure

- Modify `app/routes/glossary.py`: add the validated bulk conflict API and keep persistence ordering server-side.
- Modify `app/templates/glossary.html`: render three row types, load the three data sources, and implement type-specific single and bulk actions.
- Modify `tests/test_routes_glossary.py`: cover conflict bulk take/keep, stale snapshots, validation, and pending snapshot concurrency.
- Create `tests/test_glossary_template.py`: lightweight source-level regression checks for required controls, payload fields, and row-type separation.

### Task 1: Atomic Bulk Conflict Resolution

**Files:**
- Modify: `app/routes/glossary.py:246-264`
- Modify: `tests/test_routes_glossary.py:304-390`

**Interfaces:**
- Consumes: `Storage.read_extra_json("glossary_conflicts")`, `Storage.write_extra_json("glossary_conflicts", rows)`, and `Storage.upsert_glossary_entry(source, target, note)`.
- Produces: `POST /api/ebooks/{slug}/glossary/conflicts/bulk-resolve` with JSON `{ "action": "take" | "keep", "entries": [{ "source": str, "original_new": str, "target": str, "note": str }] }`; returns `{ "resolved": int, "remaining": int }`.

- [ ] **Step 1: Write route tests for taking edited AI values and preserving stale/unselected conflicts**

Append these tests near the existing pending/conflict route tests in `tests/test_routes_glossary.py`:

```python
def test_bulk_conflicts_take_upserts_edited_values_and_keeps_unselected(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "叶凡 = Diệp Phàm cũ\n")
    storage.write_extra_json(
        "glossary_conflicts",
        [
            {"source": "叶凡", "existing": "Diệp Phàm cũ", "new": "Diệp Phàm"},
            {"source": "林动", "existing": "Lâm Động", "new": "Lâm Động mới"},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={
            "action": "take",
            "entries": [
                {
                    "source": "叶凡",
                    "original_new": "Diệp Phàm",
                    "target": "Diệp Phàm hiệu chỉnh",
                    "note": "nhân vật chính",
                }
            ],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"resolved": 1, "remaining": 1}
    assert ("叶凡", "Diệp Phàm hiệu chỉnh", "nhân vật chính") in storage.read_glossary_entries("names.txt")
    assert storage.read_extra_json("glossary_conflicts") == [
        {"source": "林动", "existing": "Lâm Động", "new": "Lâm Động mới"}
    ]


def test_bulk_conflicts_take_ignores_stale_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "叶凡 = Giá trị hiện tại\n")
    storage.write_extra_json(
        "glossary_conflicts",
        [{"source": "叶凡", "existing": "Giá trị hiện tại", "new": "Đề xuất mới hơn"}],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={
            "action": "take",
            "entries": [
                {
                    "source": "叶凡",
                    "original_new": "Đề xuất cũ đã biến mất",
                    "target": "Không được ghi",
                    "note": "",
                }
            ],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"resolved": 0, "remaining": 1}
    assert storage.read_glossary_file("names.txt") == {"叶凡": "Giá trị hiện tại"}
```

- [ ] **Step 2: Run the take tests to verify they fail**

Run:

```bash
pytest tests/test_routes_glossary.py::test_bulk_conflicts_take_upserts_edited_values_and_keeps_unselected tests/test_routes_glossary.py::test_bulk_conflicts_take_ignores_stale_snapshot -v
```

Expected: both tests fail with `404 Not Found` because the bulk endpoint does not exist.

- [ ] **Step 3: Implement the minimal bulk conflict endpoint**

Add below `ebook_glossary_conflict_resolve` in `app/routes/glossary.py`:

```python
@router.post("/api/ebooks/{slug}/glossary/conflicts/bulk-resolve")
def ebook_glossary_conflicts_bulk_resolve(slug: str, payload: dict = Body(...)):
    action = payload.get("action")
    if action not in {"take", "keep"}:
        raise HTTPException(status_code=400, detail="Thao tác conflict không hợp lệ.")

    requested: dict[tuple[str, str], dict[str, str]] = {}
    rows = payload.get("entries")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source", "")).strip()
        original_new = str(row.get("original_new", "")).strip()
        target = str(row.get("target", "")).strip()
        if not source or not original_new or (action == "take" and not target):
            continue
        requested[(source, original_new)] = {
            "target": target,
            "note": str(row.get("note", "")).strip(),
        }
    if not requested:
        raise HTTPException(status_code=400, detail="Chưa chọn conflict hợp lệ.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    raw = storage.read_extra_json("glossary_conflicts")
    conflicts = raw if isinstance(raw, list) else []
    remaining = []
    resolved = 0
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            remaining.append(conflict)
            continue
        key = (str(conflict.get("source", "")).strip(), str(conflict.get("new", "")).strip())
        request_row = requested.get(key)
        if request_row is None:
            remaining.append(conflict)
            continue
        if action == "take":
            storage.upsert_glossary_entry(key[0], request_row["target"], request_row["note"])
        resolved += 1

    storage.write_extra_json("glossary_conflicts", remaining)
    return JSONResponse({"resolved": resolved, "remaining": len(remaining)})
```

- [ ] **Step 4: Run the take tests to verify they pass**

Run the command from Step 2.

Expected: `2 passed`.

- [ ] **Step 5: Add tests for keep, validation, and pending snapshot concurrency**

Append:

```python
def test_bulk_conflicts_keep_resolves_without_changing_glossary(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "叶凡 = Giữ nguyên\n")
    storage.write_extra_json(
        "glossary_conflicts",
        [{"source": "叶凡", "existing": "Giữ nguyên", "new": "Không lấy"}],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={
            "action": "keep",
            "entries": [{"source": "叶凡", "original_new": "Không lấy"}],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"resolved": 1, "remaining": 0}
    assert storage.read_glossary_file("names.txt") == {"叶凡": "Giữ nguyên"}


def test_bulk_conflicts_rejects_invalid_action_and_empty_entries(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)

    bad_action = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={"action": "delete", "entries": [{"source": "叶凡", "original_new": "x"}]},
    )
    empty = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={"action": "take", "entries": []},
    )

    assert bad_action.status_code == 400
    assert empty.status_code == 400


def test_pending_approve_preserves_suggestions_outside_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_extra_json(
        "glossary_pending",
        [
            {"source": "叶凡", "target": "Diệp Phàm", "chapter_index": 1},
            {"source": "Mới", "target": "Được thêm đồng thời", "chapter_index": 2},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/pending/approve",
        json={
            "entries": [
                {
                    "source": "叶凡",
                    "target": "Diệp Phàm sửa",
                    "note": "",
                    "original_source": "叶凡",
                }
            ]
        },
    )

    assert res.status_code == 200
    assert [row["source"] for row in storage.read_extra_json("glossary_pending")] == ["Mới"]
```

- [ ] **Step 6: Run focused route tests**

Run:

```bash
pytest tests/test_routes_glossary.py -k "bulk_conflicts or pending_approve" -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the backend unit**

```bash
git add app/routes/glossary.py tests/test_routes_glossary.py
git commit -m "feat: add bulk glossary conflict resolution"
```

### Task 2: Unified Glossary Table and Bulk Approval UI

**Files:**
- Modify: `app/templates/glossary.html:15-452`
- Create: `tests/test_glossary_template.py`

**Interfaces:**
- Consumes: existing glossary list/pending/suspects endpoints and Task 1's `POST /api/ebooks/{slug}/glossary/conflicts/bulk-resolve` payload.
- Produces: JavaScript state `PENDING_ROWS` and `CONFLICT_ROWS`; row checkboxes with `data-kind="pending" | "conflict" | "entry"`; toolbar buttons `btn-approve-selected`, `btn-approve-all`, `btn-pending-clear`, `btn-conflict-take`, `btn-conflict-keep`, and existing `btn-bulk-delete`.

- [ ] **Step 1: Write source-level template tests for the required table contract**

Create `tests/test_glossary_template.py`:

```python
from pathlib import Path


TEMPLATE = (Path(__file__).parents[1] / "app" / "templates" / "glossary.html").read_text(
    encoding="utf-8"
)


def test_glossary_table_exposes_pending_and_conflict_controls():
    required_ids = {
        "btn-approve-selected",
        "btn-approve-all",
        "btn-pending-clear",
        "btn-conflict-take",
        "btn-conflict-keep",
    }
    for control_id in required_ids:
        assert f'id="{control_id}"' in TEMPLATE
    assert "AI đề xuất mới" in TEMPLATE
    assert 'data-kind="pending"' in TEMPLATE
    assert 'data-kind="conflict"' in TEMPLATE
    assert 'data-kind="entry"' in TEMPLATE


def test_glossary_loader_fetches_all_three_sources_in_parallel():
    assert "Promise.all" in TEMPLATE
    assert "/glossary/list?" in TEMPLATE
    assert "/glossary/pending" in TEMPLATE
    assert "/glossary/suspects" in TEMPLATE
    assert "PENDING_ROWS" in TEMPLATE
    assert "CONFLICT_ROWS" in TEMPLATE


def test_glossary_bulk_payloads_use_explicit_snapshots():
    assert "original_source" in TEMPLATE
    assert "original_new" in TEMPLATE
    assert "/glossary/pending/approve" in TEMPLATE
    assert "/glossary/pending/clear" in TEMPLATE
    assert "/glossary/conflicts/bulk-resolve" in TEMPLATE
    assert 'action: "take"' in TEMPLATE
    assert 'action: "keep"' in TEMPLATE
```

- [ ] **Step 2: Run the template tests to verify they fail**

Run:

```bash
pytest tests/test_glossary_template.py -v
```

Expected: three failures because the unified-table controls and state do not exist.

- [ ] **Step 3: Add the unified columns and type-specific toolbar controls**

In `app/templates/glossary.html`, replace the single delete bulk control with:

```html
<button type="button" id="btn-approve-selected" class="btn btn-sm btn-primary hidden">Duyệt đã chọn (<span id="approve-count">0</span>)</button>
<button type="button" id="btn-approve-all" class="btn btn-sm btn-primary hidden">Duyệt tất cả (<span id="approve-all-count">0</span>)</button>
<button type="button" id="btn-pending-clear" class="btn btn-sm btn-secondary hidden">Bỏ đề xuất đã chọn (<span id="pending-clear-count">0</span>)</button>
<button type="button" id="btn-conflict-take" class="btn btn-sm btn-primary hidden">Chấp nhận ghi đè (<span id="conflict-take-count">0</span>)</button>
<button type="button" id="btn-conflict-keep" class="btn btn-sm btn-secondary hidden">Giữ hiện tại (<span id="conflict-keep-count">0</span>)</button>
<button type="button" id="btn-bulk-delete" class="btn btn-sm btn-danger hidden">Xóa đã chọn (<span id="bulk-count">0</span>)</button>
```

Change the header to seven columns:

```html
<th class="w-8"><input type="checkbox" id="check-all" class="rounded border-surface-border dark:border-surface-border-dark" title="Chọn các dòng đang hiển thị"></th>
<th class="w-24">Trạng thái</th>
<th data-dt-sort class="gloss-th">Hán <span class="sort-ind"></span></th>
<th data-dt-sort data-dt-filter class="gloss-th">Việt hiện tại <span class="sort-ind"></span></th>
<th>AI đề xuất mới</th>
<th>Ghi chú</th>
<th class="w-56">Thao tác</th>
```

- [ ] **Step 4: Add separate pending/conflict state and three-source loading**

Near `ROWS`, add:

```javascript
let PENDING_ROWS = [];
let CONFLICT_ROWS = [];
```

Replace `loadPage()`'s single fetch with `Promise.all` and normalize editable snapshots:

```javascript
const [listRes, pendingRes, suspectsRes] = await Promise.all([
    fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/list?${params}`),
    fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/pending`),
    fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/suspects`),
]);
if (!listRes.ok || !pendingRes.ok || !suspectsRes.ok) {
    toast("Không tải được dữ liệu glossary.", "error");
    return;
}
const [data, pendingData, suspectData] = await Promise.all([
    listRes.json(), pendingRes.json(), suspectsRes.json(),
]);
ROWS = data.entries.map(e => ({ ...e, _saved: e.source, _savedTarget: e.target }));
PENDING_ROWS = pendingData.entries.map(e => ({
    ...e, note: "", originalSource: e.source, selected: false,
}));
CONFLICT_ROWS = suspectData.conflicts.map(e => ({
    ...e, target: e.new, note: "", originalNew: e.new, selected: false,
}));
```

Keep the existing assignments for `total`, `pages`, `state.page`, and `state.perPage`, then call `render()`.

- [ ] **Step 5: Render conflict, pending, then approved rows**

Split rendering into `conflictRow`, `pendingRow`, and `entryRow` functions. The rendered HTML must include these stable row contracts:

```javascript
function conflictRow(e, idx) {
    return `<tr class="border-t border-status-warn-light dark:border-status-warn-dark bg-status-warn-light/40 dark:bg-status-warn-dark/30" data-kind="conflict" data-conflict-idx="${idx}">
        <td class="px-2 py-1"><input type="checkbox" class="bulk-check" data-kind="conflict"></td>
        <td class="px-2 py-1"><span class="badge badge-warn">Xung đột</span></td>
        <td class="px-2 py-1 font-mono">${escapeHtml(e.source)}</td>
        <td class="px-2 py-1">${escapeHtml(e.kept)}</td>
        <td class="px-2 py-1"><input data-conflict-field="target" value="${escapeHtml(e.target)}" class="${inputCls}"></td>
        <td class="px-2 py-1"><input data-conflict-field="note" value="${escapeHtml(e.note)}" placeholder="—" class="${inputCls}"></td>
        <td class="px-2 py-1 whitespace-nowrap">
            <button type="button" data-act="conflict-take" class="btn btn-sm btn-primary">Chấp nhận ghi đè</button>
            <button type="button" data-act="conflict-keep" class="btn btn-sm btn-ghost">Giữ hiện tại</button>
        </td>
    </tr>`;
}

function pendingRow(e, idx) {
    return `<tr class="border-t border-brand-200 dark:border-brand-800 bg-brand-50/50 dark:bg-brand-950/20" data-kind="pending" data-pending-idx="${idx}">
        <td class="px-2 py-1"><input type="checkbox" class="bulk-check" data-kind="pending"></td>
        <td class="px-2 py-1"><span class="badge badge-run">Chờ duyệt</span></td>
        <td class="px-2 py-1"><input data-pending-field="source" value="${escapeHtml(e.source)}" class="${inputCls} font-mono"></td>
        <td class="px-2 py-1 text-fg-muted dark:text-fg-muted-dark">—</td>
        <td class="px-2 py-1"><input data-pending-field="target" value="${escapeHtml(e.target)}" class="${inputCls}"></td>
        <td class="px-2 py-1"><input data-pending-field="note" value="${escapeHtml(e.note)}" placeholder="—" class="${inputCls}"></td>
        <td class="px-2 py-1 whitespace-nowrap">
            <button type="button" data-act="pending-approve" class="btn btn-sm btn-primary">Duyệt</button>
            <button type="button" data-act="pending-clear" class="btn btn-sm btn-ghost">Bỏ đề xuất</button>
        </td>
    </tr>`;
}
```

Adapt the current approved row HTML into `entryRow(e, idx)` by adding `data-kind="entry"`, a checkbox `data-kind="entry"`, an empty status cell, and an empty AI-proposal cell. Then render in this exact order:

```javascript
body.innerHTML = [
    ...CONFLICT_ROWS.map(conflictRow),
    ...PENDING_ROWS.map(pendingRow),
    ...ROWS.map(entryRow),
].join("");
```

Set the empty message based on all three arrays, and update the counter:

```javascript
countLabel.textContent = `${total} mục · ${PENDING_ROWS.length} chờ duyệt · ${CONFLICT_ROWS.length} xung đột`;
```

When `state.q` is non-empty, retain the existing approved-match wording and append the two queue counts.

- [ ] **Step 6: Separate selection by row kind**

Replace source-only checkbox helpers with:

```javascript
function checkedRows(kind) {
    return Array.from(document.querySelectorAll(`.bulk-check[data-kind="${kind}"]:checked`))
        .map(cb => cb.closest("tr"));
}

function refreshBulkBtn() {
    const pendingCount = checkedRows("pending").length;
    const conflictCount = checkedRows("conflict").length;
    const entryCount = checkedRows("entry").length;
    approveCount.textContent = pendingCount;
    approveAllCount.textContent = PENDING_ROWS.length;
    pendingClearCount.textContent = pendingCount;
    conflictTakeCount.textContent = conflictCount;
    conflictKeepCount.textContent = conflictCount;
    bulkCount.textContent = entryCount;
    approveSelectedBtn.classList.toggle("hidden", pendingCount === 0);
    approveAllBtn.classList.toggle("hidden", PENDING_ROWS.length === 0);
    pendingClearBtn.classList.toggle("hidden", pendingCount === 0);
    conflictTakeBtn.classList.toggle("hidden", conflictCount === 0);
    conflictKeepBtn.classList.toggle("hidden", conflictCount === 0);
    bulkBtn.classList.toggle("hidden", entryCount === 0);
}
```

Declare the referenced button/count elements next to the existing bulk declarations. Update `check-all` to toggle every `#gloss-body .bulk-check`, and update approved bulk deletion to derive sources only from checked entry rows and their `data-idx` values.

- [ ] **Step 7: Track edits and build explicit pending/conflict snapshots**

Add delegated input handling:

```javascript
body.addEventListener("input", e => {
    const pendingField = e.target.dataset.pendingField;
    if (pendingField) {
        const row = PENDING_ROWS[Number(e.target.closest("tr").dataset.pendingIdx)];
        if (row) row[pendingField] = e.target.value;
        return;
    }
    const conflictField = e.target.dataset.conflictField;
    if (conflictField) {
        const row = CONFLICT_ROWS[Number(e.target.closest("tr").dataset.conflictIdx)];
        if (row) row[conflictField] = e.target.value;
        return;
    }
    const field = e.target.dataset.field;
    if (!field) return;
    const row = rowByEl(e.target);
    if (row) row[field] = e.target.value;
});
```

Add payload helpers:

```javascript
function pendingPayload(rows) {
    return rows.map(tr => PENDING_ROWS[Number(tr.dataset.pendingIdx)])
        .filter(row => row && row.source.trim() && row.target.trim())
        .map(row => ({
            source: row.source.trim(), target: row.target.trim(), note: row.note,
            original_source: row.originalSource,
        }));
}

function conflictPayload(rows) {
    return rows.map(tr => CONFLICT_ROWS[Number(tr.dataset.conflictIdx)])
        .filter(row => row && row.source && row.originalNew)
        .map(row => ({
            source: row.source, original_new: row.originalNew,
            target: row.target.trim(), note: row.note,
        }));
}
```

- [ ] **Step 8: Implement pending single and bulk actions**

Add helpers that disable the triggering button for the request and always restore it in `finally`. Implement approval with JSON `{entries}` sent to `/glossary/pending/approve`, clear with `{sources: originalSource[]}` sent to `/glossary/pending/clear`, and call `loadPage()` only after success.

Use these exact calls for the toolbar:

```javascript
approveSelectedBtn.addEventListener("click", () => approvePending(checkedRows("pending"), approveSelectedBtn));
approveAllBtn.addEventListener("click", () => {
    const rows = Array.from(document.querySelectorAll('tr[data-kind="pending"]'));
    approvePending(rows, approveAllBtn);
});
pendingClearBtn.addEventListener("click", () => clearPending(checkedRows("pending"), pendingClearBtn));
```

In the delegated body click handler, dispatch `pending-approve` and `pending-clear` with `[tr]`. Before bulk approval or clear, use `confirmDialog` with the number of valid entries. On success, toast the API's `approved` or `cleared` count.

- [ ] **Step 9: Implement conflict single and bulk actions**

Add:

```javascript
async function resolveConflicts(action, rows, button) {
    const entries = conflictPayload(rows);
    if (!entries.length) return;
    const verb = action === "take" ? "ghi đè" : "giữ giá trị hiện tại cho";
    if (!await confirmDialog(`${verb} ${entries.length} xung đột?`)) return;
    button.disabled = true;
    try {
        const res = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/conflicts/bulk-resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, entries }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(data.detail || "Xử lý xung đột thất bại.", "error"); return; }
        toast(`Đã xử lý ${data.resolved} xung đột.`, "success");
        await loadPage();
    } catch (err) {
        toast("Lỗi kết nối mạng.", "error");
    } finally {
        button.disabled = false;
    }
}
```

Wire toolbar actions:

```javascript
conflictTakeBtn.addEventListener("click", () => resolveConflicts("take", checkedRows("conflict"), conflictTakeBtn));
conflictKeepBtn.addEventListener("click", () => resolveConflicts("keep", checkedRows("conflict"), conflictKeepBtn));
```

In the body click handler, dispatch `conflict-take` and `conflict-keep` with `[tr]`. After a single successful `take`, call `showPropagateBanner` with `kept` and the edited target if those values differ; bulk overwrite only shows the success toast because one banner cannot represent multiple replacements safely.

- [ ] **Step 10: Keep the suspects view compatible and correct colspan values**

Do not remove `loadSuspects()` or its existing conflict controls. Change the propagate banner's `colspan="5"` to `colspan="7"` for the unified main table. Ensure `setView(true)` hides the unified table and toolbar bulk buttons refresh from only currently rendered suspect checkboxes; existing suspect entry deletion must continue to use entry-kind checkboxes or remain isolated from the unified bulk controls.

- [ ] **Step 11: Run template and route regressions**

Run:

```bash
pytest tests/test_glossary_template.py tests/test_routes_glossary.py -v
```

Expected: all tests pass.

- [ ] **Step 12: Run translator prompt-source regression tests**

Run:

```bash
pytest tests/test_translator.py -k "glossary" -v
```

Expected: all selected tests pass, including pending being excluded from prompt sources.

- [ ] **Step 13: Commit the UI unit**

```bash
git add app/templates/glossary.html tests/test_glossary_template.py
git commit -m "feat: review pending glossary entries in main table"
```

### Task 3: Full Glossary Verification

**Files:**
- Verify: `app/routes/glossary.py`
- Verify: `app/templates/glossary.html`
- Verify: `tests/test_routes_glossary.py`
- Verify: `tests/test_glossary_template.py`

**Interfaces:**
- Consumes: completed route and browser-table behavior from Tasks 1-2.
- Produces: verified feature with no additional interface.

- [ ] **Step 1: Run all glossary-related tests**

Run:

```bash
pytest tests/test_routes_glossary.py tests/test_glossary_review.py tests/test_glossary_template.py tests/test_translator.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the complete test suite**

Run:

```bash
pytest tests/ -v
```

Expected: all tests pass. If an unrelated pre-existing failure occurs, record its exact test name and output rather than modifying unrelated code.

- [ ] **Step 3: Inspect the final diff for scope and accidental changes**

Run:

```bash
git status --short
git diff --check
git diff -- app/routes/glossary.py app/templates/glossary.html tests/test_routes_glossary.py tests/test_glossary_template.py
```

Expected: no whitespace errors; only the planned glossary route, template, and tests are changed.

- [ ] **Step 4: Commit any verification-only corrections**

Only if verification required corrections:

```bash
git add app/routes/glossary.py app/templates/glossary.html tests/test_routes_glossary.py tests/test_glossary_template.py
git commit -m "fix: finalize glossary approval workflow"
```
