"""Roundtrip xuat/nhap ebook giua hai app (novel2epub.ebook_transfer)."""
import pytest

from novel2epub import ebook_transfer as t
from novel2epub.config_writer import update_ebook
from novel2epub.db import resolve_db_path
from novel2epub.storage import Chapter, Manifest, Storage


def _seed(data_dir, slug="truyen-mau"):
    storage = Storage(data_dir, slug)
    storage.ensure_dirs()
    manifest = Manifest(
        slug=slug, source_url="https://example.com/toc", title="Truyen Mau",
        author="Tac Gia", description="Mo ta", cover_url="https://example.com/c.jpg",
        chapters=[
            Chapter(index=1, url="https://example.com/1", title="Chuong 1: Mo dau",
                    title_zh="第1章 开端"),
            Chapter(index=2, url="https://example.com/2", title="Chuong 2",
                    title_zh="第2章"),
        ],
    )
    storage.save_manifest(manifest)
    ch1, ch2 = Chapter(index=1, url=""), Chapter(index=2, url="")
    storage.write_raw(ch1, "raw mot", crawl_pages=1)
    storage.write_raw(ch2, "raw hai", crawl_pages=2)
    storage.write_branch_text(ch1, "ai", "ban dich AI 1")
    storage.write_branch_titles(ch1, "ai", "Chuong 1: Mo dau", "第1章 开端")
    storage.write_branch_mt_snapshot(ch1, "ai", "snapshot AI 1")
    storage.write_branch_text(ch1, "local_mt", "ban dich MT 1")
    storage.write_branch_titles(ch1, "local_mt", "Chuong 1 MT", "第1章")
    storage.write_branch_mt_snapshot(ch1, "local_mt", "snapshot MT 1")
    storage.write_meta(ch1, {"complete": True, "local_mt_complete": True})
    storage.write_glossary_entries("names.txt", [("李逸", "Ly Dich", "nhan vat")])
    storage.upsert_character(source="李逸", target="Ly Dich", gender="nam")
    storage.upsert_relation(a_source="李逸", b_source="林动", a_calls_b="su de")
    storage.write_notes([{"para_index": 0, "selected_text": "abc"}])
    storage.import_entity_overrides(
        [{"source": "Hachimi", "target": "Hachimi", "protect": True}], merge=False)
    storage.write_extra_json("cost_summary", {"total_cost_usd": 1.5})
    storage.write_cover(b"fake-image-bytes", "jpg")
    return storage


