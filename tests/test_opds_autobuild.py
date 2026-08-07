"""Gọi catalog OPDS kích hoạt build NỀN — feed không bao giờ chờ build.

Bổ sung cho `test_epub_autobuild.py` (logic thuần): ở đây kiểm tra phần nối
dây HTTP — job có được đẩy đúng lúc không, và quan trọng hơn là feed có trả
về được trong mọi tình huống hỏng hóc không.
"""
from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient

from novel2epub.config import (
    ApiConfig,
    Config,
    CrawlConfig,
    LibraryConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


class _FakeQueue:
    def __init__(self, pending_build_slugs: list[str] | None = None):
        self._pending = [{"ebook": s} for s in (pending_build_slugs or [])]

    def snapshot(self) -> dict:
        return {"pending": {"build": list(self._pending), "crawl": [], "translate": []}}


class _FakeJob:
    """Thay JobRunner thật: ghi lại job được đẩy thay vì build EPUB thật."""

    def __init__(self, busy: set[tuple[str, str]] | None = None,
                 pending_build_slugs: list[str] | None = None):
        self.queue = _FakeQueue(pending_build_slugs)
        self._busy = busy or set()
        self.started: list[dict] = []

    def is_ebook_busy(self, category: str, ebook: str) -> bool:
        return (category, ebook) in self._busy

    def start_custom(self, step, target_fn, category, *, ebook="", spec=None, cancel_event=None):
        self.started.append({"step": step, "category": category, "ebook": ebook, "spec": spec})
        return True


def _cfg(tmp_path, slug: str, *, auto_build: bool = True) -> Config:
    return Config(
        novel=NovelConfig(slug=slug, title=f"Tên {slug}", author="Tác Giả"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path), epub_path=str(tmp_path / f"{slug}.epub")),
        api=ApiConfig(auto_build=auto_build),
    )


def _seed(tmp_path, slug: str, *, translated: bool, with_epub: bool, epub_newer_by: float = 5.0):
    storage = Storage(tmp_path, slug)
    ch = Chapter(index=1, url="http://x/1", title="C1")
    storage.save_manifest(Manifest(slug=slug, title=f"Tên {slug}", author="TG", chapters=[ch]))
    if translated:
        storage.write_translated(ch, "# Chương 1\n\nĐoạn một.")
    if with_epub:
        epub = tmp_path / f"{slug}.epub"
        epub.write_bytes(b"PK\x03\x04gia-lap-epub")
        # Test ghi cả hai thứ trong cùng một tích tắc, còn `translated_updated_at`
        # chỉ có độ phân giải 1 giây — không đẩy mtime ra xa thì mốc nới của
        # `epub_autobuild` (cố ý) kết luận STALE. Đẩy ra để dựng đúng tình
        # huống thật "build SAU khi dịch xong".
        ts = time.time() + epub_newer_by
        os.utime(epub, (ts, ts))
    return storage


def _client(monkeypatch, tmp_path, slugs, *, job, auto_build=True):
    from app import deps
    from app.main import app
    from app.routes import opds as opds_route

    # State cooldown sống ở module — không dọn thì test sau bị test trước khoá.
    opds_route._last_autobuild.clear()

    cfgs = {s: _cfg(tmp_path, s, auto_build=auto_build) for s in slugs}
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig(ebooks={s: object() for s in slugs}))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfgs[slug])
    monkeypatch.setattr(deps, "cfg", lambda: next(iter(cfgs.values())))
    monkeypatch.setattr(opds_route, "archived_slugs", lambda _p: set())
    monkeypatch.setattr(app.state, "job", job, raising=False)
    return TestClient(app, client=("127.0.0.1", 12345))


def test_sach_chua_build_thi_day_job_khi_goi_catalog(monkeypatch, tmp_path):
    _seed(tmp_path, "a", translated=True, with_epub=False)
    job = _FakeJob()
    r = _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert r.status_code == 200
    assert [j["ebook"] for j in job.started] == ["a"]
    assert job.started[0]["category"] == "build"
    assert job.started[0]["spec"] == {"kind": "opds-autobuild", "params": {"slug": "a"}}


