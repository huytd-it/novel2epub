"""Test vòng đời candidate trong pipeline: no-raw vào AI rewrite, candidate
không tự kích hoạt, optimistic lock khi chấp nhận, engine report không áp được.
"""
from __future__ import annotations

import pytest

from novel2epub import glossary_ai, pipeline, revisions
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
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, translated="bản dịch cũ"):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 gốc không được lộ")
    if translated is not None:
        storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, translated)
    return storage, ch


def _rewrite_prompt_raw_capture():
    seen = {"raw": None}

    def fake_rewrite(ai_cfg, raw, current, glossary, **kw):
        seen["raw"] = raw
        return "bản nháp đã biên tập"

    return fake_rewrite, seen


def test_rewrite_preview_khong_lo_vao_ai(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    fake, seen = _rewrite_prompt_raw_capture()
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", fake)
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})

    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)

    # KHÔNG đưa raw_text vào prompt AI của engine rewrite.
    assert seen["raw"] == ""
    # Candidate sinh ở trạng thái pending; bản dịch hoạt động giữ nguyên.
    cand = storage.read_ai_revision(ch, rid)
    assert cand.branch == revisions.BRANCH_LOCAL_MT
    assert cand.status == revisions.STATUS_PENDING
    assert cand.payload == "bản nháp đã biên tập"
    assert cand.has_raw is False
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản dịch cũ"
    # Back-compat: meta vẫn đọc được cho UI cũ, kèm revision_id.
    meta_rewrite = storage.read_meta(ch)["ai_rewrite"]
    assert meta_rewrite["text"] == "bản nháp đã biên tập"
    assert meta_rewrite["revision_id"] == rid


def test_chap_toi_khong_ap_dung_ban_nhap(tmp_path, monkeypatch):
    """Candidate không bao giờ tự active — bản dịch hoạt động chỉ đổi khi apply."""
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản nháp")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản dịch cũ"
    assert storage.read_ai_revision(ch, rid).status == revisions.STATUS_PENDING


def test_apply_revision_optimistic_lock(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản nháp A")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)
    before_rev = storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT)

    out = pipeline.step_apply_ai_revision(_cfg(tmp_path), lambda m: None, revision_id=rid)

    assert out == "bản nháp A"
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản nháp A"
    assert storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT) == before_rev + 1
    assert storage.read_ai_revision(ch, rid).status == revisions.STATUS_APPLIED
    # Bản trước rewrite được giữ để khôi phục.
    assert storage.read_meta(ch)["before_rewrite"] == "bản dịch cũ"
    assert "ai_rewrite" not in storage.read_meta(ch)


def test_apply_revision_stale_khi_ban_dich_doi(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản nháp")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)

    # Bản dịch nhánh local_mt bị sửa tay ngay sau khi tạo bản nháp → snapshot lệch.
    storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, "người khác sửa")
    with pytest.raises(revisions.RevisionError, match="thay đổi"):
        pipeline.step_apply_ai_revision(_cfg(tmp_path), lambda m: None, revision_id=rid)

    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "người khác sửa"
    assert storage.read_ai_revision(ch, rid).status == revisions.STATUS_PENDING


def test_apply_revision_het_han_bi_tu_choi(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản nháp")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)

    cand = storage.read_ai_revision(ch, rid)
    cand.expires_at = "2000-01-01T00:00:00.000000Z"
    with storage.conn:
        storage.conn.execute(
            "UPDATE ai_revisions SET expires_at=? WHERE id=?",
            (cand.expires_at, rid),
        )

    with pytest.raises(revisions.RevisionError, match="hết hạn"):
        pipeline.step_apply_ai_revision(_cfg(tmp_path), lambda m: None, revision_id=rid)
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản dịch cũ"
    assert storage.read_ai_revision(ch, rid).status == revisions.STATUS_EXPIRED


def test_apply_revision_report_engine_khong_ap_duoc(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    cand = revisions.create_revision(
        engine="review", idx=1, payload='{"score": 5}', base_rev=1,
        base_translated_text="bản dịch cũ", has_raw=True,
    )
    rid = storage.create_ai_revision(cand)
    with pytest.raises(revisions.RevisionError, match="không áp dụng"):
        pipeline.step_apply_ai_revision(_cfg(tmp_path), lambda m: None, revision_id=rid)


def test_discard_revision_khong_dong_den_ban_dich(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản nháp")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)

    assert pipeline.step_discard_ai_revision(_cfg(tmp_path), lambda m: None, revision_id=rid) is True
    assert storage.read_ai_revision(ch, rid).status == revisions.STATUS_DISCARDED
    assert storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) == "bản dịch cũ"
    assert "ai_rewrite" not in storage.read_meta(ch)


def test_bulk_rewrite_khong_lo_raw(tmp_path, monkeypatch):
    """Bulk rewrite (người dùng chạy explicit) cũng không đưa raw vào AI edit."""
    storage = Storage(tmp_path, "t")
    chapters = [
        Chapter(index=1, url="http://x/1"),
        Chapter(index=2, url="http://x/2"),
    ]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        storage.write_raw(ch, "原文 gốc")
        storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, f"bản dịch {ch.index}")
    seen = {"raws": []}
    monkeypatch.setattr(
        glossary_ai, "rewrite_chapter",
        lambda ai, raw, cur, gloss, **kw: (seen["raws"].append(raw), f"sửa {cur}")[1],
    )
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})

    pipeline.step_rewrite_chapters(_cfg(tmp_path), lambda m: None)

    assert seen["raws"] == ["", ""]
    # Batch legacy tạo draft pending, không ghi đè bản dịch nhánh.
    assert storage.read_branch_text(chapters[0], revisions.BRANCH_LOCAL_MT) == "bản dịch 1"
    drafts = [r for r in storage.list_ai_revisions(chapters[0]) if r["status"] == revisions.STATUS_PENDING]
    assert drafts and drafts[0]["payload_json"] == "sửa bản dịch 1"


def test_build_chi_dung_workspace_hoat_dong_khong_lo_candidate(tmp_path, monkeypatch):
    """EPUB (active workspace) không bao giờ chứa bản nháp candidate chưa áp."""
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "BẢN NHÁP CHƯA ÁP")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda *a, **kw: {})
    rid = pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)
    assert rid > 0

    epub_path = tmp_path / "t.epub"
    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path), epub_path=str(epub_path)),
    )
    pipeline.step_build_selected(cfg, lambda m: None)

    def _epub_text(path) -> str:
        import zipfile
        with zipfile.ZipFile(path) as zf:
            parts = [
                zf.read(name).decode("utf-8", errors="ignore")
                for name in zf.namelist()
                if name.endswith(".xhtml")
            ]
        return "\n".join(parts)

    epub_text = _epub_text(epub_path)
    # Bản nháp KHÔNG lọt vào EPUB; bản dịch hoạt động (Local MT) thì có.
    assert "BẢN NHÁP CHƯA ÁP" not in epub_text
    assert "bản dịch cũ" in epub_text

    # Sau khi CHẤP NHẬN bản nháp thì nó trở thành bản hoạt động → vào EPUB.
    pipeline.step_apply_ai_revision(cfg, lambda m: None, revision_id=rid)
    pipeline.step_build_selected(cfg, lambda m: None)
    assert "BẢN NHÁP CHƯA ÁP" in _epub_text(epub_path)