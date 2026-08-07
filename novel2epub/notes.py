"""Helper thuần cho ghi chú lỗi dịch trong trang đọc (reader).

Ghi chú được tạo khi người đọc bôi đen text trong 1 đoạn văn của bản dịch
(`translated/`), lưu server-side vào `<data_dir>/<slug>/notes.json`
(xem `Storage.read_notes`/`write_notes`). Mỗi ghi chú neo vào đoạn văn qua
`para_index` (index trong danh sách đoạn KHÔNG rỗng — đúng cách reader tách
đoạn) + `para_text` (snapshot cả đoạn lúc tạo, dùng khử nhập nhằng khi bản
dịch đổi). Module này chỉ chứa logic thuần (không I/O) để test độc lập.
"""
from __future__ import annotations


def split_paras(translated: str) -> list[str]:
    """Tách bản dịch thành danh sách đoạn không rỗng — ĐÚNG split của reader.

    `para_index` trong ghi chú luôn trỏ vào danh sách này, không phải danh
    sách dòng gốc (có thể chứa dòng trống).
    """
    return [p for p in translated.split("\n") if p.strip()]


def locate_note_para(paras: list[str], note: dict) -> int | None:
    """Tìm index đoạn chứa `selected_text` của ghi chú trong `paras`.

    Thứ tự: (1) đúng `para_index` đã lưu; (2) tìm toàn cục — duy nhất 1 đoạn
    khớp thì lấy; (3) nhiều đoạn khớp thì khử nhập nhằng bằng `para_text`
    (snapshot đoạn lúc tạo note). Trả None khi không thấy (stale) hoặc còn
    nhập nhằng.
    """
    selected = note.get("selected_text", "")
    if not selected:
        return None

    idx = note.get("para_index")
    if isinstance(idx, int) and 0 <= idx < len(paras) and selected in paras[idx]:
        return idx

    candidates = [i for i, p in enumerate(paras) if selected in p]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        para_text = note.get("para_text", "")
        matched = [i for i in candidates if paras[i] == para_text]
        if len(matched) == 1:
            return matched[0]
    return None


def apply_note_fix(translated: str, note: dict, fixed_text: str) -> tuple[str | None, str]:
    """Thay `selected_text` bằng `fixed_text` trong đúng đoạn văn của ghi chú.

    Thao tác theo DÒNG trên văn bản gốc (giữ nguyên các dòng trống): map index
    đoạn-không-rỗng → index dòng gốc, thay lần xuất hiện ĐẦU TIÊN của
    `selected_text` trong đúng 1 dòng đó. UI đã chặn chọn vùng vượt quá 1
    đoạn nên không cần xử lý thay thế đa dòng.

    Trả (văn_bản_mới, "") khi thành công, (None, lý_do) khi thất bại.
    """
    selected = note.get("selected_text", "")
    if not selected:
        return None, "Ghi chú không có đoạn văn được chọn."

    lines = translated.split("\n")
    para_line_indexes = [i for i, line in enumerate(lines) if line.strip()]
    paras = [lines[i] for i in para_line_indexes]

    para_idx = locate_note_para(paras, note)
    if para_idx is None:
        return None, "Không tìm thấy đoạn văn — bản dịch đã thay đổi."

    line_idx = para_line_indexes[para_idx]
    lines[line_idx] = lines[line_idx].replace(selected, fixed_text, 1)
    return "\n".join(lines), ""


def replace_para(
    translated: str,
    para_index: int,
    para_text_expected: str,
    new_text: str,
) -> tuple[str | None, str]:
    """Thay TOÀN BỘ một đoạn (đoạn-không-rỗng thứ `para_index`) bằng `new_text`.

    Thao tác theo DÒNG trên văn bản gốc (giữ nguyên dòng trống): map index
    đoạn-không-rỗng → index dòng gốc, đúng cách reader tách đoạn. Kiểm tra
    `para_text_expected` khớp dòng hiện tại trước khi ghi để chống ghi đè khi
    bản dịch đã đổi sau lúc mở editor.

    `new_text` nhiều dòng bị gộp về MỘT dòng (nối bằng khoảng trắng). Nếu nội
    dung mới rỗng, xóa hẳn dòng đoạn đó; client phải đánh lại `para_index` cho
    các đoạn phía sau.

    Trả (văn_bản_mới, "") khi thành công, (None, lý_do) khi thất bại.
    """
    lines = translated.split("\n")
    para_line_indexes = [i for i, line in enumerate(lines) if line.strip()]
    if not isinstance(para_index, int) or not (0 <= para_index < len(para_line_indexes)):
        return None, "Không tìm thấy đoạn — bản dịch đã thay đổi."

    line_idx = para_line_indexes[para_index]
    if lines[line_idx] != para_text_expected:
        return None, "Bản dịch đã thay đổi — tải lại trang."

    cleaned = " ".join(seg.strip() for seg in new_text.splitlines() if seg.strip())
    if not cleaned:
        lines.pop(line_idx)
        remaining = [line.strip() for line in lines if line.strip()]
        return "\n\n".join(remaining), ""

    lines[line_idx] = cleaned
    return "\n".join(lines), ""


def insert_para(translated: str, after_index: int, text: str) -> tuple[str | None, str]:
    """Chèn một đoạn mới (dòng mới, không rỗng) vào bản dịch.

    `after_index` là index đoạn-không-rỗng (theo `split_paras`) để chèn đoạn
    mới NGAY SAU; dùng `-1` để chèn ở đầu bản dịch (trước đoạn đầu tiên).
    Đoạn mới luôn có nội dung — nếu `text` rỗng thì dùng placeholder để có
    chỗ bấm sửa ngay trên trang đọc.

    Trả (văn_bản_mới, "") khi thành công, (None, lý_do) khi thất bại.
    """
    lines = translated.split("\n") if translated else []
    para_line_indexes = [i for i, line in enumerate(lines) if line.strip()]
    if after_index != -1 and not (0 <= after_index < len(para_line_indexes)):
        return None, "Không tìm thấy đoạn để chèn sau — bản dịch đã thay đổi."

    cleaned = " ".join(seg.strip() for seg in text.splitlines() if seg.strip())
    if not cleaned:
        cleaned = "Đoạn mới…"

    insert_at = 0 if after_index == -1 else para_line_indexes[after_index] + 1
    lines.insert(insert_at, cleaned)
    return "\n".join(lines), ""
