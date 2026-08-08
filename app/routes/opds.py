"""Catalog OPDS cho trình đọc ngoài (readest) + phục vụ file EPUB và ảnh bìa.

Chỉ liệt kê ebook ĐÃ BUILD EPUB. Ebook chưa build thì vắng mặt hẳn — thà
không thấy còn hơn thấy rồi bấm tải về báo lỗi.

Việc gọi catalog KÍCH HOẠT build, nhưng build chạy NỀN: request phát hiện
ebook thiếu file EPUB hoặc có bản dịch mới hơn file, đẩy job vào JobQueue rồi
trả feed ngay. Feed KHÔNG BAO GIỜ chờ build xong — ebook lớn nhất 2907 chương,
build trong request sẽ làm readest timeout và người dùng chỉ thấy "Failed to
load OPDS feed". Sách vừa được đẩy job sẽ xuất hiện ở lần làm mới sau.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from novel2epub import epub_autobuild, opds
from novel2epub.notes import replace_para, split_paras
from novel2epub.pipeline import step_build_selected
from novel2epub.storage import Storage

from .. import deps
from ..auth import require_api_auth
from ..library_state import archived_slugs
from ..logging_config import logger

router = APIRouter(dependencies=[Depends(require_api_auth)])

# Thời gian nghỉ giữa hai lần kích hoạt build cho CÙNG một ebook. readest hỏi
# lại catalog rất thường xuyên (mỗi lần mở app, mỗi lần kéo-để-làm-mới); không
# có mốc nghỉ này thì mỗi cú kéo lại đẻ thêm một job build cho cùng cuốn sách.
_AUTOBUILD_COOLDOWN_SECONDS = 300.0

# slug -> lúc kích hoạt gần nhất. Cố ý để trong RAM chứ không vào DB: mất khi
# restart chỉ tốn thêm đúng một lần build dư, mà đổi lại không phải thêm bảng
# và không ghi DB trên đường phục vụ feed.
_last_autobuild: dict[str, float] = {}
_autobuild_lock = threading.Lock()

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


def autobuild_job_factory(params: dict):
    """Tái tạo `target(log)` của job tự-build từ spec — cho phép job pending
    sống sót qua restart (xem JobQueue.register_kind/load_pending)."""
    slug = str(params.get("slug", ""))

    def _target(log):
        step_build_selected(deps.resolved_cfg(slug), log, translated_only=True)

    return _target


def _build_states() -> list[epub_autobuild.BuildState]:
    """Trạng thái build của mọi ebook chưa archive."""
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    states: list[epub_autobuild.BuildState] = []
    for slug in deps.library().ebooks:
        if slug in archived:
            continue
        cfg = deps.resolved_cfg(slug)
        epub = _epub_path(cfg)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        count, latest = storage.translated_stats()
        states.append(
            epub_autobuild.BuildState(
                slug=slug,
                translated_count=count,
                latest_translated_at=latest,
                epub_mtime=epub.stat().st_mtime if epub.exists() else None,
            )
        )
    return states


def _has_queued_build(job, slug: str) -> bool:
    """Ebook đã có job build đang chạy HOẶC đang chờ trong hàng đợi chưa.

    `is_ebook_busy` chỉ thấy job đang CHẠY; phải soi cả pending, nếu không thì
    mỗi request OPDS lại chồng thêm một job build cho cuốn sách đang xếp hàng.
    """
    if job.is_ebook_busy("build", slug):
        return True
    pending = job.queue.snapshot().get("pending", {})
    return any(j.get("ebook") == slug for j in pending.get("build", []))


def _maybe_autobuild(request: Request) -> None:
    """Đẩy job build nền cho ebook thiếu file EPUB hoặc có bản dịch mới hơn.

    KHÔNG BAO GIỜ được ném ra ngoài: catalog phải trả về được ngay cả khi việc
    tự build hỏng. Lỗi ở đây chỉ khiến sách cập nhật chậm, còn ném lên thì
    readest mất luôn cả feed.
    """
    try:
        job = getattr(request.app.state, "job", None)
        if job is None or not deps.cfg().api.auto_build:
            return
        now = _now()
        for state in epub_autobuild.pending_builds(_build_states()):
            slug = state.slug
            # Đang dịch dở thì để yên: bản dịch còn đang chảy vào DB, build
            # bây giờ chỉ tốn công cho một ảnh chụp sẽ cũ ngay lập tức.
            if job.is_ebook_busy("translate", slug) or _has_queued_build(job, slug):
                continue
            with _autobuild_lock:
                if not epub_autobuild.due_for_trigger(
                    _last_autobuild.get(slug, 0.0), now, _AUTOBUILD_COOLDOWN_SECONDS
                ):
                    continue
                _last_autobuild[slug] = now
            spec = {"kind": "opds-autobuild", "params": {"slug": slug}}
            job.start_custom(
                f"opds-autobuild:{slug}",
                autobuild_job_factory(spec["params"]),
                category="build",
                ebook=slug,
                spec=spec,
            )
            logger.info(
                "[opds] tự build %s (%s) — %d chương đã dịch",
                slug, epub_autobuild.decide(state), state.translated_count,
            )
    except Exception:  # noqa: BLE001 - feed phải sống sót mọi lỗi ở đây
        logger.exception("[opds] tự build thất bại, bỏ qua và vẫn trả feed")


@router.get("/opds")
def opds_root(request: Request) -> Response:
    """Feed điều hướng gốc — URL người dùng dán vào readest."""
    _maybe_autobuild(request)
    base = str(request.base_url).rstrip("/")
    body = opds.navigation_feed(base_url=base, updated=opds.iso_utc(_now()))
    return _xml(body, opds.NAV_TYPE)


@router.get("/opds/books")
def opds_books(request: Request) -> Response:
    """Feed acquisition — mỗi ebook đã build một entry.

    Sách vừa được đẩy job build ở đây chưa có file nên chưa lên feed lần này;
    nó xuất hiện ở lần readest làm mới kế tiếp.
    """
    _maybe_autobuild(request)
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


class ParagraphPatch(BaseModel):
    """Thân request sửa một đoạn.

    `expected` PHẢI lấy từ `GET .../chapters/{idx}`, KHÔNG được lấy từ DOM của
    trang đang đọc: văn bản trong EPUB đã qua html.escape và marker footnote đã
    thành <sup>, nên không bao giờ khớp bản trong DB.
    """
    text: str
    expected: str


def _chapter_or_404(slug: str, idx: int):
    """(storage, chapter) của một chương, hoặc 404."""
    _cfg, storage = _ebook_or_404(slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == idx), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return storage, ch


@router.get("/api/v1/ebooks/{slug}/chapters/{idx}")
def api_chapter(slug: str, idx: int) -> dict:
    """Các đoạn của một chương kèm chỉ số — nguồn `expected` cho PATCH."""
    storage, ch = _chapter_or_404(slug, idx)
    translated = storage.read_active_branch_text(ch)
    paras = split_paras(translated)
    return {
        "slug": slug,
        "index": idx,
        "title": ch.title or f"Chương {idx}",
        "paragraphs": [{"index": i, "text": p} for i, p in enumerate(paras)],
    }


@router.patch("/api/v1/ebooks/{slug}/chapters/{idx}/paragraphs/{para_index}")
def api_patch_paragraph(slug: str, idx: int, para_index: int, body: ParagraphPatch) -> dict:
    """Thay toàn bộ một đoạn. Chống ghi đè bằng `expected`.

    Không cho `text` rỗng: `replace_para` khi nhận rỗng sẽ xoá hẳn dòng rồi
    đánh lại chỉ số mọi đoạn phía sau, mà client vẫn giữ chỉ số cũ. Xoá đoạn
    chỉ làm ở web UI, nơi trang tự tải lại sau mỗi thao tác.
    """
    storage, ch = _chapter_or_404(slug, idx)
    if not body.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Không xoá đoạn qua API — dùng trang biên tập trên web.",
        )
    if not storage.has_active_branch_text(ch):
        raise HTTPException(status_code=404, detail="Chương chưa có bản dịch.")

    translated = storage.read_active_branch_text(ch)
    updated, error = replace_para(translated, para_index, body.expected, body.text)
    if updated is None:
        paras = split_paras(translated)
        current = paras[para_index] if 0 <= para_index < len(paras) else ""
        raise HTTPException(status_code=409, detail={"error": error, "current": current})

    storage.write_branch_text(ch, storage.active_branch(ch), updated)
    return {"ok": True, "index": para_index, "text": split_paras(updated)[para_index]}
