"""Gióng đoạn cho khung so sánh 3 cột (bản gốc | dịch máy | bản biên tập).

Tách khỏi route vì cả trang Jinja2 cũ (`chapter.html`) lẫn API của SPA
(`/api/ui/ebooks/{slug}/chapters/{index}`) đều cần đúng cách chia này — hai
bên chia lệch nhau thì số đoạn không khớp và người dùng sửa nhầm dòng.

Cách chia ĐOẠN = TỪNG DÒNG không rỗng (`novel2epub.blocks.split_paragraphs`,
trùng `notes.split_paras`) — mỗi hàng của khung đối chiếu đúng bằng một đoạn
của chế độ Đọc. `split_blocks` (chia theo khối cách dòng trống) vẫn re-export
ở đây cho find-preview raw.
"""
from __future__ import annotations

from novel2epub.blocks import split_blocks, split_paragraphs  # noqa: F401  (split_blocks: re-export canonical)


def align_paragraphs(raw: str, mt: str, edited: str) -> list[tuple[str, str, str]]:
    """Ghép ba bản văn thành các hàng `(gốc, dịch máy, biên tập)`.

    Mỗi hàng = MỘT ĐOẠN (một dòng không rỗng), đúng cách chia của chế độ Đọc.
    Cột ngắn hơn được đệm chuỗi rỗng. Hàng có bản gốc rỗng bị loại — chúng chỉ
    là dòng trống thừa ở cuối bản dịch, hiện ra thành hàng trắng vô nghĩa.
    Luôn trả về ít nhất một hàng để khung so sánh không sập khi chương rỗng.
    """
    columns = [split_paragraphs(raw), split_paragraphs(mt), split_paragraphs(edited)]
    height = max((len(col) for col in columns), default=0)
    for col in columns:
        col.extend([""] * (height - len(col)))

    rows = [row for row in zip(*columns) if row[0].strip()]
    return rows or [("", "", "")]
