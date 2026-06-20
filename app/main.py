"""Web UI cho novel2epub: chạy crawl/translate/build, xem & sửa tay bản dịch.

Chạy: uvicorn app.main:app --reload   (từ thư mục novel2epub/)
Đường dẫn config lấy từ biến môi trường NOVEL2EPUB_CONFIG (mặc định config.yaml).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from novel2epub.config import load_config, load_library
from novel2epub.storage import Storage

from .job import JobRunner

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = os.environ.get("NOVEL2EPUB_CONFIG", "config.yaml")
LIBRARY_PATH = os.environ.get("NOVEL2EPUB_LIBRARY", "library.yaml")

app = FastAPI(title="novel2epub")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.state.job = JobRunner()


def _cfg():
    try:
        return load_config(CONFIG_PATH)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{e} — copy config.example.yaml thành {CONFIG_PATH} rồi chỉnh sửa.",
        ) from e


def _library():
    return load_library(LIBRARY_PATH)


def _resolve_path(base: Path, value: str) -> str:
    if not value:
        return value
    p = Path(value)
    if p.is_absolute():
        return value
    return str((base / p).resolve())


def _ebook_config_path(slug: str) -> str:
    library = _library()
    entry = library.ebooks.get(slug)
    if entry and entry.config:
        return _resolve_path(Path(LIBRARY_PATH).resolve().parent, entry.config)
    return CONFIG_PATH


def _ebook_cfg(slug: str):
    try:
        return load_config(_ebook_config_path(slug))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _chapter_rows(cfg) -> list[dict]:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return []
    rows = []
    for ch in manifest.chapters:
        rows.append(
            {
                "index": ch.index,
                "title_zh": ch.title_zh,
                "title_vi": ch.title_vi,
                "url": ch.url,
                "has_raw": storage.has_raw(ch),
                "has_translated": storage.has_translated(ch),
            }
        )
    return rows


@app.get("/")
def index(request: Request):
    library = _library()
    ebooks = []
    if library.ebooks:
        entries = library.ebooks.items()
    else:
        entries = [("default", None)]
    for slug, entry in entries:
        if entry is None:
            cfg = _cfg()
            name = cfg.novel.title or cfg.novel.slug
        else:
            cfg = load_config(_ebook_config_path(slug))
            name = entry.name or cfg.novel.title or slug
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        raw_count = sum(1 for ch in (manifest.chapters if manifest else []) if storage.has_raw(ch))
        translated_count = sum(1 for ch in (manifest.chapters if manifest else []) if storage.has_translated(ch))
        ebooks.append(
            {
                "slug": slug,
                "name": name,
                "cfg": cfg,
                "manifest": manifest,
                "raw_count": raw_count,
                "translated_count": translated_count,
                "epub_exists": Path(cfg.epub_path).exists(),
            }
        )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "config_path": CONFIG_PATH,
            "library_path": LIBRARY_PATH,
            "ebooks": ebooks,
            "job": app.state.job.status(),
        },
    )


@app.get("/ebooks/{slug}")
def ebook_home(request: Request, slug: str):
    cfg = _ebook_cfg(slug) if _library().ebooks else _cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    epub_path = Path(cfg.epub_path)
    return templates.TemplateResponse(
        request,
        "ebook.html",
        {
            "slug": slug,
            "config_path": _ebook_config_path(slug),
            "cfg": cfg,
            "manifest": manifest,
            "chapters": _chapter_rows(cfg),
            "epub_exists": epub_path.exists(),
            "epub_path": str(epub_path),
            "job": app.state.job.status(),
        },
    )


@app.post("/jobs/{step}")
def start_job(step: str):
    cfg = _cfg()
    started = app.state.job.start(step, cfg)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/ebooks/{slug}/jobs/{step}")
def start_ebook_job(slug: str, step: str):
    cfg = _ebook_cfg(slug) if _library().ebooks else _cfg()
    started = app.state.job.start(step, cfg)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@app.get("/api/status")
def api_status():
    return app.state.job.status()


@app.get("/download")
def download():
    cfg = _cfg()
    path = Path(cfg.epub_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chưa có EPUB, hãy chạy bước build.")
    return FileResponse(path, filename=path.name, media_type="application/epub+zip")


@app.get("/ebooks/{slug}/download")
def ebook_download(slug: str):
    cfg = _ebook_cfg(slug) if _library().ebooks else _cfg()
    path = Path(cfg.epub_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chưa có EPUB, hãy chạy bước build.")
    return FileResponse(path, filename=path.name, media_type="application/epub+zip")


@app.get("/chapters/{index}")
def chapter_detail(request: Request, index: int):
    cfg = _cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    return templates.TemplateResponse(
        request,
        "chapter.html",
        {"ch": ch, "raw": raw, "translated": translated, "slug": cfg.novel.slug},
    )


@app.get("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_detail(request: Request, slug: str, index: int):
    cfg = _ebook_cfg(slug) if _library().ebooks else _cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    return templates.TemplateResponse(
        request,
        "chapter.html",
        {"ch": ch, "raw": raw, "translated": translated, "slug": slug, "meta": meta},
    )


@app.post("/chapters/{index}")
def chapter_save(index: int, translated: str = Form(...)):
    """Lưu bản dịch sửa tay — chính là khâu 'edit' cuối cùng trước khi build."""
    cfg = _cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    storage.write_translated(ch, translated)
    return RedirectResponse(url=f"/chapters/{index}", status_code=303)


@app.post("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_save(slug: str, index: int, translated: str = Form(...)):
    cfg = _ebook_cfg(slug) if _library().ebooks else _cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    storage.write_translated(ch, translated)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)
