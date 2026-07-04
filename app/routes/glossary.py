"""Trang quản lý glossary: CRUD thủ công."""
from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.pipeline import step_find_replace
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()

_GLOSSARY_FILES = ("names.txt", "vietphrase.txt")


def _conflicts_count(storage) -> int:
    conflicts_path = storage.root / "translation_meta" / "_glossary_conflicts.json"
    if not conflicts_path.exists():
        return 0
    try:
        data = json.loads(conflicts_path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, list) else 0
    except (OSError, json.JSONDecodeError):
        return 0


def _append_glossary_entry(
    storage: Storage, target_file: str, source: str, suggested: str, note: str = ""
) -> bool:
    """Thêm 1 dòng `source = suggested [| note]` vào file glossary, bỏ qua nếu thiếu
    dữ liệu hoặc mục đã tồn tại với đúng giá trị đó. Trả True nếu có ghi thật."""
    source, suggested, note = source.strip(), suggested.strip(), note.strip()
    if not source or not suggested or target_file not in _GLOSSARY_FILES:
        return False
    if storage.read_glossary_file(target_file).get(source) == suggested and not note:
        return False

    path = storage.glossary_path(target_file)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    line = f"{source} = {suggested}" + (f" | {note}" if note else "")
    storage.write_glossary_file(target_file, f"{existing}{line}\n")
    return True


@router.get("/ebooks/{slug}/glossary")
def ebook_glossary(request: Request, slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    names = storage.glossary_path("names.txt")
    vietphrase = storage.glossary_path("vietphrase.txt")
    return deps.templates.TemplateResponse(
        request,
        "glossary.html",
        {
            "slug": slug,
            "names": names.read_text(encoding="utf-8") if names.exists() else "",
            "vietphrase": vietphrase.read_text(encoding="utf-8") if vietphrase.exists() else "",
            "job": request.app.state.job.status(),
            "conflicts_count": _conflicts_count(storage),
        },
    )


@router.post("/ebooks/{slug}/glossary")
def ebook_glossary_save(slug: str, names: str = Form(""), vietphrase: str = Form("")):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.write_glossary_file("names.txt", names)
    storage.write_glossary_file("vietphrase.txt", vietphrase)
    return RedirectResponse(url=f"/ebooks/{slug}/glossary", status_code=303)


@router.post("/ebooks/{slug}/glossary/quick-add")
def ebook_glossary_quick_add(
    slug: str,
    chapter_index: int = Form(...),
    source: str = Form(""),
    suggested: str = Form(""),
    note: str = Form(""),
    target_file: str = Form("vietphrase.txt"),
):
    """Thêm nhanh 1 mục glossary ngay từ trang chương — dùng khi đang đọc bản
    dịch và phát hiện thuật ngữ/tên riêng cần thống nhất, không cần qua trang
    Glossary riêng."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    _append_glossary_entry(storage, target_file, source, suggested, note)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{chapter_index}", status_code=303)


@router.post("/ebooks/{slug}/glossary/find-replace")
def ebook_glossary_find_replace(
    request: Request,
    slug: str,
    find: str = Form(...),
    replace: str = Form(""),
    chapter_from: int = Form(0),
    chapter_to: int = Form(0),
    also_raw: bool = Form(False),
):
    """Tìm & thay thế literal trên các chương đã dịch (chạy nền qua job system)."""
    cfg = deps.resolved_cfg(slug)
    start = chapter_from or None
    end = chapter_to or None

    def _target(log):
        step_find_replace(
            cfg, log, find=find, replace=replace, start=start, end=end, also_raw=also_raw
        )

    started = request.app.state.job.start_custom("find_replace", _target, category="translate")
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/glossary", status_code=303)


