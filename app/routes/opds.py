"""Catalog OPDS cho trình đọc ngoài (readest) + phục vụ file EPUB và ảnh bìa.

Chỉ liệt kê ebook ĐÃ BUILD EPUB. Ebook chưa build thì vắng mặt hẳn — thà
không thấy còn hơn thấy rồi bấm tải về báo lỗi. EPUB cũ hơn bản dịch vẫn
được phục vụ nguyên trạng: build lại là việc của trang Tự động hoá, không
phải của một request HTTP (ebook lớn nhất 2907 chương, build trong request
sẽ treo).
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from novel2epub import opds
from novel2epub.storage import Storage

from .. import deps
from ..auth import require_api_auth
from ..library_state import archived_slugs

router = APIRouter(dependencies=[Depends(require_api_auth)])

_MEDIA_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _now() -> float:
    return time.time()


def _epub_path(cfg) -> Path:
    """Đường dẫn tuyệt đối tới file EPUB của một ebook."""
    return Path(cfg.epub_path).resolve()


def _xml(body: str, media_type: str) -> Response:
    return Response(content=body, media_type=media_type)


def _cover_media_type(ext: str) -> str:
    return _MEDIA_BY_EXT.get(ext.lower().lstrip("."), "image/jpeg")


def _ebook_or_404(slug: str):
    """(cfg, storage) của ebook, hoặc 404."""
    if slug not in deps.library().ebooks:
        raise HTTPException(status_code=404, detail="Không tìm thấy ebook.")
    cfg = deps.resolved_cfg(slug)
    return cfg, Storage(cfg.output.data_dir, cfg.novel.slug)


def _collect_books() -> list[opds.OpdsBook]:
    """Các ebook đủ điều kiện lên feed: chưa archive VÀ đã có file EPUB."""
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    books: list[opds.OpdsBook] = []
    for slug in deps.library().ebooks:
        if slug in archived:
            continue
        cfg = deps.resolved_cfg(slug)
        epub = _epub_path(cfg)
        if not epub.exists():
            continue
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        cover = storage.read_cover_bytes()
        novel = cfg.novel
        books.append(
            opds.OpdsBook(
                slug=slug,
                title=novel.title or slug,
                author=novel.author,
                description=novel.description,
                language=novel.language or "vi",
                identifier=novel.identifier,
                publisher=novel.publisher,
                pubdate=novel.pubdate,
                subjects=list(novel.subjects or []),
                # mtime của FILE, không phải của bản dịch — readest tải lại
                # dựa vào trường này và thứ nó tải là file.
                updated=opds.iso_utc(epub.stat().st_mtime),
                has_cover=cover is not None,
                cover_type=_cover_media_type(cover[1]) if cover else "image/jpeg",
            )
        )
    return books


@router.get("/opds")
def opds_root(request: Request) -> Response:
    """Feed điều hướng gốc — URL người dùng dán vào readest."""
    base = str(request.base_url).rstrip("/")
    body = opds.navigation_feed(base_url=base, updated=opds.iso_utc(_now()))
    return _xml(body, opds.NAV_TYPE)


@router.get("/opds/books")
def opds_books(request: Request) -> Response:
    """Feed acquisition — mỗi ebook đã build một entry."""
    base = str(request.base_url).rstrip("/")
    books = _collect_books()
    updated = max((b.updated for b in books), default=opds.iso_utc(_now()))
    body = opds.acquisition_feed(books, base_url=base, updated=updated)
    return _xml(body, opds.ACQ_TYPE)


@router.get("/opds/download/{slug}.epub")
def opds_download(slug: str) -> Response:
    cfg, _storage = _ebook_or_404(slug)
    epub = _epub_path(cfg)
    if not epub.exists():
        raise HTTPException(status_code=404, detail="Chưa build EPUB cho ebook này.")
    return Response(
        content=epub.read_bytes(),
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.epub"'},
    )


@router.get("/opds/cover/{slug}")
def opds_cover(slug: str) -> Response:
    _cfg, storage = _ebook_or_404(slug)
    cover = storage.read_cover_bytes()
    if cover is None:
        raise HTTPException(status_code=404, detail="Ebook chưa có ảnh bìa.")
    content, ext = cover
    return Response(content=content, media_type=_cover_media_type(ext))
