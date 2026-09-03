"""Parser upload TXT/EPUB: tách chương, rút số, encoding fallback."""
from __future__ import annotations

import io

import pytest

from novel2epub.upload_parser import (
    ParseError,
    _parse_zh_number,
    extract_chapter_number,
    parse_upload_file,
    split_txt_chapters,
    suggest_slug,
)


def test_split_txt_mixed_headings():
    text = (
        "Tên Truyện\n"
        "Tác giả XYZ\n"
        "\n"
        "Chương 1: Khởi đầu\n"
        "Nội dung chương một dòng 1.\n"
        "Nội dung chương một dòng 2.\n"
        "\n"
        "Chapter 2\n"
        "Second chapter body.\n"
        "\n"
        "第3章 标题\n"
        "第三章内容。\n"
    )
    chapters = split_txt_chapters(text)
    assert [t for t, _ in chapters] == ["Chương 1: Khởi đầu", "Chapter 2", "第3章 标题"]
    assert "dòng 1" in chapters[0][1]
    assert "Second chapter" in chapters[1][1]


def test_split_txt_no_heading_raises():
    with pytest.raises(ParseError, match="Không tìm thấy tiêu đề"):
        split_txt_chapters("Chỉ là đoạn văn.\nKhông có tiêu đề chương nào.\n")


def test_split_txt_heading_only_without_body_skipped_but_rest_kept():
    chapters = split_txt_chapters("Chương 1\n\n\nChương 2\nCó nội dung.\n")
    assert [t for t, _ in chapters] == ["Chương 2"]


def test_extract_chapter_number_cases():
    assert extract_chapter_number("Chương 12: Tên") == 12
    assert extract_chapter_number("Chương 12.1") == 12
    assert extract_chapter_number("chapter 7") == 7
    assert extract_chapter_number("Ch. 9") == 9
    assert extract_chapter_number("Hồi 3") == 3
    assert extract_chapter_number("第123章 标题") == 123
    assert extract_chapter_number("Tiêu đề không số") is None
    # Số Hán thuần → rút được số
    assert extract_chapter_number("第十章") == 10
    # "Chương một" (số bằng chữ) → heading nhưng không rút được số
    assert extract_chapter_number("Chương một: Mở đầu") is None


def test_parse_zh_number():
    assert _parse_zh_number("123") == 123
    assert _parse_zh_number("十") == 10
    assert _parse_zh_number("十二") == 12
    assert _parse_zh_number("二十") == 20
    assert _parse_zh_number("一百二十三") == 123
    assert _parse_zh_number("abc") is None


def test_txt_gb18030_fallback():
    text = "Chương 1\nNội dung tiếng Trung 中文内容。\n\nChương 2\nTiếp theo。\n"
    raw = text.encode("gb18030")
    # Đảm bảo bytes này KHÔNG decode được bằng utf-8 strict
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    book = parse_upload_file("truyen.txt", raw)
    assert len(book.chapters) == 2
    assert "中文内容" in book.chapters[0].content
    assert book.chapters[0].index == 1
    assert book.title == "truyen"


def test_txt_chapter_index_none_when_no_number():
    book = parse_upload_file("a.txt", "Chương một\nNội dung.\n".encode("utf-8"))
    assert len(book.chapters) == 1
    assert book.chapters[0].index is None


def test_unsupported_extension_raises():
    with pytest.raises(ParseError, match="không hỗ trợ"):
        parse_upload_file("truyen.pdf", b"data")


def test_suggest_slug_from_title_then_filename():
    assert suggest_slug("Tên Truyện Hay", "x.txt") == "ten-truyen-hay"
    assert suggest_slug("", "My Story File.txt") == "my-story-file"
    assert suggest_slug("纯中文标题", "纯中文.txt") == ""


def _build_epub_bytes() -> bytes:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Truyện EPUB Test")
    book.add_author("Tác Giả Test")
    c1 = epub.EpubHtml(title="Chương 1", file_name="ch1.xhtml", lang="zh")
    c1.content = "<h1>Chương 1</h1><p>Nội dung một.</p>"
    c2 = epub.EpubHtml(title="Chương 2", file_name="ch2.xhtml", lang="zh")
    c2.content = "<h1>Chương 2</h1><p>Nội dung hai.</p>"
    book.add_item(c1)
    book.add_item(c2)
    book.spine = ["nav", c1, c2]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    # Ảnh bìa fake (PNG 1px)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    book.set_cover("cover.png", png, create_page=False)
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def test_parse_epub_chapters_and_cover():
    data = _build_epub_bytes()
    book = parse_upload_file("truyen.epub", data)
    assert book.title == "Truyện EPUB Test"
    assert book.author == "Tác Giả Test"
    assert len(book.chapters) == 2
    assert "Nội dung một" in book.chapters[0].content
    assert "<" not in book.chapters[0].content  # đã strip HTML
    assert book.cover_bytes is not None
    assert book.cover_ext == "png"


def test_parse_epub_invalid_bytes_raises():
    with pytest.raises(ParseError):
        parse_upload_file("bad.epub", b"not an epub")
