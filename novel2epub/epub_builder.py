"""Đóng gói các chương đã dịch thành file EPUB bằng ebooklib."""
from __future__ import annotations

import html
import re
from pathlib import Path

from . import footnotes
from .config import NovelConfig
from .storage import Chapter, Manifest

_CSS = """
body { font-family: serif; line-height: 1.6; margin: 5%; }
h1 { text-align: center; font-size: 1.4em; margin: 1em 0; }
p { text-indent: 1.5em; margin: 0.4em 0; text-align: justify; }
sup.fn a { text-decoration: none; font-size: 0.8em; }
.footnotes { margin-top: 2em; font-size: 0.9em; }
.footnotes ol { padding-left: 1.2em; }
.footnotes li { text-indent: 0; margin: 0.3em 0; }
"""

_markers_to_html = footnotes.markers_to_html


def _md_to_xhtml_body(md: str, *, anchored: bool = False) -> str:
    """Chuyển markdown đơn giản -> các đoạn <p>/<h2> (escape an toàn).

    Placeholder footnote (ký tự PUA) được giữ qua html.escape rồi đổi thành <sup>.

    `anchored=True` gắn thêm `data-n2e-p="<chỉ số>"` cho từng đoạn, để trình
    đọc ngoài (readest) định vị được đoạn mà gọi API sửa. Chỉ số đếm theo
    DÒNG-KHÔNG-RỖNG xuyên suốt cả chương, kể cả heading — khớp chính xác
    `notes.split_paras`, tức là thứ `notes.replace_para` dùng để ghi. Đếm theo
    block cách-dòng-trống (cách hàm này tách khối) sẽ lệch ở chương có block
    nhiều dòng, và mọi lần sửa sau đó ghi nhầm đoạn.

    Hình thức hiển thị KHÔNG đổi khi bật neo: vẫn một <p> cho mỗi block, các
    dòng trong block vẫn nối bằng <br/>. Neo bọc trong <span> chứ không tách
    thành nhiều <p> để không đổi thụt đầu dòng và giãn cách của mọi EPUB cũ.
    """
    blocks: list[str] = []
    para_index = 0
    for block in re.split(r"\n\s*\n", md.strip()):
        block = block.strip()
        if not block:
            continue
        # `\s+` trong regex khớp cả xuống dòng, nên block 2 dòng mà dòng đầu chỉ
        # có dấu thăng ("#", "## ") sẽ bị nuốt thành MỘT <h2> — một neo cho hai
        # dòng của split_paras, lệch toàn bộ chỉ số phía sau. Heading thật luôn
        # là block một dòng, nên chặn ở đây.
        heading = re.match(r"^#{1,6}\s+(.*)$", block) if "\n" not in block else None
        if heading:
            inner = _markers_to_html(html.escape(heading.group(1).strip()))
            attr = f' data-n2e-p="{para_index}"' if anchored else ""
            blocks.append(f"<h2{attr}>{inner}</h2>")
            para_index += 1
            continue
        # Gộp các dòng trong cùng đoạn, xuống dòng -> <br/>
        rendered: list[str] = []
        for line in block.splitlines():
            if not line.strip():
                continue
            inner = _markers_to_html(html.escape(line.strip()))
            if anchored:
                inner = f'<span data-n2e-p="{para_index}">{inner}</span>'
            rendered.append(inner)
            para_index += 1
        blocks.append("<p>" + "<br/>".join(rendered) + "</p>")
    return "\n".join(blocks)


_render_footnotes = footnotes.render_footnotes_html


def build_epub(
    manifest: Manifest,
    chapters_html: list[tuple[Chapter, str, str]],
    out_path: str | Path,
    language: str = "vi",
    cover_path: str | Path | None = None,
    footnotes_by_stem: dict[str, list[dict]] | None = None,
    metadata: NovelConfig | None = None,
    anchored_stems: set[str] | None = None,
) -> Path:
    """chapters_html: danh sách (chapter, tiêu_đề_hiển_thị, nội_dung_markdown).

    Ưu tiên metadata tiếng Việt (title/author/description) nếu có; nhúng
    ảnh bìa khi cover_path tồn tại. `footnotes_by_stem` (tùy chọn) map ch.stem ->
    danh sách footnote để render khối chú thích ở cuối chương tương ứng.
    `metadata` (tùy chọn) cung cấp publisher/pubdate/subjects/series/series_index/
    identifier/date_added — field rỗng bị bỏ qua, không ghi giá trị trống vào EPUB
    (xem spec ebook-metadata).

    `anchored_stems` (tùy chọn): tập `ch.stem` được gắn neo `data-n2e-p`.
    CHỈ truyền stem của chương có BẢN DỊCH — chương rơi về `raw_text` chứa
    văn bản Hán gốc, mà API sửa lại ghi vào `translated_text`; gắn neo cho
    chúng là mời người dùng sửa nhầm cột.
    """
    footnotes_by_stem = footnotes_by_stem or {}
    anchored_stems = anchored_stems or set()
    try:
        from ebooklib import epub
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Chưa cài ebooklib. Chạy: pip install ebooklib"
        ) from e

    book = epub.EpubBook()
    identifier = (metadata.identifier if metadata else "") or f"novel2epub-{manifest.slug}"
    book.set_identifier(identifier)
    book.set_title(manifest.title or manifest.slug)
    book.set_language(language)
    author = manifest.author
    if author:
        book.add_author(author)
    description = manifest.description
    if description:
        book.add_metadata("DC", "description", description)

    if metadata is not None:
        if metadata.publisher:
            book.add_metadata("DC", "publisher", metadata.publisher)
        if metadata.pubdate:
            book.add_metadata("DC", "date", metadata.pubdate)
        for subject in metadata.subjects:
            if subject:
                book.add_metadata("DC", "subject", subject)
        if metadata.series:
            book.add_metadata(None, "meta", "", {"name": "calibre:series", "content": metadata.series})
            if metadata.series_index:
                book.add_metadata(
                    None, "meta", "", {"name": "calibre:series_index", "content": metadata.series_index}
                )
        if metadata.date_added:
            book.add_metadata(None, "meta", "", {"name": "calibre:timestamp", "content": metadata.date_added})

    if cover_path is not None:
        cover_path = Path(cover_path)
        if cover_path.exists():
            book.set_cover(cover_path.name, cover_path.read_bytes())

    css = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=_CSS,
    )
    book.add_item(css)

    epub_chapters = []
    for ch, title, md in chapters_html:
        item = epub.EpubHtml(
            title=title,
            file_name=f"chap_{ch.stem}.xhtml",
            lang=language,
        )
        body = _md_to_xhtml_body(md, anchored=ch.stem in anchored_stems)
        body += _render_footnotes(footnotes_by_stem.get(ch.stem, []))
        item.content = (
            f"<html><head><title>{html.escape(title)}</title>"
            f'<link rel="stylesheet" href="style/main.css" type="text/css"/></head>'
            f"<body><h1>{html.escape(title)}</h1>{body}</body></html>"
        )
        item.add_item(css)
        book.add_item(item)
        epub_chapters.append(item)

    book.toc = tuple(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *epub_chapters]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    return out_path
