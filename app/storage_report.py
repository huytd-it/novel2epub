"""Báo cáo dung lượng đĩa theo từng ebook + dọn dẹp/đóng gói (xem spec
storage-management). Đi trực tiếp trên `Storage` paths, không cần biết về
manifest/chapter — chỉ duyệt thư mục và cộng dồn kích thước file.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from novel2epub.storage import Storage


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def ebook_storage_report(storage: Storage, epub_path: str | Path | None = None) -> dict:
    """Kích thước (byte) theo từng category + tổng cho 1 ebook."""
    raw = _dir_size(storage.raw_dir)
    translated = _dir_size(storage.translated_dir)
    translated_mt = _dir_size(storage.translated_mt_dir)
    meta = _dir_size(storage.meta_dir)
    glossary = _dir_size(storage.glossary_dir)
    epub = 0
    epub_p = Path(epub_path) if epub_path else None
    if epub_p and epub_p.exists():
        epub = epub_p.stat().st_size
    total = raw + translated + translated_mt + meta + glossary + epub
    return {
        "raw": raw,
        "translated": translated,
        "translated_mt": translated_mt,
        "meta": meta,
        "glossary": glossary,
        "epub": epub,
        "total": total,
    }


def purge_raw(storage: Storage) -> int:
    """Xóa toàn bộ raw/ (bản gốc đã crawl). KHÔNG đụng translated/ (bản đã
    biên tập tay). Trả số byte đã giải phóng."""
    freed = _dir_size(storage.raw_dir)
    for p in storage.raw_dir.glob("*"):
        if p.is_file():
            p.unlink()
    return freed


def purge_translated_mt(storage: Storage) -> int:
    """Xóa snapshot máy dịch (translated_mt/, cột "VI" trong editor 3 cột).
    KHÔNG đụng translated/ (bản đã biên tập)."""
    freed = _dir_size(storage.translated_mt_dir)
    for p in storage.translated_mt_dir.glob("*"):
        if p.is_file():
            p.unlink()
    return freed


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
    """Gói toàn bộ artifact của 1 ebook (raw/translated/translated_mt/meta/
    glossary/manifest + config hiệu lực + EPUB nếu có) thành 1 file .zip duy
    nhất để tải về/sao lưu."""
    out_path = Path(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if storage.root.exists():
            for p in storage.root.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=str(p.relative_to(storage.root.parent)))
        if config_snippet:
            zf.writestr(f"{storage.root.name}/config.yaml", config_snippet)
        epub_p = Path(epub_path) if epub_path else None
        if epub_p and epub_p.exists():
            zf.write(epub_p, arcname=f"{storage.root.name}/{epub_p.name}")
    return out_path
