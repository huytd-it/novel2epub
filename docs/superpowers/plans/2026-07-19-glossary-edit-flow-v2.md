# Glossary Edit Flow v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One unified "edit → show match count → pick propagation scope" pattern for every place glossary gets edited, plus bulk delete and a "Nghi vấn" (suspects) review view.

**Architecture:** New thin routes in `app/routes/glossary.py` (match-count, propagate, bulk delete, suspects, conflict resolve) reusing existing Storage primitives and `step_find_replace`; pure suspect-grouping logic in a new `novel2epub/glossary_review.py`; vanilla-JS UI changes in `glossary.html` (banner, checkboxes, suspects tab) and `chapter.html` (selection popover). The old "Áp dụng lại" modal and its 2 routes are deleted.

**Tech Stack:** Python 3.10+, FastAPI, SQLite (via existing `Storage`), Jinja2, vanilla JS + Tailwind utility classes, pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-07-19-glossary-edit-flow-v2-design.md`

## Global Constraints

- All UI copy in Vietnamese, matching existing tone (e.g. "Lỗi kết nối mạng.", "Đã lưu.").
- No new dependencies — vanilla JS, existing Tailwind utility classes, existing helpers (`toast`, `escapeHtml`).
- No DB schema changes. No chapter-meta format changes (`before_find_replace` backup format must stay identical to `step_find_replace`'s).
- Comments in code follow house style: Vietnamese, explain constraints not mechanics.
- Tests: pytest, reuse `_cfg` / `_FakeJob` / `_client` helpers already in `tests/test_routes_glossary.py`.
- Run tests with: `python -m pytest tests/<file> -v` from repo root `D:\Projects\novel2epub`.

---

### Task 1: Fix fatal duplicate `const statusSection` in chapter.html

The main `<script>` block of the chapter page declares `const statusSection` twice (lines ~544 and ~556) in the same scope — a `SyntaxError` that kills ALL JS on the page (glossary highlight, diff, job polling). The popover (Task 9) lives in this block, so this must be fixed first.

**Files:**
- Modify: `app/templates/chapter.html:544-556`

**Interfaces:**
- Produces: a working top-level script scope in chapter.html with exactly one `statusSection` binding (used by Task 9).

- [ ] **Step 1: Remove the second declaration**

In `app/templates/chapter.html`, find the two occurrences of:

```js
const statusSection = document.getElementById("job-status-section");
```

One sits right before `function jobCategoryFor(form) {`; the second sits right after that function, before `document.addEventListener("submit", ...)`. Delete the **second** occurrence (and its surrounding blank line), keeping the first.

- [ ] **Step 2: Verify exactly one declaration remains**

Run: `grep -c "const statusSection" app/templates/chapter.html` (Git Bash)
Expected: `1`

- [ ] **Step 3: Verify page JS parses in browser**

Start the dev server via the browser preview tools using `.claude/launch.json` — if it doesn't exist, create it with:

```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "web", "runtimeExecutable": "uvicorn", "runtimeArgs": ["app.main:app", "--port", "8010"], "port": 8010 }
  ]
}
```

Open any chapter page (`/ebooks/<slug>/chapters/<n>`) and check the browser console: no `SyntaxError: Identifier 'statusSection' has already been declared`. Glossary highlight `<mark>` tags should now appear in the ZH column when "Tô sáng glossary" is checked.

- [ ] **Step 4: Commit**

```bash
git add app/templates/chapter.html
git commit -m "fix: duplicate const statusSection killed all chapter-page JS"
```

---

### Task 2: `match-count` + `propagate` routes; delete the 2 `reapply` routes

**Files:**
- Modify: `app/routes/glossary.py` (rename `_reapply_chapters`→`_matching_chapters`; delete `_snippet`, `ebook_glossary_reapply_preview`, `ebook_glossary_reapply`; add 2 routes)
- Test: `tests/test_routes_glossary.py` (replace the 2 `reapply` tests with the tests below)

**Interfaces:**
- Consumes: `Storage.read_translated/write_translated/read_meta/write_meta/has_meta/has_translated/load_manifest`, `pipeline.step_find_replace(cfg, log, *, find, replace, start, end, also_raw)`, `pipeline._chapter_range`.
- Produces:
  - `GET /api/ebooks/{slug}/glossary/match-count?find=X&chapter_index=N` → `{"find", "chapter_count", "total_count", "chapter_total"}` (chapter_index optional, default 0 = no per-chapter count).
  - `POST /api/ebooks/{slug}/glossary/propagate` form `find, replace, scope("chapter"|"all"), chapter_index` → scope=chapter: `{"replaced": n}` sync; scope=all: `{"ok": true}` (job named `"propagate"`), 409 when queue busy.
  - Old routes `POST .../glossary/reapply-preview` and `POST /ebooks/{slug}/glossary/reapply` return 404.

- [ ] **Step 1: Write the failing tests**

In `tests/test_routes_glossary.py`, DELETE the two tests `test_reapply_preview_lists_affected_chapters` and `test_reapply_applies_and_updates_glossary` (and the comment header above them), then append:

```python
# ----- route: match-count + propagate (pattern "sửa → lan truyền") -----

def test_match_count_counts_all_and_chapter(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ. Trương Tam về nhà.")
    storage.write_translated(chapters[1], "Trương Tam ngủ.")
    client = _client(cfg, monkeypatch)

    res = client.get(
        "/api/ebooks/t/glossary/match-count",
        params={"find": "Trương Tam", "chapter_index": 1},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["chapter_count"] == 2      # trong chương 1
    assert data["total_count"] == 3        # toàn bộ đã dịch
    assert data["chapter_total"] == 2      # số chương chứa chuỗi


def test_match_count_rejects_blank_find(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1")]))
    client = _client(cfg, monkeypatch)
    res = client.get("/api/ebooks/t/glossary/match-count", params={"find": "  "})
    assert res.status_code == 400


def test_propagate_chapter_writes_and_backs_up(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ.")
    storage.write_translated(chapters[1], "Trương Tam ngủ.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "Trương Tam", "replace": "Trần Tam", "scope": "chapter", "chapter_index": 1},
    )
    assert res.status_code == 200
    assert res.json()["replaced"] == 1
    # Chỉ chương 1 bị thay; backup đúng format before_find_replace.
    assert storage.read_translated(chapters[0]) == "Trần Tam đi chợ."
    assert storage.read_meta(chapters[0])["before_find_replace"] == "Trương Tam đi chợ."
    assert storage.read_translated(chapters[1]) == "Trương Tam ngủ."


def test_propagate_all_runs_find_replace_job(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "Trương Tam", "replace": "Trần Tam", "scope": "all"},
    )
    assert res.status_code == 200
    # _FakeJob chạy target sync → file đã đổi ngay trong test.
    assert storage.read_translated(chapters[0]) == "Trần Tam đi chợ."


def test_propagate_rejects_bad_scope_and_missing_chapter(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1")]))
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "a", "replace": "b", "scope": "everything"},
    )
    assert res.status_code == 400
    # scope=chapter nhưng chương chưa dịch → 404.
    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "a", "replace": "b", "scope": "chapter", "chapter_index": 1},
    )
    assert res.status_code == 404


