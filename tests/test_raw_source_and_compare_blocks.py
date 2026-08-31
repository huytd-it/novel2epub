"""Tests cho tính năng nguồn Bản dịch/Gốc trong tìm-thay và sửa/xóa KHỐI trong
khung đối chiếu 3 cột.

Phủ:
- `/search?source=raw` gồm cả chương chưa dịch, default = translated.
- `/find-preview?source=raw` chia theo KHỐI, raw apply backup + stale.
- `/compare/block` edit_raw / edit_translated / delete (đồng bộ raw+MT+active),
  stale/conflict không ghi đè.
- Pure helpers trong `novel2epub/blocks.py`.
"""
from __future__ import annotations

import json

import pytest
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
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    return TestClient(app)


def _seed(tmp_path):
    """Chương 1 có raw + dịch, chương 2 CHỈ có raw (chưa dịch)."""
    storage = Storage(tmp_path, "t")
    chapters = [
        Chapter(index=1, url="http://x/1", title="Chương 1"),
        Chapter(index=2, url="http://x/2", title="Chương 2"),
    ]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "Trương Tam đi chợ.\n\nTrương Tam về nhà.")
    storage.write_translated(chapters[0], "Trương Tam đi chợ.\n\nTrương Tam về nhà.")
    storage.write_translated_mt(chapters[0], "Trương Tam đi chợ.\n\nTrương Tam về nhà.")
    storage.write_raw(chapters[1], "Trương Tam ngủ.\n\nChưa dịch.")
    return storage, chapters


# ── blocks.py: pure helpers ────────────────────────────────────────────────

def test_split_blocks_canonical_shared_with_compare():
    """`app.chapter_compare.split_blocks` re-export đúng `novel2epub.blocks`
    — nếu hai nơi chia khác nhau thì chỉ số KHỐI trong khung đối chiếu lệch
    khỏi chỉ số mà find-preview raw / compare-block dùng (sai âm thầm)."""
    from novel2epub.blocks import split_blocks as canonical

    from app.chapter_compare import split_blocks as compare
    text = "Hắn nói:\n— Đi thôi.\n\nĐoạn sau.\n\n\nĐoạn nữa"
    assert compare(text) == canonical(text) == ["Hắn nói: — Đi thôi.", "Đoạn sau.", "Đoạn nữa"]


def test_blocks_split_and_edit():
    from novel2epub.blocks import edit_block, replace_block, split_blocks

    text = "Hắn nói:\n— Đi thôi.\n\nĐoạn sau."
    assert split_blocks(text) == ["Hắn nói: — Đi thôi.", "Đoạn sau."]

    new, reason = edit_block(text, 0, "Đã sửa")
    assert reason == ""
    assert new == "Đã sửa\n\nĐoạn sau."

    new, reason = replace_block(text, 1, "Đoạn sau.", "Đoạn mới")
    assert reason == ""
    assert new == "Hắn nói:\n— Đi thôi.\n\nĐoạn mới"


def test_blocks_replace_block_stale_text_rejected():
    from novel2epub.blocks import replace_block

    new, reason = replace_block("A\n\nB", 0, "KHÔNG KHỚP", "X")
    assert new is None
    assert "tải lại trang" in reason


def test_blocks_delete_block_removes_separator():
    from novel2epub.blocks import delete_block, split_blocks

    text = "Khối một\n\nKhối hai\n\nKhối ba"
    assert split_blocks(text) == ["Khối một", "Khối hai", "Khối ba"]

    new, reason = delete_block(text, 1, "Khối hai")
    assert reason == ""
    assert split_blocks(new) == ["Khối một", "Khối ba"]
    assert new.count("\n\n") == 1  # chỉ còn một dòng trống ngăn cách


def test_blocks_delete_last_block():
    from novel2epub.blocks import delete_block, split_blocks

    text = "Một\n\nHai\n\nBa"
    new, reason = delete_block(text, 2, "Ba")
    assert reason == ""
    assert split_blocks(new) == ["Một", "Hai"]


