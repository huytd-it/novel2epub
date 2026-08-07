"""Gióng đoạn cho khung so sánh 3 cột.

Logic này được dùng chung bởi trang Jinja2 cũ và API của SPA. Lệch nhau giữa
hai bên nghĩa là hai giao diện đánh số đoạn khác nhau trên cùng một chương —
kiểu sai âm thầm không có lỗi nào nổ ra.
"""
from __future__ import annotations

from app.chapter_compare import align_paragraphs, split_blocks


def test_cat_theo_dong_trong():
    assert split_blocks("A\n\nB\n\nC") == ["A", "B", "C"]


def test_gop_cac_dong_trong_cung_mot_khoi():
    """Cặp "lời dẫn + lời thoại" phải nằm cùng một hàng với đoạn gốc của nó."""
    assert split_blocks("Hắn nói:\n— Đi thôi.\n\nĐoạn sau.") == [
        "Hắn nói: — Đi thôi.",
        "Đoạn sau.",
    ]


def test_bo_qua_khoi_rong_va_khoang_trang_thua():
    assert split_blocks("\n\n  \n\nA\n\n\n\nB\n\n") == ["A", "B"]


def test_van_ban_rong_khong_sinh_khoi_nao():
    assert split_blocks("") == []


def test_ba_cot_bang_nhau_thi_ghep_thang_hang():
    rows = align_paragraphs("原文一\n\n原文二", "MT một\n\nMT hai", "Sửa một\n\nSửa hai")
    assert rows == [("原文一", "MT một", "Sửa một"), ("原文二", "MT hai", "Sửa hai")]


def test_cot_ngan_hon_duoc_dem_rong():
    """Chương mới crawl chưa dịch vẫn phải hiện đủ số hàng của bản gốc."""
    rows = align_paragraphs("原文一\n\n原文二", "", "")
    assert rows == [("原文一", "", ""), ("原文二", "", "")]


def test_loai_hang_khong_co_ban_goc():
    """Bản dịch thừa đoạn so với bản gốc thì phần thừa không thành hàng trắng."""
    rows = align_paragraphs("原文", "MT một\n\nMT thừa", "Sửa một\n\nSửa thừa")
    assert rows == [("原文", "MT một", "Sửa một")]


def test_chuong_rong_van_tra_mot_hang():
    """Khung so sánh không được sập khi chương chưa có gì."""
    assert align_paragraphs("", "", "") == [("", "", "")]


def test_khong_trung_cach_danh_so_cua_split_paras():
    """Chốt lại sự khác biệt khiến `para/save` không dùng được chỉ số hàng ở đây.

    `notes.split_paras` đếm theo TỪNG DÒNG, khung so sánh đếm theo KHỐI. Hàng
    thứ 2 ở đây là đoạn thứ 3 bên kia — lấy nhầm chỉ số là ghi đè nhầm dòng.
    """
    from novel2epub.notes import split_paras

    text = "Hắn nói:\n— Đi thôi.\n\nĐoạn sau."
    assert split_paras(text) == ["Hắn nói:", "— Đi thôi.", "Đoạn sau."]
    assert [row[2] for row in align_paragraphs(text, text, text)] == [
        "Hắn nói: — Đi thôi.",
        "Đoạn sau.",
    ]
