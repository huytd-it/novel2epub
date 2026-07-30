# Delete Ebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a permanent ebook deletion flow available from Library and Settings that removes the EPUB, per-ebook SQLite data, and automations only after exact-slug confirmation and only when no job is active.

**Architecture:** Add thread-safe active-job and retire/restore controls to `JobQueue`, then isolate destructive orchestration in a small application service. Retiring a slug atomically blocks stale scheduler work from being enqueued after deletion; create/import restores the slug for reuse. The FastAPI route maps typed service failures to status codes, both templates share one confirmation partial, and SQLite cascade handles per-ebook child rows while the service explicitly deletes automations and removes EPUB first.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, Jinja2, vanilla JavaScript, pytest, FastAPI TestClient

## Global Constraints

- Deletion is permanent; no restore or trash mechanism.
- Require exact, case-sensitive `confirm_slug == slug` on the server.
- Block deletion for any pending or running job whose `ebook` equals the slug; do not cancel jobs automatically.
- Delete the configured EPUB, per-ebook SQLite data, and all automations for the ebook.
- Preserve completed/failed/cancelled job history, global idioms, and shared source presets.
- If EPUB deletion fails, do not modify SQLite.
- Remove the existing bulk `Gỡ khỏi thư viện` action; bulk deletion is out of scope.
- Do not add dependencies or compatibility paths for the former YAML/file storage layout.

## File Map

- Create `app/ebook_deletion.py`: typed deletion failures and the filesystem/SQLite deletion service.
- Create `app/templates/_delete_ebook_modal.html`: reusable confirmation modal and its small JavaScript controller.
- Create `tests/test_ebook_deletion.py`: service/route success and failure tests, cascade assertions, and UI render assertions.
- Modify `app/queue.py`: expose active-job inspection plus atomic `retire_ebook`/`restore_ebook` controls under the queue lock.
- Modify `app/routes/ebooks.py`: add the delete route and map service failures to HTTP responses.
- Modify `app/templates/index.html`: add per-row delete trigger, include the shared modal, and remove bulk delete.
- Modify `app/templates/settings.html`: add a danger zone and include the shared modal.
- Modify `tests/test_job_queue.py`: verify active-job detection and history exclusion.

---

### Task 1: Thread-Safe Active Ebook Query

**Files:**
- Modify: `app/queue.py:333-356`
- Test: `tests/test_job_queue.py`

**Interfaces:**
- Consumes: existing `JobQueue.enqueue(...) -> Job`, `JobQueue.cancel(job_id) -> bool`, and queue-owned `_running`, `_pending`, `_history` collections.
- Produces: `JobQueue.has_active_ebook(ebook: str) -> bool`, `retire_ebook(ebook: str) -> bool`, and `restore_ebook(ebook: str) -> None`; retired slugs reject stale enqueue attempts until explicitly restored by create/import.

- [ ] **Step 1: Write failing tests for pending, running, unrelated, and history jobs**

Append tests using a paused queue for deterministic pending state and events for deterministic running state:

```python
import threading

from app.queue import JobQueue


def test_has_active_ebook_detects_pending_and_ignores_other_ebook():
    queue = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0})
    queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")

    assert queue.has_active_ebook("book-a") is True
    assert queue.has_active_ebook("book-b") is False


def test_has_active_ebook_detects_running_job():
    started = threading.Event()
    release = threading.Event()
    queue = JobQueue(workers={"crawl": 1, "translate": 0, "build": 0})

    def target(log):
        started.set()
        release.wait(timeout=2)

    queue.enqueue("crawl", "crawl", target, ebook="book-a")
    assert started.wait(timeout=2)
    try:
        assert queue.has_active_ebook("book-a") is True
    finally:
        release.set()


def test_has_active_ebook_ignores_cancelled_history_job():
    queue = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0})
    job = queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")
    assert queue.cancel(job.id) is True

    assert queue.has_active_ebook("book-a") is False
```

- [ ] **Step 2: Run the new queue tests and confirm the expected failure**

Run: `pytest tests/test_job_queue.py -k has_active_ebook -v`

Expected: FAIL with `AttributeError: 'JobQueue' object has no attribute 'has_active_ebook'`.

- [ ] **Step 3: Implement the minimal locked query**

