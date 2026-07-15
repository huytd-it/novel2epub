"""Tests cho việc đưa log của novel2epub.* (crawler, search...) lên job log UI.

Trước đây handler chỉ gắn cho logger 'novel2epub.web' với propagate=False, nên
mọi logger.info() trong crawler.py (vd "Mục lục — trang 1: 0 chương") không tới
đâu cả — user nhìn UI chỉ thấy lỗi mơ hồ cuối cùng, không thấy chỗ thật sự hỏng.
"""
from __future__ import annotations

import logging
import threading

import pytest

from app.logging_config import JobLogHandler, job_log_capture


@pytest.fixture
def parent_logger():
    """Cô lập logger 'novel2epub': test khác có thể đã gọi setup_logging() và
    gắn handler sẵn, gắn chồng thêm sẽ làm log bị nhân đôi trong test."""
    parent = logging.getLogger("novel2epub")
    saved_handlers = parent.handlers[:]
    saved_level = parent.level
    parent.handlers = []
    parent.setLevel(logging.INFO)
    try:
        yield parent
    finally:
        parent.handlers = saved_handlers
        parent.setLevel(saved_level)


def _attach(parent: logging.Logger) -> JobLogHandler:
    handler = JobLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    parent.addHandler(handler)
    return handler


def test_crawler_log_lands_in_job_buffer(parent_logger):
    _attach(parent_logger)
    buf: list[str] = []

    with job_log_capture(buf):
        logging.getLogger("novel2epub.crawler").info("Mục lục — trang 1: %s chương", 0)

    assert any("Mục lục — trang 1: 0 chương" in ln for ln in buf), buf


def test_no_capture_outside_context(parent_logger):
    """Ngoài phạm vi job, log không được rò vào buffer của job nào."""
    _attach(parent_logger)
    buf: list[str] = []

    with job_log_capture(buf):
        pass
    logging.getLogger("novel2epub.crawler").info("sau khi job xong")

    assert buf == []


def test_web_logger_records_are_skipped_to_avoid_duplicates(parent_logger):
    """log_fn đã append thẳng vào job.log rồi mới logger.info() — không nhân đôi."""
    _attach(parent_logger)
    buf: list[str] = []

    with job_log_capture(buf):
        logging.getLogger("novel2epub.web").info("[crawl] Đọc mục lục: http://x")

    assert buf == [], f"log .web bị nhân đôi vào job.log: {buf}"


def test_capture_works_with_deque_buffer(parent_logger):
    """Job.log là deque(maxlen=500), không phải list — capture phải chạy đúng."""
    from collections import deque

    _attach(parent_logger)
    buf: deque = deque(maxlen=500)

    with job_log_capture(buf):
        logging.getLogger("novel2epub.crawler").info("Mục lục — trang 2: 40 chương")

    assert list(buf) == ["Mục lục — trang 2: 40 chương"]


def test_capture_is_isolated_per_thread(parent_logger):
    """Nhiều job chạy song song (queue có N worker) — log không được lẫn sang job khác."""
    _attach(parent_logger)
    buf_a: list[str] = []
    buf_b: list[str] = []
    started = threading.Barrier(2)

    def worker(buf: list[str], marker: str) -> None:
        with job_log_capture(buf):
            started.wait()
            logging.getLogger("novel2epub.crawler").info("job %s", marker)

    ta = threading.Thread(target=worker, args=(buf_a, "A"))
    tb = threading.Thread(target=worker, args=(buf_b, "B"))
    ta.start(); tb.start()
    ta.join(); tb.join()

    assert buf_a == ["job A"], buf_a
    assert buf_b == ["job B"], buf_b
