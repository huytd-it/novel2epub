"""Gọi Supabase PostgREST của app đọc novel-reader.

Dùng `service_role` key (bypass RLS) gọi thẳng `/rest/v1/...` — đúng cách
`scripts/ingest-epub.ts` của chính repo novel-reader đang làm, nên KHÔNG cần
sửa hay deploy gì bên đó.

Khác biệt cốt lõi với đường ingest sẵn có: bên đó xoá sạch `chapters` của sách
rồi insert lại (sinh `chapters.id` mới, làm hỏng bookmark/tiến độ đọc trỏ theo
`chapter_id`); ở đây dùng UPSERT theo `on_conflict=book_id,index` — constraint
`unique(book_id, index)` đã có sẵn trong `0001_init.sql` — nên `id` giữ nguyên.

Bảo mật: `cfg.service_key` KHÔNG bao giờ được đưa vào log hay thông báo lỗi
(log job hiện công khai trên /queue, /logs).
"""
from __future__ import annotations

import time
from typing import Any, Callable

import requests

from .config import ReaderConfig
from .reader_sync import ChapterPush, is_free

# Retry cho lỗi tạm thời (429 / 5xx). Giữ đơn giản và cục bộ: import
# `pipeline._retry_wait_seconds` sẽ thành vòng lặp import (pipeline import
# module này), còn `CrawlRetryConfig` thì thuộc về ngữ cảnh cào trang.
_RETRY_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0
_RETRY_BACKOFF = 2.0
_RETRY_MAX_DELAY_SECONDS = 30.0

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ReaderError(RuntimeError):
    """Lỗi khi nói chuyện với Supabase của Reader (đã ẩn service_key)."""


