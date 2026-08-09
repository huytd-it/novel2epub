"""Thao tác theo KHỐI cho khung đối chiếu 3 cột (bản gốc | dịch máy | bản hiện tại).

Khung đối chiếu chia theo KHỐI (cách bởi dòng trống, `app/chapter_compare.py`),
KHÁC với `notes.split_paras` chia theo TỪNG DÒNG. Module này chứa MỌI logic
thuần (không I/O) để sửa/xóa đoạn ở mức khối — test được độc lập, và là nơi
duy nhất map block index → chỉ số dòng gốc để không bao giờ nhầm với line
index của `split_paras`.
"""
from __future__ import annotations

import re

_BLANK_LINE = re.compile(r"\n\s*\n")


def split_blocks(text: str) -> list[str]:
    """Cắt theo dòng trống, mỗi khối gộp về một dòng.

    Đây là cách chia KHỐI CANONICAL — `app.chapter_compare.split_blocks` re-export
    đúng hàm này (kèm test khớp) để chỉ số KHỐI khung đối chiếu, find-preview raw
    và delete/edit block luôn trỏ về cùng một index. Gộp là có chủ đích: cặp
    "lời dẫn + lời thoại" nằm trên hai dòng liền nhau phải đứng CÙNG một hàng
    với đoạn gốc tương ứng.
    """
    if not text:
        return []
    blocks = _BLANK_LINE.split(text.strip())
    return [" ".join(b.splitlines()) for b in blocks if b.strip()]


def _block_line_ranges(text: str) -> list[tuple[int, int]]:
    """Trả danh sách `(start_line, end_line)` (start inclusive, end exclusive)
    của từng khối trong văn bản gốc.

    Khối = chuỗi các dòng không rỗng cách nhau bởi dòng trống. Dòng trống giữ
    nguyên vị trí trong văn bản (không xoá) để mọi thứ còn lại không dịch
    chuyển. Khi `new_text` rỗng (xóa khối), các dòng trống ngăn cách cũng bị
    gộp/xoá — `delete_block` xử lý riêng.
    """
    lines = text.split("\n")
    ranges: list[tuple[int, int]] = []
    start = None
    for i, line in enumerate(lines):
        if line.strip():
            if start is None:
                start = i
        else:
            if start is not None:
                ranges.append((start, i))
                start = None
    if start is not None:
        ranges.append((start, len(lines)))
    return ranges


def edit_block(text: str, block_index: int, new_text: str) -> tuple[str | None, str]:
    """Thay TOÀN BỘ khối thứ `block_index` bằng `new_text`.

    Sửa theo DÒNG trên văn bản gốc: tìm dải dòng của khối, thay bằng nội dung
    mới đã gộp về một dòng. Dòng trống không thuộc khối giữ nguyên vị trí.

    `new_text` rỗng = xóa khối (xem `delete_block`). Trả `(văn_bản_mới, "")`
    khi thành công, `(None, lý_do)` khi block index lệch.
    """
    if not text:
        return None, "Chương không có nội dung."
    ranges = _block_line_ranges(text)
    if not (0 <= block_index < len(ranges)):
        return None, "Đoạn đã thay đổi — tải lại trang."
    start, end = ranges[block_index]
    lines = text.split("\n")
    cleaned = " ".join(seg.strip() for seg in new_text.splitlines() if seg.strip())
    lines[start:end] = [cleaned] if cleaned else []
    return "\n".join(lines), ""


def replace_block(
    text: str,
    block_index: int,
    expected_text: str,
    new_text: str,
) -> tuple[str | None, str]:
    """Như `edit_block` nhưng kiểm tra khối hiện tại khớp `expected_text` trước
    khi ghi — optimistic/stale protection cho raw (vốn không có revision)."""
    if not text:
        return None, "Chương không có nội dung."
    blocks = split_blocks(text)
    if not (0 <= block_index < len(blocks)):
        return None, "Đoạn đã thay đổi — tải lại trang."
    if blocks[block_index] != expected_text:
        return None, "Bản đã thay đổi — tải lại trang."
    return edit_block(text, block_index, new_text)


def delete_block(
    text: str,
    block_index: int,
    expected_text: str,
) -> tuple[str | None, str]:
    """Xóa khối thứ `block_index` (kiểm tra `expected_text` trước) và nối lại
    văn bản theo chuẩn block: xoá luôn dòng trống ngăn cách để không còn khe
    trống đôi.

    Việc tách/nối lại thao tác trên CHUỖI gốc (giữ nguyên dòng trống còn lại)
    chứ không nối `split_blocks` — nếu không các khối khác bị mất dấu xuống
    dòng nội bộ. Trả `(văn_bản_mới, "")` khi thành công.
    """
    if not text:
        return None, "Chương không có nội dung."
    blocks = split_blocks(text)
    if not (0 <= block_index < len(blocks)):
        return None, "Đoạn đã thay đổi — tải lại trang."
    if blocks[block_index] != expected_text:
        return None, "Bản đã thay đổi — tải lại trang."
    ranges = _block_line_ranges(text)
    start, end = ranges[block_index]
    lines = text.split("\n")

    # Đoạn được xoá + dòng trống phía SAU (ngăn cách với khối kế). Nếu đây là
    # khối cuối cùng, xoá dòng trống phía TRƯỚC. Giữ lại đúng MỘT dòng trống
    # giữa các khối còn lại (chuẩn "cách bởi dòng trống").
    if end < len(lines):
        del lines[start : min(end + 1, len(lines))]
    else:
        del lines[max(0, start - 1) : len(lines)]
    return "\n".join(lines), ""