def test_export_preview_import_roundtrip(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    _seed(d1)
    db1 = resolve_db_path(d1)
    update_ebook(str(db1), "truyen-mau",
                 {"crawl": {"delay_seconds": 2.5}, "translate": {"genre": "tien-hiep"}})

    payload = t.build_transfer_zip(d1, "truyen-mau")
    preview = t.preview_transfer_zip(payload)
    assert preview["slug"] == "truyen-mau"
    assert preview["chapters"] == 2
    assert preview["has_raw"] == 2
    assert preview["has_translated"] == 1
    assert preview["glossary"] == 1
    assert preview["characters"] == 1
    assert preview["has_cover"] is True

    db2 = resolve_db_path(d2)
    result = t.import_transfer_zip(db2, d2, payload)
    assert result["slug"] == "truyen-mau"
    assert result["counts"]["chapters"] == 2

    dst = Storage(d2, "truyen-mau")
    manifest = dst.load_manifest()
    assert manifest is not None
    assert manifest.title == "Truyen Mau"
    assert [c.title for c in manifest.chapters] == ["Chuong 1: Mo dau", "Chuong 2"]
    ch1 = Chapter(index=1, url="")
    assert dst.read_raw(ch1) == "raw mot"
    assert dst.crawl_pages(ch1) == 1
    assert dst.read_branch_text(ch1, "ai") == "ban dich AI 1"
    assert dst.read_branch_title(ch1, "ai") == "Chuong 1: Mo dau"
    assert dst.read_branch_mt_snapshot(ch1, "ai") == "snapshot AI 1"
    assert dst.read_branch_text(ch1, "local_mt") == "ban dich MT 1"
    assert dst.read_branch_title(ch1, "local_mt") == "Chuong 1 MT"
    assert dst.active_branch(ch1) == "ai"
    assert dst.read_meta(ch1)["complete"] is True
    assert dst.read_glossary_entries("names.txt") == [("李逸", "Ly Dich", "nhan vat")]
    assert dst.read_character_entries()[0][0] == "李逸"
    assert dst.read_relation_entries()[0][:2] == ("李逸", "林动")
    assert dst.read_notes() == [{"para_index": 0, "selected_text": "abc"}]
    assert dst.export_entity_overrides() == [
        {"source": "Hachimi", "target": "Hachimi", "protect": True}]
    assert dst.read_extra_json("cost_summary") == {"total_cost_usd": 1.5}
    assert dst.read_cover_bytes()[0] == b"fake-image-bytes"
    # Overrides crawl/translate duoc giu lai.
    from novel2epub.db import get_thread_connection
    row = get_thread_connection(db2).execute(
        "SELECT crawl_overrides_json, translate_overrides_json FROM ebooks WHERE slug=?",
        ("truyen-mau",)).fetchone()
    assert "2.5" in row["crawl_overrides_json"]
    assert "tien-hiep" in row["translate_overrides_json"]


def test_import_conflict_and_overwrite(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    _seed(d1)
    payload = t.build_transfer_zip(d1, "truyen-mau")
    db2 = resolve_db_path(d2)
    t.import_transfer_zip(db2, d2, payload)
    with pytest.raises(FileExistsError):
        t.import_transfer_zip(db2, d2, payload)
    # Ghi de: khong loi, du lieu moi thang.
    result = t.import_transfer_zip(db2, d2, payload, overwrite=True)
    assert result["slug"] == "truyen-mau"
    assert result["counts"]["chapters"] == 2
    # Doi slug khi nhap.
    result = t.import_transfer_zip(db2, d2, payload, slug="truyen-khac")
    assert result["slug"] == "truyen-khac"
    assert Storage(d2, "truyen-khac").load_manifest() is not None


def test_preview_rejects_bad_files():
    with pytest.raises(ValueError):
        t.preview_transfer_zip(b"khong phai zip")
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(ValueError):
        t.preview_transfer_zip(buf.getvalue())


def test_export_missing_ebook(tmp_path):
    with pytest.raises(KeyError):
        t.build_transfer_zip(tmp_path / "empty", "khong-co")


# ── Route /api/ui (export → preview → import) ─────────────────────────────

class _Queue:
    def restore_ebook(self, slug):
        pass


class _Job:
    def __init__(self):
        self.queue = _Queue()


import pytest


@pytest.fixture
def route_client(monkeypatch, tmp_path):
    """TestClient voi DB tam. LUU VA KHOI PHUC `app.state.job` sau test —
    khong lam ban cac test khac dung chung object `app` (vd test_job_outcomes
    can queue that)."""
    from fastapi.testclient import TestClient

    from app import deps
    from app.main import app

    db_path = tmp_path / "transfer.db"
    from tests.helpers.db import write_db_config
    write_db_config(db_path)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    monkeypatch.setattr(deps, "DB_PATH", db_path)
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db_path))
    old_job = getattr(app.state, "job", None)
    had_job = hasattr(app.state, "job")
    app.state.job = _Job()
    try:
        yield TestClient(app), db_path
    finally:
        if had_job:
            app.state.job = old_job
        else:
            try:
                del app.state.job
            except AttributeError:
                pass


