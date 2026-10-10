"""Xóa hoàn toàn mục lục ở Cài đặt → Nguồn: mất chương + bản gốc + bản dịch,
giữ truyện/cấu hình/glossary; đã có nội dung thì server bắt xác nhận lại."""
from __future__ import annotations

from pathlib import Path

from novel2epub.config import load_config
from novel2epub.db import get_connection
from novel2epub.storage import Storage
from tests.helpers.db import write_db_config
from tests.test_ebook_deletion import make_client, row_count


def _db(tmp_path: Path, *, with_content: bool) -> Path:
    db = write_db_config(
        tmp_path / "novel2epub.db",
        ebooks={
            "book-a": {"novel": {"title": "Book A"},
                       "crawl": {"toc_url": "https://a.test/book/1"}},
            "book-b": {"novel": {"title": "Book B"}},
        },
    )
    conn = get_connection(db)
    with conn:
        for idx in (1, 2, 3):
            conn.execute(
                "INSERT INTO chapters (ebook_slug, idx, url, title) VALUES (?, ?, ?, ?)",
                ("book-a", idx, f"https://a.test/{idx}", f"Chương {idx}"),
            )
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, raw_text) VALUES ('book-b', 1, 'B1', 'raw b')"
        )
        if with_content:
            conn.execute(
                "UPDATE chapters SET raw_text = 'gốc' WHERE ebook_slug = 'book-a' AND idx IN (1, 2)"
            )
            conn.execute(
                "UPDATE chapters SET translated_text = 'dịch' WHERE ebook_slug = 'book-a' AND idx = 1"
            )
        conn.execute(
            "INSERT INTO glossary_entries (ebook_slug, list_name, source, target) "
            "VALUES ('book-a', 'names.txt', '甲', 'Giáp')"
        )
        conn.execute(
            "INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES "
            "('book-a', 'content_validation:chapter:1', '{}'), ('book-a', 'giu_lai', '{}')"
        )
    conn.close()
    return db


def _storage(db: Path, slug: str) -> Storage:
    cfg = load_config(db, slug)
    return Storage(cfg.output.data_dir, cfg.novel.slug)


def test_toc_summary_dem_chuong_ban_goc_ban_dich(tmp_path):
    db = _db(tmp_path, with_content=True)
    assert _storage(db, "book-a").toc_summary() == {"chapters": 3, "raw": 2, "translated": 1}


def test_clear_toc_xoa_chuong_va_du_lieu_theo_chuong_giu_phan_con_lai(tmp_path):
    db = _db(tmp_path, with_content=True)
    storage = _storage(db, "book-a")

    assert storage.clear_toc() == {"chapters": 3, "raw": 2, "translated": 1}

    assert storage.toc_summary() == {"chapters": 0, "raw": 0, "translated": 0}
    manifest = storage.load_manifest()
    assert manifest is not None and manifest.chapters == []
    assert row_count(db, "chapter_ui_state", "ebook_slug = ?", ("book-a",)) == 0
    assert row_count(db, "ebook_extra_json", "ebook_slug = ?", ("book-a",)) == 1
    # Không lây sang truyện khác, không mất truyện / glossary.
    assert row_count(db, "ebooks", "slug = ?", ("book-a",)) == 1
    assert row_count(db, "glossary_entries", "ebook_slug = ?", ("book-a",)) == 1
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-b",)) == 1


def test_route_muc_luc_chua_co_noi_dung_xoa_ngay(monkeypatch, tmp_path):
    db = _db(tmp_path, with_content=False)
    client = make_client(monkeypatch, db)

    assert client.get("/api/ui/ebooks/book-a/toc/summary").json() == {
        "chapters": 3, "raw": 0, "translated": 0,
    }
    response = client.post("/api/ui/ebooks/book-a/toc/clear", json={})

    assert response.status_code == 200
    assert response.json()["removed"]["chapters"] == 3
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-a",)) == 0


def test_route_da_co_ban_goc_ban_dich_thi_bat_xac_nhan_lai(monkeypatch, tmp_path):
    db = _db(tmp_path, with_content=True)
    client = make_client(monkeypatch, db)

    response = client.post("/api/ui/ebooks/book-a/toc/clear", json={})
    assert response.status_code == 409
    assert "xác nhận lại" in response.json()["detail"]
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-a",)) == 3

    response = client.post("/api/ui/ebooks/book-a/toc/clear", json={"confirm_content": True})
    assert response.status_code == 200
    assert response.json()["removed"] == {"chapters": 3, "raw": 2, "translated": 1}
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-a",)) == 0


def test_route_tu_choi_khi_truyen_dang_co_job(monkeypatch, tmp_path):
    db = _db(tmp_path, with_content=True)
    client = make_client(monkeypatch, db, active=True)

    response = client.post("/api/ui/ebooks/book-a/toc/clear", json={"confirm_content": True})

    assert response.status_code == 409
    assert row_count(db, "chapters", "ebook_slug = ?", ("book-a",)) == 3