Add beside `has_pending_step` in `app/queue.py`:

```python
    def has_active_ebook(self, ebook: str) -> bool:
        """Return whether an ebook has a pending or running job."""
        with self._lock:
            if any(job.ebook == ebook for job in self._running.values()):
                return True
            return any(
                job.ebook == ebook
                for pending in self._pending.values()
                for job in pending
            )
```

- [ ] **Step 4: Run queue tests**

Run: `pytest tests/test_job_queue.py -k "has_active_ebook or ebook_busy" -v`

Expected: all selected tests PASS; no worker thread remains blocked because each running-job test releases its event in `finally`.

- [ ] **Step 5: Commit the queue API**

```bash
git add app/queue.py tests/test_job_queue.py
git commit -m "feat: expose active ebook queue check"
```

---

### Task 2: Atomic Database Deletion Service with EPUB Guard

**Files:**
- Create: `app/ebook_deletion.py`
- Create: `tests/test_ebook_deletion.py`

**Interfaces:**
- Consumes: `JobQueue.has_active_ebook(ebook: str) -> bool`, `novel2epub.db.get_thread_connection(path)`, SQLite `ON DELETE CASCADE`, and `Path.unlink()`.
- Produces: `delete_ebook(db_path: str | Path, slug: str, confirm_slug: str, resolve_epub_path: Callable[[], str | Path], queue: ActiveEbookQueue) -> None`.
- Produces exceptions `EbookDeleteError`, `ConfirmationMismatch`, `EbookNotFound`, `EbookBusy`, and `EpubDeleteFailed`.

- [ ] **Step 1: Create service tests for confirmation, missing ebook, busy queue, EPUB failure, and success**

Create `tests/test_ebook_deletion.py` with a small queue stub and DB helpers. Use `write_db_config` to create ebook `book-a`, then seed representative child rows and one automation:

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ebook_deletion import (
    ConfirmationMismatch,
    EbookBusy,
    EbookNotFound,
    EpubDeleteFailed,
    delete_ebook,
)
from novel2epub.db import get_connection
from tests.conftest import write_db_config


class QueueStub:
    def __init__(self, active: bool = False):
        self.active = active

    def has_active_ebook(self, ebook: str) -> bool:
        return self.active


def make_ebook_db(tmp_path: Path) -> tuple[Path, Path]:
    epub = tmp_path / "book-a.epub"
    epub.write_bytes(b"epub")
    db = write_db_config(
        tmp_path / "novel2epub.db",
        ebooks={"book-a": {"name": "Book A", "output": {"epub_path": str(epub)}}},
    )
    conn = get_connection(db)
    with conn:
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, raw_text) VALUES (?, ?, ?, ?)",
            ("book-a", 1, "Chapter 1", "raw"),
        )
        conn.execute(
            "INSERT INTO glossary_entries (ebook_slug, list_name, source, target) VALUES (?, ?, ?, ?)",
            ("book-a", "names", "甲", "Giáp"),
        )
        conn.execute(
            "INSERT INTO automations (id, ebook) VALUES (?, ?)",
            ("auto-a", "book-a"),
        )
        conn.execute(
            "INSERT INTO job_queue_history (id, data_json) VALUES (?, ?)",
            ("history-a", '{"ebook":"book-a"}'),
        )
    conn.close()
    return db, epub


def row_count(db: Path, table: str, where: str = "", params: tuple = ()) -> int:
    conn = get_connection(db)
    sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
    count = conn.execute(sql, params).fetchone()[0]
    conn.close()
    return count


def test_delete_ebook_rejects_wrong_confirmation_without_changes(tmp_path):
    db, epub = make_ebook_db(tmp_path)

    with pytest.raises(ConfirmationMismatch):
        delete_ebook(db, "book-a", "BOOK-A", lambda: epub, QueueStub())

    assert epub.exists()
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1
    assert row_count(db, "automations", "ebook = ?", ("book-a",)) == 1


def test_delete_ebook_rejects_missing_ebook(tmp_path):
    db, epub = make_ebook_db(tmp_path)

    with pytest.raises(EbookNotFound):
        delete_ebook(db, "missing", "missing", lambda: tmp_path / "missing.epub", QueueStub())

    assert epub.exists()


