"""Preview and confirm migration of an ebook's crawl source."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Literal

from novel2epub.crawler import ScraplingCrawler
from novel2epub.source_switch import apply_switch, propose, validate_url
from novel2epub.sources import load_presets
from novel2epub.storage import Manifest, Storage
from .. import deps

router = APIRouter(prefix="/api/ui/ebooks/{slug}/source-switch")


class SourceRequest(BaseModel):
    source_name: str
    toc_url: str
    crawl_mode: Literal["fetcher", "stealthy"] | None = None
    headless: bool | None = None


class Choice(BaseModel):
    position: int
    action: str
    old_index: int | None = None
    new_index: int | None = None


class ConfirmRequest(SourceRequest):
    old_fingerprint: str
    toc_fingerprint: str
    choices: list[Choice]


def _read_toc(source_name: str, toc_url: str, slug: str,
              crawl_mode: str | None = None, headless: bool | None = None):
    toc_url = validate_url(toc_url)
    preset = load_presets(deps.DB_PATH).get(source_name)
    if preset is None:
        raise ValueError("Nguồn đã chọn không tồn tại. Hãy tạo preset nguồn trước.")
    cfg = preset.to_crawl_config(toc_url, mode_override=crawl_mode or "")
    if headless is not None:
        cfg.headless = headless
    crawler = ScraplingCrawler(cfg)
    try:
        toc = crawler.fetch_toc()
    finally:
        crawler.close()
    if not toc.chapters:
        raise ValueError("Mục lục nguồn mới không có chương nào. Kiểm tra URL và cấu hình nguồn.")
    incoming = Manifest(slug=slug, source_url=toc_url, chapters=toc.chapters)
    return incoming, toc_url, cfg.scrapling.mode, cfg.headless


def _old(slug: str) -> tuple[Storage, Manifest]:
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None or not manifest.chapters:
        raise ValueError("Ebook chưa có mục lục để chuyển nguồn.")
    return storage, manifest


@router.post("/preview")
def preview(slug: str, payload: SourceRequest):
    try:
        storage, manifest = _old(slug)
        incoming, _, _, _ = _read_toc(payload.source_name, payload.toc_url, slug,
                                       payload.crawl_mode, payload.headless)
        return propose(manifest, incoming, storage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/confirm")
def confirm(request: Request, slug: str, payload: ConfirmRequest):
    queue = request.app.state.job.queue
    if not queue.retire_ebook(slug):
        raise HTTPException(status_code=409, detail="Ebook có job đang chạy hoặc chờ. Hãy đợi job xong rồi xem trước lại.")
    try:
        storage, manifest = _old(slug)
        incoming, toc_url, crawl_mode, headless = _read_toc(
            payload.source_name, payload.toc_url, slug, payload.crawl_mode, payload.headless)
        return apply_switch(storage, manifest, incoming, [c.model_dump() for c in payload.choices],
                            payload.old_fingerprint, payload.toc_fingerprint,
                            payload.source_name, toc_url, crawl_mode=crawl_mode, headless=headless)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        queue.restore_ebook(slug)
