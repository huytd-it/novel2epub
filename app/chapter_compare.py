"""Gióng đoạn cho khung so sánh 3 cột (bản gốc | dịch máy | bản biên tập).

Tách khỏi route vì cả trang Jinja2 cũ (`chapter.html`) lẫn API của SPA
(`/api/ui/ebooks/{slug}/chapters/{index}`) đều cần đúng cách chia này — hai
bên chia lệch nhau thì số đoạn không khớp và người dùng sửa nhầm dòng.
"""
from __future__ import annotations

import re

_BLANK_LINE = re.compile(r"\n\s*\n")


def split_blocks(text: str) -> list[str]:
    """Cắt theo dòng trống, mỗi khối gộp về một dòng.

    Gộp là có chủ đích: cặp "lời dẫn + lời thoại" nằm trên hai dòng liền nhau
    phải đứng CÙNG một hàng với đoạn gốc tương ứng, nếu không hai cột lệch nhau
    ngay từ đoạn đầu tiên.
    """
    if not text:
        return []
    blocks = _BLANK_LINE.split(text.strip())
    return [" ".join(b.splitlines()) for b in blocks if b.strip()]


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
