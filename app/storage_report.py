"""Báo cáo dung lượng đĩa theo từng ebook + dọn dẹp/đóng gói (xem spec
storage-management). Nội dung ebook nay nằm trong SQLite — kích thước/dọn dẹp
đi qua `Storage.content_bytes/purge_raw/purge_translated_mt`; chỉ EPUB build
ra vẫn là file rời trên đĩa (deliberate, xem kế hoạch SQLite unification)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from novel2epub.storage import Storage


def ebook_storage_report(storage: Storage, epub_path: str | Path | None = None) -> dict:
    """Kích thước (byte, ước lượng) theo từng category + tổng cho 1 ebook."""
    sizes = storage.content_bytes()
    epub = 0
    epub_p = Path(epub_path) if epub_path else None
    epub_exists = bool(epub_p and epub_p.exists())
    if epub_exists:
        epub = epub_p.stat().st_size
    total = sum(sizes.values()) + epub
    return {
        "raw": sizes["raw"],
        "translated": sizes["translated"],
        "translated_mt": sizes["translated_mt"],
        "meta": sizes["meta"],
        "glossary": sizes["glossary"],
        "epub": epub,
        # Phân biệt "chưa build" với "build ra file 0 byte" — `epub > 0` không đủ.
        "epub_exists": epub_exists,
        "total": total,
    }


def purge_raw(storage: Storage) -> int:
    return storage.purge_raw()


def purge_translated_mt(storage: Storage) -> int:
    return storage.purge_translated_mt()


def remove_epub(epub_path: str | Path) -> int:
    path = Path(epub_path)
    if not path.exists():
        return 0
    freed = path.stat().st_size
    path.unlink()
    return freed


def build_archive_bundle(
    storage: Storage,
    out_path: str | Path,
    *,
    config_snippet: str | None = None,
    epub_path: str | Path | None = None,
) -> Path:
    """Gói toàn bộ dữ liệu của 1 ebook (đọc từ DB) thành 1 file `.zip` để
    tải về/sao lưu — tái tạo lại layout thư mục cũ (`manifest.json`,
    `raw/NNNN.md`, ...) bên trong zip để vẫn đọc/duyệt được ngoài app,
    dù nguồn thật giờ là SQLite."""
    out_path = Path(out_path)
    root_name = storage.slug
    manifest = storage.load_manifest()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if manifest is not None:
            zf.writestr(f"{root_name}/manifest.json", manifest.to_json())
            for ch in manifest.chapters:
                if storage.has_raw(ch):
                    zf.writestr(f"{root_name}/raw/{ch.stem}.md", storage.read_raw(ch))
                if storage.read_translated(ch):
                    zf.writestr(f"{root_name}/translated/{ch.stem}.md", storage.read_translated(ch))
                if storage.has_translated_mt(ch):
                    zf.writestr(f"{root_name}/translated_mt/{ch.stem}.md", storage.read_translated_mt(ch))
                if storage.has_meta(ch):
                    zf.writestr(
                        f"{root_name}/translation_meta/{ch.stem}.json",
                        json.dumps(storage.read_meta(ch), ensure_ascii=False, indent=2),
                    )
            for name in ("names.txt", "vietphrase.txt"):
                entries = storage.read_glossary_entries(name)
                if entries:
                    lines = [
                        f"{s} = {t}" + (f" | {n}" if n else "") for s, t, n in entries
                    ]
                    zf.writestr(f"{root_name}/glossary/{name}", "\n".join(lines) + "\n")
            notes = storage.read_notes()
            if notes:
                zf.writestr(f"{root_name}/notes.json", json.dumps(notes, ensure_ascii=False, indent=2))
            cover = storage.read_cover_bytes()
            if cover is not None:
                content, ext = cover
                zf.writestr(f"{root_name}/cover.{ext}", content)
        if config_snippet:
            zf.writestr(f"{root_name}/config.yaml", config_snippet)
        epub_p = Path(epub_path) if epub_path else None
        if epub_p and epub_p.exists():
            zf.write(epub_p, arcname=f"{root_name}/{epub_p.name}")
    return out_path
