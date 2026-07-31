# Manual Chapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a modal to the ebook workspace that inserts a title-and-URL chapter at a chosen index while atomically shifting and preserving all existing chapter data.

**Architecture:** A new `Storage.insert_chapter(Chapter)` method owns transactional index shifting and persistence validation. A synchronous FastAPI form route translates user input into that method, while `ebook.html` provides an existing-style modal and normal POST form.

**Tech Stack:** Python 3.10+, SQLite, FastAPI forms, Jinja2, browser JavaScript, pytest, FastAPI TestClient

## Global Constraints

- Add only a TOC entry; do not accept raw or translated content and do not start a crawl automatically.
- Require an insertion index in `1..N+1`, a non-empty title, and a non-empty source URL.
- Reject duplicate URLs within the ebook.
- Preserve every column of shifted chapter rows in one SQLite transaction.
- Set both `title` and `title_zh` on the new chapter to the submitted title.
- Keep unrelated ebook-deletion worktree changes untouched and stage only files belonging to each task.

---

## File Structure

- Modify `novel2epub/storage.py`: provide the atomic chapter insertion boundary.
- Create `tests/test_manual_chapter.py`: cover storage integrity, route behavior, and template wiring in one focused feature test module.
- Modify `app/routes/chapters.py`: expose the manual-add form endpoint.
- Modify `app/templates/ebook.html`: add the toolbar trigger, modal form, and small open/close hooks.

### Task 1: Atomic Chapter Insertion

**Files:**
- Modify: `novel2epub/storage.py:257` (before `save_chapter`)
- Create: `tests/test_manual_chapter.py`

**Interfaces:**
- Consumes: `Chapter(index: int, url: str, title: str = "", title_zh: str = "", ...)` and the existing `Storage.conn` SQLite connection.
- Produces: `Storage.insert_chapter(self, ch: Chapter) -> None`, raising `ValueError` for an invalid index or duplicate URL.

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_manual_chapter.py` with helpers and tests that inspect complete persisted rows:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from novel2epub.storage import Chapter, Manifest, Storage


def _storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t"))
    return storage


def _chapter_row(storage: Storage, index: int):
    return storage.conn.execute(
        "SELECT * FROM chapters WHERE ebook_slug=? AND idx=?",
        ("t", index),
    ).fetchone()


def test_insert_chapter_into_empty_manifest(tmp_path):
    storage = _storage(tmp_path)

    storage.insert_chapter(Chapter(index=1, url="https://x/1", title="第一章", title_zh="第一章"))

    manifest = storage.load_manifest()
    assert [(ch.index, ch.url, ch.title, ch.title_zh) for ch in manifest.chapters] == [
        (1, "https://x/1", "第一章", "第一章")
    ]


def test_insert_chapter_appends_at_n_plus_one(tmp_path):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))

    storage.insert_chapter(Chapter(2, "https://x/2", "Two", "Two"))

    assert [ch.index for ch in storage.load_manifest().chapters] == [1, 2]


def test_insert_chapter_shifts_complete_rows_without_data_loss(tmp_path):
    storage = _storage(tmp_path)
    first = Chapter(1, "https://x/1", "One", "一", "note", ["author"], None, "done", True)
    second = Chapter(2, "https://x/2", "Two", "二")
    storage.save_manifest(Manifest(slug="t", chapters=[first, second]))
    storage.write_raw(second, "RAW TWO")
    storage.write_translated(second, "TRANSLATED TWO")
    storage.write_translated_mt(second, "MT TWO")
    storage.write_meta(second, {"complete": True, "warnings": ["kept"]})
    before = dict(_chapter_row(storage, 2))

    storage.insert_chapter(Chapter(2, "https://x/new", "New", "New"))

    shifted = dict(_chapter_row(storage, 3))
    assert {k: v for k, v in shifted.items() if k != "idx"} == {
        k: v for k, v in before.items() if k != "idx"
    }
    assert storage.read_raw(storage.load_manifest().chapters[2]) == "RAW TWO"
    assert storage.read_translated(storage.load_manifest().chapters[2]) == "TRANSLATED TWO"
    assert storage.read_translated_mt(storage.load_manifest().chapters[2]) == "MT TWO"
    assert storage.read_meta(storage.load_manifest().chapters[2]) == {
        "complete": True,
        "warnings": ["kept"],
    }


@pytest.mark.parametrize("index", [0, 3])
def test_insert_chapter_rejects_out_of_range_without_changes(tmp_path, index):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))
    before = storage.load_manifest().to_json()

    with pytest.raises(ValueError, match="Vị trí"):
        storage.insert_chapter(Chapter(index, "https://x/new", "New"))

    assert storage.load_manifest().to_json() == before


def test_insert_chapter_rejects_duplicate_url_without_changes(tmp_path):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))
    before = storage.load_manifest().to_json()

    with pytest.raises(ValueError, match="URL"):
        storage.insert_chapter(Chapter(1, "https://x/1", "Duplicate"))

    assert storage.load_manifest().to_json() == before
```

