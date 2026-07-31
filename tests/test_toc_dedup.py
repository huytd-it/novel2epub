from novel2epub.crawler import _dedupe_keep_last
from novel2epub.storage import Chapter
from novel2epub.toc import mark_duplicate_chapters


def test_dedupe_keep_last_keeps_last_exact_pair_and_order():
    pairs = [
        ("http://x/1", "Chương 1"),
        ("http://x/2", "Chương 2"),
        ("http://x/1", "Chương 1"),
        ("http://x/3", "Chương 3"),
    ]

    assert _dedupe_keep_last(pairs) == [
        ("http://x/2", "Chương 2"),
        ("http://x/1", "Chương 1"),
        ("http://x/3", "Chương 3"),
    ]


def test_dedupe_keep_last_keeps_same_url_with_different_titles():
    pairs = [("http://x/1", "Chương 1"), ("http://x/1", "Chương 1 sửa")]

    assert _dedupe_keep_last(pairs) == pairs


def test_dedupe_keep_last_drops_empty_title_when_url_has_title():
    pairs = [("http://x/1", ""), ("http://x/2", "Chương 2"), ("http://x/1", "Chương 1")]

    assert _dedupe_keep_last(pairs) == [("http://x/2", "Chương 2"), ("http://x/1", "Chương 1")]


def test_mark_duplicate_chapters_only_flags_exact_url_title_match():
    chapters = [
        Chapter(index=1, url="http://x/1", title="Chương 1"),
        Chapter(index=2, url="http://x/1", title="Chương 1"),
        Chapter(index=3, url="http://x/1", title="Chương 1 sửa"),
    ]

    mark_duplicate_chapters(chapters)

    assert chapters[1].duplicate_of == 1
    assert "duplicate" in chapters[1].missing_fields
    assert chapters[2].duplicate_of is None
    assert "duplicate" not in chapters[2].missing_fields


def test_mark_duplicate_chapters_flags_empty_title_for_seen_url():
    chapters = [
        Chapter(index=1, url="http://x/1", title="Chương 1"),
        Chapter(index=2, url="http://x/1", title=""),
    ]

    mark_duplicate_chapters(chapters)

    assert chapters[1].duplicate_of == 1
    assert "duplicate" in chapters[1].missing_fields
