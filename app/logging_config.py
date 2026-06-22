"""Cấu hình logging chi tiết ra file cho web UI.

Mọi dòng log của job (crawl/dịch/build...) được ghi ra `logs/app.log` (xoay
vòng theo dung lượng) kèm traceback đầy đủ khi có lỗi, độc lập với buffer
log trong bộ nhớ (giới hạn dòng, mất khi job mới bắt đầu) dùng để hiển thị
trên UI.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .deps import BASE_DIR

LOG_DIR = BASE_DIR.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"

logger = logging.getLogger("novel2epub.web")


def setup_logging() -> None:
    if logger.handlers:
        return  # tránh gắn handler trùng khi reload

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
