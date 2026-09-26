"""Đổi tên source preset.

Ebook tham chiếu preset BẰNG TÊN (`ebooks.source_preset`), nên đổi tên preset mà
không trỏ lại sẽ làm mọi truyện đó rơi về "preset không tồn tại" — `load_config`
chỉ cảnh báo rồi fallback sang field riêng, tức là truyện âm thầm crawl sai
cấu hình. Vì vậy rename phải ghi tới `ebooks.source_preset` trong CÙNG
transaction với việc tạo/xoá row preset.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel2epub.db import get_connection
from novel2epub.sources import load_presets, rename_preset

from tests.conftest import write_db_config


def _make_db(tmp_path, sources=None, ebooks=None):
    return write_db_config(
        tmp_path / "novel2epub.db",
        sources=sources or {"old-name": {"content_selector": ".content"}},
        ebooks=ebooks
        or {
            "novel-a": {"source": "old-name", "novel": {"title": "A"}},
            "novel-b": {"source": "old-name", "novel": {"title": "B"}},
            "novel-c": {"novel": {"title": "C"}},
        },
    )


def _source_of(db, slug):
    conn = get_connection(str(db))
    row = conn.execute("SELECT source_preset FROM ebooks WHERE slug=?", (slug,)).fetchone()
    conn.close()
    return row["source_preset"] if row else None


def _codes(db):
    conn = get_connection(str(db))
    rows = {r["name"]: r["code"] for r in conn.execute("SELECT name, code FROM sources")}
    conn.close()
    return rows


class TestRenamePreset:
    def test_ten_doi_va_ebook_duoc_tro_lai(self, tmp_path):
        db = _make_db(tmp_path)

        rename_preset(db, "old-name", "new-name")

        presets = load_presets(db)
        assert set(presets) == {"new-name"}
        assert presets["new-name"].content_selector == ".content"
        assert _source_of(db, "novel-a") == "new-name"
        assert _source_of(db, "novel-b") == "new-name"
        # Ebook không gắn nguồn thì không bị đụng.
        assert _source_of(db, "novel-c") is None

    def test_ebook_van_resolve_dung_preset_sau_khi_doi_ten(self, tmp_path):
        from novel2epub.config import load_config

        db = _make_db(tmp_path)
        rename_preset(db, "old-name", "new-name")

        cfg = load_config(db, "novel-a")
        assert cfg.source == "new-name"
        assert cfg.crawl.content_selector == ".content"
        assert cfg.warnings == []

    def test_code_nguyen_ven_de_code_ebook_on_dinh(self, tmp_path):
        db = _make_db(tmp_path)
        load_presets(db)  # backfill_codes chạy khi DB được mở lần đầu
        before = _codes(db)
        assert before["old-name"]

        rename_preset(db, "old-name", "new-name")

        assert _codes(db)["new-name"] == before["old-name"]

    def test_trung_ten_thi_value_error(self, tmp_path):
        db = _make_db(tmp_path, sources={
            "a": {"content_selector": ".a"},
            "b": {"content_selector": ".b"},
        })

        with pytest.raises(ValueError, match="đã tồn tại"):
            rename_preset(db, "a", "b")

        assert set(load_presets(db)) == {"a", "b"}

    def test_ten_rong_va_ten_khong_ton_tai(self, tmp_path):
        db = _make_db(tmp_path)

        with pytest.raises(ValueError):
            rename_preset(db, "old-name", "   ")
        with pytest.raises(ValueError):
            rename_preset(db, "khong-co", "new-name")

        assert set(load_presets(db)) == {"old-name"}

    def test_ten_khong_doi_thi_no_op(self, tmp_path):
        db = _make_db(tmp_path)
        rename_preset(db, "old-name", " old-name ")
        assert set(load_presets(db)) == {"old-name"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db = _make_db(tmp_path)
    from app import deps

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    monkeypatch.setattr(deps, "WORKSPACE_DIR", db.parent / ".n2e")
    from app.main import app

    return TestClient(app, follow_redirects=False)


class TestRenameApi:
    def test_save_voi_rename_from(self, client):
        res = client.post(
            "/api/ui/sources",
            json={
                "name": "new-name",
                "rename_from": "old-name",
                "content_selector": "#chuong",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "new-name"

        overview = client.get("/api/ui/sources").json()
        assert [p["name"] for p in overview["presets"]] == ["new-name"]
        assert overview["presets"][0]["content_selector"] == "#chuong"
        # Usage phải bám theo tên mới, nếu không thẻ nguồn mới báo "0 truyện dùng".
        assert overview["usage"]["new-name"] == ["novel-a", "novel-b"]
        assert "old-name" not in overview["usage"]

    def test_save_thuong_khong_rename(self, client):
        res = client.post("/api/ui/sources", json={"name": "new-name"})
        assert res.status_code == 200, res.text
        # Không có rename_from → preset cũ vẫn còn nguyên.
        overview = client.get("/api/ui/sources").json()
        assert sorted(p["name"] for p in overview["presets"]) == ["new-name", "old-name"]

    def test_rename_trung_ten_thi_409(self, client):
        client.post("/api/ui/sources", json={"name": "khac"})
        res = client.post(
            "/api/ui/sources",
            json={"name": "khac", "rename_from": "old-name"},
        )
        assert res.status_code == 409
        assert "đã tồn tại" in res.json()["detail"]
        # Không mất preset cũ khi rename bị chặn.
        assert sorted(p["name"] for p in client.get("/api/ui/sources").json()["presets"]) == ["khac", "old-name"]

    def test_ket_qua_test_di_theo_ten_moi(self, client, monkeypatch, tmp_path):
        from app import deps
        from app.routes.sources import _record_validation

        monkeypatch.setattr(deps, "WORKSPACE_DIR", tmp_path / ".n2e")
        _record_validation("old-name", True, "OK")

        client.post("/api/ui/sources", json={"name": "new-name", "rename_from": "old-name"})

        validation = client.get("/api/ui/sources").json()["validation"]
        assert validation["new-name"]["message"] == "OK"
        assert "old-name" not in validation
