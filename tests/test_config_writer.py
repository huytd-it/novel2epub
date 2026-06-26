from novel2epub.config import LibraryConfig, LibraryEntry, load_config, load_library
from novel2epub.config_writer import (
    add_ebook,
    clean_prompt_text,
    remove_ebook,
    save_library,
    update_ebook,
)



def _write_workspace(path):
    path.write_text(
        "# comment đầu file\n"
        "defaults:\n"
        "  crawl:\n"
        "    content_selector: '#default'\n"
        "  translate:\n"
        "    openai:\n"
        "      base_url: https://custom.test/v1\n"
        "ebooks:\n"
        "  a:\n"
        "    name: A  # giữ comment này\n"
        "    novel:\n"
        "      slug: a\n"
        "      title: Cũ\n"
        "    crawl:\n"
        "      toc_url: https://a\n"
        "      content_selector: '#old'\n",
        encoding="utf-8",
    )


def test_update_ebook_preserves_comments_and_inheritance(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    _write_workspace(path)

    update_ebook(path, "a", {"crawl": {"content_selector": "#new"}})

    text = path.read_text(encoding="utf-8")
    assert "# comment đầu file" in text
    assert "# giữ comment này" in text
    assert "#new" in text

    cfg = load_config(path, "a")
    assert cfg.crawl.content_selector == "#new"   # override
    assert cfg.crawl.toc_url == "https://a"       # giữ nguyên
    assert cfg.novel.slug == "a"
    assert cfg.translate.openai.base_url == "https://custom.test/v1"  # kế thừa từ defaults


def test_update_ebook_does_not_touch_siblings(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    _write_workspace(path)
    # Thêm ebook thứ 2 rồi sửa ebook 'a' -> 'b' phải nguyên vẹn.
    add_ebook(path, "b", name="B", title="Bê", toc_url="https://b", engine="scrapling")
    update_ebook(path, "a", {"novel": {"title": "Mới"}})

    cfg_b = load_config(path, "b")
    assert cfg_b.novel.title == "Bê"
    assert cfg_b.crawl.toc_url == "https://b"
    assert load_config(path, "a").novel.title == "Mới"


def test_add_ebook_minimal_override_inherits_defaults(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    _write_workspace(path)
    add_ebook(
        path,
        "test-truyen",
        name="Tên Truyện",
        title="Tên Truyện",
        toc_url="https://x/book/1/",
        engine="scrapling",
    )
    cfg = load_config(path, "test-truyen")
    assert cfg.novel.slug == "test-truyen"
    assert cfg.novel.title == "Tên Truyện"
    assert cfg.crawl.toc_url == "https://x/book/1/"
    # Vẫn kế thừa phần dùng chung từ defaults.
    assert cfg.translate.openai.base_url == "https://custom.test/v1"
    assert "test-truyen" in load_library(path).ebooks


def test_remove_ebook(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    _write_workspace(path)
    add_ebook(path, "b", name="B", title="Bê", toc_url="https://b")
    remove_ebook(path, "a")
    lib = load_library(path)
    assert "a" not in lib.ebooks
    assert "b" in lib.ebooks


def test_save_library_syncs_names_keeps_bodies(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    _write_workspace(path)
    lib = LibraryConfig(ebooks={"a": LibraryEntry(slug="a", name="A mới")})
    save_library(path, lib)
    loaded = load_library(path)
    assert loaded.ebooks["a"].name == "A mới"
    # Override body của 'a' vẫn còn (không bị dựng lại từ đầu).
    assert load_config(path, "a").crawl.toc_url == "https://a"


def test_clean_prompt_text_normalizes_whitespace():
    raw = "  Dịch đoạn sau:  \r\n\r\n\r\n\r\n{text}   \r\n  Giữ {glossary}.  \r\n\r\n"
    cleaned = clean_prompt_text(raw)
    assert cleaned == "  Dịch đoạn sau:\n\n{text}\n  Giữ {glossary}."
    assert "{text}" in cleaned and "{glossary}" in cleaned
    assert "\r" not in cleaned
    assert not any(line != line.rstrip() for line in cleaned.split("\n"))
    assert cleaned == cleaned.strip("\n")


def test_update_ebook_cleans_crlf_prompt_no_blank_lines(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        "ebooks:\n  a:\n    crawl:\n      toc_url: https://a\n", encoding="utf-8"
    )
    template = clean_prompt_text("Dòng 1\r\nDòng 2\r\nDòng 3")
    update_ebook(path, "a", {"translate": {"openai": {"prompt_template": template}}})
    text = path.read_text(encoding="utf-8")
    # Block scalar literal: 3 dòng liền nhau, KHÔNG chèn dòng trống khi round-trip.
    assert "\n\nDòng 2" not in text and "\r" not in text
    cfg = load_config(path, "a")
    assert cfg.translate.openai.prompt_template == "Dòng 1\nDòng 2\nDòng 3"



