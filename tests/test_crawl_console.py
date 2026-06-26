"""Crawl console: phân biệt missing/empty/ok + danh sách retry (xem spec
crawl-management)."""
from __future__ import annotations

from novel2epub.storage import Chapter, Storage
from novel2epub.toc import chapter_crawl_status, crawl_problem_indexes


def test_status_missing_when_no_raw_file(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    ch = Chapter(index=1, url="http://x/1")
    assert chapter_crawl_status(ch, storage) == "missing"


def test_status_empty_when_below_min_chars(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    ch = Chapter(index=1, url="http://x/1")
    storage.write_raw(ch, "x")
    assert chapter_crawl_status(ch, storage, min_chars=30) == "empty"


def test_status_ok_when_content_above_threshold(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    ch = Chapter(index=1, url="http://x/1")
    storage.write_raw(ch, "nội dung đủ dài để vượt ngưỡng tối thiểu của bài test này")
    assert chapter_crawl_status(ch, storage, min_chars=30) == "ok"


def test_crawl_problem_indexes_includes_missing_and_empty_only(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    chapters = [Chapter(index=i, url=f"http://x/{i}") for i in range(1, 4)]
    storage.write_raw(chapters[0], "nội dung đủ dài để vượt ngưỡng tối thiểu của bài test này")
    storage.write_raw(chapters[1], "x")  # empty
    # chapters[2]: missing (chưa crawl)
    assert crawl_problem_indexes(chapters, storage, min_chars=30) == [2, 3]
