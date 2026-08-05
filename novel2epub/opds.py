"""Sinh catalog OPDS 1.2 (Atom XML) cho trình đọc ngoài — chủ yếu là readest.

Logic THUẦN: nhận list `OpdsBook` đã dựng sẵn, trả chuỗi XML. Không I/O,
không DB, không FastAPI.

Vì sao Atom 1.2 chứ không phải OPDS 2.0 (JSON): readest parse feed bằng
`foliate-js/opds.js`, vốn xử lý cả hai và chuẩn hoá về cùng một shape; Atom
1.2 là bản mà Calibre/Komga/Kavita phục vụ nên là đường đi được thử nhiều
nhất.

Dùng `ElementTree` chứ không nối chuỗi tay: nó bảo đảm escape đúng và tài
liệu đóng gọn. Rác sau `</feed>` sẽ khiến DOMParser nghiêm ngặt (Firefox,
jsdom) huỷ cả tài liệu, và readest khi đó tưởng response là HTML rồi quay lui.
"""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/terms/"

# `rel` readest thực sự dò (hằng REL trong apps/readest-app/src/types/opds.ts).
# Phải là token CHÍNH XÁC — nó tách rel theo khoảng trắng rồi so bằng.
REL_ACQUISITION = "http://opds-spec.org/acquisition"
REL_IMAGE = "http://opds-spec.org/image"
REL_THUMBNAIL = "http://opds-spec.org/image/thumbnail"

NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
EPUB_TYPE = "application/epub+zip"

_CATALOG_TITLE = "novel2epub"

# Register namespaces
ET.register_namespace("", ATOM_NS)
ET.register_namespace("dc", DC_NS)


@dataclass
class OpdsBook:
    """Một ebook đã build EPUB, sẵn sàng phát ra feed."""
    slug: str
    title: str
    author: str = ""
    description: str = ""
    language: str = "vi"
    identifier: str = ""
    publisher: str = ""
    pubdate: str = ""
    subjects: list[str] = field(default_factory=list)
    # Thời điểm sửa của FILE EPUB, không phải của bản dịch — readest quyết
    # định tải lại dựa vào trường này, mà thứ nó tải là file.
    updated: str = ""
    has_cover: bool = False
    cover_type: str = "image/jpeg"


def iso_utc(timestamp: float) -> str:
    """Epoch giây -> chuỗi thời gian Atom (UTC, hậu tố Z)."""
    moment = _dt.datetime.fromtimestamp(timestamp, tz=_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(parent: ET.Element, tag: str, value: str) -> None:
    """Thêm thẻ có nội dung; bỏ qua khi giá trị rỗng (không sinh thẻ rỗng)."""
    if not value:
        return
    ET.SubElement(parent, tag).text = value


def _link(parent: ET.Element, *, rel: str, href: str, type_: str) -> None:
    ET.SubElement(parent, f"{{{ATOM_NS}}}link", {"rel": rel, "href": href, "type": type_})


def _serialize(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body.rstrip()


def _feed_root(*, feed_id: str, title: str, updated: str) -> ET.Element:
    root = ET.Element(f"{{{ATOM_NS}}}feed")
    _text(root, f"{{{ATOM_NS}}}id", feed_id)
    _text(root, f"{{{ATOM_NS}}}title", title)
    _text(root, f"{{{ATOM_NS}}}updated", updated)
    return root


def navigation_feed(*, base_url: str, updated: str) -> str:
    """Feed gốc — chỉ trỏ tới feed acquisition. Giữ một mục: 6 ebook chưa
    đáng chia nhóm."""
    base = base_url.rstrip("/")
    root = _feed_root(feed_id="urn:novel2epub:catalog", title=_CATALOG_TITLE, updated=updated)
    _link(root, rel="self", href=f"{base}/opds", type_=NAV_TYPE)
    _link(root, rel="start", href=f"{base}/opds", type_=NAV_TYPE)

    entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")
    _text(entry, f"{{{ATOM_NS}}}title", "Tất cả truyện")
    _text(entry, f"{{{ATOM_NS}}}id", "urn:novel2epub:books")
    _text(entry, f"{{{ATOM_NS}}}updated", updated)
    _link(entry, rel="subsection", href=f"{base}/opds/books", type_=ACQ_TYPE)
    ET.SubElement(entry, f"{{{ATOM_NS}}}content", {"type": "text"}).text = (
        "Toàn bộ ebook đã build"
    )
    return _serialize(root)


def acquisition_feed(books: list[OpdsBook], *, base_url: str, updated: str) -> str:
    """Feed danh sách sách tải được. Mỗi `OpdsBook` thành một `<entry>`."""
    base = base_url.rstrip("/")
    root = _feed_root(feed_id="urn:novel2epub:books", title=_CATALOG_TITLE, updated=updated)
    _link(root, rel="self", href=f"{base}/opds/books", type_=ACQ_TYPE)
    _link(root, rel="start", href=f"{base}/opds", type_=NAV_TYPE)

    for book in books:
        entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")
        _text(entry, f"{{{ATOM_NS}}}title", book.title or book.slug)
        _text(entry, f"{{{ATOM_NS}}}id", f"urn:novel2epub:{book.slug}")
        _text(entry, f"{{{ATOM_NS}}}updated", book.updated or updated)
        if book.author:
            author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
            _text(author, f"{{{ATOM_NS}}}name", book.author)
        if book.description:
            summary = ET.SubElement(entry, f"{{{ATOM_NS}}}summary", {"type": "text"})
            summary.text = book.description
        _text(entry, f"{{{DC_NS}}}language", book.language)
        _text(entry, f"{{{DC_NS}}}identifier", book.identifier)
        _text(entry, f"{{{DC_NS}}}publisher", book.publisher)
        _text(entry, f"{{{DC_NS}}}issued", book.pubdate)
        for subject in book.subjects:
            if subject:
                ET.SubElement(entry, f"{{{ATOM_NS}}}category", {"term": subject})
        if book.has_cover:
            cover = f"{base}/opds/cover/{book.slug}"
            _link(entry, rel=REL_IMAGE, href=cover, type_=book.cover_type)
            _link(entry, rel=REL_THUMBNAIL, href=cover, type_=book.cover_type)
        _link(
            entry,
            rel=REL_ACQUISITION,
            href=f"{base}/opds/download/{book.slug}.epub",
            type_=EPUB_TYPE,
        )
    return _serialize(root)