def test_feed_tra_ve_ngay_khong_cho_build(monkeypatch, tmp_path):
    """Sách vừa được đẩy job chưa có file nên chưa lên feed lần này — nhưng
    request vẫn phải trả 200 tức thì thay vì treo chờ build."""
    _seed(tmp_path, "a", translated=True, with_epub=False)
    job = _FakeJob()
    r = _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert r.status_code == 200
    assert "<entry>" not in r.text
    assert job.started, "job phải được đẩy dù sách chưa lên feed"


def test_sach_da_build_va_khong_co_ban_dich_moi_thi_khong_day_job(monkeypatch, tmp_path):
    _seed(tmp_path, "a", translated=True, with_epub=True)
    job = _FakeJob()
    r = _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert r.status_code == 200
    assert job.started == []


def test_ban_dich_moi_hon_file_thi_day_job(monkeypatch, tmp_path):
    """EPUB đã build từ lâu, sau đó có chương được dịch/sửa → phải build lại."""
    _seed(tmp_path, "a", translated=True, with_epub=True, epub_newer_by=-3600.0)
    job = _FakeJob()
    _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert [j["ebook"] for j in job.started] == ["a"]


def test_chua_dich_chuong_nao_thi_khong_day_job(monkeypatch, tmp_path):
    _seed(tmp_path, "a", translated=False, with_epub=False)
    job = _FakeJob()
    _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert job.started == []


def test_tat_co_auto_build_thi_khong_day_job(monkeypatch, tmp_path):
    _seed(tmp_path, "a", translated=True, with_epub=False)
    job = _FakeJob()
    r = _client(monkeypatch, tmp_path, ["a"], job=job, auto_build=False).get("/opds/books")
    assert r.status_code == 200
    assert job.started == []


def test_dang_dich_do_thi_de_yen(monkeypatch, tmp_path):
    """Build giữa lúc job dịch đang chảy chỉ đóng gói một ảnh chụp cũ ngay."""
    _seed(tmp_path, "a", translated=True, with_epub=False)
    job = _FakeJob(busy={("translate", "a")})
    _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert job.started == []


def test_da_co_job_build_dang_cho_thi_khong_day_them(monkeypatch, tmp_path):
    """`is_ebook_busy` chỉ thấy job ĐANG CHẠY — phải soi cả hàng chờ, nếu
    không mỗi request lại chồng thêm một job cho cùng cuốn sách."""
    _seed(tmp_path, "a", translated=True, with_epub=False)
    job = _FakeJob(pending_build_slugs=["a"])
    _client(monkeypatch, tmp_path, ["a"], job=job).get("/opds/books")
    assert job.started == []


def test_goi_lai_trong_thoi_gian_nghi_thi_khong_day_job_thu_hai(monkeypatch, tmp_path):
    """readest hỏi lại catalog mỗi lần kéo-để-làm-mới."""
    _seed(tmp_path, "a", translated=True, with_epub=False)
    job = _FakeJob()
    client = _client(monkeypatch, tmp_path, ["a"], job=job)
    client.get("/opds/books")
    client.get("/opds/books")
    client.get("/opds")
    assert len(job.started) == 1


def test_loi_khi_tu_build_khong_lam_hong_feed(monkeypatch, tmp_path):
    """Feed phải sống sót mọi lỗi của việc tự build: chậm cập nhật thì chấp
    nhận được, mất luôn catalog thì không."""
    _seed(tmp_path, "a", translated=True, with_epub=True)
    from app.routes import opds as opds_route

    job = _FakeJob()
    client = _client(monkeypatch, tmp_path, ["a"], job=job)

    def _no(*_a, **_kw):
        raise RuntimeError("DB sập")

    monkeypatch.setattr(opds_route, "_build_states", _no)
    r = client.get("/opds/books")
    assert r.status_code == 200
    assert "Tên a" in r.text


def test_ebook_archive_khong_duoc_build(monkeypatch, tmp_path):
    _seed(tmp_path, "a", translated=True, with_epub=False)
    from app.routes import opds as opds_route

    job = _FakeJob()
    client = _client(monkeypatch, tmp_path, ["a"], job=job)
    monkeypatch.setattr(opds_route, "archived_slugs", lambda _p: {"a"})
    client.get("/opds/books")
    assert job.started == []
