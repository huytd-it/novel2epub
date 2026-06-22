"""Web UI cho novel2epub: chạy crawl/translate/build, xem & sửa tay bản dịch.

Chạy: uvicorn app.main:app --reload   (từ thư mục novel2epub/)
Đường dẫn config lấy từ biến môi trường NOVEL2EPUB_CONFIG (mặc định config.yaml).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .deps import BASE_DIR
from .job import JobRunner
from .logging_config import setup_logging
from .routes import chapters, ebooks, glossary, jobs, library, preset_builder, settings, sources

setup_logging()

app = FastAPI(title="novel2epub")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.state.job = JobRunner()

app.include_router(ebooks.router)
app.include_router(chapters.router)
app.include_router(glossary.router)
app.include_router(jobs.router)
app.include_router(library.router)
app.include_router(preset_builder.router)
app.include_router(settings.router)
app.include_router(sources.router)
