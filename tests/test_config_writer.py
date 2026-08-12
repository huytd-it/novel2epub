from novel2epub.config import LibraryConfig, LibraryEntry, load_config, load_library
from novel2epub.config_writer import (
    add_ebook,
    clean_prompt_text,
    remove_ebook,
    save_library,
    update_defaults,
    update_ebook,
)
from tests.conftest import write_db_config


def _write_workspace(path):
    return write_db_config(
        path,
        defaults={
            "crawl": {"content_selector": "#default"},
            "translate": {"openai": {"base_url": "https://custom.test/v1"}},
        },
        ebooks={
            "a": {
                "novel": {"slug": "a", "title": "Cũ"},
                "crawl": {"toc_url": "https://a", "content_selector": "#old"},
            },
        },
    )


def test_update_ebook_merges_and_inherits(tmp_path):
    path = tmp_path / "novel2epub.db"
    _write_workspace(path)

    update_ebook(path, "a", {"crawl": {"content_selector": "#new"}})

    cfg = load_config(path, "a")
    assert cfg.crawl.content_selector == "#new"   # override
    assert cfg.crawl.toc_url == "https://a"       # giữ nguyên
    assert cfg.novel.slug == "a"
    assert cfg.translate.openai.base_url == "https://custom.test/v1"  # kế thừa từ defaults


def test_update_ebook_does_not_touch_siblings(tmp_path):
    path = tmp_path / "novel2epub.db"
    _write_workspace(path)
    # Thêm ebook thứ 2 rồi sửa ebook 'a' -> 'b' phải nguyên vẹn.
    add_ebook(path, "b", title="Bê", toc_url="https://b")
    update_ebook(path, "a", {"novel": {"title": "Mới"}})

    cfg_b = load_config(path, "b")
    assert cfg_b.novel.title == "Bê"
    assert cfg_b.crawl.toc_url == "https://b"
    assert load_config(path, "a").novel.title == "Mới"


def test_add_ebook_minimal_override_inherits_defaults(tmp_path):
    path = tmp_path / "novel2epub.db"
    _write_workspace(path)
    add_ebook(
        path,
        "test-truyen",
        title="Tên Truyện",
        toc_url="https://x/book/1/",
    )
    cfg = load_config(path, "test-truyen")
    assert cfg.novel.slug == "test-truyen"
    assert cfg.novel.title == "Tên Truyện"
    assert cfg.crawl.toc_url == "https://x/book/1/"
    # Vẫn kế thừa phần dùng chung từ defaults.
    assert cfg.translate.openai.base_url == "https://custom.test/v1"
    assert "test-truyen" in load_library(path).ebooks


def test_remove_ebook(tmp_path):
    path = tmp_path / "novel2epub.db"
    _write_workspace(path)
    add_ebook(path, "b", title="Bê", toc_url="https://b")
    remove_ebook(path, "a")
    lib = load_library(path)
    assert "a" not in lib.ebooks
    assert "b" in lib.ebooks


def test_save_library_keeps_bodies_and_syncs_slugs(tmp_path):
    path = tmp_path / "novel2epub.db"
    _write_workspace(path)
    lib = LibraryConfig(ebooks={"a": LibraryEntry(slug="a"), "c": LibraryEntry(slug="c")})
    save_library(path, lib)
    loaded = load_library(path)
    assert "a" in loaded.ebooks and "c" in loaded.ebooks
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


def test_update_defaults_persists_prompt_template(tmp_path):
    path = tmp_path / "novel2epub.db"
    write_db_config(path, ebooks={"a": {"novel": {"slug": "a"}, "crawl": {"toc_url": "https://a"}}})
    template = clean_prompt_text("Dòng 1\r\nDòng 2\r\nDòng 3")
    update_defaults(path, {"translate": {"openai": {"prompt_template": template}}})
    cfg = load_config(path, "a")
    assert cfg.translate.openai.prompt_template == "Dòng 1\nDòng 2\nDòng 3"


def test_global_ai_provider_with_per_ebook_model_overrides(tmp_path):
    path = tmp_path / "novel2epub.db"
    write_db_config(
        path,
        defaults={
            "global_ai": {
                "base_url": "https://global.example/v1",
                "api_key": "global-secret",
                "translation_model": "translate-global",
                "assistant_model": "assistant-global",
                "timeout_seconds": 45,
                "temperature": 0.2,
            }
        },
        ebooks={
            "a": {
                "novel": {"slug": "a"},
                "translate": {
                    "translation_model": "translate-ebook",
                    "openai": {
                        "base_url": "https://legacy-ebook.example/v1",
                        "api_key": "legacy-secret",
                    },
                },
                "ai": {
                    "assistant_model": "assistant-ebook",
                    "openai": {"api_key": "legacy-ai-secret"},
                },
            }
        },
    )

    cfg = load_config(path, "a")
    assert cfg.translate.openai.base_url == "https://global.example/v1"
    assert cfg.translate.openai.api_key == "global-secret"
    assert cfg.translate.openai.model == "translate-ebook"
    assert cfg.ai.openai.base_url == "https://global.example/v1"
    assert cfg.ai.openai.api_key == "global-secret"
    assert cfg.ai.openai.model == "assistant-ebook"
    assert cfg.translate.openai.timeout_seconds == 45
    assert cfg.ai.openai.temperature == 0.2


def test_update_ebook_discards_provider_credentials_but_keeps_model_overrides(tmp_path):
    path = tmp_path / "novel2epub.db"
    write_db_config(path, ebooks={"a": {"novel": {"slug": "a"}}})

    update_ebook(
        path,
        "a",
        {
            "translate": {
                "translation_model": "translation-override",
                "openai": {"base_url": "https://forbidden", "api_key": "secret"},
            },
            "ai": {
                "assistant_model": "assistant-override",
                "openai": {"api_key": "secret-2"},
            },
        },
    )

    import json
    from novel2epub.db import get_connection

    conn = get_connection(path)
    row = conn.execute(
        "SELECT translate_overrides_json, ai_overrides_json FROM ebooks WHERE slug='a'"
    ).fetchone()
    translate = json.loads(row[0])
    assistant = json.loads(row[1])
    assert translate == {"translation_model": "translation-override"}
    assert assistant == {"assistant_model": "assistant-override"}


def test_update_defaults_writes_shared_config_to_all_ebooks(tmp_path):
    """`translate`/`ai` dùng chung: ghi vào defaults, mọi ebook đều thấy."""
    path = tmp_path / "novel2epub.db"
    write_db_config(
        path,
        defaults={"translate": {"type": "none"}},
        ebooks={
            "a": {"novel": {"slug": "a"}},
            "b": {"novel": {"slug": "b"}, "crawl": {"toc_url": "https://b"}},
        },
    )

    update_defaults(path, {"translate": {"type": "openai", "openai": {"model": "new-model"}}})

    for slug in ("a", "b"):
        cfg = load_config(path, slug)
        assert cfg.translate.type == "openai"
        assert cfg.translate.openai.model == "new-model"
    # Phần per-ebook khác giữ nguyên.
    assert load_config(path, "b").crawl.toc_url == "https://b"
