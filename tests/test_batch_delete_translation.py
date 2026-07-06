"""Test route xóa hàng loạt bản dịch (POST /api/ebooks/{slug}/batch/delete-translation)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    # Test khác (vd. test_add_ebook_flow, test_ebook_management) ghi đè
    # app.state.job thành fake chỉ có status(). Lắp lại stub có start_custom.
    app.state.job = _FakeJob()
    return TestClient(app)


class _FakeJob:
    """Stub cho app.state.job — chỉ cần start_custom (sync, chạy target luôn)
    và status. Các test khác chỉ stub status() nên kế thừa để tránh phá vỡ."""

    def __init__(self):
        self.started = []

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }

    def start_custom(self, name, target, *, category):
        self.started.append({"name": name, "target": target, "category": category})
        target(lambda msg: None)  # chạy sync để file bị xoá ngay trong test
        return True


def _seed_two_chapters_with_translation(tmp_path):
    """Seed: 2 chương, cả 2 đều có translated + translated_mt + meta."""
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Bản dịch chương 1")
    storage.write_translated(chapters[1], "Bản dịch chương 2")
    storage.write_translated_mt(chapters[0], "MT 1")
    storage.write_translated_mt(chapters[1], "MT 2")
    storage.write_meta(chapters[0], {"complete": True})
    storage.write_meta(chapters[1], {"complete": True})
    return storage, chapters


def test_batch_delete_returns_started_and_total(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, chapters = _seed_two_chapters_with_translation(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/delete-translation", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data["started"] is True
    assert data["total"] == 2


def test_batch_delete_removes_translated_and_mt_and_meta(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed_two_chapters_with_translation(tmp_path)
    client = _client(cfg, monkeypatch)

    # Trước khi xoá: 3 loại file đều tồn tại
    for ch in chapters:
        assert storage.has_translated(ch)
        assert storage.has_translated_mt(ch)
        assert storage.has_meta(ch)

    res = client.post("/api/ebooks/t/batch/delete-translation", data={"indexes": "1,2"})
    assert res.status_code == 200

    # _FakeJob.start_custom chạy target sync → file bị xoá ngay trong request
    for ch in chapters:
        assert not storage.has_any_translation_data(ch), f"chương {ch.stem} còn dữ liệu dịch"
        assert not storage.has_translated(ch)
        assert not storage.has_translated_mt(ch)


def test_batch_delete_empty_indexes_returns_422(tmp_path, monkeypatch):
    """Empty/missing indexes: FastAPI's Form(...) rejects trước khi vào handler
    với 422. UI client-side đã chặn (alert + return) nên case này không xảy ra
    trong flow thật — test chỉ document contract giữa client/server."""
    cfg = _cfg(tmp_path)
    _storage, _chapters = _seed_two_chapters_with_translation(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/delete-translation", data={"indexes": ""})
    assert res.status_code == 422


def test_batch_delete_handles_missing_chapters_gracefully(tmp_path, monkeypatch):
    """Chapter không có file bản dịch vẫn được xử lý — không raise, chỉ skip."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    # Chỉ chương 1 có bản dịch; chương 2 không có gì.
    storage.write_translated(chapters[0], "Chỉ có chương 1")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/delete-translation", data={"indexes": "1,2"})
    assert res.status_code == 200
    assert res.json()["total"] == 2


def test_batch_delete_invalid_index_string_raises_valueerror(tmp_path, monkeypatch):
    """Index không phải số (vd. 'abc') làm int(...) ném ValueError — endpoint
    chưa validate format. Cùng pattern với `api_batch_translate_titles`.
    UI client-side chỉ gửi số nên case này không xảy ra trong flow thật.
    Test chỉ document: KHÔNG âm thầm nuốt lỗi — exception phải propagate."""
    cfg = _cfg(tmp_path)
    _storage, _chapters = _seed_two_chapters_with_translation(tmp_path)
    from app.main import app
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    # raise_server_exceptions=False để TestClient không re-raise mà trả 500.
    client = TestClient(app, raise_server_exceptions=False)

    res = client.post("/api/ebooks/t/batch/delete-translation", data={"indexes": "abc"})
    assert res.status_code == 500
