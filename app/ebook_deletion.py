"""Điều phối xóa vĩnh viễn một ebook và dữ liệu liên quan."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from novel2epub.db import get_thread_connection


class ActiveEbookQueue(Protocol):
    def retire_ebook(self, ebook: str) -> bool: ...

    def restore_ebook(self, ebook: str) -> None: ...


class EbookDeleteError(Exception):
    """Lỗi nghiệp vụ dự kiến khi xóa ebook."""


class ConfirmationMismatch(EbookDeleteError):
    pass


class EbookNotFound(EbookDeleteError):
    pass


class EbookBusy(EbookDeleteError):
    pass


class EpubDeleteFailed(EbookDeleteError):
    pass


def delete_ebook(
    db_path: str | Path,
    slug: str,
    confirm_slug: str,
    resolve_epub_path: Callable[[], str | Path],
    queue: ActiveEbookQueue,
) -> None:
    if confirm_slug != slug:
        raise ConfirmationMismatch("Slug xác nhận không khớp.")

    conn = get_thread_connection(db_path)
    exists = conn.execute("SELECT 1 FROM ebooks WHERE slug = ?", (slug,)).fetchone()
    if exists is None:
        raise EbookNotFound(f"Không tìm thấy ebook '{slug}'.")
    if not queue.retire_ebook(slug):
        raise EbookBusy("Ebook đang có job chạy hoặc chờ trong hàng đợi.")
    try:
        epub_path = resolve_epub_path()
        epub = Path(epub_path) if epub_path else None
        if epub is not None and epub.exists():
            try:
                epub.unlink()
            except OSError as exc:
                raise EpubDeleteFailed(f"Không thể xóa EPUB: {exc}") from exc

        with conn:
            conn.execute("DELETE FROM automations WHERE ebook = ?", (slug,))
            conn.execute("DELETE FROM ebooks WHERE slug = ?", (slug,))
    except Exception:
        queue.restore_ebook(slug)
        raise