def _headers(cfg: ReaderConfig, *, prefer: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "apikey": cfg.service_key,
        "Authorization": f"Bearer {cfg.service_key}",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _retry_after_seconds(resp: requests.Response, attempt: int) -> float:
    """Chờ bao lâu trước lần thử lại: ưu tiên header `Retry-After` của server,
    không có thì backoff luỹ thừa."""
    raw = resp.headers.get("Retry-After", "") if resp is not None else ""
    try:
        if raw:
            return min(max(float(raw.strip()), 0.0), _RETRY_MAX_DELAY_SECONDS)
    except ValueError:
        pass
    wait = _RETRY_DELAY_SECONDS * (_RETRY_BACKOFF ** (attempt - 1))
    return min(wait, _RETRY_MAX_DELAY_SECONDS)


def _describe_error(resp: requests.Response) -> str:
    """Thông điệp lỗi ngắn từ response PostgREST, KHÔNG kèm key."""
    try:
        data = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    if isinstance(data, dict):
        parts = [str(data[k]) for k in ("message", "details", "hint") if data.get(k)]
        if parts:
            return f"HTTP {resp.status_code}: {' — '.join(parts)}"
    return f"HTTP {resp.status_code}: {str(data)[:200]}"


def _request(
    cfg: ReaderConfig,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: Any = None,
    prefer: str = "",
    log: Callable[[str], None] | None = None,
) -> Any:
    """Gọi PostgREST, retry lỗi tạm thời, trả JSON đã parse (hoặc None nếu
    response rỗng). Raise `ReaderError` khi hết lượt thử."""
    url = f"{cfg.url}/rest/v1/{path}"
    last_error = ""
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=_headers(cfg, prefer=prefer),
                params=params,
                json=json_body,
                timeout=cfg.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            last_error = f"quá thời gian ({cfg.timeout_seconds}s)"
        except requests.exceptions.RequestException as e:
            last_error = f"lỗi kết nối: {e}"
        else:
            if resp.status_code < 400:
                if not resp.content:
                    return None
                try:
                    return resp.json()
                except ValueError:
                    return None
            last_error = _describe_error(resp)
            if resp.status_code not in _RETRYABLE_STATUS:
                raise ReaderError(f"{method} {path} thất bại — {last_error}")
            if attempt < _RETRY_ATTEMPTS:
                wait = _retry_after_seconds(resp, attempt)
                if log:
                    log(f"[đẩy-reader]   {last_error}, thử lại sau {wait:.0f}s "
                        f"({attempt}/{_RETRY_ATTEMPTS})")
                time.sleep(wait)
                continue
        if attempt < _RETRY_ATTEMPTS:
            wait = min(_RETRY_DELAY_SECONDS * (_RETRY_BACKOFF ** (attempt - 1)),
                       _RETRY_MAX_DELAY_SECONDS)
            if log:
                log(f"[đẩy-reader]   {last_error}, thử lại sau {wait:.0f}s "
                    f"({attempt}/{_RETRY_ATTEMPTS})")
            time.sleep(wait)
    raise ReaderError(f"{method} {path} thất bại sau {_RETRY_ATTEMPTS} lần — {last_error}")


def fetch_book(cfg: ReaderConfig, slug: str, *, log=None) -> dict | None:
    """Sách đang có trên Reader theo slug, hoặc None."""
    rows = _request(
        cfg, "GET", "books",
        params={"slug": f"eq.{slug}", "select": "id,is_published,chapter_count", "limit": "1"},
        log=log,
    )
    return rows[0] if isinstance(rows, list) and rows else None


def upsert_book(
    cfg: ReaderConfig,
    *,
    slug: str,
    title: str = "",
    author: str = "",
    description: str = "",
    cover_url: str = "",
    log=None,
) -> str:
    """Tạo sách nếu chưa có, ngược lại cập nhật metadata. Trả `books.id`.

    `is_published` CHỈ set lúc tạo mới — sách đã có thì trạng thái xuất bản do
    người quản lý bên Reader quyết định, đẩy chương không được đạp lên.
    """
    existing = fetch_book(cfg, slug, log=log)
    payload: dict[str, Any] = {"title": title, "author": author}
    if description:
        payload["description"] = description
    if cover_url:
        payload["cover_url"] = cover_url

    if existing:
        _request(
            cfg, "PATCH", "books",
            params={"id": f"eq.{existing['id']}"},
            json_body=payload,
            prefer="return=minimal",
            log=log,
        )
        return str(existing["id"])

    payload["slug"] = slug
    payload["is_published"] = cfg.published
    rows = _request(
        cfg, "POST", "books",
        json_body=[payload],
        prefer="return=representation",
        log=log,
    )
    if not isinstance(rows, list) or not rows or not rows[0].get("id"):
        raise ReaderError(f"Tạo sách {slug!r} trên Reader không trả về id.")
    return str(rows[0]["id"])


def fetch_remote_chapter_ids(cfg: ReaderConfig, book_id: str, *, log=None) -> dict[int, str]:
    """Map `index -> chapters.id` của các chương đang có trên Reader.

    Đây là nguồn sự thật để hoà giải với state local: chương local tưởng "đã
    đẩy" mà remote không có (vd Reader từng bị ingest xoá sạch) sẽ được đẩy lại.
    """
    rows = _request(
        cfg, "GET", "chapters",
        params={"book_id": f"eq.{book_id}", "select": "index,id", "limit": "100000"},
        log=log,
    )
    if not isinstance(rows, list):
        return {}
    return {int(r["index"]): str(r["id"]) for r in rows if r.get("id") is not None}


def upsert_chapters(
    cfg: ReaderConfig,
    book_id: str,
    pushes: list[ChapterPush],
    *,
    include_is_free: bool,
    free_chapters: int = 0,
    log=None,
) -> dict[int, str]:
    """Upsert metadata chương theo `on_conflict=book_id,index`, trả map
    `index -> chapters.id`.

    `include_is_free=False` cho chương SỬA: PostgREST `merge-duplicates` chỉ
    `DO UPDATE SET` những cột CÓ TRONG payload, nên bỏ `is_free` ra khỏi payload
    là cách giữ nguyên chỉnh tay `is_free` bên Reader. Cũng vì PostgREST bắt mọi
    object trong một request phải cùng bộ key ("All object keys must match") nên
    chương MỚI và chương SỬA buộc phải là hai request riêng.
    """
    if not pushes:
        return {}
    rows: list[dict[str, Any]] = []
    for p in pushes:
        row: dict[str, Any] = {
            "book_id": book_id,
            "index": p.index,
            "title": p.title,
            "word_count": p.word_count,
        }
        if include_is_free:
            row["is_free"] = is_free(p.index, free_chapters)
        rows.append(row)

    result = _request(
        cfg, "POST", "chapters",
        params={"on_conflict": "book_id,index"},
        json_body=rows,
        prefer="resolution=merge-duplicates,return=representation",
        log=log,
    )
    if not isinstance(result, list):
        raise ReaderError("Upsert chapters không trả về dữ liệu.")
    return {int(r["index"]): str(r["id"]) for r in result if r.get("id") is not None}


def upsert_contents(
    cfg: ReaderConfig,
    rows: list[tuple[str, str]],
    *,
    anchors_by_id: dict[str, list[int]] | None = None,
    log=None,
) -> None:
    """Upsert `chapter_contents` theo `on_conflict=chapter_id`.

    `rows`: list `(chapter_id, content)`.

    `anchors_by_id` (chỉ truyền khi `cfg.push_anchors`): neo đoạn đi kèm, ghi
    vào cột `para_anchors`. Phải nằm trong CÙNG payload với `content` — neo và
    nội dung lệch phiên bản là sai lệch âm thầm, loại nguy hiểm nhất: không có
    lỗi nào nổ ra, chỉ có bản sửa ghi nhầm đoạn.
    """
    if not rows:
        return
    payload = [{"chapter_id": cid, "content": content} for cid, content in rows]
    if anchors_by_id:
        for row in payload:
            anchors = anchors_by_id.get(row["chapter_id"])
            if anchors is not None:
                row["para_anchors"] = anchors
    _request(
        cfg, "POST", "chapter_contents",
        params={"on_conflict": "chapter_id"},
        json_body=payload,
        prefer="resolution=merge-duplicates,return=minimal",
        log=log,
    )


def count_remote_chapters(cfg: ReaderConfig, book_id: str, *, log=None) -> int:
    return len(fetch_remote_chapter_ids(cfg, book_id, log=log))


def update_chapter_count(cfg: ReaderConfig, book_id: str, count: int, *, log=None) -> None:
    _request(
        cfg, "PATCH", "books",
        params={"id": f"eq.{book_id}"},
        json_body={"chapter_count": count},
        prefer="return=minimal",
        log=log,
    )