def test_blocks_delete_keeps_inner_newlines():
    from novel2epub.blocks import delete_block

    text = "Lời dẫn:\n— Thoại.\n\nKhối hai"
    new, reason = delete_block(text, 0, "Lời dẫn: — Thoại.")
    assert reason == ""
    # Khối còn lại giữ nguyên dấu xuống dòng nội bộ của nó.
    assert new == "Khối hai"


def test_blocks_split_paragraphs_matches_split_paras():
    """Đoạn = TỪNG DÒNG không rỗng, trùng `notes.split_paras` của chế độ Đọc."""
    from novel2epub.blocks import split_paragraphs
    from novel2epub.notes import split_paras

    text = "Hắn nói:\n— Đi thôi.\n\nĐoạn sau."
    assert split_paragraphs(text) == split_paras(text) == [
        "Hắn nói:",
        "— Đi thôi.",
        "Đoạn sau.",
    ]
    assert split_paragraphs("\n\n  \n") == []
    assert split_paragraphs("") == []


def test_blocks_replace_paragraph_by_line():
    from novel2epub.blocks import replace_paragraph, split_paragraphs

    text = "Lời dẫn:\n— Thoại.\n\nĐoạn sau."
    # Chỉ sửa dòng thứ 0, dòng "— Thoại." giữ nguyên.
    new, reason = replace_paragraph(text, 0, "Lời dẫn:", "Lời dẫn đã sửa:")
    assert reason == ""
    assert split_paragraphs(new) == ["Lời dẫn đã sửa:", "— Thoại.", "Đoạn sau."]

    # new_text rỗng = xóa đoạn.
    new, reason = replace_paragraph(text, 1, "— Thoại.", "")
    assert reason == ""
    assert split_paragraphs(new) == ["Lời dẫn:", "Đoạn sau."]


def test_blocks_replace_paragraph_stale_expected_409():
    from novel2epub.blocks import replace_paragraph

    new, reason = replace_paragraph("A\n\nB", 0, "KHÔNG KHỚP", "X")
    assert new is None
    assert "tải lại trang" in reason


def test_blocks_delete_paragraph_by_line():
    from novel2epub.blocks import delete_paragraph, split_paragraphs

    text = "Hắn nói:\n— Đi thôi.\n\nĐoạn sau."
    # Xóa dòng "— Đi thôi." — dòng "Hắn nói:" và "Đoạn sau." còn nguyên.
    new, reason = delete_paragraph(text, 1, "— Đi thôi.")
    assert reason == ""
    assert split_paragraphs(new) == ["Hắn nói:", "Đoạn sau."]
    assert "— Đi thôi." not in new


# ── /search?source=raw ─────────────────────────────────────────────────────

