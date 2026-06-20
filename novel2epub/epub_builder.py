"""Đóng gói các chương đã dịch thành file EPUB bằng ebooklib."""
from __future__ import annotations

import html
import re
from pathlib import Path

from ebooklib import epub

from .storage import Chapter, Manifest

_CSS = """
body { font-family: serif; line-height: 1.6; margin: 5%; }
h1 { text-align: center; font-size: 1.4em; margin: 1em 0; }
p { text-indent: 1.5em; margin: 0.4em 0; text-align: justify; }
"""


def _md_to_xhtml_body(md: str) -> str:
    """Chuyển markdown đơn giản -> các đoạn <p>/<h2> (escape an toàn)."""
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", md.strip()):
        block = block.strip()
        if not block:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", block)
        if heading:
            blocks.append(f"<h2>{html.escape(heading.group(1).strip())}</h2>")
            continue
        # Gộp các dòng trong cùng đoạn, xuống dòng -> <br/>
        lines = [html.escape(ln.strip()) for ln in block.splitlines() if ln.strip()]
        blocks.append("<p>" + "<br/>".join(lines) + "</p>")
    return "\n".join(blocks)


def build_epub(
    manifest: Manifest,
    chapters_html: list[tuple[Chapter, str, str]],
    out_path: str | Path,
    language: str = "vi",
) -> Path:
    """chapters_html: danh sách (chapter, tiêu_đề_hiển_thị, nội_dung_markdown)."""
    book = epub.EpubBook()
    book.set_identifier(f"novel2epub-{manifest.slug}")
    book.set_title(manifest.title or manifest.slug)
    book.set_language(language)
    if manifest.author:
        book.add_author(manifest.author)

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
        body = _md_to_xhtml_body(md)
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
