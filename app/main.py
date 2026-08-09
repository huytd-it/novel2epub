"""Web UI cho novel2epub: chạy crawl/translate/build, xem & sửa tay bản dịch.

Chạy: uvicorn app.main:app --reload   (từ thư mục novel2epub/)
Đường dẫn config gộp lấy từ biến môi trường NOVEL2EPUB_FILE (mặc định novel2epub.yaml).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import deps
from .auth import check_api_auth
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
    webui,
    wireguard,
)
from .scheduler import AutomationScheduler

setup_logging()


# Đọc số worker từng loại từ defaults trong config.
def _load_queue_workers() -> dict[str, int]:
    from novel2epub.config import QueueConfig, load_config
    try:
        _cfg = load_config(WORKSPACE_PATH)
        return {
            "crawl": _cfg.queue.crawl_workers,
            "local-mt": _cfg.queue.local_mt_workers,
            "ai-translate": _cfg.queue.translate_workers,
            "ai-edit": _cfg.queue.ai_edit_workers,
            "build": _cfg.queue.build_workers,
        }
    except Exception:
        _dq = QueueConfig()
        return {
            "crawl": _dq.crawl_workers,
            "local-mt": _dq.local_mt_workers,
            "ai-translate": _dq.translate_workers,
            "ai-edit": _dq.ai_edit_workers,
            "build": _dq.build_workers,
        }


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


app = FastAPI(
    title="novel2epub API",
    version="1.0.0",
    description=(
        "API crawl, dịch, biên tập và xuất EPUB. Swagger UI hỗ trợ thử các "
        "endpoint JSON; khi truy cập từ máy khác localhost, gửi token trong "
        "header `Authorization: Bearer <token>`."
    ),
    openapi_tags=[
        {"name": "Glossary", "description": "Glossary, hàng chờ duyệt và trích xuất tên riêng."},
        {"name": "Reader", "description": "Đọc, tìm kiếm và biên tập chương."},
        {"name": "Translation", "description": "Dịch AI và Local MT."},
    ],
)


def _load_oidc_validator():
    """Đọc OIDC global trực tiếp từ SQLite; không log config hay token."""
    from novel2epub.db import get_connection, init_schema
    from novel2epub.oidc import OIDCValidator, config_from_mapping

    conn = get_connection(deps.DB_PATH)
    try:
        init_schema(conn)
        row = conn.execute("SELECT oidc_json FROM settings WHERE id = 1").fetchone()
        config = config_from_mapping(json.loads(row["oidc_json"] or "{}") if row else {})
        return OIDCValidator(config) if config else None
    finally:
        conn.close()


app.state.oidc_validator = _load_oidc_validator()
# ponytail: add GZip compression for faster page loads
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)

# Đường dẫn được phép nhận CORS — CHỈ nhóm API thuần JSON, không bao giờ mở
# rộng ra /settings hay bất kỳ route web UI nào khác (token bị lộ ở
# /settings/api dạng cleartext, xem finding review nhánh readest-opds-integration).
#
# `/api` bao trọn `/api/v1` (readest), `/api/ui` (SPA) và các endpoint nội bộ
# mà SPA cần. An toàn vì KHÔNG route nào dưới `/api` trả secret — token chỉ
# xuất hiện trong HTML của trang `/settings/api`, và tiền tố đó không khớp.
_CORS_PREFIXES = ("/opds", "/api")

# Nhóm đường dẫn đòi token khi gọi từ ngoài localhost. Trước đây chỉ `/opds` và
# `/api/v1` được bảo vệ vì phần còn lại giả định "chỉ máy này gọi". Đưa SPA lên
# host khác (Vercel/Cloudflare Pages, backend qua Tailscale) phá vỡ đúng giả
# định đó: không chặn thì ai tới được cổng là điều khiển được crawler và queue.
#
# Web UI Jinja2 vẫn là công cụ chạy tại chỗ — mở qua http://localhost:8010 thì
# không đổi gì; mở qua địa chỉ tailnet thì các lời gọi `/api/*` của nó sẽ 401.
_AUTH_PREFIXES = ("/opds", "/api")


def _legacy_auth_path(path: str) -> bool:
    """Static token chỉ còn áp cho OPDS/v1/legacy; v2 dùng OIDC dependency."""
    return path.startswith(_AUTH_PREFIXES) and not path.startswith("/api/v2")


def _cors_eligible_path(path: str) -> bool:
    return path.startswith(_CORS_PREFIXES)


@app.middleware("http")
async def api_token_gate(request: Request, call_next):
    """Đòi token cho `/api/*` và `/opds/*` khi client không phải localhost.

    Đặt ở middleware chứ không phải dependency vì các router trộn lẫn route
    HTML và route JSON trong cùng một file (`jobs.py` vừa có trang `/queue`
    vừa có `/api/queue`), nên gắn theo router sẽ chặn nhầm trang.

    ĐĂNG KÝ TRƯỚC `opds_api_cors` là có chủ đích: Starlette chạy middleware
    đăng ký sau ở vòng NGOÀI, nên thứ tự này đặt CORS bọc ngoài auth. Ngược
    lại thì response 401 không đi qua lớp CORS, và trình duyệt sẽ báo "CORS
    error" mơ hồ thay vì để frontend đọc được "Token không hợp lệ".

    Preflight `OPTIONS` đi qua không kiểm tra: trình duyệt không đính kèm
    `Authorization` vào preflight, chặn ở đây thì mọi request chéo chết trước
    khi kịp gửi token.
    """
    if request.method == "OPTIONS" or not _legacy_auth_path(request.url.path):
        return await call_next(request)

    failure = check_api_auth(request)
    if failure is None:
        return await call_next(request)

    return JSONResponse(
        {"detail": failure.detail},
        status_code=failure.status,
        headers=failure.headers or None,
    )


@app.middleware("http")
async def opds_api_cors(request: Request, call_next):
    """CORS thủ công, chỉ áp cho /opds/* và /api/* — KHÔNG dùng
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
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


@app.middleware("http")
async def cache_policy(request: Request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
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

# SPA React build ra `app/webui/`. Chỉ gắn khi đã build — thiếu bundle thì
# server vẫn chạy bình thường với UI Jinja2 và `/app` trả 404.
_SPA_DIR = BASE_DIR / "webui"
_SPA_BUILT = (_SPA_DIR / "index.html").exists()

if _SPA_BUILT:
    # Giao diện mặc định là SPA. Đăng ký TRƯỚC `ebooks.router` vì router đó
    # cũng khai báo `/` (trang Thư viện Jinja2) và FastAPI khớp theo thứ tự
    # đăng ký — route nào vào trước thắng.
    #
    # Chỉ redirect chứ KHÔNG chuyển Jinja2 xuống tiền tố khác: SPA vẫn link
    # sang các trang cũ cho phần chưa port (wizard AI dò selector, nhập YAML
    # nguồn, TTS/dịch nhanh trong trang đọc, tải archive .zip), và mọi href
    # nội bộ trong template đều là đường dẫn tuyệt đối hiện tại.
    @app.get("/", include_in_schema=False)
    def spa_default():
        return RedirectResponse(url="/app/", status_code=307)

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
app.include_router(wireguard.router)
app.include_router(webui.router)


if _SPA_BUILT:
    app.mount("/app/assets", StaticFiles(directory=str(_SPA_DIR / "assets")), name="spa-assets")

    @app.get("/app")
    @app.get("/app/{path:path}")
    def spa(path: str = ""):
        """Mọi đường dẫn con trả về index.html để router phía client tự xử lý.

        File tĩnh ngoài `assets/` (favicon, font tải rời) vẫn phải trả đúng
        file, nếu không trình duyệt nhận HTML với đuôi `.woff2`.
        """
        candidate = (_SPA_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_SPA_DIR):
            return FileResponse(candidate)
        return FileResponse(_SPA_DIR / "index.html")
