from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.ebook_deletion import (
    ConfirmationMismatch,
    EbookBusy,
    EbookNotFound,
    EpubDeleteFailed,
    delete_ebook,
)
from novel2epub.db import get_connection
from novel2epub.config import load_config
from tests.conftest import write_db_config


class QueueStub:
    def __init__(self, active: bool = False):
        self.active = active
        self.restored: list[str] = []

    def retire_ebook(self, ebook: str) -> bool:
        return not self.active

    def restore_ebook(self, ebook: str) -> None:
        self.restored.append(ebook)


class FakeJobRunner:
    def __init__(self, active: bool = False):
        self.queue = QueueStub(active)

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
            "build": {"running": False, "step": "", "error": "", "log": []},
        }


def make_ebook_db(tmp_path: Path) -> tuple[Path, Path]:
    epub = tmp_path / "book-a.epub"
    epub.write_bytes(b"epub")
    db = write_db_config(
        tmp_path / "novel2epub.db",
        ebooks={"book-a": {"novel": {"title": "Book A"}, "output": {"epub_path": str(epub)}}},
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


def make_client(monkeypatch, db: Path, *, active: bool = False):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "LIBRARY_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    monkeypatch.setattr(deps, "LIBRARY_STATE_PATH", str(db))
    monkeypatch.setattr(deps, "library", lambda: __import__(
        "novel2epub.config", fromlist=["load_library"]
    ).load_library(db))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: load_config(db, slug))
    monkeypatch.setattr(deps, "ebook_config_path", lambda slug: str(db))
    app.state.job = FakeJobRunner(active)
    return TestClient(app)


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
    queue = QueueStub()

    with patch("app.ebook_deletion.Path.unlink", side_effect=OSError("locked")):
        with pytest.raises(EpubDeleteFailed, match="locked"):
            delete_ebook(db, "book-a", "book-a", lambda: epub, queue)

    assert queue.restored == ["book-a"]
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


def test_delete_route_success_returns_ok(monkeypatch, tmp_path):
    db, _epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db)

    response = client.post(
        "/api/ui/library/ebooks/book-a/delete",
        data={"confirm_slug": "book-a"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
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
    db, _epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db, active=active)

    response = client.post(
        f"/api/ui/library/ebooks/{url_slug}/delete",
        data={"confirm_slug": confirm_slug},
    )

    assert response.status_code == expected
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1


def test_delete_route_maps_epub_failure_to_500(monkeypatch, tmp_path):
    db, _epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db)

    with patch("app.ebook_deletion.Path.unlink", side_effect=OSError("locked")):
        response = client.post(
            "/api/ui/library/ebooks/book-a/delete",
            data={"confirm_slug": "book-a"},
        )

    assert response.status_code == 500
    assert "Không thể xóa EPUB" in response.json()["detail"]
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1


def test_library_api_reports_book_with_delete_metadata(monkeypatch, tmp_path):
    db, _epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db)

    response = client.get("/api/ui/library")

    assert response.status_code == 200
    data = response.json()
    slugs = {ebook["slug"] for ebook in data["ebooks"]}
    assert "book-a" in slugs


def test_settings_api_exposes_delete_danger_zone_data(monkeypatch, tmp_path):
    db, _epub = make_ebook_db(tmp_path)
    client = make_client(monkeypatch, db)

    response = client.get("/api/ui/ebooks/book-a/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "book-a"
    assert data["novel"]["title"] == "Book A"
