"""AI biên tập GHI TRỰC TIẾP vào nhánh `local_mt` — không qua bản nháp.

Những gì bước này đảm bảo (xem `novel2epub/pipeline.step_ai_edit_local_mt`):
- Ghi thẳng kết quả AI vào nhánh `local_mt`, không tạo hàng `ai_revisions`.
- Snapshot MT được backfill từ bản dịch hiện tại TRƯỚC lần biên tập đầu tiên
  (giữ bản gốc dịch máy), snapshot có sẵn thì KHÔNG bị đè.
- AI không bao giờ thấy raw (engine rewrite `allows_raw=False`).
- CAS theo revision: lệch giữa chừng → `RevisionError`, không ghi đè mù.
- Meta `local_mt_ai_edited` ghi cùng transaction; `active_branch` không đổi.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub import glossary_ai, pipeline, revisions
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path, slug="t"):
    return Config(
        novel=NovelConfig(slug=slug, title="Truyện Thử"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, slug="t", local_mt="MT gốc", snapshot=""):
    """1 chương index=1 có bản dịch Local MT (snapshot tùy chọn)."""
    storage = Storage(tmp_path, slug)
    ch = Chapter(index=1, url="http://x/1", title="Chương 1")
    storage.save_manifest(Manifest(slug=slug, chapters=[ch]))
    storage.write_raw(ch, "原文 gốc không được lộ")
    storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, local_mt)
    if snapshot:
        storage.write_branch_mt_snapshot(ch, revisions.BRANCH_LOCAL_MT, snapshot)
    return storage, ch


def _rewrite(raw_capture=None):
    """Fake `rewrite_chapter`; ghi raw vào `raw_capture` nếu truyền vào."""
    seen = {"raw": None} if raw_capture is None else raw_capture

    def fake(ai_cfg, raw, current, glossary, **kw):
        seen["raw"] = raw
        return "bản AI đã biên tập"

    return fake, seen


def test_ai_edit_ghi_truc_tiep_khong_tao_ban_nhap(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, local_mt="MT gốc", snapshot="")
    fake, seen = _rewrite()
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", fake)
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    before_rev = storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT)

    out = pipeline.step_ai_edit_local_mt(_cfg(tmp_path), lambda m: None, index=1)

    assert out["applied"] is True
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản AI đã biên tập"
    assert storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT) == before_rev + 1
    # Snapshot backfill từ bản dịch hiện tại trước khi AI sửa.
    assert storage.read_branch_mt_snapshot(ch, revisions.BRANCH_LOCAL_MT) == "MT gốc"
    # Không tạo bản nháp — không có hàng ai_revisions.
    assert storage.list_ai_revisions(ch) == []
    # Meta ghi kèm: engine/model/generated_at/from_rev (from_rev = revision gốc).
    meta = storage.read_meta(ch)
    assert "before_rewrite" not in meta
    edited = meta["local_mt_ai_edited"]
    assert edited["from_rev"] == before_rev
    assert edited["generated_at"]
    assert "engine" in edited and "model" in edited
    # active_branch không bị đổi (mặc định `ai`).
    assert storage.active_branch(ch) == revisions.BRANCH_AI


def test_ai_edit_giu_snapshot_co_san(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, local_mt="MT hiện tại", snapshot="MT GỐC SNAPSHOT")
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản AI")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})

    pipeline.step_ai_edit_local_mt(_cfg(tmp_path), lambda m: None, index=1)

    assert storage.read_branch_mt_snapshot(ch, revisions.BRANCH_LOCAL_MT) == "MT GỐC SNAPSHOT"


def test_ai_edit_khong_lo_raw_vao_ai(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    seen: dict = {"raw": None}
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", _rewrite(seen)[0])
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})

    pipeline.step_ai_edit_local_mt(_cfg(tmp_path), lambda m: None, index=1)

    assert seen["raw"] == ""
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản AI đã biên tập"


def test_ai_edit_cas_loi_khong_ghi_de(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, local_mt="MT gốc")
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản AI khác")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    monkeypatch.setattr(
        Storage,
        "compare_and_swap_branch",
        lambda self, ch, branch, **kw: False,
    )
    before_rev = storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT)

    import pytest

    from novel2epub import revisions as rev

    with pytest.raises(rev.RevisionError, match="đổi đồng thời"):
        pipeline.step_ai_edit_local_mt(_cfg(tmp_path), lambda m: None, index=1)

    # Không ghi đè: nội dung + revision + meta giữ nguyên.
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "MT gốc"
    assert storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT) == before_rev
    assert storage.read_meta(ch).get("local_mt_ai_edited") is None


def test_ai_edit_ai_tra_rong_thi_giu_nguyen(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, local_mt="MT gốc")
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "   ")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    before_rev = storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT)

    out = pipeline.step_ai_edit_local_mt(_cfg(tmp_path), lambda m: None, index=1)

    assert out["applied"] is False
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "MT gốc"
    assert storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT) == before_rev
    assert storage.read_meta(ch).get("local_mt_ai_edited") is None


def test_ai_edit_chua_co_local_mt_thi_bao_loi(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "không nên chạy")

    import pytest

    with pytest.raises(RuntimeError, match="Local MT"):
        pipeline.step_ai_edit_local_mt(_cfg(tmp_path), lambda m: None, index=1)


def test_ai_edit_bulk_mot_loi_khong_chan_lo(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    chapters = [
        Chapter(index=1, url="http://x/1"),
        Chapter(index=2, url="http://x/2"),
    ]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, f"MT {ch.index}")

    def _flaky(ai_cfg, raw, current, glossary, **kw):
        if current == "MT 1":
            raise RuntimeError("model chết giữa chừng")
        return f"sửa {current}"

    monkeypatch.setattr(glossary_ai, "rewrite_chapter", _flaky)
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})

    applied = pipeline.step_ai_edit_local_mt_bulk(_cfg(tmp_path), lambda m: None, selected_indexes=[1, 2])

    assert applied == [2]
    assert storage.read_branch_text(chapters[0], revisions.BRANCH_LOCAL_MT) == "MT 1"
    assert storage.read_branch_text(chapters[1], revisions.BRANCH_LOCAL_MT) == "sửa MT 2"


# ── Compare API 4 nguồn ─────────────────────────────────────────────────


class _FakeQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, category, step, target, **kwargs):
        self.enqueued.append({"category": category, "step": step, **kwargs})
        return type("Job", (), {"id": f"job-{len(self.enqueued)}"})()


class _FakeJob:
    def __init__(self):
        self.queue = _FakeQueue()

    def status(self):
        return {}


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob()
    return TestClient(app)


def test_compare_api_bon_nguon(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="Chương 1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "dòng a\ndòng b")
    storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, "MT a\nMT b")
    storage.write_branch_mt_snapshot(ch, revisions.BRANCH_LOCAL_MT, "MT a\nMT b")
    storage.write_branch_text(ch, revisions.BRANCH_AI, "AI a\nAI b")
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    meta["local_mt_ai_edited"] = {
        "engine": "openai", "model": "gpt-x", "generated_at": "2026-01-01T00:00:00Z", "from_rev": 1,
    }
    storage.write_meta(ch, meta)

    client = _client(cfg, monkeypatch)
    res = client.get("/api/ui/ebooks/t/chapters/1")

    assert res.status_code == 200
    data = res.json()
    assert set(data["sources"].keys()) == {"raw", "local_mt", "ai", "ai_edit"}
    assert data["sources"]["raw"]["status"] == "ready"
    assert data["sources"]["raw"]["text"] == "dòng a\ndòng b"
    assert data["sources"]["local_mt"]["status"] == "ready"
    assert data["sources"]["ai"]["status"] == "ready"
    assert data["sources"]["ai_edit"]["status"] == "ready"
    assert data["sources"]["ai_edit"]["engine"] == "openai"
    assert data["sources"]["ai_edit"]["model"] == "gpt-x"
    assert data["sources"]["ai_edit"]["updated_at"] == "2026-01-01T00:00:00Z"
    # Hàng giữ 4 nguồn + 2 field legacy.
    row = data["paragraphs"][0]
    assert row["raw"] == "dòng a"
    assert row["local_mt"] == "MT a"
    assert row["ai"] == "AI a"
    assert row["ai_edit"] == "MT a"
    assert row["mt"] == "MT a"
    assert row["edited"] == "MT a"
    # Legacy field vẫn còn — `translated` là bản của nhánh ĐANG HOẠT ĐỘNG (ai).
    assert data["translated"] == "AI a\nAI b"
    assert data["translated_mt"] == "AI a\nAI b"


def test_compare_api_ai_edit_missing_khi_chua_bien_tap(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "nội dung")
    storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, "MT")
    storage.write_branch_mt_snapshot(ch, revisions.BRANCH_LOCAL_MT, "MT")

    client = _client(cfg, monkeypatch)
    data = client.get("/api/ui/ebooks/t/chapters/1").json()

    assert data["sources"]["ai_edit"]["status"] == "missing"
    assert data["sources"]["ai_edit"]["edited"] is None
