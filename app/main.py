"""Web UI cho novel2epub: chạy crawl/translate/build, xem & sửa tay bản dịch.

Chạy: uvicorn app.main:app --reload   (từ thư mục novel2epub/)
Đường dẫn config gộp lấy từ biến môi trường NOVEL2EPUB_FILE (mặc định novel2epub.yaml).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .deps import AUTOMATIONS_PATH, BASE_DIR, WORKSPACE_DIR, WORKSPACE_PATH
from .job import JobRunner
from .logging_config import setup_logging
from .routes import automation, chapters, ebooks, glossary, jobs, library, settings, storage
from .scheduler import AutomationScheduler

setup_logging()

app = FastAPI(title="novel2epub")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.state.job = JobRunner(history_path=WORKSPACE_DIR / "queue_history.json")
app.state.scheduler = AutomationScheduler(AUTOMATIONS_PATH, WORKSPACE_PATH, app.state.job.queue)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler.start()
    yield
    app.state.scheduler.stop()


app.router.lifespan_context = lifespan

app.include_router(ebooks.router)
app.include_router(chapters.router)
app.include_router(glossary.router)
app.include_router(jobs.router)
app.include_router(library.router)
app.include_router(settings.router)
app.include_router(storage.router)
app.include_router(automation.router)
