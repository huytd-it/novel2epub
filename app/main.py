"""Web UI cho novel2epub: chạy crawl/translate/build, xem & sửa tay bản dịch.

Chạy: uvicorn app.main:app --reload   (từ thư mục novel2epub/)
Đường dẫn config gộp lấy từ biến môi trường NOVEL2EPUB_FILE (mặc định novel2epub.yaml).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import deps
from .deps import BASE_DIR, WORKSPACE_PATH
from .job import JobRunner
from .logging_config import setup_logging
from .routes import (
    automation,
    chapters,
    characters,
    dashboard,
    ebooks,
    glossary,
    idioms,
    jobs,
    library,
    notes,
    opds,
    reader,
    settings,
    sources,
    storage,
)
from .scheduler import AutomationScheduler

setup_logging()


# Đọc queue.translate_workers / queue.crawl_workers từ defaults: trong config.
# Nếu file chưa tồn tại hoặc parse lỗi → dùng mặc định của QueueConfig (5/2).
def _load_queue_workers() -> dict[str, int]:
    from novel2epub.config import QueueConfig, load_config
    try:
        _cfg = load_config(WORKSPACE_PATH)
        return {
            "translate": _cfg.queue.translate_workers,
            "crawl": _cfg.queue.crawl_workers,
        }
    except Exception:
        _dq = QueueConfig()
        return {"translate": _dq.translate_workers, "crawl": _dq.crawl_workers}


def _cors_origins(path: str | None = None) -> list[str]:
    """Origin được phép gọi chéo — chỉ bản readest WEB cần (Tauri desktop và
    mobile gọi HTTP native, không đi qua CORS).

    "*" bị loại thẳng: kết hợp với credential nó phá luôn ý nghĩa của token,
    và không có tình huống nào ở đây cần nó.
    """
    from novel2epub.config import load_config

    try:
        cfg = load_config(path or WORKSPACE_PATH)
    except Exception:
        return []
    return [o for o in cfg.api.cors_origins if o and o != "*"]


app = FastAPI(title="novel2epub")
# ponytail: add GZip compression for faster page loads
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# Đường dẫn được phép nhận CORS — CHỈ OPDS + API sửa đoạn, không bao giờ mở
# rộng ra /settings hay bất kỳ route web UI nào khác (token bị lộ ở
# /settings/api dạng cleartext, xem finding review nhánh readest-opds-integration).
_CORS_PREFIXES = ("/opds", "/api/v1")


def _cors_eligible_path(path: str) -> bool:
    return path.startswith(_CORS_PREFIXES)


@app.middleware("http")
async def opds_api_cors(request: Request, call_next):
    """CORS thủ công, chỉ áp cho /opds/* và /api/v1/* — KHÔNG dùng
    `CORSMiddleware` app-wide: nó sẽ mở luôn `/settings/api`, nơi token hiện
    ra cleartext trong HTML, cho origin đã cấu hình đọc trộm qua fetch().

    Đọc `cors_origins` MỚI mỗi request (không cache ở import time) để khớp
    hành vi với token — sửa trong Cài đặt có hiệu lực ngay, không cần restart.

    `allow_credentials` không bật: auth ở đây là header `Authorization`
    tường minh (Basic/Bearer), không phải cookie/session — không có state nào
    để "credentials" bảo vệ, bật lên chỉ khiến trình duyệt sẵn sàng đính kèm
    state ẩn cho request chéo mà không được lợi gì.
    """
    path = request.url.path
    origin = request.headers.get("origin")

    if not _cors_eligible_path(path) or not origin:
        return await call_next(request)

    allowed = _cors_origins()
    if origin not in allowed:
        return await call_next(request)

    if request.method == "OPTIONS":
        response = Response(status_code=200)
    else:
        response = await call_next(request)

    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, PATCH, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return response


@app.middleware("http")
async def cache_policy(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store"
    return response

app.state.job = JobRunner(
    db_path=deps.DB_PATH,
    workers=_load_queue_workers(),
)
# Đăng ký các loại job tuỳ biến còn dang dở lúc shutdown (spec JSON-serializable
# trong queue_pending.json) trước khi nạp lại — job pending có kind chưa
# register sẽ bị bỏ qua vĩnh viễn (xem JobQueue.register_kind/load_pending).
app.state.job.queue.register_kind("batch-translate", chapters.batch_translate_job_factory)
app.state.job.queue.register_kind("publish-reader", ebooks.publish_reader_job_factory)
app.state.job.queue.register_kind("glossary-approve", glossary.glossary_approve_job_factory)
app.state.job.queue.register_kind("opds-autobuild", opds.autobuild_job_factory)
app.state.job.queue.load_pending()
app.state.scheduler = AutomationScheduler(deps.DB_PATH, WORKSPACE_PATH, app.state.job.queue)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler.start()
    yield
    app.state.scheduler.stop()


app.router.lifespan_context = lifespan

app.include_router(ebooks.router)
app.include_router(chapters.router)
app.include_router(characters.router)
app.include_router(glossary.router)
app.include_router(idioms.router)
app.include_router(jobs.router)
app.include_router(library.router)
app.include_router(settings.router)
app.include_router(sources.router)
app.include_router(storage.router)
app.include_router(notes.router)
app.include_router(reader.router)
app.include_router(automation.router)
app.include_router(dashboard.router)
app.include_router(opds.router)