def test_search_raw_includes_untranslated_chapters(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get("/api/ebooks/t/search", params={"q": "Trương Tam", "source": "raw"})
    assert res.status_code == 200
    data = res.json()
    # Cả chương 1 (2 chỗ) lẫn chương 2 chưa dịch (1 chỗ).
    assert [(r["chapter_index"], r["count"]) for r in data] == [(1, 2), (2, 1)]


def test_search_default_is_translated_skips_untranslated(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get("/api/ebooks/t/search", params={"q": "Trương Tam"})
    assert res.status_code == 200
    data = res.json()
    # Chương 2 chưa dịch → không lọt vào.
    assert [(r["chapter_index"], r["count"]) for r in data] == [(1, 2)]


def test_search_raw_rejects_bad_source(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    res = client.get("/api/ebooks/t/search", params={"q": "x", "source": "nope"})
    assert res.status_code == 400


def test_search_only_reports_matches_that_preview_can_apply(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_translated(ch, "Đoạn một.\n\nĐoạn hai.")
    client = _client(_cfg(tmp_path), monkeypatch)

    # Regex này chỉ khớp khi chạy xuyên ranh giới hai đoạn. Cả `/search` lẫn
    # `/find-preview?regex` đều áp pattern lên TOÀN BỘ text (không chia đoạn
    # trước), nên cả hai đều khớp xuyên ranh giới — preview gói mỗi match vào
    # 1 item với `para_index` âm (danh sách match, không phải chỉ số đoạn).
    search = client.get(
        "/api/ebooks/t/search",
        params={"q": r"một\.\s+Đoạn", "regex": "true"},
    )
    preview = client.get(
        "/api/ebooks/t/glossary/find-preview",
        params={
            "find": r"một\.\s+Đoạn",
            "regex": "true",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )

    assert search.status_code == 200
    assert [r["chapter_index"] for r in search.json()] == [1]
    assert preview.status_code == 200
    items = preview.json()["items"]
    assert len(items) == 1
    assert items[0]["chapter_index"] == 1
    assert items[0]["before"] == "một.\n\nĐoạn"
    assert items[0]["para_index"] < 0  # regex fulltext: không phải chỉ số đoạn


# ── /find-preview?source=raw + apply ───────────────────────────────────────

def test_find_preview_raw_splits_by_block(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get(
        "/api/ebooks/t/glossary/find-preview",
        params={"find": "Trương Tam", "source": "raw", "scope": "all"},
    )
    assert res.status_code == 200
    items = res.json()["items"]
    # Chương 2 chưa dịch vẫn được quét (raw).
    assert [i["chapter_index"] for i in items] == [1, 1, 2]
    assert items[0]["before"] == "Trương Tam đi chợ."


def test_apply_selected_raw_writes_backup_and_meta(tmp_path, monkeypatch):
    storage, chapters = _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/apply-selected",
        data={
            "find": "Trương Tam",
            "replace": "Trần Tam",
            "regex": "false",
            "source": "raw",
            "selections": json.dumps([
                {"chapter_index": 1, "para_index": 0, "expected": "Trương Tam đi chợ."},
                {"chapter_index": 2, "para_index": 0, "expected": "Trương Tam ngủ."},
            ]),
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["replaced"] == 2
    assert res.json()["chapters"] == 2
    # Raw đổi, bản dịch KHÔNG đổi (raw replace chỉ sửa raw).
    assert storage.read_raw(chapters[0]) == "Trần Tam đi chợ.\n\nTrương Tam về nhà."
    assert storage.read_translated(chapters[0]) == "Trương Tam đi chợ.\n\nTrương Tam về nhà."
    assert storage.read_raw(chapters[1]) == "Trần Tam ngủ.\n\nChưa dịch."
    # Backup raw dùng key riêng.
    assert storage.read_meta(chapters[0])["before_find_replace_raw"] == "Trương Tam đi chợ.\n\nTrương Tam về nhà."
    assert storage.read_meta(chapters[1])["before_find_replace_raw"] == "Trương Tam ngủ.\n\nChưa dịch."


def test_apply_selected_raw_stale_skips_changed_block(tmp_path, monkeypatch):
    storage, chapters = _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/apply-selected",
        data={
            "find": "Trương Tam",
            "replace": "Trần Tam",
            "regex": "false",
            "source": "raw",
            "selections": json.dumps([
                {"chapter_index": 1, "para_index": 0, "expected": "ĐÃ BỊ ĐỔI"},  # stale
                {"chapter_index": 1, "para_index": 1, "expected": "Trương Tam về nhà."},
            ]),
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["replaced"] == 1
    assert body["stale"] == 1
    # Chỉ khối không stale bị thay.
    assert storage.read_raw(chapters[0]) == "Trương Tam đi chợ.\n\nTrần Tam về nhà."


def test_apply_selected_raw_delete_block_with_empty_replacement(tmp_path, monkeypatch):
    storage, chapters = _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/apply-selected",
        data={
            "find": "Trương Tam đi chợ.",
            "replace": "",
            "regex": "false",
            "source": "raw",
            "selections": json.dumps([
                {"chapter_index": 1, "para_index": 0, "expected": "Trương Tam đi chợ."},
            ]),
        },
    )

    assert res.status_code == 200, res.text
    assert res.json()["replaced"] == 1
    # Khối bị xóa hẳn (khớp toàn bộ khối, thay bằng rỗng).
    assert storage.read_raw(chapters[0]) == "Trương Tam về nhà."


def test_apply_selected_raw_multi_block_descending_indices(tmp_path, monkeypatch):
    """Ba khối cùng chương, xóa khối 2 và khối 0 — xử lý giảm dần nên chỉ số
    khối 0 sau khi xóa khối 2 vẫn đúng."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "Khối một.\n\nKhối hai.\n\nKhối ba.")
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/apply-selected",
        data={
            "find": "Khối ba.",
            "replace": "",
            "regex": "false",
            "source": "raw",
            "selections": json.dumps([
                {"chapter_index": 1, "para_index": 2, "expected": "Khối ba."},
            ]),
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["replaced"] == 1
    # Xóa khối 2 trước — khối 0/1 vẫn nguyên.
    assert storage.read_raw(ch) == "Khối một.\n\nKhối hai."

    # Giờ xóa khối 0 (chỉ số cũ) — descending xử lý đúng.
    res = client.post(
        "/api/ebooks/t/glossary/apply-selected",
        data={
            "find": "Khối một.",
            "replace": "",
            "regex": "false",
            "source": "raw",
            "selections": json.dumps([
                {"chapter_index": 1, "para_index": 0, "expected": "Khối một."},
            ]),
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["replaced"] == 1
    assert storage.read_raw(ch) == "Khối hai."
    assert storage.read_meta(ch)["before_find_replace_raw"] == "Khối một.\n\nKhối hai."


# ── /compare/block: edit raw ───────────────────────────────────────────────

def _block_client(tmp_path):
    """Chương 1 có raw + MT + translated active (ai)."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 một.\n\n原文 hai.")
    storage.write_translated(ch, "Bản dịch một.\n\nBản dịch hai.")
    storage.write_translated_mt(ch, "MT một.\n\nMT hai.")
    return storage, ch


def _post(client, slug, index, payload):
    return client.post(f"/api/ui/ebooks/{slug}/chapters/{index}/compare/block", json=payload)


def test_compare_edit_raw_only_touches_raw(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "ai")

    res = _post(client, "t", 1, {
        "op": "edit_raw",
        "block": 0,
        "raw_expected": "原文 một.",
        "new_text": "原文 mới.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    assert storage.read_raw(ch) == "原文 mới.\n\n原文 hai."
    # MT và bản dịch giữ nguyên.
    assert storage.read_translated_mt(ch) == "MT một.\n\nMT hai."
    assert storage.read_translated(ch) == "Bản dịch một.\n\nBản dịch hai."


def test_compare_edit_raw_stale_409(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = _post(client, "t", 1, {
        "op": "edit_raw",
        "block": 0,
        "raw_expected": "KHÔNG KHỚP",
        "new_text": "原文 mới.",
        "revision": storage.read_branch_revision(ch, "ai"),
    })

    assert res.status_code == 409
    assert storage.read_raw(ch) == "原文 một.\n\n原文 hai."


def test_compare_edit_translated_only_touches_active_branch(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    storage.write_branch_text(ch, "local_mt", "MT cục bộ.\n\nMT cục bộ hai.")
    storage.mark_branch_complete(ch, "local_mt")
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "ai")

    res = _post(client, "t", 1, {
        "op": "edit_translated",
        "block": 0,
        "block_expected": "Bản dịch một.",
        "new_text": "Bản dịch mới.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    assert storage.read_translated(ch) == "Bản dịch mới.\n\nBản dịch hai."
    assert storage.read_branch_revision(ch, "ai") == revision + 1
    # MT snapshot giữ nguyên.
    assert storage.read_translated_mt(ch) == "MT một.\n\nMT hai."
    # Nhánh local_mt không bị đụng.
    assert storage.read_branch_text(ch, "local_mt") == "MT cục bộ.\n\nMT cục bộ hai."


def test_compare_edit_translated_stale_revision_409(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    storage.write_translated(ch, "người khác sửa.\n\nBản dịch hai.")

    res = _post(client, "t", 1, {
        "op": "edit_translated",
        "block": 0,
        "block_expected": "Bản dịch một.",
        "new_text": "Bản dịch mới.",
        "revision": storage.read_branch_revision(ch, "ai") - 1,
    })

    assert res.status_code == 409
    assert storage.read_translated(ch) == "người khác sửa.\n\nBản dịch hai."


def test_compare_edit_translated_active_local_mt_branch(tmp_path, monkeypatch):
    """Nhánh active = local_mt — edit_translated phải sửa nhánh local_mt."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 một.\n\n原文 hai.")
    storage.write_branch_text(ch, "local_mt", "Cục bộ một.\n\nCục bộ hai.")
    storage.write_branch_mt_snapshot(ch, "local_mt", "MT cục bộ một.\n\nMT cục bộ hai.")
    storage.mark_branch_complete(ch, "local_mt")
    storage.set_active_branch(ch, "local_mt")
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "local_mt")

    res = _post(client, "t", 1, {
        "op": "edit_translated",
        "block": 0,
        "block_expected": "Cục bộ một.",
        "new_text": "Cục bộ mới.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    assert storage.read_branch_text(ch, "local_mt") == "Cục bộ mới.\n\nCục bộ hai."
    assert storage.read_branch_revision(ch, "local_mt") == revision + 1
    # Snapshot MT của nhánh giữ nguyên.
    assert storage.read_branch_mt_snapshot(ch, "local_mt") == "MT cục bộ một.\n\nMT cục bộ hai."
    # Nhánh ai không bị đụng.
    assert storage.read_branch_text(ch, "ai") == ""


def test_compare_edit_translated_finds_unique_paragraph_after_column_drift(tmp_path, monkeypatch):
    """Sau khi xóa một đoạn Local MT, index hàng vẫn theo cột raw; khóa nội
    dung duy nhất phải giúp sửa/xóa đúng đoạn thay vì báo stale giả."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 một.\n\n原文 rác.\n\n原文 hai.")
    storage.write_branch_text(ch, "local_mt", "Cục bộ một.\n\nCập nhật không dễ, nhớ chia sẻ mạng")
    storage.mark_branch_complete(ch, "local_mt")
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "local_mt")

    res = _post(client, "t", 1, {
        "op": "edit_translated",
        "branch": "local_mt",
        "block": 2,
        "block_expected": "Cập nhật không dễ, nhớ chia sẻ mạng",
        "new_text": "",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    assert storage.read_branch_text(ch, "local_mt") == "Cục bộ một.\n"
    assert storage.read_branch_revision(ch, "local_mt") == revision + 1


def test_compare_delete_active_local_mt_removes_its_branch_only(tmp_path, monkeypatch):
    """Xóa khối khi active = local_mt: xóa raw + snapshot MT local_mt + bản
    local_mt; nhánh ai giữ nguyên."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 một.\n\n原文 hai.")
    storage.write_translated(ch, "AI một.\n\nAI hai.")
    storage.write_branch_text(ch, "local_mt", "Cục bộ một.\n\nCục bộ hai.")
    storage.write_branch_mt_snapshot(ch, "local_mt", "MT cục bộ một.\n\nMT cục bộ hai.")
    storage.mark_branch_complete(ch, "local_mt")
    storage.set_active_branch(ch, "local_mt")
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "local_mt")

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 0,
        "raw_expected": "原文 một.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    assert storage.read_raw(ch) == "原文 hai."
    assert storage.read_branch_text(ch, "local_mt") == "Cục bộ hai."
    assert storage.read_branch_mt_snapshot(ch, "local_mt") == "MT cục bộ hai."
    assert storage.read_branch_revision(ch, "local_mt") == revision + 1
    # Nhánh ai không active giữ nguyên cả text lẫn snapshot.
    assert storage.read_branch_text(ch, "ai") == "AI một.\n\nAI hai."
    assert storage.read_branch_mt_snapshot(ch, "ai") == ""


# ── /compare/block: delete đồng bộ ─────────────────────────────────────────

def test_compare_delete_removes_raw_mt_and_active_translated(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "ai")

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 0,
        "raw_expected": "原文 một.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deleted"] is True
    assert body["blocks_removed"] == ["raw", "mt", "translated"]
    assert storage.read_raw(ch) == "原文 hai."
    assert storage.read_translated_mt(ch) == "MT hai."
    assert storage.read_translated(ch) == "Bản dịch hai."
    assert storage.read_branch_revision(ch, "ai") == revision + 1


def test_compare_delete_inactive_branch_untouched(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    storage.write_branch_text(ch, "local_mt", "Cục bộ một.\n\nCục bộ hai.")
    storage.mark_branch_complete(ch, "local_mt")
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "ai")

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 0,
        "raw_expected": "原文 một.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    # Nhánh không active (local_mt) giữ nguyên.
    assert storage.read_branch_text(ch, "local_mt") == "Cục bộ một.\n\nCục bộ hai."
    assert storage.read_raw(ch) == "原文 hai."
    assert storage.read_translated(ch) == "Bản dịch hai."


def test_compare_delete_when_mt_shorter_only_removes_present_blocks(tmp_path, monkeypatch):
    """MT chỉ có 1 khối — xóa raw khối 0 thì MT khối 0 bị xóa, raw khối 1 còn,
    MT không còn gì (không lỗi)."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 một.\n\n原文 hai.")
    storage.write_translated(ch, "Bản dịch một.\n\nBản dịch hai.")
    storage.write_translated_mt(ch, "MT một.")
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "ai")

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 0,
        "raw_expected": "原文 một.",
        "revision": revision,
    })

    assert res.status_code == 200, res.text
    assert storage.read_raw(ch) == "原文 hai."
    # Snapshot MT thật (cột translated_mt_text) đã bị xóa; read_translated_mt
    # fallback về translated nên không dùng để kiểm tra cột gốc.
    assert storage.read_branch_mt_snapshot(ch, "ai") == ""
    assert storage.read_translated(ch) == "Bản dịch hai."


def test_compare_delete_stale_raw_409_no_partial_write(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    revision = storage.read_branch_revision(ch, "ai")

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 0,
        "raw_expected": "ĐÃ THAY ĐỔI",
        "revision": revision,
    })

    assert res.status_code == 409
    # Không ghi gì cả — atomic.
    assert storage.read_raw(ch) == "原文 một.\n\n原文 hai."
    assert storage.read_translated_mt(ch) == "MT một.\n\nMT hai."
    assert storage.read_translated(ch) == "Bản dịch một.\n\nBản dịch hai."


def test_compare_delete_stale_revision_409(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    storage.write_translated(ch, "sửa xen giữa.\n\nBản dịch hai.")

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 0,
        "raw_expected": "原文 một.",
        "revision": storage.read_branch_revision(ch, "ai") - 1,
    })

    assert res.status_code == 409
    assert storage.read_raw(ch) == "原文 một.\n\n原文 hai."


def test_compare_delete_block_index_out_of_range_409(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = _post(client, "t", 1, {
        "op": "delete",
        "block": 99,
        "raw_expected": "原文 một.",
        "revision": storage.read_branch_revision(ch, "ai"),
    })

    assert res.status_code == 409


def test_compare_block_rejects_bad_op_and_missing_fields(tmp_path, monkeypatch):
    storage, ch = _block_client(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    assert _post(client, "t", 1, {"op": "nope", "block": 0}).status_code == 400
    assert _post(client, "t", 1, {"op": "delete", "block": "x"}).status_code == 400
    assert _post(client, "t", 1, {"op": "delete", "block": 0, "revision": "x"}).status_code == 400
