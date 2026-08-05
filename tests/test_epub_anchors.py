"""Neo đoạn văn trong EPUB — `data-n2e-p` phải khớp CHÍNH XÁC notes.split_paras.

Đây là bất biến nền của cả tính năng sửa từ readest: neo cho biết ĐOẠN NÀO,
còn `notes.replace_para` ghi theo đúng chỉ số đó. Lệch một bậc là sửa nhầm đoạn.
"""
from __future__ import annotations

import re

from novel2epub.epub_builder import _md_to_xhtml_body
from novel2epub.notes import split_paras


def _anchors(html: str) -> list[int]:
    return [int(n) for n in re.findall(r'data-n2e-p="(\d+)"', html)]


def _anchored_text(html: str, index: int) -> str:
    m = re.search(rf'data-n2e-p="{index}"[^>]*>(.*?)<', html, re.S)
    return m.group(1) if m else ""


def test_khong_bat_thi_khong_co_neo_nao():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    assert _anchors(_md_to_xhtml_body(md)) == []
    assert "data-n2e-p" not in _md_to_xhtml_body(md, anchored=False)


def test_neo_danh_so_lien_tuc_tu_0():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    assert _anchors(_md_to_xhtml_body(md, anchored=True)) == [0, 1, 2]


def test_so_luong_neo_bang_so_doan_cua_split_paras():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai.\n\nĐoạn ba."
    html = _md_to_xhtml_body(md, anchored=True)
    assert _anchors(html) == list(range(len(split_paras(md))))


def test_heading_cung_duoc_dem_vao_chi_so():
    # split_paras GIỮ dòng heading, nên bộ đếm phải tính nó — bỏ qua là lệch
    # toàn bộ chương một bậc.
    md = "# Chương 1\n\nĐoạn một."
    html = _md_to_xhtml_body(md, anchored=True)
    assert 'data-n2e-p="0"' in html
    assert "<h2" in html
    assert split_paras(md)[0] == "# Chương 1"


def test_block_nhieu_dong_moi_dong_mot_neo():
    # ĐÂY là ca đã làm hai định nghĩa đoạn lệch nhau trong dữ liệu thật
    # (161 dòng-không-rỗng vs 160 block). Đếm theo DÒNG mới đúng.
    md = "Dòng một\nDòng hai\n\nĐoạn sau"
    html = _md_to_xhtml_body(md, anchored=True)
    assert len(split_paras(md)) == 3
    assert _anchors(html) == [0, 1, 2]
    assert html.count("<p>") == 2  # hình thức hiển thị KHÔNG đổi
    assert "<br/>" in html


def test_giu_nguyen_cach_hien_thi_khi_bat_neo():
    md = "Dòng một\nDòng hai\n\nĐoạn sau"
    plain = _md_to_xhtml_body(md)
    anchored = _md_to_xhtml_body(md, anchored=True)
    assert re.sub(r'<span data-n2e-p="\d+">|</span>|\sdata-n2e-p="\d+"', "", anchored) == plain


def test_neo_khop_split_paras_tren_moi_kieu_xuong_dong():
    for md in (
        "# T\n\nA\n\nB",
        "# T\nA\nB",
        "A\n\n\n\nB",
        "A\n  \nB",
        "Dòng một\nDòng hai\n\nC\nD\n\nE",
        "  \n\n# T\n\nA\n\n  ",
    ):
        html = _md_to_xhtml_body(md, anchored=True)
        assert _anchors(html) == list(range(len(split_paras(md)))), md


def test_noi_dung_tai_neo_khop_doan_tuong_ung():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    html = _md_to_xhtml_body(md, anchored=True)
    paras = split_paras(md)
    assert _anchored_text(html, 1) == paras[1]
    assert _anchored_text(html, 2) == paras[2]


def test_ky_tu_dac_biet_van_duoc_escape_khi_co_neo():
    md = "A & B < C"
    html = _md_to_xhtml_body(md, anchored=True)
    assert "&amp;" in html and "&lt;" in html
    assert 'data-n2e-p="0"' in html


def test_footnote_khong_lam_lech_chi_so():
    from novel2epub import footnotes

    md = "# Chương 1\n\nTrang Quốc là nơi đó.\n\nĐoạn sau."
    marked, fns = footnotes.annotate(md, {"Trang Quốc": "nước hư cấu"})
    assert fns  # phải có footnote thì test mới có ý nghĩa
    # annotate chỉ CHÈN ký tự inline, không thêm/bớt dòng.
    assert len(split_paras(marked)) == len(split_paras(md))
    assert _anchors(_md_to_xhtml_body(marked, anchored=True)) == [0, 1, 2]


def test_chi_chuong_da_dich_moi_duoc_gan_neo(tmp_path):
    """Chương rơi về raw_text (Hán gốc) tuyệt đối không được có neo — API sửa
    ghi vào translated_text, gắn neo là mời sửa nhầm cột."""
    import zipfile

    from novel2epub.pipeline import step_build_selected
    from novel2epub.storage import Chapter, Manifest, Storage
    from tests.test_opds_routes import _cfg  # dựng Config tối thiểu

    storage = Storage(tmp_path, "t")
    da_dich = Chapter(index=1, url="http://x/1", title="Đã dịch")
    chua_dich = Chapter(index=2, url="http://x/2", title="Chưa dịch")
    storage.save_manifest(Manifest(slug="t", title="T", chapters=[da_dich, chua_dich]))
    storage.write_translated(da_dich, "# Đã dịch\n\nĐoạn tiếng Việt.")
    storage.mark_translated_complete(da_dich)
    storage.write_raw(chua_dich, "# 第二章\n\n这是中文。")

    cfg = _cfg(tmp_path, "t", epub_name=str(tmp_path / "t.epub"))
    step_build_selected(cfg, log=lambda _m: None)

    with zipfile.ZipFile(tmp_path / "t.epub") as z:
        names = [n for n in z.namelist() if n.endswith(".xhtml")]
        bodies = {n: z.read(n).decode("utf-8") for n in names}

    co_neo = [n for n, b in bodies.items() if "data-n2e-p" in b]
    assert any("0001" in n for n in co_neo)
    assert not any("0002" in n for n in co_neo)
