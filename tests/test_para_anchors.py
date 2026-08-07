"""Neo đoạn cho đường đẩy sang Reader — `anchors[j]` phải trỏ ĐÚNG dòng nguồn.

Đây là bất biến nền của toàn bộ pipeline hai chiều: neo cho biết đoạn hiển thị
bên Reader tương ứng dòng nào trong `translated_text`, còn `notes.replace_para`
ghi theo đúng chỉ số đó. Lệch một bậc là sửa nhầm đoạn — âm thầm, không lỗi.

Bổ sung cho `test_epub_anchors.py` (neo `data-n2e-p` trong EPUB, đường OPDS).
Hai đường neo khác nhau nhưng cùng quy chiếu về `notes.split_paras`.
"""
from __future__ import annotations

import pytest

from novel2epub.notes import replace_para, split_paras
from novel2epub.reader_sync import md_to_plaintext, md_to_plaintext_with_anchors


def _plain_lines(content: str) -> list[str]:
    """Các dòng không rỗng của plaintext — đơn vị mà `anchors` đánh chỉ số."""
    return [ln for ln in content.split("\n") if ln.strip()]


# ── bất biến cấu trúc ────────────────────────────────────────────────

def test_so_neo_bang_so_dong_plaintext():
    md = "Đoạn một.\n\nDòng dẫn:\n— Lời thoại.\n\nĐoạn cuối."
    content, anchors = md_to_plaintext_with_anchors(md)
    assert len(anchors) == len(_plain_lines(content))


def test_neo_tang_dan_va_khong_trung():
    md = "A\n\nB\nC\n\nD"
    _content, anchors = md_to_plaintext_with_anchors(md)
    assert anchors == sorted(anchors)
    assert len(set(anchors)) == len(anchors)


def test_neo_tro_dung_dong_trong_split_paras():
    md = "Đoạn một.\n\nDòng dẫn:\n— Lời thoại.\n\nĐoạn cuối."
    content, anchors = md_to_plaintext_with_anchors(md)
    paras = split_paras(md)
    for j, line in enumerate(_plain_lines(content)):
        assert paras[anchors[j]] == line


def test_khong_co_heading_thi_neo_la_anh_xa_dong_nhat():
    """Dữ liệu thật hiện tại không có heading — neo phải suy biến về identity,
    đó là mốc kiểm tra rẻ nhất khi nghi ngờ."""
    md = "A\n\nB\nC\n\nD"
    _content, anchors = md_to_plaintext_with_anchors(md)
    assert anchors == [0, 1, 2, 3]


def test_wrapper_cu_tra_dung_van_ban_nhu_truoc():
    md = "# Chương 1\n\nĐoạn một.\n\nDòng dẫn:\n— Lời thoại."
    assert md_to_plaintext(md) == md_to_plaintext_with_anchors(md)[0]


# ── ca làm neo lệch: heading ─────────────────────────────────────────

def test_heading_dau_bi_bo_nhung_van_chiem_mot_bac():
    """`split_paras` GIỮ dòng `# Chương 1`, plaintext thì BỎ. Quên tiêu thụ
    dòng nguồn đó là toàn chương lệch một bậc — ca hỏng kinh điển."""
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    content, anchors = md_to_plaintext_with_anchors(md)
    assert _plain_lines(content) == ["Đoạn một.", "Đoạn hai."]
    assert anchors == [1, 2]
    paras = split_paras(md)
    assert paras[0] == "# Chương 1"
    assert paras[anchors[0]] == "Đoạn một."


def test_heading_giua_bai_duoc_giu_nhung_mat_dau_thang():
    """Neo trỏ đúng DÒNG; nó không hứa hai chuỗi bằng nhau."""
    md = "Mở đầu.\n\n## Tiểu mục\n\nThân bài."
    content, anchors = md_to_plaintext_with_anchors(md)
    assert _plain_lines(content) == ["Mở đầu.", "Tiểu mục", "Thân bài."]
    assert anchors == [0, 1, 2]
    assert split_paras(md)[anchors[1]] == "## Tiểu mục"


def test_block_nhieu_dong_moi_dong_mot_neo():
    """Cặp lời dẫn + lời thoại: 105 chỗ trong dữ liệu thật. Gộp hai dòng thành
    một đơn vị sửa thì bản sửa không đi ngược về được."""
    md = "Lương Bát Đẩu thở dài:\n— Bang Kim Hà muốn hút cạn tủy xương.\n\nĐoạn sau."
    content, anchors = md_to_plaintext_with_anchors(md)
    assert anchors == [0, 1, 2]
    assert len(_plain_lines(content)) == 3
    # Dòng trống vẫn ngăn cách đúng chỗ để Reader render sát nhau như <br/>.
    assert content.split("\n\n")[0].count("\n") == 1


