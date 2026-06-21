"""Sinh footnote (chú thích) cho 1 chương từ glossary có ghi chú.

Editor ghi chú giải nghĩa vào glossary (định dạng `Hán = Việt | ghi chú`). Khi
build EPUB, mỗi thuật ngữ có ghi chú sẽ được chèn marker `(N)` ở LẦN XUẤT HIỆN
ĐẦU TIÊN trong chương, và danh sách định nghĩa được thêm ở cuối chương.

Module này thuần (không phụ thuộc ebooklib) để dễ test. Việc render marker/danh
sách thành HTML do epub_builder đảm nhiệm — ở đây chỉ chèn placeholder ký tự
Private-Use để qua html.escape không bị phá.
"""
from __future__ import annotations

# Bao quanh số footnote bằng ký tự Private-Use Area (U+E000/U+E001) để không trùng
# nội dung thật và sống sót qua html.escape (escape không đụng tới các ký tự này).
MARK_OPEN = ""
MARK_CLOSE = ""


def make_marker(num: int) -> str:
    return f"{MARK_OPEN}{num}{MARK_CLOSE}"


def _is_word_char(ch: str) -> bool:
    """Ký tự coi là 'thuộc từ' để kiểm tra ranh giới (chữ cái Unicode + số)."""
    return ch.isalnum()


def _find_first_unclaimed(text: str, term: str, claimed: list[tuple[int, int]]) -> int:
    """Vị trí khớp đầu tiên của `term` không nằm chồng lên vùng đã claim, có kiểm
    tra ranh giới chữ ở hai đầu. Trả -1 nếu không có.

    Vùng đã claim (của các term dài hơn) giúp tránh đánh dấu 'Trang' nằm trong
    'Trang Quốc'. Ranh giới chữ tránh khớp giữa một từ dài hơn không có trong notes.
    """
    start = 0
    while True:
        idx = text.find(term, start)
        if idx == -1:
            return -1
        end = idx + len(term)
        before = text[idx - 1] if idx > 0 else ""
        after = text[end] if end < len(text) else ""
        left_ok = not (before and _is_word_char(before) and _is_word_char(term[0]))
        right_ok = not (after and _is_word_char(after) and _is_word_char(term[-1]))
        overlaps = any(idx < c_end and end > c_start for c_start, c_end in claimed)
        if left_ok and right_ok and not overlaps:
            return idx
        start = idx + 1


def annotate(text: str, notes: dict[str, str]) -> tuple[str, list[dict]]:
    """Chèn marker footnote cho các term có ghi chú, trả (text_đã_đánh_dấu, list).

    - Chỉ đánh dấu LẦN XUẤT HIỆN ĐẦU TIÊN của mỗi term.
    - Term không xuất hiện trong chương sẽ bị bỏ (không đánh số).
    - Đánh số 1..n theo thứ tự VỊ TRÍ xuất hiện trong chương.
    - Term dài được ưu tiên dò trước; vùng nó chiếm được claim để term ngắn hơn
      (vd 'Trang' trong 'Trang Quốc') không khớp chồng lên.
    """
    if not text or not notes:
        return text, []

    # Dò vị trí khớp đầu tiên cho từng term (term dài trước), claim vùng đã chiếm.
    hits: list[tuple[int, str, str]] = []  # (pos, term, note)
    claimed: list[tuple[int, int]] = []
    for term in sorted(notes, key=len, reverse=True):
        if not term:
            continue
        pos = _find_first_unclaimed(text, term, claimed)
        if pos != -1:
            hits.append((pos, term, notes[term]))
            claimed.append((pos, pos + len(term)))

    if not hits:
        return text, []

    # Sắp theo vị trí xuất hiện để đánh số theo thứ tự đọc.
    hits.sort(key=lambda h: h[0])

    footnotes: list[dict] = []
    # Vị trí chèn marker = ngay sau term; chèn từ cuối về đầu để không lệch offset.
    insertions: list[tuple[int, str]] = []
    for num, (pos, term, note) in enumerate(hits, 1):
        footnotes.append({"num": num, "term": term, "note": note})
        insertions.append((pos + len(term), make_marker(num)))

    for at, marker in sorted(insertions, key=lambda x: x[0], reverse=True):
        text = text[:at] + marker + text[at:]

    return text, footnotes
