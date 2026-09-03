"""Route upload TXT/EPUB: preview, tạo ebook mới, bổ sung chương (merge an toàn)."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from novel2epub.storage import Chapter, Storage

from .conftest import write_db_config

TXT_THREE = (
    "Chương 1: Khởi đầu\nNội dung một.\n\n"
    "Chương 2: Tiếp nối\nNội dung hai.\n\n"
    "Chương 3: Hồi kết\nNội dung ba.\n"
).encode("utf-8")

TXT_NO_HEADING = "Chỉ là đoạn văn.\nKhông có tiêu đề nào.\n".encode("utf-8")


class _Queue:
    def restore_ebook(self, slug):
        pass


class _Job:
    def __init__(self):
        self.queue = _Queue()


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app

    db_path = tmp_path / "upload.db"
    write_db_config(db_path)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    monkeypatch.setattr(deps, "DB_PATH", db_path)
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db_path))
    app.state.job = _Job()
    return TestClient(app), db_path


def _load_storage(db_path, slug) -> Storage:
    from novel2epub.config import load_config

    cfg = load_config(str(db_path), slug)
    return Storage(cfg.output.data_dir, cfg.novel.slug)


def test_upload_preview_txt(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/library/ebooks/upload/preview",
        files={"file": ("Test Truyen.txt", TXT_THREE, "text/plain")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["chapter_count"] == 3
    assert data["title"] == "Test Truyen"
    assert data["slug"] == "test-truyen"
    assert len(data["chapters_preview"]) == 3
    assert data["has_cover"] is False


def test_upload_preview_no_heading_is_400(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/library/ebooks/upload/preview",
        files={"file": ("nohead.txt", TXT_NO_HEADING, "text/plain")},
    )
    assert res.status_code == 400
    assert "tiêu đề" in res.json()["detail"]


def test_upload_preview_bad_extension_is_400(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/library/ebooks/upload/preview",
        files={"file": ("truyen.pdf", b"data", "application/pdf")},
    )
    assert res.status_code == 400


def test_upload_create_ebook_from_txt(monkeypatch, tmp_path):
    client, db_path = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/library/ebooks/upload",
        files={"file": ("Test Truyen.txt", TXT_THREE, "text/plain")},
        data={"title": "Test Truyen", "author": "TG Test"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "test-truyen"
    assert res.json()["chapter_count"] == 3

    storage = _load_storage(db_path, "test-truyen")
    manifest = storage.load_manifest()
    assert manifest is not None
    assert [c.index for c in manifest.chapters] == [1, 2, 3]
    # toc_url optional — ebook upload không cần toc_url
    from novel2epub.config import load_config

    cfg = load_config(str(db_path), "test-truyen")
    assert cfg.crawl.toc_url == ""
    assert storage.has_raw(Chapter(index=1, url=""))
    assert "Nội dung hai" in storage.read_raw(Chapter(index=2, url=""))


def test_upload_create_duplicate_slug_409(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    files = {"file": ("Test Truyen.txt", TXT_THREE, "text/plain")}
    first = client.post("/api/ui/library/ebooks/upload", files=files)
    assert first.status_code == 200
    second = client.post("/api/ui/library/ebooks/upload", files=files)
    assert second.status_code == 409


def test_upload_append_only_missing_indexes(monkeypatch, tmp_path):
    client, db_path = _client(monkeypatch, tmp_path)
    # Ebook ban đầu có chương 1, 2
    two = "Chương 1: Khởi đầu\nNội dung GỐC một.\n\nChương 2: Tiếp nối\nNội dung hai.\n".encode("utf-8")
    res = client.post(
        "/api/ui/library/ebooks/upload",
        files={"file": ("Gap Truyen.txt", two, "text/plain")},
        data={"slug": "gap-truyen"},
    )
    assert res.status_code == 200, res.text

    # File bổ sung có index 1 (trùng), 3, 5 (lấp đúng index)
    more = (
        "Chương 1: Khởi đầu KHÁC\nNội dung MỚI một (phải bị bỏ qua).\n\n"
        "Chương 3: Mới\nNội dung ba.\n\n"
        "Chương 5: Nhảy cóc\nNội dung năm.\n"
    ).encode("utf-8")
    res = client.post(
        "/api/ui/ebooks/gap-truyen/chapters/upload",
        files={"file": ("more.txt", more, "text/plain")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["added"] == 2
    assert data["skipped"] == 1
    assert sorted(data["added_indexes"]) == [3, 5]

    storage = _load_storage(db_path, "gap-truyen")
    manifest = storage.load_manifest()
    assert manifest is not None
    # Không mất chương cũ, index mới nằm đúng vị trí
    assert [c.index for c in manifest.chapters] == [1, 2, 3, 5]
    # Không ghi đè chương đã có raw
    assert "Nội dung GỐC một" in storage.read_raw(Chapter(index=1, url=""))
    assert "Nội dung ba" in storage.read_raw(Chapter(index=3, url=""))


def test_upload_append_missing_ebook_404(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/ebooks/khong-co/chapters/upload",
        files={"file": ("a.txt", TXT_THREE, "text/plain")},
    )
    assert res.status_code == 404


def _build_epub_bytes() -> bytes:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("route-test")
    book.set_title("Route Epub")
    book.add_author("Epub Author")
    c1 = epub.EpubHtml(title="Chapter 1", file_name="c1.xhtml")
    c1.content = "<h1>Chapter 1</h1><p>Body one.</p>"
    c2 = epub.EpubHtml(title="Chapter 2", file_name="c2.xhtml")
    c2.content = "<h1>Chapter 2</h1><p>Body two.</p>"
    book.add_item(c1)
    book.add_item(c2)
    book.spine = ["nav", c1, c2]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    book.set_cover("cover.png", png, create_page=False)
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def test_upload_create_ebook_from_epub_keeps_cover(monkeypatch, tmp_path):
    client, db_path = _client(monkeypatch, tmp_path)
    data = _build_epub_bytes()
    res = client.post(
        "/api/ui/library/ebooks/upload",
        files={"file": ("route.epub", data, "application/epub+zip")},
        data={"slug": "route-epub"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["chapter_count"] == 2

    storage = _load_storage(db_path, "route-epub")
    manifest = storage.load_manifest()
    assert manifest is not None
    assert manifest.cover_file == "cover.png"
    assert storage.read_cover_bytes() is not None
    assert [c.index for c in manifest.chapters] == [1, 2]