def test_heading_dau_va_block_nhieu_dong_cung_luc():
    md = "# Chương 1\n\nDòng dẫn:\n— Lời thoại.\n\nKết."
    content, anchors = md_to_plaintext_with_anchors(md)
    assert anchors == [1, 2, 3]
    paras = split_paras(md)
    for j, line in enumerate(_plain_lines(content)):
        assert paras[anchors[j]] == line


def test_block_nhieu_dong_mo_dau_bang_dau_thang_khong_bi_coi_la_heading():
    """`_HEADING_RE` không bật MULTILINE nên chỉ khớp block MỘT dòng."""
    md = "# Chương 1\n\n# Không phải heading\nvì block có hai dòng.\n\nKết."
    content, anchors = md_to_plaintext_with_anchors(md)
    assert _plain_lines(content)[0] == "# Không phải heading"
    assert anchors == [1, 2, 3]


def test_dong_trong_thua_khong_lam_lech_neo():
    md = "A\n\n\n\nB\n\n   \n\nC"
    content, anchors = md_to_plaintext_with_anchors(md)
    paras = split_paras(md)
    for j, line in enumerate(_plain_lines(content)):
        assert paras[anchors[j]] == line


def test_chuong_rong_tra_ve_rong():
    assert md_to_plaintext_with_anchors("") == ("", [])
    assert md_to_plaintext_with_anchors("   \n\n  ") == ("", [])


# ── khứ hồi: neo -> replace_para -> văn bản nguồn ────────────────────

@pytest.mark.parametrize("md", [
    "Đoạn một.\n\nĐoạn hai.\n\nĐoạn ba.",
    "# Chương 1\n\nĐoạn một.\n\nĐoạn hai.",
    "# Chương 1\n\nDòng dẫn:\n— Lời thoại.\n\nKết.",
    "Mở đầu.\n\n## Tiểu mục\n\nThân bài.\n\nDẫn:\n— Thoại.",
])
def test_khu_hoi_sua_dung_dong_va_khong_dong_dong_khac(md):
    """Chứng minh cả cơ chế: lấy neo của một đoạn bên Reader -> dùng nó gọi
    `replace_para` -> ĐÚNG dòng đó đổi, không dòng nào khác động."""
    content, anchors = md_to_plaintext_with_anchors(md)
    lines_truoc = split_paras(md)

    for j in range(len(anchors)):
        moi = f"ĐÃ SỬA {j}"
        expected = lines_truoc[anchors[j]]
        ket_qua, loi = replace_para(md, anchors[j], expected, moi)

        assert loi == "", f"đoạn {j} không ghi được: {loi}"
        lines_sau = split_paras(ket_qua)
        assert len(lines_sau) == len(lines_truoc), "số dòng đổi — neo sẽ lệch"
        assert lines_sau[anchors[j]] == moi
        for i, (a, b) in enumerate(zip(lines_truoc, lines_sau)):
            if i != anchors[j]:
                assert a == b, f"dòng {i} bị động nhầm khi sửa đoạn {j}"


def test_khu_hoi_tren_du_lieu_giong_that():
    """Dựng theo đúng hình dạng chương thật: đoạn đơn xen cặp dẫn-thoại."""
    md = (
        "Đầm lau sậy bao la vô bờ bến, rung rinh xào xạc trong gió.\n\n"
        "— Hương Long Vương… lại tăng ba phần trăm!\n\n"
        "Lương Bát Đẩu thở dài thật dài, giọng đầy bất lực:\n"
        "— Bang Kim Hà rõ ràng muốn hút cạn tủy xương chúng ta.\n\n"
        "— Tối qua bố tôi ho cả đêm."
    )
    content, anchors = md_to_plaintext_with_anchors(md)
    assert len(anchors) == 5
    assert anchors == [0, 1, 2, 3, 4]

    # Editor sửa đúng dòng lời thoại nằm CHUNG block với lời dẫn.
    j = 3
    expected = split_paras(md)[anchors[j]]
    assert expected.startswith("— Bang Kim Hà")
    moi = "— Bang Kim Hà rõ ràng muốn vắt kiệt chúng ta."
    ket_qua, loi = replace_para(md, anchors[j], expected, moi)

    assert loi == ""
    assert split_paras(ket_qua)[3] == moi
    # Lời dẫn ngay trên vẫn nguyên vẹn và vẫn cùng block.
    assert split_paras(ket_qua)[2].startswith("Lương Bát Đẩu")
    assert "Lương Bát Đẩu thở dài thật dài, giọng đầy bất lực:\n" + moi in ket_qua