def _seed_route_ebook(db_path, slug="truyen-goc"):
    from novel2epub.config import load_config
    from novel2epub.config_writer import add_ebook

    add_ebook(str(db_path), slug, title="Truyen Goc", author="Tac Gia",
              toc_url="https://example.com/toc")
    cfg = load_config(str(db_path), slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.save_manifest(Manifest(
        slug=slug, source_url="https://example.com/toc", title="Truyen Goc",
        author="Tac Gia", chapters=[Chapter(index=1, url="https://example.com/1",
                                            title="Chuong 1", title_zh="第1章")],
    ))
    ch = Chapter(index=1, url="")
    storage.write_raw(ch, "raw mot", crawl_pages=1)
    storage.write_branch_text(ch, "ai", "ban dich mot")
    storage.write_meta(ch, {"complete": True})
    return storage


def test_route_export_preview_import(route_client):
    client, db_path = route_client
    _seed_route_ebook(db_path)

    res = client.get("/api/ui/ebooks/truyen-goc/transfer/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert res.content[:2] == b"PK"
    payload = res.content

    res = client.post(
        "/api/ui/library/ebooks/transfer/preview",
        files={"file": ("truyen-goc.n2e.zip", payload, "application/zip")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "truyen-goc"
    assert res.json()["chapters"] == 1
    assert res.json()["exists"] is True

    res = client.post(
        "/api/ui/library/ebooks/transfer/import",
        files={"file": ("truyen-goc.n2e.zip", payload, "application/zip")},
        data={"slug": "truyen-moi"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "truyen-moi"
    assert res.json()["counts"]["chapters"] == 1

    # Nhap trung slug goc ma khong ghi de → 409.
    res = client.post(
        "/api/ui/library/ebooks/transfer/import",
        files={"file": ("truyen-goc.n2e.zip", payload, "application/zip")},
        data={},
    )
    assert res.status_code == 409
    # Ghi de → 200.
    res = client.post(
        "/api/ui/library/ebooks/transfer/import",
        files={"file": ("truyen-goc.n2e.zip", payload, "application/zip")},
        data={"overwrite": "1"},
    )
    assert res.status_code == 200, res.text


def test_route_preview_rejects_non_zip(route_client):
    client, _ = route_client
    res = client.post(
        "/api/ui/library/ebooks/transfer/preview",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400
    res = client.get("/api/ui/ebooks/khong-co/transfer/export")
    assert res.status_code == 404


def _seed_with_source(data_dir, slug="truyen-mau", source_name="nguon-la"):
    from novel2epub.config_writer import add_ebook
    from novel2epub.sources import SourcePreset, save_preset

    _seed(data_dir, slug)
    db = resolve_db_path(data_dir)
    save_preset(str(db), SourcePreset(name=source_name, content_selector=".x"))
    add_ebook(
        str(db), slug,
        title="Truyen Mau", author="Tac Gia",
        toc_url="https://example.com/toc", source_name=source_name,
    )
    return db


def test_import_keeps_missing_source_preset_with_warning(tmp_path):
    """Preset gốc không có trên app đích: import vẫn xong, giữ liên kết + cảnh báo."""
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    _seed_with_source(d1)
    payload = t.build_transfer_zip(d1, "truyen-mau")

    db2 = resolve_db_path(d2)
    result = t.import_transfer_zip(db2, d2, payload)

    assert result["slug"] == "truyen-mau"
    assert any("nguon-la" in w for w in result["warnings"])
    from novel2epub.db import get_thread_connection

    row = get_thread_connection(db2).execute(
        "SELECT source_preset FROM ebooks WHERE slug=?", ("truyen-mau",)
    ).fetchone()
    assert row["source_preset"] == "nguon-la"


def test_ensure_source_stub_for_legacy_fk(tmp_path):
    """Lưới an toàn cho DB cũ còn FK: stub preset rỗng để INSERT không nổ."""
    import sqlite3

    from novel2epub.config_writer import _ensure_source_stub_for_legacy_fk

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE sources (
            name TEXT PRIMARY KEY,
            data_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE ebooks (
            slug TEXT PRIMARY KEY,
            source_preset TEXT REFERENCES sources(name) ON DELETE SET NULL
        );
    """)
    with conn:
        _ensure_source_stub_for_legacy_fk(conn, "nguon-la")
        # Stub xong thì INSERT ref treo không còn nổ FK.
        conn.execute(
            "INSERT INTO ebooks (slug, source_preset) VALUES ('a', 'nguon-la')"
        )
    assert conn.execute(
        "SELECT 1 FROM sources WHERE name='nguon-la'"
    ).fetchone() is not None
    conn.close()

    # DB mới (không FK): no-op tuyệt đối, không sinh stub rác.
    from novel2epub.db import get_connection, init_schema

    fresh = get_connection(":memory:")
    init_schema(fresh)
    with fresh:
        _ensure_source_stub_for_legacy_fk(fresh, "nguon-la")
    assert fresh.execute("SELECT COUNT(*) AS c FROM sources").fetchone()["c"] == 0


def test_route_import_maps_integrity_error_to_400(route_client, monkeypatch):
    """DB lỗi integrity còn sót → 400 có message, không 500."""
    import sqlite3

    from novel2epub import ebook_transfer

    def _boom(*args, **kwargs):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(ebook_transfer, "import_transfer_zip", _boom)
    client, _ = route_client
    res = client.post(
        "/api/ui/library/ebooks/transfer/import",
        files={"file": ("x.n2e.zip", b"PK-fake", "application/zip")},
        data={"slug": "x"},
    )
    assert res.status_code == 400
