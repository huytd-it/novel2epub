"""Sinh feed OPDS 1.2 (Atom). Logic thuần — không mạng, không DB.

Các khẳng định ở đây bám sát thứ readest THỰC SỰ đọc (hằng `REL` trong
`apps/readest-app/src/types/opds.ts`), không phải bám bản chuẩn OPDS chung
chung.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from novel2epub.opds import (
    ACQ_TYPE,
    NAV_TYPE,
    OpdsBook,
    acquisition_feed,
    iso_utc,
    navigation_feed,
)

ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/terms/"
UPDATED = "2026-08-05T10:00:00Z"


def _book(**kw) -> OpdsBook:
    base = dict(
        slug="truyen-a",
        title="Truyện A",
        author="Tác Giả",
        description="Mô tả",
        language="vi",
        updated=UPDATED,
        has_cover=True,
    )
    base.update(kw)
    return OpdsBook(**base)


def _links(entry) -> dict[str, str]:
    return {ln.get("rel"): ln.get("href") for ln in entry.findall(f"{{{ATOM}}}link")}


# ---------- feed điều hướng ----------


def test_navigation_feed_la_xml_hop_le_va_goc_la_feed():
    root = ET.fromstring(navigation_feed(base_url="http://h:8010", updated=UPDATED))
    assert root.tag == f"{{{ATOM}}}feed"


def test_navigation_feed_tro_toi_feed_acquisition():
    root = ET.fromstring(navigation_feed(base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    assert entry is not None
    link = entry.find(f"{{{ATOM}}}link")
    assert link.get("href") == "http://h:8010/opds/books"
    assert link.get("type") == ACQ_TYPE


def test_navigation_feed_co_link_self_va_start():
    root = ET.fromstring(navigation_feed(base_url="http://h:8010", updated=UPDATED))
    rels = {ln.get("rel") for ln in root.findall(f"{{{ATOM}}}link")}
    assert {"self", "start"} <= rels


# ---------- feed acquisition ----------


def test_acquisition_feed_mot_entry_moi_sach():
    xml = acquisition_feed([_book(), _book(slug="b", title="B")],
                           base_url="http://h:8010", updated=UPDATED)
    root = ET.fromstring(xml)
    assert len(root.findall(f"{{{ATOM}}}entry")) == 2


def test_link_tai_sach_dung_rel_acquisition_va_media_type_epub():
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    acq = [
        ln for ln in entry.findall(f"{{{ATOM}}}link")
        if ln.get("rel") == "http://opds-spec.org/acquisition"
    ]
    assert len(acq) == 1
    assert acq[0].get("href") == "http://h:8010/opds/download/truyen-a.epub"
    assert acq[0].get("type") == "application/epub+zip"


def test_phat_ca_hai_rel_anh_voi_token_chinh_xac():
    # readest so khớp rel bằng token chính xác; thiếu một trong hai thì hoặc
    # mất bìa, hoặc mất ảnh thu nhỏ.
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    links = _links(root.find(f"{{{ATOM}}}entry"))
    assert links["http://opds-spec.org/image"] == "http://h:8010/opds/cover/truyen-a"
    assert links["http://opds-spec.org/image/thumbnail"] == "http://h:8010/opds/cover/truyen-a"


def test_sach_khong_co_bia_thi_khong_phat_link_anh():
    root = ET.fromstring(
        acquisition_feed([_book(has_cover=False)], base_url="http://h:8010", updated=UPDATED)
    )
    links = _links(root.find(f"{{{ATOM}}}entry"))
    assert "http://opds-spec.org/image" not in links
    assert "http://opds-spec.org/image/thumbnail" not in links


def test_mo_ta_nam_trong_summary():
    # Parser OPDS 1.x của foliate-js đọc mô tả ở <summary>.
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    summary = root.find(f"{{{ATOM}}}entry/{{{ATOM}}}summary")
    assert summary is not None
    assert summary.text == "Mô tả"
    assert summary.get("type") == "text"


def test_metadata_dc_duoc_phat():
    book = _book(language="vi", identifier="isbn:123", publisher="NXB X", pubdate="2026-01-02")
    root = ET.fromstring(acquisition_feed([book], base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    assert entry.find(f"{{{DC}}}language").text == "vi"
    assert entry.find(f"{{{DC}}}identifier").text == "isbn:123"
    assert entry.find(f"{{{DC}}}publisher").text == "NXB X"
    assert entry.find(f"{{{DC}}}issued").text == "2026-01-02"


def test_truong_rong_khong_sinh_the_rong():
    book = _book(author="", description="", identifier="", publisher="", pubdate="")
    root = ET.fromstring(acquisition_feed([book], base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    assert entry.find(f"{{{ATOM}}}author") is None
    assert entry.find(f"{{{ATOM}}}summary") is None
    assert entry.find(f"{{{DC}}}identifier") is None
    assert entry.find(f"{{{DC}}}publisher") is None
    assert entry.find(f"{{{DC}}}issued") is None


def test_the_loai_thanh_category():
    book = _book(subjects=["Tiên hiệp", "Huyền huyễn"])
    root = ET.fromstring(acquisition_feed([book], base_url="http://h:8010", updated=UPDATED))
    terms = [c.get("term") for c in root.findall(f"{{{ATOM}}}entry/{{{ATOM}}}category")]
    assert terms == ["Tiên hiệp", "Huyền huyễn"]


def test_id_entry_on_dinh_theo_slug():
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    assert root.find(f"{{{ATOM}}}entry/{{{ATOM}}}id").text == "urn:novel2epub:truyen-a"


def test_danh_sach_rong_van_ra_feed_hop_le():
    root = ET.fromstring(acquisition_feed([], base_url="http://h:8010", updated=UPDATED))
    assert root.tag == f"{{{ATOM}}}feed"
    assert root.findall(f"{{{ATOM}}}entry") == []


# ---------- an toàn XML ----------


def test_ky_tu_dac_biet_trong_tieu_de_duoc_escape():
    book = _book(title="《Truyện》 & <Ký> \"Sự\"", author="A & B")
    xml = acquisition_feed([book], base_url="http://h:8010", updated=UPDATED)
    root = ET.fromstring(xml)  # nổ ở đây nghĩa là escape sai
    assert root.find(f"{{{ATOM}}}entry/{{{ATOM}}}title").text == "《Truyện》 & <Ký> \"Sự\""


def test_khong_co_ky_tu_nao_sau_the_dong_goc():
    # Rác sau </feed> khiến DOMParser nghiêm ngặt (Firefox, jsdom) huỷ CẢ tài
    # liệu — readest sẽ tưởng response là HTML rồi quay lui.
    for xml in (
        navigation_feed(base_url="http://h:8010", updated=UPDATED),
        acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED),
    ):
        assert xml.endswith("</feed>")
        assert xml == xml.rstrip()


def test_feed_bat_dau_bang_khai_bao_xml():
    xml = acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED)
    assert xml.startswith("<?xml ")


def test_base_url_co_dau_gach_cuoi_khong_sinh_duong_dan_doi():
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010/", updated=UPDATED))
    links = _links(root.find(f"{{{ATOM}}}entry"))
    assert links["http://opds-spec.org/acquisition"] == "http://h:8010/opds/download/truyen-a.epub"


def test_iso_utc_dinh_dang_atom():
    assert iso_utc(0) == "1970-01-01T00:00:00Z"


def test_content_type_phan_biet_hai_loai_feed():
    assert "kind=navigation" in NAV_TYPE
    assert "kind=acquisition" in ACQ_TYPE