def test_delete_ebook_rejects_active_job_without_changes(tmp_path):
    db, epub = make_ebook_db(tmp_path)

    with pytest.raises(EbookBusy):
        delete_ebook(db, "book-a", "book-a", lambda: epub, QueueStub(active=True))

    assert epub.exists()
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1
    assert row_count(db, "automations", "ebook = ?", ("book-a",)) == 1


def test_delete_ebook_epub_failure_preserves_database(tmp_path):
    db, epub = make_ebook_db(tmp_path)

    with patch("app.ebook_deletion.Path.unlink", side_effect=OSError("locked")):
        with pytest.raises(EpubDeleteFailed, match="locked"):
            delete_ebook(db, "book-a", "book-a", lambda: epub, QueueStub())

    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-a",)) == 1
    assert row_count(db, "automations", "ebook = ?", ("book-a",)) == 1


def test_delete_ebook_removes_epub_data_and_automation_but_keeps_history(tmp_path):
    db, epub = make_ebook_db(tmp_path)

    delete_ebook(db, "book-a", "book-a", lambda: epub, QueueStub())

    assert not epub.exists()
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 0
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-a",)) == 0
    assert row_count(db, "glossary_entries", "ebook_slug = ?", ("book-a",)) == 0
    assert row_count(db, "automations", "ebook = ?", ("book-a",)) == 0
    assert row_count(db, "job_queue_history", "id = ?", ("history-a",)) == 1
