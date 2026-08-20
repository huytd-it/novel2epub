"""Bộ lọc bảng chương: tách nhánh Local MT / AI và lọc tiêu đề sai mẫu.

Xem `novel2epub.toc.apply_chapter_query` và endpoint
`GET /api/ui/ebooks/{slug}/chapters`.
"""
from __future__ import annotations

import pytest

from novel2epub.storage import Chapter, Manifest, Storage
from novel2epub.toc import apply_chapter_query, chapter_rows, title_format_ok


@pytest.mark.parametrize(
    "title",
    [
        "Chương 5",
        "Chương 5: Tên chương",
        "Chương 5 Tên chương",
        "Chương 12.1: Phần một",
        "Chương 5. Tên chương",
        "Chương 300 - Hồi kết",
        "Chương 5 (thượng)",
    ],
)
def test_title_format_accepts_three_shapes(title):
    assert title_format_ok(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "",
        "   ",
        "Chapter 5",
        "第5章 回家",
        "Chương: tên chương",
        "Lời nói đầu",
        "Chương5: dính liền",
        "5. Tên chương",
    ],
)
def test_title_format_rejects_wrong_shapes(title):
    assert title_format_ok(title) is False


def _seed(tmp_path) -> Storage:
    """3 chương: 1 chỉ có Local MT, 2 chỉ có AI, 3 chưa dịch + tiêu đề sai mẫu."""
    storage = Storage(tmp_path, "t")
    ch1 = Chapter(index=1, url="http://x/1", title="Chương 1: Khởi đầu")
    ch2 = Chapter(index=2, url="http://x/2", title="Chương 2")
    ch3 = Chapter(index=3, url="http://x/3", title="Lời bạt")
    storage.save_manifest(Manifest(slug="t", chapters=[ch1, ch2, ch3]))

    storage.write_branch_text(ch1, "local_mt", "bản dịch máy")
    storage.mark_branch_complete(ch1, "local_mt")
    storage.set_active_branch(ch1, "local_mt")

    storage.write_branch_text(ch2, "ai", "bản dịch AI")
    storage.mark_branch_complete(ch2, "ai")
    storage.set_active_branch(ch2, "ai")

    return storage


def _rows(storage: Storage):
    manifest = storage.load_manifest()
    return chapter_rows(manifest.chapters, storage)


def _indexes(rows, **kwargs) -> list[int]:
    return [row.index for row in apply_chapter_query(rows, **kwargs)]


def test_local_mt_and_ai_filters_are_independent(tmp_path):
    rows = _rows(_seed(tmp_path))

    assert _indexes(rows, filter_local_mt="yes") == [1]
    assert _indexes(rows, filter_ai="yes") == [2]
    assert _indexes(rows, filter_local_mt="no", filter_ai="no") == [3]
    # Đã dịch ở nhánh nào đó, nhưng chưa có bản AI.
    assert _indexes(rows, filter_translated="yes", filter_ai="no") == [1]


def test_local_mt_and_ai_filters_default_to_any(tmp_path):
    rows = _rows(_seed(tmp_path))
    assert _indexes(rows) == [1, 2, 3]


def test_title_error_filter(tmp_path):
    rows = _rows(_seed(tmp_path))

    assert _indexes(rows, filter_title_error="yes") == [3]
    assert _indexes(rows, filter_title_error="no") == [1, 2]


def test_chapter_row_exposes_title_format_flag(tmp_path):
    rows = {row.index: row for row in _rows(_seed(tmp_path))}

    assert rows[1].title_format_ok is True
    assert rows[3].title_format_ok is False
    assert rows[3].has_title_error is True


def test_missing_title_counts_as_format_error(tmp_path):
    """`visible_title` có fallback "Chương N" — cờ phải tính trên tiêu đề thật."""
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=9, url="http://x/9", title="")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))

    row = _rows(storage)[0]
    assert row.visible_title == "Chương 9"
    assert row.title_format_ok is False
