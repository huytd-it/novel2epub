"""Test đẩy chương lên app đọc novel-reader (route + pipeline step).

Supabase được giả lập ở tầng `requests.request` của `reader_client` nên toàn
bộ payload thật đi qua được soi — chỗ đáng giá nhất là kiểm chứng lô SỬA
không gửi `is_free` và `chapters.id` không bị sinh lại.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import deps
from novel2epub import reader_client
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    ReaderConfig,
    TranslateConfig,
)
from novel2epub.pipeline import step_publish_reader
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path, **reader_kwargs):
    reader = ReaderConfig(
        url="https://demo.supabase.co",
        service_key="service-role-key",
        slug="truyen-test",
        free_chapters=2,
        batch_size=50,
    )
    for k, v in reader_kwargs.items():
        setattr(reader, k, v)
    return Config(
        novel=NovelConfig(slug="t", title="Truyện Test", author="Ai Đó"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
        reader=reader,
    )


def _seed(tmp_path, chapters: list[tuple[int, str, str]]):
    """`chapters`: list `(index, title, translated_markdown)`. Text rỗng = chưa dịch."""
    storage = Storage(tmp_path, "t")
    objs = [Chapter(index=i, url=f"http://x/{i}", title=title) for i, title, _ in chapters]
    storage.save_manifest(Manifest(slug="t", chapters=objs))
    for ch, (_, _, md) in zip(objs, chapters):
        if md:
            storage.write_translated(ch, md)
            storage.mark_translated_complete(ch)
    return storage, objs


class FakeSupabase:
    """Ghi lại mọi request và trả response giống PostgREST."""

    def __init__(self, *, book=None, remote_chapters=None):
        self.calls: list[dict] = []
        self.book = book  # None = sách chưa tồn tại
        self.remote_chapters = dict(remote_chapters or {})  # index -> id
        self._next_id = 100

    def _new_id(self) -> str:
        self._next_id += 1
        return f"uuid-{self._next_id}"

    def __call__(self, method, url, *, headers=None, params=None, json=None, timeout=None):
        table = url.rsplit("/", 1)[-1]
        self.calls.append({
            "method": method, "table": table, "params": params or {},
            "json": json, "prefer": (headers or {}).get("Prefer", ""),
        })
        if table == "books" and method == "GET":
            return _Resp(200, [self.book] if self.book else [])
        if table == "books" and method == "POST":
            self.book = {"id": "book-1", "is_published": json[0].get("is_published"), "chapter_count": 0}
            return _Resp(201, [self.book])
        if table == "books" and method == "PATCH":
            return _Resp(204, None)
        if table == "chapters" and method == "GET":
            return _Resp(200, [{"index": i, "id": cid} for i, cid in self.remote_chapters.items()])
        if table == "chapters" and method == "POST":
            rows = []
            for item in json:
                idx = item["index"]
                cid = self.remote_chapters.get(idx) or self._new_id()
                self.remote_chapters[idx] = cid
                rows.append({"index": idx, "id": cid})
            return _Resp(201, rows)
        if table == "chapter_contents" and method == "POST":
            return _Resp(201, None)
        raise AssertionError(f"request không mong đợi: {method} {url}")

    def chapter_upserts(self) -> list[dict]:
        return [c for c in self.calls if c["table"] == "chapters" and c["method"] == "POST"]

    def content_upserts(self) -> list[dict]:
        return [c for c in self.calls if c["table"] == "chapter_contents"]


class _Resp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.content = b"" if payload is None else json.dumps(payload).encode()
        self.text = self.content.decode()

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _install(monkeypatch, fake):
    monkeypatch.setattr(reader_client.requests, "request", fake)


# ──────────────────────────── step_publish_reader ───────────────────────────


def test_day_lan_dau_tao_sach_va_them_moi_toan_bo(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, [(1, "Chương 1", "Nội dung một."), (2, "Chương 2", "Nội dung hai.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    counts = step_publish_reader(cfg, lambda _m: None)

    assert counts == {"new": 2, "edited": 0, "unchanged": 0, "skipped": 0}
    created = [c for c in fake.calls if c["table"] == "books" and c["method"] == "POST"]
    assert created and created[0]["json"][0]["slug"] == "truyen-test"
    upserts = fake.chapter_upserts()
    assert len(upserts) == 1
    assert upserts[0]["params"]["on_conflict"] == "book_id,index"
    assert "resolution=merge-duplicates" in upserts[0]["prefer"]


def test_chuong_moi_duoc_set_is_free_theo_cau_hinh(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, free_chapters=2)
    _seed(tmp_path, [(1, "C1", "A."), (2, "C2", "B."), (3, "C3", "C.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    step_publish_reader(cfg, lambda _m: None)

    rows = fake.chapter_upserts()[0]["json"]
    assert {r["index"]: r["is_free"] for r in rows} == {1: True, 2: True, 3: False}


def test_lan_day_thu_hai_khong_sua_gi_thi_khong_gui_request_ghi(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, [(1, "C1", "A."), (2, "C2", "B.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)
    step_publish_reader(cfg, lambda _m: None)

    fake.calls.clear()
    counts = step_publish_reader(cfg, lambda _m: None)

    assert counts == {"new": 0, "edited": 0, "unchanged": 2, "skipped": 0}
    assert fake.chapter_upserts() == []
    assert fake.content_upserts() == []


def test_lo_sua_khong_gui_is_free_de_khong_dap_chinh_tay_ben_reader(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, objs = _seed(tmp_path, [(1, "C1", "A."), (2, "C2", "B.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)
    step_publish_reader(cfg, lambda _m: None)

    storage.write_translated(objs[0], "A đã sửa.")
    storage.mark_translated_complete(objs[0])
    fake.calls.clear()
    counts = step_publish_reader(cfg, lambda _m: None)

    assert counts == {"new": 0, "edited": 1, "unchanged": 1, "skipped": 0}
    upserts = fake.chapter_upserts()
    assert len(upserts) == 1
    rows = upserts[0]["json"]
    assert [r["index"] for r in rows] == [1]
    assert "is_free" not in rows[0]


def test_chapter_id_giu_nguyen_qua_cac_lan_day(tmp_path, monkeypatch):
    """Hồi quy chính mà tính năng này sửa: admin-import/ingest-epub.ts xoá sạch
    chapters rồi insert lại nên id đổi, làm hỏng bookmark/tiến độ đọc."""
    cfg = _cfg(tmp_path)
    storage, objs = _seed(tmp_path, [(1, "C1", "A."), (2, "C2", "B.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)
    step_publish_reader(cfg, lambda _m: None)
    ids_lan_1 = dict(fake.remote_chapters)

    storage.write_translated(objs[1], "B đã sửa.")
    storage.mark_translated_complete(objs[1])
    step_publish_reader(cfg, lambda _m: None)

    assert fake.remote_chapters == ids_lan_1
    assert not any(c["method"] == "DELETE" for c in fake.calls)


def test_noi_dung_day_len_la_plain_text_khong_con_markdown(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, [(1, "Chương 1", "# Chương 1: Khởi đầu\n\nĐoạn một.\n\nĐoạn hai.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    step_publish_reader(cfg, lambda _m: None)

    payload = fake.content_upserts()[0]["json"]
    assert payload[0]["content"] == "Đoạn một.\n\nĐoạn hai."
    assert payload[0]["chapter_id"] == fake.remote_chapters[1]


def test_bo_qua_chuong_chua_dich_va_chuong_skip(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, objs = _seed(tmp_path, [(1, "C1", "A."), (2, "C2", ""), (3, "C3", "C.")])
    objs[2].skipped = True
    storage.save_chapter(objs[2])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    counts = step_publish_reader(cfg, lambda _m: None)

    assert counts == {"new": 1, "edited": 0, "unchanged": 0, "skipped": 2}
    assert [r["index"] for r in fake.chapter_upserts()[0]["json"]] == [1]


def test_ban_dich_do_dang_khong_bi_day_len(tmp_path, monkeypatch):
    """`has_translated` chặn meta['complete'] is False — job dịch đang chạy
    song song không làm rò bản nửa vời lên Reader."""
    cfg = _cfg(tmp_path)
    storage, objs = _seed(tmp_path, [(1, "C1", "A.")])
    storage.write_meta(objs[0], {"complete": False})
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    counts = step_publish_reader(cfg, lambda _m: None)

    assert counts == {"new": 0, "edited": 0, "unchanged": 0, "skipped": 1}
    assert fake.chapter_upserts() == []


def test_day_lai_khi_reader_bi_xoa_sach_chapters(tmp_path, monkeypatch):
    """Ai đó chạy lại `npm run ingest` (xoá sạch + insert lại) -> state local
    nói 'đã đẩy' nhưng id remote khác hẳn. Lần đẩy sau phải tự chữa."""
    cfg = _cfg(tmp_path)
    _seed(tmp_path, [(1, "C1", "A.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)
    step_publish_reader(cfg, lambda _m: None)

    fake.remote_chapters.clear()  # Reader bị nuke
    fake.calls.clear()
    counts = step_publish_reader(cfg, lambda _m: None)

    assert counts == {"new": 1, "edited": 0, "unchanged": 0, "skipped": 0}


def test_is_published_chi_set_luc_tao_sach_moi(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, published=True)
    _seed(tmp_path, [(1, "C1", "A.")])
    fake = FakeSupabase(book={"id": "book-1", "is_published": False, "chapter_count": 1})
    _install(monkeypatch, fake)

    step_publish_reader(cfg, lambda _m: None)

    patches = [c for c in fake.calls if c["table"] == "books" and c["method"] == "PATCH"]
    assert patches, "phải cập nhật metadata sách đã tồn tại"
    assert all("is_published" not in c["json"] for c in patches)


def test_chua_cau_hinh_thi_bao_loi_ro_rang(tmp_path):
    cfg = _cfg(tmp_path, url="", service_key="")
    _seed(tmp_path, [(1, "C1", "A.")])
    try:
        step_publish_reader(cfg, lambda _m: None)
    except RuntimeError as e:
        assert "Chưa cấu hình Reader" in str(e)
    else:
        raise AssertionError("phải raise RuntimeError khi chưa cấu hình")


def test_service_key_khong_bao_gio_lot_vao_log(tmp_path, monkeypatch):
    """Log job hiện công khai ở /queue và /logs."""
    cfg = _cfg(tmp_path)
    _seed(tmp_path, [(1, "C1", "A.")])
    _install(monkeypatch, FakeSupabase(book=None))
    lines: list[str] = []

    step_publish_reader(cfg, lines.append)

    assert lines, "step phải có log"
    assert not any("service-role-key" in ln for ln in lines)


def test_dry_run_khong_ghi_gi_ca_remote_lan_local(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, objs = _seed(tmp_path, [(1, "C1", "A.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    counts = step_publish_reader(cfg, lambda _m: None, dry_run=True)

    assert counts == {"new": 1, "edited": 0, "unchanged": 0, "skipped": 0}
    assert all(c["method"] == "GET" for c in fake.calls), "xem trước chỉ được đọc"
    assert "reader" not in storage.read_meta(objs[0])


def test_batch_size_chia_lo_va_ghi_state_sau_moi_lo(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, batch_size=2)
    storage, objs = _seed(tmp_path, [(i, f"C{i}", f"Nội dung {i}.") for i in range(1, 6)])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)

    step_publish_reader(cfg, lambda _m: None)

    assert len(fake.chapter_upserts()) == 3  # 2 + 2 + 1
    for ch in objs:
        assert storage.read_meta(ch)["reader"]["remote_id"]


# ──────────────────────────────── routes ────────────────────────────────────


def _patch_deps(monkeypatch, cfg):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)


def test_preview_tra_so_lieu_va_khong_ghi_gi(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, [(1, "C1", "A."), (2, "C2", "B.")])
    fake = FakeSupabase(book=None)
    _install(monkeypatch, fake)
    _patch_deps(monkeypatch, cfg)
    from app.main import app

    res = TestClient(app).get("/api/ebooks/t/publish/preview")

    assert res.status_code == 200
    assert res.json() == {"new": 2, "edited": 0, "unchanged": 0, "skipped": 0}
    assert all(c["method"] == "GET" for c in fake.calls)


def test_preview_bao_400_khi_chua_cau_hinh(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, url="", service_key="")
    _seed(tmp_path, [(1, "C1", "A.")])
    _patch_deps(monkeypatch, cfg)
    from app.main import app

    res = TestClient(app).get("/api/ebooks/t/publish/preview")

    assert res.status_code == 400
    assert "Chưa cấu hình Reader" in res.json()["detail"]


def test_push_bao_400_khi_chua_cau_hinh(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, url="", service_key="")
    _seed(tmp_path, [(1, "C1", "A.")])
    _patch_deps(monkeypatch, cfg)
    from app.main import app

    res = TestClient(app).post("/api/ebooks/t/publish/push")

    assert res.status_code == 400