- [ ] **Step 2: Run the storage tests and verify RED**

Run: `pytest tests/test_manual_chapter.py -v`

Expected: all insertion tests fail with `AttributeError: 'Storage' object has no attribute 'insert_chapter'`.

- [ ] **Step 3: Implement transactional insertion**

Add this method before `save_chapter` in `novel2epub/storage.py`:

```python
    def insert_chapter(self, ch: Chapter) -> None:
        """Insert one TOC row and shift complete persisted rows atomically."""
        with self.conn:
            ebook = self.conn.execute(
                "SELECT 1 FROM ebooks WHERE slug = ?", (self.slug,)
            ).fetchone()
            if ebook is None:
                raise ValueError("Chưa có manifest.")

            count = self.conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE ebook_slug = ?", (self.slug,)
            ).fetchone()[0]
            if ch.index < 1 or ch.index > count + 1:
                raise ValueError(f"Vị trí phải từ 1 đến {count + 1}.")

            duplicate = self.conn.execute(
                "SELECT 1 FROM chapters WHERE ebook_slug = ? AND url = ?",
                (self.slug, ch.url),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("URL nguồn đã tồn tại trong danh mục.")

            indexes = self.conn.execute(
                "SELECT idx FROM chapters WHERE ebook_slug = ? AND idx >= ? ORDER BY idx DESC",
                (self.slug, ch.index),
            ).fetchall()
            for row in indexes:
                self.conn.execute(
                    "UPDATE chapters SET idx = ? WHERE ebook_slug = ? AND idx = ?",
                    (row["idx"] + 1, self.slug, row["idx"]),
                )

            self.conn.execute(
                """
                INSERT INTO chapters (
                    ebook_slug, idx, url, title, title_zh, title_note,
                    missing_fields_json, duplicate_of, last_action_status, skipped
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.slug, ch.index, ch.url, ch.title, ch.title_zh, ch.title_note,
                    json.dumps(ch.missing_fields, ensure_ascii=False), ch.duplicate_of,
                    ch.last_action_status, int(ch.skipped),
                ),
            )
```

- [ ] **Step 4: Run focused and storage regression tests**

Run: `pytest tests/test_manual_chapter.py tests/test_storage.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the storage boundary**

```bash
git add novel2epub/storage.py tests/test_manual_chapter.py
git commit -m "feat: add atomic manual chapter insertion"
```

### Task 2: Manual Chapter Route And Modal

**Files:**
- Modify: `app/routes/chapters.py:27,178`
- Modify: `app/templates/ebook.html:214-218,405-433,754-790,812-820`
- Modify: `tests/test_manual_chapter.py`

**Interfaces:**
- Consumes: `Storage.insert_chapter(self, ch: Chapter) -> None` from Task 1.
- Produces: `POST /ebooks/{slug}/chapters/manual` with form fields `index: int`, `title: str`, and `url: str`; HTTP 303 on success and HTTP 400 for expected validation failures.

- [ ] **Step 1: Add failing route and template tests**

Append to `tests/test_manual_chapter.py`:

```python
from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t", title="Test"),
        crawl=CrawlConfig(toc_url="https://x/book"),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(monkeypatch, tmp_path):
    from app.main import app

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    return TestClient(app), cfg


def test_manual_chapter_route_inserts_and_redirects(monkeypatch, tmp_path):
    client, cfg = _client(monkeypatch, tmp_path)
    storage = Storage(cfg.output.data_dir, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))

    response = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": "1", "title": "  新章  ", "url": "  https://x/new  "},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ebooks/t"
    chapters = storage.load_manifest().chapters
    assert [(ch.index, ch.title, ch.title_zh, ch.url) for ch in chapters] == [
        (1, "新章", "新章", "https://x/new"),
        (2, "One", "", "https://x/1"),
    ]


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        ({"index": "1", "title": " ", "url": "https://x/new"}, "Tiêu đề"),
        ({"index": "1", "title": "New", "url": " "}, "URL"),
        ({"index": "2", "title": "New", "url": "https://x/new"}, "Vị trí"),
    ],
)
def test_manual_chapter_route_rejects_invalid_input(monkeypatch, tmp_path, data, detail):
    client, cfg = _client(monkeypatch, tmp_path)
    Storage(cfg.output.data_dir, "t").save_manifest(Manifest(slug="t"))

    response = client.post("/ebooks/t/chapters/manual", data=data)

    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_manual_chapter_route_rejects_duplicate_url(monkeypatch, tmp_path):
    client, cfg = _client(monkeypatch, tmp_path)
    storage = Storage(cfg.output.data_dir, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))

    response = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": "1", "title": "Duplicate", "url": "https://x/1"},
    )

    assert response.status_code == 400
    assert "URL" in response.json()["detail"]
    assert [(ch.index, ch.url) for ch in storage.load_manifest().chapters] == [(1, "https://x/1")]


