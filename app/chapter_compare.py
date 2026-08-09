"""Gióng đoạn cho khung so sánh 3 cột (bản gốc | dịch máy | bản biên tập).

Tách khỏi route vì cả trang Jinja2 cũ (`chapter.html`) lẫn API của SPA
(`/api/ui/ebooks/{slug}/chapters/{index}`) đều cần đúng cách chia này — hai
bên chia lệch nhau thì số đoạn không khớp và người dùng sửa nhầm dòng.

Cách chia KHỐI nằm ở `novel2epub/blocks.py` (canonical) — tái dùng cho
find-preview raw và thao tác sửa/xóa block. Module này chỉ dựng 3 cột từ nó.
"""
from __future__ import annotations

from novel2epub.blocks import split_blocks  # noqa: F401  (re-export canonical)


def align_paragraphs(raw: str, mt: str, edited: str) -> list[tuple[str, str, str]]:
    """Ghép ba bản văn thành các hàng `(gốc, dịch máy, biên tập)`.

    Cột ngắn hơn được đệm chuỗi rỗng. Hàng có bản gốc rỗng bị loại — chúng chỉ
    là dòng trống thừa ở cuối bản dịch, hiện ra thành hàng trắng vô nghĩa.
    Luôn trả về ít nhất một hàng để khung so sánh không sập khi chương rỗng.
    """
    columns = [split_blocks(raw), split_blocks(mt), split_blocks(edited)]
    height = max((len(col) for col in columns), default=0)
    for col in columns:
        col.extend([""] * (height - len(col)))

    rows = [row for row in zip(*columns) if row[0].strip()]
    return rows or [("", "", "")]
