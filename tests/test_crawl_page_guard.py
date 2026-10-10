"""Guard bắt buộc khi crawl chương nhiều trang: lỗi một trang con ⇒ chương
thất bại và KHÔNG ghi raw vào bảng chapters (xem `fetch_chapter_paginated`).
"""
from __future__ import annotations

from novel2epub import pipeline
from novel2epub.config import (
    Config,
    CrawlConfig,
    CrawlRetryConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.crawler import ChapterPageError
from novel2epub.storage import Chapter, Manifest, Storage


class _PageFailingCrawler:
    """Chương 2 luôn hỏng ở trang con thứ 2; các chương khác tải bình thường."""

    def __init__(self):
        self.calls: list[int] = []

    def fetch_chapter(self, ch):
        self.calls.append(ch.index)
        if ch.index == 2:
            raise ChapterPageError("Chương 0002: lỗi tải trang 2 (http://x/2_2): timed out")
        return f"noi dung moi {ch.index}"

    def sleep(self):
        pass

    def close(self):
        pass


def _crawl(tmp_path, monkeypatch, **kwargs):
    crawler = _PageFailingCrawler()
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: crawler)
    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(
            toc_url="http://x/book/1/", delay_seconds=0, max_workers=1,
            retry=CrawlRetryConfig(attempts=1, delay_seconds=0),
        ),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    logs: list[str] = []
    pipeline.step_crawl_selected(cfg, logs.append, **kwargs)
    return crawler, logs


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    return storage, chapters


def test_chapter_with_failed_page_is_not_written(tmp_path, monkeypatch):
    storage, chapters = _seed(tmp_path)

    crawler, logs = _crawl(tmp_path, monkeypatch)

    assert [storage.has_raw(ch) for ch in chapters] == [True, False, True]
    assert storage.raw_len(chapters[1]) is None  # không có cả raw rỗng
    # Cả chương được thử lại trọn vẹn (1 lần đầu + 1 retry) rồi mới bỏ qua.
    assert crawler.calls.count(2) == 2
    statuses = {ch.index: ch.last_action_status for ch in storage.load_manifest().chapters}
    assert statuses[2] == "failed"
    assert any("Bỏ qua chương 0002" in line for line in logs)


def test_failed_recrawl_keeps_existing_raw(tmp_path, monkeypatch):
    storage, chapters = _seed(tmp_path)
    storage.write_raw(chapters[1], "noi dung cu day du")

    _crawl(tmp_path, monkeypatch, force=True, selected_indexes=[2])

    assert storage.read_raw(chapters[1]) == "noi dung cu day du"
