from pathlib import Path

from novel2epub.config import LibraryConfig, LibraryEntry, load_config, load_library
from novel2epub.config_writer import (
    save_library,
    scaffold_config_file,
    update_config_file,
)
from novel2epub.sources import SourcePreset, load_presets, save_presets


def test_update_preserves_comments_and_only_changes_target(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "# comment đầu file\n"
        "novel:\n"
        "  slug: old-slug  # giữ comment này\n"
        "  title: Cũ\n"
        "crawl:\n"
        "  toc_url: https://a\n"
        "  content_selector: '#old'\n",
        encoding="utf-8",
    )

    update_config_file(path, {"crawl": {"content_selector": "#new"}})

    text = path.read_text(encoding="utf-8")
    assert "# comment đầu file" in text
    assert "# giữ comment này" in text
    assert "#new" in text
    # Key không đụng tới vẫn nguyên
    cfg = load_config(path)
    assert cfg.crawl.content_selector == "#new"
    assert cfg.crawl.toc_url == "https://a"
    assert cfg.novel.slug == "old-slug"


def test_scaffold_creates_config_from_example(tmp_path):
    dest = tmp_path / "configs" / "test-truyen.yaml"
    preset = SourcePreset(name="biquge", content_selector="#chaptercontent")
    scaffold_config_file(
        dest,
        slug="test-truyen",
        title="Tên Truyện",
        toc_url="https://x/book/1/",
        engine="http",
        preset=preset.crawl_overrides(),
    )
    assert dest.exists()
    cfg = load_config(dest)
    assert cfg.novel.slug == "test-truyen"
    assert cfg.novel.title == "Tên Truyện"
    assert cfg.crawl.toc_url == "https://x/book/1/"
    assert cfg.crawl.content_selector == "#chaptercontent"


def test_save_library_round_trip(tmp_path):
    path = tmp_path / "library.yaml"
    lib = LibraryConfig(ebooks={"a": LibraryEntry(slug="a", name="A", config="configs/a.yaml")})
    save_library(path, lib)
    loaded = load_library(path)
    assert "a" in loaded.ebooks
    assert loaded.ebooks["a"].config == "configs/a.yaml"


def test_sources_round_trip(tmp_path):
    path = tmp_path / "sources.yaml"
    presets = {"biquge": SourcePreset(name="biquge", engine="http", content_selector="#content", headless=False)}
    save_presets(path, presets)
    loaded = load_presets(path)
    assert loaded["biquge"].content_selector == "#content"
    assert loaded["biquge"].headless is False
    assert "toc_url" not in loaded["biquge"].crawl_overrides()