def test_old_reapply_routes_removed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    assert client.post(
        "/api/ebooks/t/glossary/reapply-preview", data={"find": "x"}
    ).status_code == 404
    assert client.post(
        "/ebooks/t/glossary/reapply", data={"find": "x", "replace": "y"}
    ).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_routes_glossary.py -v -k "match_count or propagate or reapply"`
Expected: new tests FAIL (404 on match-count/propagate); `test_old_reapply_routes_removed` FAILS (routes still exist → not 404).

- [ ] **Step 3: Implement in `app/routes/glossary.py`**

Rename `_reapply_chapters` to `_matching_chapters` (same body, update the docstring's "preview + apply" wording to "match-count + propagate"). Delete `_snippet`, `ebook_glossary_reapply_preview`, `ebook_glossary_reapply` entirely. Update the module docstring (line 1-2) to mention "match-count + propagate (lan truyền)" instead of "áp dụng lại (có preview)". Then add:

```python
@router.get("/api/ebooks/{slug}/glossary/match-count")
def ebook_glossary_match_count(slug: str, find: str, chapter_index: int = 0):
    """Đếm số chỗ khớp `find` trong bản dịch: theo 1 chương (nếu truyền
    chapter_index) + toàn bộ. Số đếm này chính là preview của propagate —
    không có bước xem trước riêng."""
    find = find.strip()
    if not find:
        raise HTTPException(status_code=400, detail="Chuỗi cần tìm đang rỗng.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    chapter_count = total = chapter_total = 0
    for ch, _content, count in _matching_chapters(storage, manifest, find, None, None):
        total += count
        chapter_total += 1
        if chapter_index and ch.index == chapter_index:
            chapter_count = count
    return JSONResponse(
        {
            "find": find,
            "chapter_count": chapter_count,
            "total_count": total,
            "chapter_total": chapter_total,
        }
    )


@router.post("/api/ebooks/{slug}/glossary/propagate")
def ebook_glossary_propagate(
    request: Request,
    slug: str,
    find: str = Form(...),
    replace: str = Form(...),
    scope: str = Form(...),
    chapter_index: int = Form(0),
):
    """Lan truyền thay đổi glossary vào bản dịch: `scope=chapter` thay đồng bộ
    NGAY trong 1 chương (backup vào meta như step_find_replace), `scope=all`
    enqueue job step_find_replace toàn bộ. Không tự sửa mục glossary — client
    đã upsert qua /glossary/entry trước."""
    find, replace = find.strip(), replace.strip()
    if not find or not replace:
        raise HTTPException(status_code=400, detail="Cần cả chuỗi tìm và chuỗi thay.")
    if scope not in ("chapter", "all"):
        raise HTTPException(status_code=400, detail="scope phải là 'chapter' hoặc 'all'.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    if scope == "chapter":
        if not chapter_index:
            raise HTTPException(status_code=400, detail="Thiếu chapter_index.")
        manifest = storage.load_manifest()
        if manifest is None:
            raise HTTPException(status_code=404, detail="Chưa có manifest.")
        ch = next((c for c in manifest.chapters if c.index == chapter_index), None)
        if ch is None or not storage.has_translated(ch):
            raise HTTPException(status_code=404, detail="Chương chưa có bản dịch.")
        content = storage.read_translated(ch)
        count = content.count(find)
        if count:
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            meta["before_find_replace"] = content
            storage.write_meta(ch, meta)
            storage.write_translated(ch, content.replace(find, replace))
        return JSONResponse({"replaced": count})

    def _target(log):
        step_find_replace(
            cfg, log, find=find, replace=replace, start=None, end=None, also_raw=False
        )

    started = request.app.state.job.start_custom(
        "propagate", _target, category="translate", ebook=cfg.novel.slug
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_routes_glossary.py -v`
Expected: ALL PASS (including untouched pagination/autosave tests).

- [ ] **Step 5: Commit**

```bash
git add app/routes/glossary.py tests/test_routes_glossary.py
git commit -m "feat: glossary match-count + propagate routes, drop reapply preview/apply"
```

---

### Task 3: Bulk-delete route `entries/delete`

**Files:**
- Modify: `app/routes/glossary.py` (add 1 route after `ebook_glossary_delete_entry`)
- Test: `tests/test_routes_glossary.py`

**Interfaces:**
- Consumes: `Storage.delete_glossary_entry(source) -> bool` (existing; deletes from both names + vietphrase legacy lists).
- Produces: `POST /api/ebooks/{slug}/glossary/entries/delete` JSON body `{"sources": [...]}` → `{"deleted": n}`; 400 when list empty/blank.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes_glossary.py`:

```python
# ----- route: xóa hàng loạt -----

def test_bulk_delete_removes_selected_sources(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n斗气 = Đấu khí\n林动 = Lâm Động\n")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/entries/delete",
        json={"sources": ["萧炎", "林动", "不存在"]},
    )
    assert res.status_code == 200
    assert res.json()["deleted"] == 2  # "不存在" không có → không tính
    assert storage.read_glossary_entries("names.txt") == [("斗气", "Đấu khí", "")]


def test_bulk_delete_rejects_empty_list(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/glossary/entries/delete", json={"sources": ["  "]})
    assert res.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_routes_glossary.py -v -k bulk_delete`
Expected: FAIL with 404 (route missing).

- [ ] **Step 3: Implement**

In `app/routes/glossary.py`, right after `ebook_glossary_delete_entry`, add:

```python
@router.post("/api/ebooks/{slug}/glossary/entries/delete")
def ebook_glossary_delete_entries(slug: str, payload: dict = Body(...)):
    """Xoá NHIỀU mục một lần (multi-select trên bảng). Body JSON
    `{"sources": [...]}`. Source không tồn tại được bỏ qua, không lỗi."""
    sources = [str(s).strip() for s in payload.get("sources", []) if str(s).strip()]
    if not sources:
        raise HTTPException(status_code=400, detail="Chưa chọn mục nào để xoá.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    deleted = sum(1 for s in sources if storage.delete_glossary_entry(s))
    return JSONResponse({"deleted": deleted})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_routes_glossary.py -v -k bulk_delete`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/glossary.py tests/test_routes_glossary.py
git commit -m "feat: bulk-delete glossary entries route"
```

---

### Task 4: Pure suspect-grouping helpers `novel2epub/glossary_review.py`

**Files:**
- Create: `novel2epub/glossary_review.py`
- Create: `tests/test_glossary_review.py`

**Interfaces:**
- Consumes: nothing (pure functions on plain data).
- Produces: `find_suspects(entries: list[tuple[str, str, str]], conflicts_raw) -> dict` with keys `same_target` (list of `{"target", "entries": [{source,target,note}]}`), `nested_source` (list of `{"outer": {...}, "inner": {...}}`), `conflicts` (list of `{"source", "kept", "new"}`). Used by Task 5's route.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_glossary_review.py`:

```python
from novel2epub.glossary_review import find_suspects


def test_same_target_groups_case_insensitive():
    entries = [
        ("张三", "Trương Tam", ""),
        ("斗气", "Đấu khí", "note"),
        ("张叁", "trương tam ", ""),  # khác hoa thường + thừa space vẫn gộp
    ]
    out = find_suspects(entries, None)
    assert len(out["same_target"]) == 1
    group = out["same_target"][0]
    assert group["target"] == "Trương Tam"  # target của mục đầu tiên trong nhóm
    assert [e["source"] for e in group["entries"]] == ["张三", "张叁"]


def test_nested_source_pairs_detects_substring_both_directions():
    entries = [
        ("张三", "Trương Tam", ""),
        ("张三爷", "Trương Tam gia", ""),
        ("斗气", "Đấu khí", ""),
    ]
    out = find_suspects(entries, None)
    assert len(out["nested_source"]) == 1
    pair = out["nested_source"][0]
    assert pair["inner"]["source"] == "张三"
    assert pair["outer"]["source"] == "张三爷"


def test_no_suspects_when_clean():
    entries = [("张三", "Trương Tam", ""), ("斗气", "Đấu khí", "")]
    out = find_suspects(entries, None)
    assert out["same_target"] == []
    assert out["nested_source"] == []
    assert out["conflicts"] == []


def test_conflicts_mapped_and_bad_rows_skipped():
    raw = [
        {"source": "张三", "existing": "Trương Tam", "new": "Trương Tân", "target_file": "x"},
        {"source": "", "existing": "a", "new": "b"},  # thiếu source → bỏ
        "not-a-dict",
    ]
    out = find_suspects([], raw)
    assert out["conflicts"] == [
        {"source": "张三", "kept": "Trương Tam", "new": "Trương Tân"}
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_glossary_review.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'novel2epub.glossary_review'`.

- [ ] **Step 3: Implement**

Create `novel2epub/glossary_review.py`:

```python
"""Pure helpers cho tab "Nghi vấn" trang Glossary: gom mục đáng ngờ (2+ Hán
cùng 1 target Việt, source lồng nhau) + map conflicts từ lần dịch tự mở rộng
glossary. Thuần dữ liệu — không DB/route để test không cần app."""
from __future__ import annotations

Entry = tuple[str, str, str]  # (source, target, note)


def _entry_dict(e: Entry) -> dict:
    return {"source": e[0], "target": e[1], "note": e[2]}


def same_target_groups(entries: list[Entry]) -> list[dict]:
    """Nhóm 2+ source có cùng target (so sau trim, không phân biệt hoa
    thường). Giữ thứ tự xuất hiện; target hiển thị lấy từ mục đầu nhóm."""
    by_key: dict[str, list[Entry]] = {}
    order: list[str] = []
    for e in entries:
        key = e[1].strip().lower()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = []
            order.append(key)
        by_key[key].append(e)
    return [
        {
            "target": by_key[k][0][1].strip(),
            "entries": [_entry_dict(e) for e in by_key[k]],
        }
        for k in order
        if len(by_key[k]) >= 2
    ]


def nested_source_pairs(entries: list[Entry]) -> list[dict]:
    """Cặp mục mà source này là chuỗi con thực sự của source kia (张三 ⊂
    张三爷). O(n²) — vài nghìn mục vẫn tức thì, không cần index."""
    pairs: list[dict] = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            sa, sb = a[0], b[0]
            if sa == sb or not sa or not sb:
                continue
            if sa in sb:
                pairs.append({"outer": _entry_dict(b), "inner": _entry_dict(a)})
            elif sb in sa:
                pairs.append({"outer": _entry_dict(a), "inner": _entry_dict(b)})
    return pairs


def map_conflicts(raw) -> list[dict]:
    """Map conflicts từ extra json (`{"source","existing","new"}`; entry cũ có
    thể mang thêm `target_file` — bỏ) về format UI `{source, kept, new}`."""
    out: list[dict] = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        source = str(c.get("source", "")).strip()
        kept = str(c.get("existing", "")).strip()
        new = str(c.get("new", "")).strip()
        if source and new:
            out.append({"source": source, "kept": kept, "new": new})
    return out


def find_suspects(entries: list[Entry], conflicts_raw) -> dict:
    """Gộp cả 3 nhóm nghi vấn cho route /glossary/suspects."""
    return {
        "same_target": same_target_groups(entries),
        "nested_source": nested_source_pairs(entries),
        "conflicts": map_conflicts(conflicts_raw),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_glossary_review.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/glossary_review.py tests/test_glossary_review.py
git commit -m "feat: pure suspect-grouping helpers for glossary review"
```

---

### Task 5: `suspects` + `conflicts/resolve` routes

**Files:**
- Modify: `app/routes/glossary.py` (import `glossary_review`, add 2 routes after `ebook_glossary_clean`)
- Test: `tests/test_routes_glossary.py`

**Interfaces:**
- Consumes: `glossary_review.find_suspects` (Task 4), `Storage.consolidate_glossary/read_glossary_entries/read_extra_json/write_extra_json`.
- Produces:
  - `GET /api/ebooks/{slug}/glossary/suspects` → `{"same_target": [...], "nested_source": [...], "conflicts": [...], "count": n}` (count = sum of group counts).
  - `POST /api/ebooks/{slug}/glossary/conflicts/resolve` form `source, new` → `{"removed": n}` — removes matching `(source, new)` entries from the persisted conflicts list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes_glossary.py`:

```python
# ----- route: nghi vấn (suspects) + resolve conflicts -----

def test_suspects_returns_groups_and_count(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file(
        "names.txt", "张三 = Trương Tam\n张叁 = Trương Tam\n张三爷 = Trương Tam gia\n"
    )
    storage.write_extra_json(
        "glossary_conflicts",
        [{"source": "斗气", "existing": "Đấu khí", "new": "Đẩu khí"}],
    )
    client = _client(cfg, monkeypatch)

    res = client.get("/api/ebooks/t/glossary/suspects")
    assert res.status_code == 200
    data = res.json()
    assert len(data["same_target"]) == 1          # 张三 + 张叁 → cùng "Trương Tam"
    assert len(data["nested_source"]) == 1        # chỉ 张三 ⊂ 张三爷 (张叁 là chữ khác)
    assert data["conflicts"] == [
        {"source": "斗气", "kept": "Đấu khí", "new": "Đẩu khí"}
    ]
    assert data["count"] == (
        len(data["same_target"]) + len(data["nested_source"]) + len(data["conflicts"])
    )


def test_conflict_resolve_removes_matching_entry(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_extra_json(
        "glossary_conflicts",
        [
            {"source": "斗气", "existing": "Đấu khí", "new": "Đẩu khí"},
            {"source": "张三", "existing": "Trương Tam", "new": "Trương Tân"},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/resolve",
        data={"source": "斗气", "new": "Đẩu khí"},
    )
    assert res.status_code == 200
    assert res.json()["removed"] == 1
    remaining = storage.read_extra_json("glossary_conflicts")
    assert len(remaining) == 1
    assert remaining[0]["source"] == "张三"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_routes_glossary.py -v -k "suspects or conflict_resolve"`
Expected: FAIL with 404.

- [ ] **Step 3: Implement**

In `app/routes/glossary.py`, extend the imports:

```python
from novel2epub import bulk_transfer, glossary_review
```

and add after `ebook_glossary_clean`:

```python
@router.get("/api/ebooks/{slug}/glossary/suspects")
def ebook_glossary_suspects(slug: str):
    """Tab "Nghi vấn": nhóm mục trùng target / source lồng nhau / conflicts
    từ lần dịch. Consolidate legacy trước để chỉ quét names.txt."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.consolidate_glossary()
    data = glossary_review.find_suspects(
        storage.read_glossary_entries("names.txt"),
        storage.read_extra_json("glossary_conflicts"),
    )
    data["count"] = (
        len(data["same_target"]) + len(data["nested_source"]) + len(data["conflicts"])
    )
    return JSONResponse(data)


@router.post("/api/ebooks/{slug}/glossary/conflicts/resolve")
def ebook_glossary_conflict_resolve(
    slug: str, source: str = Form(...), new: str = Form(...)
):
    """Gỡ 1 conflict đã xử lý (Giữ cũ / Lấy mới đều gọi) theo khóa dedup
    `(source, new)` — trùng key pipeline dùng khi ghi — để không hiện lại."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    raw = storage.read_extra_json("glossary_conflicts")
    if not isinstance(raw, list):
        raw = []
    remaining = [
        c
        for c in raw
        if not (isinstance(c, dict) and c.get("source") == source and c.get("new") == new)
    ]
    storage.write_extra_json("glossary_conflicts", remaining)
    return JSONResponse({"removed": len(raw) - len(remaining)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_routes_glossary.py tests/test_glossary_review.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/glossary.py tests/test_routes_glossary.py
git commit -m "feat: glossary suspects + conflict-resolve routes"
```

---

### Task 6: Glossary page — checkbox column + bulk delete UI

**Files:**
- Modify: `app/templates/glossary.html` (thead, `render()`, toolbar, new JS handlers)

**Interfaces:**
- Consumes: `POST /api/ebooks/{slug}/glossary/entries/delete` (Task 3), existing `loadPage()`, `toast()`.
- Produces: table now has **5 columns** (checkbox first). Checkbox inputs carry class `bulk-check` and `data-source` — Task 8's suspects view reuses both so one collector serves both views. Toolbar button id `btn-bulk-delete`.

- [ ] **Step 1: Add checkbox column to header**

In `app/templates/glossary.html` replace the `<thead>` block:

```html
        <thead>
            <tr>
                <th class="w-8"><input type="checkbox" id="check-all" class="rounded border-surface-border dark:border-surface-border-dark" title="Chọn cả trang"></th>
                <th data-dt-sort class="gloss-th">Hán <span class="sort-ind"></span></th>
                <th data-dt-sort data-dt-filter class="gloss-th">Việt <span class="sort-ind"></span></th>
                <th>Ghi chú</th>
                <th class="w-40">Thao tác</th>
            </tr>
        </thead>
```

- [ ] **Step 2: Render checkbox per row + bulk button in toolbar**

In `render()`, replace the row template's first cell group — the full new row template:

```js
    body.innerHTML = ROWS.map((e, idx) => `
        <tr class="border-t border-surface-border dark:border-surface-border-dark transition-colors" data-idx="${idx}">
            <td class="px-2 py-1 align-top">${e._saved ? `<input type="checkbox" class="bulk-check rounded border-surface-border dark:border-surface-border-dark" data-source="${escapeHtml(e._saved)}">` : ""}</td>
            <td class="px-2 py-1 align-top"><input data-field="source" value="${escapeHtml(e.source)}" class="${inputCls} font-mono"></td>
            <td class="px-2 py-1 align-top"><input data-field="target" value="${escapeHtml(e.target)}" class="${inputCls}"></td>
            <td class="px-2 py-1 align-top"><input data-field="note" value="${escapeHtml(e.note)}" placeholder="—" class="${inputCls} text-fg-muted dark:text-fg-muted-dark"></td>
            <td class="px-2 py-1 align-top whitespace-nowrap">
                <button type="button" data-act="delete" class="btn btn-sm btn-ghost text-xs text-status-err-fg dark:text-status-err-fg-dark hover:bg-status-err-light dark:hover:bg-status-err-dark" title="Xoá mục">Xoá</button>
            </td>
        </tr>`).join("");
```

(NOTE: the `Áp dụng lại` per-row button is intentionally dropped here — Task 7 deletes its modal/JS.)

In the toolbar `<div class="ml-auto flex flex-wrap gap-2">`, add as FIRST child:

```html
        <button type="button" id="btn-bulk-delete" class="btn btn-sm btn-danger hidden">Xóa đã chọn (<span id="bulk-count">0</span>)</button>
```

- [ ] **Step 3: Wire the JS**

Add after the `loadPage()` function definition:

```js
// --- Xóa hàng loạt: checkbox class .bulk-check dùng chung cả view Nghi vấn ---
const bulkBtn = document.getElementById("btn-bulk-delete");
const bulkCount = document.getElementById("bulk-count");
const checkAll = document.getElementById("check-all");

function checkedSources() {
    return Array.from(document.querySelectorAll(".bulk-check:checked")).map(cb => cb.dataset.source);
}
function refreshBulkBtn() {
    const n = checkedSources().length;
    bulkCount.textContent = n;
    bulkBtn.classList.toggle("hidden", n === 0);
}
document.addEventListener("change", e => {
    if (e.target.classList && e.target.classList.contains("bulk-check")) refreshBulkBtn();
});
checkAll.addEventListener("change", () => {
    document.querySelectorAll("#gloss-body .bulk-check").forEach(cb => { cb.checked = checkAll.checked; });
    refreshBulkBtn();
});
bulkBtn.addEventListener("click", async () => {
    const sources = checkedSources();
    if (!sources.length) return;
    if (!window.confirm(`Xóa ${sources.length} mục đã chọn?`)) return;
    try {
        const res = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/entries/delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sources }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { toast(data.detail || "Xóa thất bại.", "error"); return; }
        toast(`Đã xóa ${data.deleted} mục.`, "success");
        checkAll.checked = false;
        await loadPage();
        refreshBulkBtn();
    } catch (err) { toast("Lỗi kết nối mạng.", "error"); }
});
```

Also add `refreshBulkBtn();` as the last line of `render()` (page reload resets checkboxes).

- [ ] **Step 4: Verify in browser**

Open `/ebooks/<slug>/glossary`: tick 2 rows → button shows "Xóa đã chọn (2)"; confirm → rows gone after reload, toast shows count; header checkbox selects the whole page.

- [ ] **Step 5: Commit**

```bash
git add app/templates/glossary.html
git commit -m "feat: multi-select bulk delete on glossary table"
```

---

### Task 7: Glossary page — propagate banner, delete "Áp dụng lại" modal

**Files:**
- Modify: `app/templates/glossary.html`

**Interfaces:**
- Consumes: `GET .../glossary/match-count` + `POST .../glossary/propagate` (Task 2); 5-column table (Task 6).
- Produces: global JS function `showPropagateBanner(afterTr, oldStr, newStr)` — inserts a single-instance `<tr id="propagate-banner">` after `afterTr`; Task 8's conflicts "Lấy mới" reuses it.

- [ ] **Step 1: Delete the modal + its JS**

Remove from `glossary.html`:
1. The whole `<div id="reapply-modal" ...>...</div>` block (HTML section "Modal: sửa tên & áp dụng lại bản dịch cũ").
2. The whole JS section from `/* ---------- Sửa tên & áp dụng lại (modal + preview) ---------- */` down to (and including) the `reapplyApplyBtn.addEventListener(...)` block.
3. In the row-click handler, the `else if (btn.dataset.act === "reapply") { openReapply(row); }` branch (the button itself was already dropped in Task 6).

- [ ] **Step 2: Track saved target + show banner after autosave**

In `loadPage()`, change the ROWS mapping to also remember the saved target:

```js
        ROWS = data.entries.map(e => ({ ...e, _saved: e.source, _savedTarget: e.target }));
```

In `saveRow(row, el)`, replace the success tail (after `const isNew = !row._saved;`) with:

```js
        const isNew = !row._saved;
        const oldTarget = row._savedTarget || "";
        row._saved = source;
        row._savedTarget = target;
        if (isNew) { total += 1; renderPager(); }
        if (el) flashRow(el, true);
        // Target đổi trên mục đã có → mời lan truyền vào bản dịch cũ.
        if (!isNew && oldTarget && oldTarget !== target) {
            const tr = el && el.closest("tr");
            if (tr) showPropagateBanner(tr, oldTarget, target);
        }
```

- [ ] **Step 3: Implement the banner (add where the old modal JS was)**

```js
/* ---------- Banner lan truyền: thay target cũ → mới trong bản dịch ---------- */
function removePropagateBanner() {
    const el = document.getElementById("propagate-banner");
    if (el) el.remove();
}

// Chèn banner ngay dưới `afterTr` (1 banner duy nhất tại 1 thời điểm).
async function showPropagateBanner(afterTr, oldStr, newStr) {
    removePropagateBanner();
    const banner = document.createElement("tr");
    banner.id = "propagate-banner";
    banner.innerHTML = `<td colspan="5" class="px-3 py-2 text-sm bg-brand-50 dark:bg-brand-950/30 border-t border-surface-border dark:border-surface-border-dark">
        Thay "<strong>${escapeHtml(oldStr)}</strong>" → "<strong>${escapeHtml(newStr)}</strong>" trong bản dịch cũ?
        <span class="prop-actions text-fg-muted dark:text-fg-muted-dark">đang đếm…</span></td>`;
    afterTr.after(banner);
    const actions = banner.querySelector(".prop-actions");
    try {
        const params = new URLSearchParams({ find: oldStr });
        const res = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/match-count?${params}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { banner.remove(); toast(data.detail || "Không đếm được số chỗ khớp.", "error"); return; }
        if (!data.total_count) { banner.remove(); return; } // không có gì để thay
        actions.innerHTML = `
            <button type="button" class="btn btn-sm btn-primary prop-all">Tất cả (${data.total_count} chỗ · ${data.chapter_total} chương)</button>
            <button type="button" class="btn btn-sm btn-ghost prop-skip">Bỏ qua</button>`;
        actions.querySelector(".prop-skip").addEventListener("click", removePropagateBanner);
        actions.querySelector(".prop-all").addEventListener("click", async () => {
            const fd = new FormData();
            fd.set("find", oldStr); fd.set("replace", newStr); fd.set("scope", "all");
            try {
                const r = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/propagate`, { method: "POST", body: fd });
                const d = await r.json().catch(() => ({}));
                if (!r.ok) { toast(d.detail || "Không bắt đầu được job.", "error"); return; }
                toast("Đã bắt đầu thay toàn bộ (job nền). Theo dõi ở Queue/Logs.", "success");
                removePropagateBanner();
            } catch (err) { toast("Lỗi kết nối mạng.", "error"); }
        });
    } catch (err) { banner.remove(); toast("Lỗi kết nối mạng.", "error"); }
}
```

- [ ] **Step 4: Verify in browser**

On `/ebooks/<slug>/glossary` (ebook with translated chapters): edit a Việt cell of an entry whose target occurs in translations, blur → banner appears under the row with real counts; "Bỏ qua" removes it; edit another row while a banner is open → old banner disappears; "Tất cả" starts the job (toast + Queue shows `propagate`). Edit a target that occurs nowhere → banner never appears. The old modal is gone; no console errors referencing `reapply`.

- [ ] **Step 5: Commit**

```bash
git add app/templates/glossary.html
git commit -m "feat: inline propagate banner replaces reapply modal on glossary page"
```

---

### Task 8: Glossary page — "Nghi vấn" tab

**Files:**
- Modify: `app/templates/glossary.html`

**Interfaces:**
- Consumes: `GET .../glossary/suspects` + `POST .../glossary/conflicts/resolve` (Task 5), `POST .../glossary/entry` (existing), `showPropagateBanner` (Task 7), `.bulk-check` collector (Task 6), `loadPage()`.
- Produces: view toggle `#view-all` / `#view-suspects`, container `#suspects-view`.

- [ ] **Step 1: Add toggle + container HTML**

In the toolbar, right after `<span id="gloss-count" ...></span>`, add:

```html
    <div class="flex rounded-lg border border-surface-border dark:border-surface-border-dark overflow-hidden">
        <button type="button" id="view-all" class="btn btn-sm btn-primary rounded-none">Tất cả</button>
        <button type="button" id="view-suspects" class="btn btn-sm btn-ghost rounded-none">Nghi vấn</button>
    </div>
```

After the pager `</div>` (id `gloss-pager`), add:

```html
<!-- View Nghi vấn: nhóm trùng target / Hán lồng nhau / conflicts -->
<div id="suspects-view" class="hidden space-y-4"></div>
```

- [ ] **Step 2: Add the JS (after the bulk-delete section)**

```js
/* ---------- Tab Nghi vấn ---------- */
const viewAllBtn = document.getElementById("view-all");
const viewSuspectsBtn = document.getElementById("view-suspects");
const suspectsView = document.getElementById("suspects-view");
const tableWrap = document.querySelector(".table-container");
const pagerEl = document.getElementById("gloss-pager");

function setView(suspects) {
    tableWrap.classList.toggle("hidden", suspects);
    pagerEl.classList.toggle("hidden", suspects);
    emptyMsg.classList.add("hidden");
    searchInput.disabled = suspects;
    suspectsView.classList.toggle("hidden", !suspects);
    viewAllBtn.className = suspects ? "btn btn-sm btn-ghost rounded-none" : "btn btn-sm btn-primary rounded-none";
    viewSuspectsBtn.className = suspects ? "btn btn-sm btn-primary rounded-none" : "btn btn-sm btn-ghost rounded-none";
}
viewAllBtn.addEventListener("click", async () => { setView(false); await loadPage(); refreshBulkBtn(); });
viewSuspectsBtn.addEventListener("click", async () => { setView(true); await loadSuspects(); refreshBulkBtn(); });

// Dòng mục trong view Nghi vấn: cùng input inline như bảng chính, nhưng lưu
// trực tiếp qua /entry khi blur (data-orig-* giữ giá trị đã lưu).
function suspectRow(e) {
    return `
        <tr class="border-t border-surface-border dark:border-surface-border-dark" data-orig-source="${escapeHtml(e.source)}" data-orig-target="${escapeHtml(e.target)}">
            <td class="px-2 py-1 align-top w-8"><input type="checkbox" class="bulk-check rounded border-surface-border dark:border-surface-border-dark" data-source="${escapeHtml(e.source)}"></td>
            <td class="px-2 py-1 align-top"><input data-sfield="source" value="${escapeHtml(e.source)}" class="${inputCls} font-mono"></td>
            <td class="px-2 py-1 align-top"><input data-sfield="target" value="${escapeHtml(e.target)}" class="${inputCls}"></td>
            <td class="px-2 py-1 align-top"><input data-sfield="note" value="${escapeHtml(e.note)}" placeholder="—" class="${inputCls} text-fg-muted dark:text-fg-muted-dark"></td>
        </tr>`;
}

function suspectTable(rowsHtml) {
    return `<div class="table-container"><table class="table"><tbody>${rowsHtml}</tbody></table></div>`;
}

async function loadSuspects() {
    suspectsView.innerHTML = '<p class="text-sm text-fg-muted dark:text-fg-muted-dark">Đang quét…</p>';
    let data;
    try {
        const res = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/suspects`);
        if (!res.ok) { toast("Không tải được danh sách nghi vấn.", "error"); return; }
        data = await res.json();
    } catch (err) { toast("Lỗi kết nối mạng.", "error"); return; }

    const parts = [];
    if (data.conflicts.length) {
        parts.push(`<h3 class="text-base font-semibold m-0">Conflicts từ lần dịch (${data.conflicts.length})</h3>`);
        parts.push(data.conflicts.map(c => `
            <div class="conflict-row flex flex-wrap items-center gap-2 px-3 py-2 rounded-lg border border-status-warn-light dark:border-status-warn-dark text-sm"
                 data-source="${escapeHtml(c.source)}" data-kept="${escapeHtml(c.kept)}" data-new="${escapeHtml(c.new)}">
                <code class="bg-surface-muted dark:bg-surface-muted-dark px-1 py-0.5 rounded">${escapeHtml(c.source)}</code>
                giữ "<strong>${escapeHtml(c.kept)}</strong>" · AI đề xuất "<strong>${escapeHtml(c.new)}</strong>"
                <span class="ml-auto flex gap-2">
                    <button type="button" class="btn btn-sm btn-ghost conflict-keep">Giữ cũ</button>
                    <button type="button" class="btn btn-sm btn-secondary conflict-take">Lấy mới</button>
                </span>
            </div>`).join(""));
    }
    if (data.same_target.length) {
        parts.push(`<h3 class="text-base font-semibold m-0 mt-2">Trùng Việt — nhiều Hán cùng 1 cách dịch (${data.same_target.length} nhóm)</h3>`);
        parts.push(data.same_target.map(g => `
            <div class="rounded-lg border border-surface-border dark:border-surface-border-dark p-2">
                <p class="m-0 mb-1 text-sm text-fg-muted dark:text-fg-muted-dark">→ "<strong>${escapeHtml(g.target)}</strong>"</p>
                ${suspectTable(g.entries.map(suspectRow).join(""))}
            </div>`).join(""));
    }
    if (data.nested_source.length) {
        parts.push(`<h3 class="text-base font-semibold m-0 mt-2">Hán lồng nhau (${data.nested_source.length} cặp)</h3>`);
        parts.push(data.nested_source.map(p => `
            <div class="rounded-lg border border-surface-border dark:border-surface-border-dark p-2">
                ${suspectTable(suspectRow(p.outer) + suspectRow(p.inner))}
            </div>`).join(""));
    }
    suspectsView.innerHTML = parts.length
        ? parts.join("")
        : '<p class="text-sm text-fg-muted dark:text-fg-muted-dark py-6 text-center">Không có mục nghi vấn nào 🎉</p>';
}

// Sửa inline trong view Nghi vấn: lưu khi blur, dùng data-orig-* làm khóa cũ.
suspectsView.addEventListener("change", async e => {
    const field = e.target.dataset.sfield;
    if (!field) return;
    const tr = e.target.closest("tr");
    const source = tr.querySelector('[data-sfield="source"]').value.trim();
    const target = tr.querySelector('[data-sfield="target"]').value.trim();
    const note = tr.querySelector('[data-sfield="note"]').value;
    if (!source || !target) return;
    const fd = new FormData();
    fd.set("source", source); fd.set("target", target); fd.set("note", note);
    fd.set("original_source", tr.dataset.origSource || "");
    try {
        const res = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/entry`, { method: "POST", body: fd });
        if (!res.ok) { flashRow(e.target, false); return; }
        flashRow(e.target, true);
        const oldTarget = tr.dataset.origTarget || "";
        tr.dataset.origSource = source;
        tr.dataset.origTarget = target;
        if (oldTarget && oldTarget !== target) showPropagateBanner(tr, oldTarget, target);
    } catch (err) { toast("Lỗi kết nối mạng.", "error"); }
});

// Conflicts: Giữ cũ = chỉ gỡ; Lấy mới = upsert target mới + gỡ + mời lan truyền.
suspectsView.addEventListener("click", async e => {
    const row = e.target.closest(".conflict-row");
    if (!row) return;
    const keep = e.target.closest(".conflict-keep");
    const take = e.target.closest(".conflict-take");
    if (!keep && !take) return;
    const { source, kept, new: newTarget } = row.dataset;
    try {
        if (take) {
            const fd = new FormData();
            fd.set("source", source); fd.set("target", newTarget); fd.set("note", "");
            const r = await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/entry`, { method: "POST", body: fd });
            if (!r.ok) { toast("Không cập nhật được mục.", "error"); return; }
        }
        const fd2 = new FormData();
        fd2.set("source", source); fd2.set("new", newTarget);
        await fetch(`/api/ebooks/${GLOSSARY_SLUG}/glossary/conflicts/resolve`, { method: "POST", body: fd2 });
        if (take && kept && kept !== newTarget) {
            // Banner cần 1 <tr> để chèn sau — bọc conflict row bằng bảng nhỏ tạm.
            const holder = document.createElement("table");
            holder.className = "w-full";
            const tbody = document.createElement("tbody");
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            tr.appendChild(td); tbody.appendChild(tr); holder.appendChild(tbody);
            row.after(holder);
            showPropagateBanner(tr, kept, newTarget);
        }
        row.classList.add("opacity-40");
        row.querySelectorAll("button").forEach(b => { b.disabled = true; });
        toast(take ? `Đã lấy "${newTarget}".` : "Đã giữ giá trị cũ.", "success");
    } catch (err) { toast("Lỗi kết nối mạng.", "error"); }
});
```

- [ ] **Step 3: Verify in browser**

Seed an ebook that has duplicate-target entries and a conflicts file (or add 2 entries with the same Việt via the table). Click "Nghi vấn": groups render; inline-edit a row in a group → green flash + (if target changed and it occurs in translations) propagate banner; tick checkboxes in groups → "Xóa đã chọn (N)" works and re-entering the tab reflects it; "Giữ cũ"/"Lấy mới" grey the conflict row out and it does NOT reappear after switching tabs (persisted resolve). "Tất cả" tab restores the paginated table.

- [ ] **Step 4: Commit**

```bash
git add app/templates/glossary.html
git commit -m "feat: suspects (nghi van) review tab on glossary page"
```

---

### Task 9: Chapter page — selection popover with propagate

**Files:**
- Modify: `app/templates/chapter.html` (HTML near end of content block + JS at end of the main script block)

**Interfaces:**
- Consumes: `GET .../glossary/list?q=` (existing), `POST .../glossary/entry` (existing), `GET .../glossary/match-count?find=&chapter_index=` + `POST .../glossary/propagate` (Task 2), existing `pollTranslated()`, `CHAPTER_SLUG`, `CHAPTER_INDEX`, `escapeHtml`. Requires Task 1's fix (script block must parse).
- Produces: floating button `#gloss-pop-trigger`, popover `#gloss-pop`.

- [ ] **Step 1: Add HTML before `</section>`** (the `{% endblock %}`-adjacent closing tag of `.chapter-workspace`):

```html
<!-- Popover glossary từ bôi đen (ZH/VI trong bảng so sánh + preview) -->
<button type="button" id="gloss-pop-trigger" class="hidden fixed z-50 btn btn-sm btn-primary shadow-card">+ Glossary</button>
<div id="gloss-pop" class="hidden fixed z-50 w-80 rounded-lg border border-surface-border dark:border-surface-border-dark bg-surface-light dark:bg-surface-dark shadow-card dark:shadow-card-dark p-3 space-y-2 text-sm">
    <div class="flex items-center justify-between">
        <strong>Mục glossary</strong>
        <button type="button" id="gloss-pop-close" class="btn btn-sm btn-ghost leading-none">✕</button>
    </div>
    <label class="block"><span class="label">Hán</span><input type="text" id="gloss-pop-source" class="input input-sm w-full font-mono"></label>
    <label class="block"><span class="label">Việt</span><input type="text" id="gloss-pop-target" class="input input-sm w-full"></label>
    <label class="block"><span class="label">Ghi chú</span><input type="text" id="gloss-pop-note" class="input input-sm w-full"></label>
    <div id="gloss-pop-actions" class="flex flex-wrap gap-2">
        <button type="button" id="gloss-pop-save" class="btn btn-sm btn-primary">Lưu</button>
    </div>
</div>
```

- [ ] **Step 2: Add JS at the end of the main `<script>` block** (before its closing `</script>`):

```js
/* ---------- Popover glossary từ bôi đen ---------- */
const popTrigger = document.getElementById("gloss-pop-trigger");
const pop = document.getElementById("gloss-pop");
const popSource = document.getElementById("gloss-pop-source");
const popTarget = document.getElementById("gloss-pop-target");
const popNote = document.getElementById("gloss-pop-note");
const popActions = document.getElementById("gloss-pop-actions");
let popSel = null;      // {text, fromZh} — selection lúc bấm nút
let popExisting = null; // {source, target} mục đã có (để biết target cũ khi lan truyền)

function hidePopover() { pop.classList.add("hidden"); popTrigger.classList.add("hidden"); }

// Bôi đen trong vùng so sánh/preview → hiện nút nổi cạnh selection.
document.addEventListener("mouseup", e => {
    if (e.target.closest("#gloss-pop") || e.target.closest("#gloss-pop-trigger")) return;
    setTimeout(() => {
        const sel = window.getSelection();
        const text = sel ? sel.toString().trim() : "";
        const anchor = sel && sel.anchorNode &&
            (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
        const cell = anchor && anchor.closest && anchor.closest(".raw-cell, .mt-cell, #translated-preview");
        if (!text || text.length > 100 || !cell) { popTrigger.classList.add("hidden"); return; }
        const rect = sel.getRangeAt(0).getBoundingClientRect();
        popSel = { text, fromZh: !!anchor.closest(".raw-cell") };
        popTrigger.style.left = Math.max(8, rect.left) + "px";
        popTrigger.style.top = (rect.bottom + 6) + "px";
        popTrigger.classList.remove("hidden");
        pop.classList.add("hidden");
    }, 0);
});

popTrigger.addEventListener("click", async () => {
    if (!popSel) return;
    popExisting = null;
    popNote.value = "";
    if (popSel.fromZh) { popSource.value = popSel.text; popTarget.value = ""; }
    else { popTarget.value = popSel.text; popSource.value = ""; }
    // Tra glossary: điền sẵn nửa còn lại nếu mục đã có (khớp chính xác).
    try {
        const params = new URLSearchParams({ q: popSel.text, per_page: "50" });
        const res = await fetch(`/api/ebooks/${encodeURIComponent(CHAPTER_SLUG)}/glossary/list?${params}`);
        if (res.ok) {
            const data = await res.json();
            const hit = (data.entries || []).find(en =>
                popSel.fromZh ? en.source === popSel.text : en.target === popSel.text);
            if (hit) {
                popSource.value = hit.source; popTarget.value = hit.target; popNote.value = hit.note || "";
                popExisting = { source: hit.source, target: hit.target };
            }
        }
    } catch (err) { /* tra không được thì để user tự điền */ }
    popActions.innerHTML = '<button type="button" id="gloss-pop-save" class="btn btn-sm btn-primary">Lưu</button>';
    document.getElementById("gloss-pop-save").addEventListener("click", savePopEntry);
    pop.style.left = popTrigger.style.left;
    pop.style.top = popTrigger.style.top;
    pop.classList.remove("hidden");
    popTrigger.classList.add("hidden");
    (popSel.fromZh ? popTarget : popSource).focus();
});

document.getElementById("gloss-pop-close").addEventListener("click", hidePopover);
document.addEventListener("keydown", e => { if (e.key === "Escape") hidePopover(); });

async function savePopEntry() {
    const source = popSource.value.trim();
    const target = popTarget.value.trim();
    if (!source || !target) { alert("Cần cả Hán và Việt."); return; }
    const fd = new FormData();
    fd.set("source", source); fd.set("target", target); fd.set("note", popNote.value);
    fd.set("original_source", popExisting ? popExisting.source : "");
    try {
        const res = await fetch(`/api/ebooks/${encodeURIComponent(CHAPTER_SLUG)}/glossary/entry`, { method: "POST", body: fd });
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            alert(d.detail || "Lưu thất bại.");
            return;
        }
    } catch (err) { alert("Lỗi kết nối mạng."); return; }

    // Chuỗi cũ cần thay: target cũ của mục có sẵn, hoặc chính đoạn VI vừa bôi
    // (mục mới thêm từ cột VI mà target gõ lại khác đi).
    let oldStr = "";
    if (popExisting && popExisting.target !== target) oldStr = popExisting.target;
    else if (!popExisting && !popSel.fromZh && popSel.text !== target) oldStr = popSel.text;
    if (!oldStr) { hidePopover(); return; }
    await showPopPropagate(oldStr, target);
}

async function showPopPropagate(oldStr, newStr) {
    popActions.innerHTML = '<span class="text-fg-muted dark:text-fg-muted-dark">đang đếm…</span>';
    let data;
    try {
        const params = new URLSearchParams({ find: oldStr, chapter_index: String(CHAPTER_INDEX) });
        const res = await fetch(`/api/ebooks/${encodeURIComponent(CHAPTER_SLUG)}/glossary/match-count?${params}`);
        data = await res.json().catch(() => ({}));
        if (!res.ok) { hidePopover(); return; }
    } catch (err) { hidePopover(); return; }
    if (!data.total_count) { hidePopover(); return; }
    popActions.innerHTML = `
        <button type="button" class="btn btn-sm btn-primary pop-prop-chapter" ${data.chapter_count ? "" : "disabled"}>Thay chương này (${data.chapter_count})</button>
        <button type="button" class="btn btn-sm btn-secondary pop-prop-all">Thay tất cả (${data.total_count} chỗ · ${data.chapter_total} chương)</button>
        <button type="button" class="btn btn-sm btn-ghost pop-prop-skip">Chỉ lưu</button>`;
    popActions.querySelector(".pop-prop-skip").addEventListener("click", hidePopover);
    popActions.querySelector(".pop-prop-chapter").addEventListener("click", () => popPropagate(oldStr, newStr, "chapter"));
    popActions.querySelector(".pop-prop-all").addEventListener("click", () => popPropagate(oldStr, newStr, "all"));
}

async function popPropagate(oldStr, newStr, scope) {
    const fd = new FormData();
    fd.set("find", oldStr); fd.set("replace", newStr); fd.set("scope", scope);
    fd.set("chapter_index", String(CHAPTER_INDEX));
    try {
        const res = await fetch(`/api/ebooks/${encodeURIComponent(CHAPTER_SLUG)}/glossary/propagate`, { method: "POST", body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { alert(data.detail || "Không thay được."); return; }
        if (scope === "chapter") {
            await pollTranslated(); // cập nhật bản dịch tại chỗ, giữ vị trí đọc
        }
    } catch (err) { alert("Lỗi kết nối mạng."); return; }
    hidePopover();
}
```

- [ ] **Step 3: Verify in browser**

On a chapter page with translations: select a name in the ZH column → "+ Glossary" appears → click → Hán prefilled (and Việt too when the entry exists); change Việt, save → 3 propagate buttons with real counts → "Thay chương này" updates the translated preview without a page reload; "Thay tất cả" starts a job. Select in the VI (MT) column → Việt prefilled, reverse lookup fills Hán when the target matches. Esc closes. Selecting >100 chars or outside the compare area shows nothing.

- [ ] **Step 4: Commit**

```bash
git add app/templates/chapter.html
git commit -m "feat: select-to-edit glossary popover with scoped propagate on chapter page"
```

---

### Task 10: Full suite, docs, final verification

**Files:**
- Modify: `CLAUDE.md` (architecture bullet)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS (no regressions — especially `test_routes_glossary.py`, `test_glossary_review.py`, `test_glossary_ai.py`).

- [ ] **Step 2: Update CLAUDE.md**

In the Architecture section's web-UI bullet (`app/` line), append one sentence:

```
Glossary edit flow v2: mọi chỗ sửa glossary (bảng Glossary, popover bôi đen trên trang chương) dùng chung pattern "sửa → đếm khớp (`glossary/match-count`) → chọn phạm vi lan truyền (`glossary/propagate`, scope=chapter đồng bộ / scope=all qua job step_find_replace)"; trang Glossary có bulk delete + tab Nghi vấn (`glossary/suspects` từ `novel2epub/glossary_review.py` thuần + `conflicts/resolve` persist); modal "Áp dụng lại" và 2 route reapply đã bỏ.
```

- [ ] **Step 3: End-to-end manual pass**

With the dev server: (1) chapter page popover ZH-select → save+propagate-chapter → preview updates; (2) glossary page target edit → banner → propagate-all job completes (check Queue) and chapter text changed; (3) suspects tab resolve a conflict → doesn't reappear; (4) bulk delete 2 entries. No console errors on either page.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: glossary edit flow v2 architecture notes"
```