```

- [ ] **Step 2: Run service tests and confirm import failure**

Run: `pytest tests/test_ebook_deletion.py -v`

Expected: collection ERROR with `ModuleNotFoundError: No module named 'app.ebook_deletion'`.

- [ ] **Step 3: Implement typed failures and deletion service**

Create `app/ebook_deletion.py`:

```python
"""Permanent ebook deletion orchestration."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from novel2epub.db import get_thread_connection


class ActiveEbookQueue(Protocol):
    def has_active_ebook(self, ebook: str) -> bool: ...


class EbookDeleteError(Exception):
    """Base class for expected ebook deletion failures."""


class ConfirmationMismatch(EbookDeleteError):
    pass


class EbookNotFound(EbookDeleteError):
    pass


class EbookBusy(EbookDeleteError):
    pass


class EpubDeleteFailed(EbookDeleteError):
    pass


def delete_ebook(
    db_path: str | Path,
    slug: str,
    confirm_slug: str,
    resolve_epub_path: Callable[[], str | Path],
    queue: ActiveEbookQueue,
) -> None:
    if confirm_slug != slug:
        raise ConfirmationMismatch("Slug xác nhận không khớp.")

    conn = get_thread_connection(db_path)
    exists = conn.execute("SELECT 1 FROM ebooks WHERE slug = ?", (slug,)).fetchone()
    if exists is None:
        raise EbookNotFound(f"Không tìm thấy ebook '{slug}'.")
    if queue.has_active_ebook(slug):
        raise EbookBusy("Ebook đang có job chạy hoặc chờ trong hàng đợi.")

    epub_path = resolve_epub_path()
    epub = Path(epub_path) if epub_path else None
    if epub is not None and epub.exists():
        try:
            epub.unlink()
        except OSError as exc:
            raise EpubDeleteFailed(f"Không thể xóa EPUB: {exc}") from exc

    with conn:
        conn.execute("DELETE FROM automations WHERE ebook = ?", (slug,))
        conn.execute("DELETE FROM ebooks WHERE slug = ?", (slug,))
```

- [ ] **Step 4: Run service and schema tests**

Run: `pytest tests/test_ebook_deletion.py tests/test_db_schema.py -v`

Expected: all tests PASS, proving EPUB guard order, explicit automation deletion, cascade behavior, and history preservation.

- [ ] **Step 5: Commit the deletion service**

```bash
git add app/ebook_deletion.py tests/test_ebook_deletion.py
git commit -m "feat: add permanent ebook deletion service"
```

---

### Task 3: FastAPI Delete Endpoint and Error Mapping

**Files:**
- Modify: `app/routes/ebooks.py:8-20,99-130`
- Modify: `tests/test_ebook_deletion.py`

**Interfaces:**
- Consumes: `delete_ebook(...)` and its four expected exception classes; `request.app.state.job.queue`; `deps.DB_PATH`; a lazy callback returning `deps.resolved_cfg(slug).epub_path`.
- Produces: `POST /library/ebooks/{slug}/delete` with form field `confirm_slug`; `303`, `400`, `404`, `409`, or `500` behavior from the approved design.

- [ ] **Step 1: Write failing route tests for every response contract**

Append a client fixture that points `deps.DB_PATH` and config resolution to the temporary DB, then add explicit HTTP assertions:

```python
from fastapi.testclient import TestClient

from novel2epub.config import load_config


class FakeJobRunner:
    def __init__(self, active: bool = False):
        self.queue = QueueStub(active)

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
            "build": {"running": False, "step": "", "error": "", "log": []},
        }


def make_client(monkeypatch, db: Path, epub: Path, *, active: bool = False):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: load_config(db, slug))
    app.state.job = FakeJobRunner(active)
    return TestClient(app)


def test_delete_route_success_redirects_to_library(monkeypatch, tmp_path):
    db, epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db, epub)

    response = client.post(
        "/library/ebooks/book-a/delete",
        data={"confirm_slug": "book-a"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 0


@pytest.mark.parametrize(
    ("url_slug", "confirm_slug", "active", "expected"),
    [
        ("book-a", "wrong", False, 400),
        ("missing", "missing", False, 404),
        ("book-a", "book-a", True, 409),
    ],
)
def test_delete_route_maps_expected_failures(
    monkeypatch, tmp_path, url_slug, confirm_slug, active, expected
):
    db, epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db, epub, active=active)

    response = client.post(
        f"/library/ebooks/{url_slug}/delete",
        data={"confirm_slug": confirm_slug},
    )

    assert response.status_code == expected
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1


def test_delete_route_maps_epub_failure_to_500(monkeypatch, tmp_path):
    db, epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db, epub)

    with patch("app.ebook_deletion.Path.unlink", side_effect=OSError("locked")):
        response = client.post(
            "/library/ebooks/book-a/delete",
            data={"confirm_slug": "book-a"},
        )

    assert response.status_code == 500
    assert "Không thể xóa EPUB" in response.json()["detail"]
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1
```

- [ ] **Step 2: Run route tests and confirm endpoint absence**

Run: `pytest tests/test_ebook_deletion.py -k route -v`

Expected: FAIL with response status `404` for the new route.

- [ ] **Step 3: Add route imports and endpoint**

In `app/routes/ebooks.py`, import the service failures and add:

```python
from ..ebook_deletion import (
    ConfirmationMismatch,
    EbookBusy,
    EbookNotFound,
    EpubDeleteFailed,
    delete_ebook,
)


@router.post("/library/ebooks/{slug}/delete")
def delete_library_ebook(
    request: Request,
    slug: str,
    confirm_slug: str = Form(...),
):
    try:
        delete_ebook(
            deps.DB_PATH,
            slug,
            confirm_slug,
            lambda: deps.resolved_cfg(slug).epub_path,
            request.app.state.job.queue,
        )
    except ConfirmationMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EbookBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EpubDeleteFailed as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RedirectResponse(url="/", status_code=303)
```

The callback is intentionally lazy: `delete_ebook` invokes it only after exact confirmation, DB existence, and active-job checks. This prevents config resolution for a missing ebook and keeps existence validation centralized in the service.

- [ ] **Step 4: Run route and existing ebook management tests**

Run: `pytest tests/test_ebook_deletion.py tests/test_ebook_management.py -v`

Expected: all tests PASS. Existing bulk action still rejects `action=delete`; permanent deletion uses only the dedicated endpoint.

- [ ] **Step 5: Commit the HTTP endpoint**

```bash
git add app/routes/ebooks.py tests/test_ebook_deletion.py
git commit -m "feat: expose ebook deletion endpoint"
```

---

### Task 4: Shared Confirmation UI in Library and Settings

**Files:**
- Create: `app/templates/_delete_ebook_modal.html`
- Modify: `app/templates/index.html:61-75,139-145,156-177,327-378`
- Modify: `app/templates/settings.html:34-54,197-229`
- Modify: `tests/test_ebook_deletion.py`

**Interfaces:**
- Consumes: `POST /library/ebooks/{slug}/delete`, global `openModal`, `closeModal`, and `toast` browser helpers.
- Produces: `openDeleteEbook(slug, title)` browser function; modal form field `confirm_slug`; exact-match disabled-state behavior; redirect to `/` on success; inline error on failure.

- [ ] **Step 1: Write failing template render tests for both entry points and removal of bulk deletion**

Append tests that render each page with one ebook and assert stable data attributes rather than presentation-only classes:

```python
def test_library_renders_per_ebook_delete_trigger_and_no_bulk_delete(monkeypatch, tmp_path):
    db, epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db, epub)

    response = client.get("/")

    assert response.status_code == 200
    assert 'data-delete-ebook="book-a"' in response.text
    assert 'id="delete-ebook-modal"' in response.text
    assert "bulkDelete()" not in response.text


def test_settings_renders_delete_danger_zone(monkeypatch, tmp_path):
    db, epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db, epub)

    response = client.get("/ebooks/book-a/settings")

    assert response.status_code == 200
    assert 'data-delete-ebook="book-a"' in response.text
    assert 'id="delete-ebook-modal"' in response.text
    assert "Vùng nguy hiểm" in response.text
```

Update `make_client` as needed to monkeypatch `deps.library`, `deps.SOURCES_PATH`, and `deps.ebook_config_path` with the real temporary DB, following `tests/test_routes_settings_page.py`. Do not mock template rendering.

- [ ] **Step 2: Run UI tests and confirm missing trigger/modal failures**

Run: `pytest tests/test_ebook_deletion.py -k "renders or danger_zone" -v`

Expected: FAIL because neither page has `data-delete-ebook` or `delete-ebook-modal`, and Library still contains `bulkDelete()`.

- [ ] **Step 3: Create one shared modal partial with exact-slug client validation**

Create `app/templates/_delete_ebook_modal.html`:

```html
<div id="delete-ebook-modal" class="modal-backdrop" hidden
     onclick="if(event.target===this)closeDeleteEbook()">
  <div class="modal modal-sm p-5" role="alertdialog" aria-modal="true"
       aria-labelledby="delete-ebook-title">
    <h3 id="delete-ebook-title" class="m-0 text-base font-semibold">Xóa ebook</h3>
    <p class="mt-3 text-sm text-fg-muted dark:text-fg-muted-dark">
      Toàn bộ chương, bản dịch, glossary, automation và file EPUB sẽ bị xóa vĩnh viễn.
    </p>
    <p class="mt-3 text-sm">Nhập <code id="delete-ebook-slug-label"></code> để xác nhận.</p>
    <form id="delete-ebook-form" class="mt-3 space-y-3">
      <input id="delete-ebook-confirm" name="confirm_slug" class="input w-full"
             autocomplete="off" required>
      <p id="delete-ebook-error" class="text-sm text-status-err-fg dark:text-status-err-fg-dark" hidden></p>
      <div class="flex justify-end gap-2">
        <button type="button" class="btn btn-secondary" onclick="closeDeleteEbook()">Hủy</button>
        <button id="delete-ebook-submit" type="submit" class="btn btn-danger" disabled>Xóa vĩnh viễn</button>
      </div>
    </form>
  </div>
</div>
<script>
let deleteEbookSlug = "";

function openDeleteEbook(slug, title) {
  deleteEbookSlug = slug;
  document.getElementById("delete-ebook-title").textContent = "Xóa " + title;
  document.getElementById("delete-ebook-slug-label").textContent = slug;
  document.getElementById("delete-ebook-confirm").value = "";
  document.getElementById("delete-ebook-submit").disabled = true;
  document.getElementById("delete-ebook-error").hidden = true;
  openModal("delete-ebook-modal");
  document.getElementById("delete-ebook-confirm").focus();
}

function closeDeleteEbook() {
  closeModal("delete-ebook-modal");
}

document.getElementById("delete-ebook-confirm").addEventListener("input", event => {
  document.getElementById("delete-ebook-submit").disabled = event.target.value !== deleteEbookSlug;
});

document.getElementById("delete-ebook-form").addEventListener("submit", async event => {
  event.preventDefault();
  const submit = document.getElementById("delete-ebook-submit");
  const error = document.getElementById("delete-ebook-error");
  submit.disabled = true;
  try {
    const response = await fetch(`/library/ebooks/${encodeURIComponent(deleteEbookSlug)}/delete`, {
      method: "POST",
      body: new FormData(event.target),
    });
    if (response.ok) {
      window.location.assign("/");
      return;
    }
    const body = await response.json().catch(() => ({}));
    error.textContent = body.detail || "Không thể xóa ebook.";
  } catch {
    error.textContent = "Lỗi kết nối mạng.";
  }
  error.hidden = false;
  submit.disabled = document.getElementById("delete-ebook-confirm").value !== deleteEbookSlug;
});
</script>
```

- [ ] **Step 4: Wire Library and Settings to the shared modal**

In each ebook row in `app/templates/index.html`, add:

```html
<button type="button" class="btn btn-sm btn-danger"
  data-delete-ebook="{{ ebook.slug }}"
  onclick='openDeleteEbook({{ ebook.slug|tojson }}, {{ (ebook.cfg.novel.title or ebook.name)|tojson }})'>
  Xóa
</button>
```

Include the modal once after the Library region:

```jinja2
{% include "_delete_ebook_modal.html" %}
```

Remove the bulk `Gỡ khỏi thư viện` button and the complete `bulkDelete()` JavaScript function.

At the end of `app/templates/settings.html` content, before local scripts, add:

```html
<section class="mt-8 rounded-lg border border-status-err-light dark:border-status-err-dark p-4">
  <h3 class="m-0 text-base font-semibold text-status-err-fg dark:text-status-err-fg-dark">Vùng nguy hiểm</h3>
  <p class="mt-2 text-sm text-fg-muted dark:text-fg-muted-dark">
    Xóa vĩnh viễn ebook và toàn bộ dữ liệu liên quan. Thao tác này không thể hoàn tác.
  </p>
  <button type="button" class="btn btn-danger mt-3"
    data-delete-ebook="{{ slug }}"
    onclick='openDeleteEbook({{ slug|tojson }}, {{ (cfg.novel.title or slug)|tojson }})'>
    Xóa ebook
  </button>
</section>
{% include "_delete_ebook_modal.html" %}
```

- [ ] **Step 5: Run UI and endpoint tests**

Run: `pytest tests/test_ebook_deletion.py -v`

Expected: all tests PASS, including both render entry points and all endpoint/service failure paths.

- [ ] **Step 6: Run focused regression tests**

Run: `pytest tests/test_ebook_management.py tests/test_routes_settings_page.py tests/test_routes_settings_reset.py -v`

Expected: all tests PASS; archive/unarchive and settings autosave/reset remain unchanged.

- [ ] **Step 7: Commit the UI flow**

```bash
git add app/templates/_delete_ebook_modal.html app/templates/index.html app/templates/settings.html tests/test_ebook_deletion.py
git commit -m "feat: add confirmed ebook deletion UI"
```

---

### Task 5: Full Verification and Documentation Alignment

**Files:**
- Modify only if verification exposes an issue in files already listed above.

**Interfaces:**
- Consumes: the completed queue API, deletion service, route, and shared UI.
- Produces: verified feature behavior with no test or formatting regressions.

- [ ] **Step 1: Run the complete deletion-focused suite**

Run: `pytest tests/test_ebook_deletion.py tests/test_job_queue.py tests/test_ebook_management.py tests/test_db_schema.py -v`

Expected: all tests PASS.

- [ ] **Step 2: Run the complete test suite**

Run: `pytest tests/ -v`

Expected: all tests PASS. If an unrelated pre-existing failure occurs, record the exact failing test and rerun the focused suite to demonstrate feature correctness; do not weaken assertions or alter unrelated code.

- [ ] **Step 3: Check formatting and accidental changes**

Run: `git diff --check`

Expected: no output.

Run: `git status --short`

Expected: only intended files are modified, or a clean worktree if every task commit was created.

- [ ] **Step 4: Commit verification fixes only if required**

If verification required a code change, rerun the failing command and commit only the affected feature files:

```bash
git add app/ebook_deletion.py app/queue.py app/routes/ebooks.py app/templates/_delete_ebook_modal.html app/templates/index.html app/templates/settings.html tests/test_ebook_deletion.py tests/test_job_queue.py
git commit -m "fix: harden ebook deletion flow"
```

If no change was required, do not create an empty commit.