def test_ebook_template_contains_manual_chapter_modal():
    template = (Path(__file__).parents[1] / "app" / "templates" / "ebook.html").read_text(encoding="utf-8")

    assert 'id="add-manual-chapter-btn"' in template
    assert 'id="manual-chapter-modal"' in template
    assert 'action="/ebooks/{{ slug }}/chapters/manual"' in template
    assert 'name="index"' in template
    assert 'name="title"' in template
    assert 'name="url"' in template
```

- [ ] **Step 2: Run route/template tests and verify RED**

Run: `pytest tests/test_manual_chapter.py -v`

Expected: storage tests pass; route tests fail with HTTP 404 and template assertions fail because the modal is absent.

- [ ] **Step 3: Implement the route**

Change the storage import in `app/routes/chapters.py` to:

```python
from novel2epub.storage import Chapter, Storage
```

Add near the existing ebook chapter routes:

```python
@router.post("/ebooks/{slug}/chapters/manual")
def ebook_chapter_add_manual(
    slug: str,
    index: int = Form(...),
    title: str = Form(...),
    url: str = Form(...),
):
    title = title.strip()
    url = url.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Tiêu đề không được rỗng.")
    if not url:
        raise HTTPException(status_code=400, detail="URL nguồn không được rỗng.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    try:
        storage.insert_chapter(Chapter(index=index, url=url, title=title, title_zh=title))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)
```

- [ ] **Step 4: Add the toolbar button and modal form**

Inside `.toc-actions`, after the fetch-TOC form, add:

```html
    <button type="button" id="add-manual-chapter-btn" class="btn btn-sm btn-secondary">Thêm chương thủ công</button>
```

Before `selected-ai-modal`, add:

```html
<div id="manual-chapter-modal" class="modal-backdrop" hidden>
    <section class="modal modal-sm" role="dialog" aria-modal="true" aria-labelledby="manual-chapter-modal-title">
        <form method="post" action="/ebooks/{{ slug }}/chapters/manual" class="p-5 space-y-4">
            <div>
                <h3 id="manual-chapter-modal-title" class="m-0 text-base font-semibold">Thêm chương thủ công</h3>
                <p class="mt-1 mb-0 text-sm text-fg-muted dark:text-fg-muted-dark">Các chương từ vị trí này trở đi sẽ được dời xuống một index.</p>
            </div>
            <label class="form-group">
                <span class="label">Vị trí</span>
                <input type="number" name="index" min="1" max="{{ chapters|length + 1 }}" value="{{ chapters|length + 1 }}" required class="input">
            </label>
            <label class="form-group">
                <span class="label">Tiêu đề</span>
                <input type="text" name="title" required class="input">
            </label>
            <label class="form-group">
                <span class="label">URL nguồn</span>
                <input type="url" name="url" required class="input">
            </label>
            <div class="flex justify-end gap-2 pt-1">
                <button type="button" class="btn btn-secondary" data-close-modal="manual-chapter-modal">Hủy</button>
                <button type="submit" class="btn btn-primary">Thêm chương</button>
            </div>
        </form>
    </section>
</div>
```

Add event handling alongside the selected-AI modal handlers:

```javascript
document.getElementById("add-manual-chapter-btn")?.addEventListener("click", () => {
    openModal("manual-chapter-modal");
});
document.querySelector('[data-close-modal="manual-chapter-modal"]')?.addEventListener("click", () => {
    closeModal("manual-chapter-modal");
});
```

Extend the Escape handler before closing the selected-more menu:

```javascript
    const manualModal = document.getElementById("manual-chapter-modal");
    if (manualModal && !manualModal.hidden) {
        closeModal("manual-chapter-modal");
        return;
    }
```

- [ ] **Step 5: Run focused and related web tests**

Run: `pytest tests/test_manual_chapter.py tests/test_chapter_api.py tests/test_job_outcomes.py -v`

Expected: PASS.

- [ ] **Step 6: Run the full test suite**

Run: `pytest tests/ -v`

Expected: PASS with no new failures. If unrelated concurrent work causes failures, record the exact failing tests and confirm `pytest tests/test_manual_chapter.py tests/test_chapter_api.py tests/test_job_outcomes.py -v` remains green.

- [ ] **Step 7: Commit the route and UI**

```bash
git add app/routes/chapters.py app/templates/ebook.html tests/test_manual_chapter.py
git commit -m "feat: add manual chapter form"
```

## Completion Audit

- [ ] Confirm the button opens the modal and Escape/Hủy close it.
- [ ] Confirm the default index is `N+1` and browser constraints permit `1..N+1`.
- [ ] Confirm successful insertion shifts existing chapters and redirects to `/ebooks/{slug}`.
- [ ] Confirm title and URL are trimmed and stored, with `title_zh` preserving the entered title.
- [ ] Confirm invalid position, blank fields, and duplicate URL leave rows unchanged.
- [ ] Confirm raw, translated, MT snapshot, metadata, flags, and timestamps survive a middle insertion.
- [ ] Confirm focused tests and the full suite have fresh verification output.
