"""Ghi cấu hình YAML mà KHÔNG làm mất comment.

`load_config`/`load_library` trong config.py chỉ đọc (PyYAML). Module này thêm lớp
*ghi* riêng bằng ruamel.yaml (round-trip) để khi web UI sửa config thì các comment
hướng dẫn trong file vẫn được giữ nguyên. Chỉ merge đúng các key form gửi lên, không
dump lại toàn bộ object Config (tránh ghi đè đường dẫn glossary đã resolve tuyệt đối).
"""
from __future__ import annotations

import uuid
from datetime import date

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

from .config import LibraryConfig


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # tránh tự wrap dòng dài
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _load(path: Path) -> CommentedMap:
    if path.exists():
        data = _yaml().load(path.read_text(encoding="utf-8"))
        if isinstance(data, CommentedMap):
            return data
    return CommentedMap()


def clean_prompt_text(value: str) -> str:
    """Làm sạch nội dung prompt nhập từ textarea cho gọn gàng, thống nhất.

    Chỉ đụng tới khoảng trắng / ký tự xuống dòng nên an toàn với các placeholder
    `{text}`, `{glossary}`, `{tone}`... mà translator dùng qua ``str.format``:

    - Chuẩn hoá CRLF/CR về ``\\n`` (textarea web gửi xuống dùng CRLF).
    - Bỏ khoảng trắng thừa ở cuối mỗi dòng.
    - Gộp >=3 dòng trống liên tiếp thành tối đa 1 dòng trống.
    - Cắt dòng trống ở đầu và cuối.

    Giữ nguyên thụt đầu dòng (có thể là chủ ý) và mọi dấu ``{...}``.
    """
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip("\n")


def _coerce(value: Any) -> Any:
    """String nhiều dòng -> block scalar literal cho dễ đọc trong file."""
    if isinstance(value, str):
        # Textarea trên web gửi xuống dùng CRLF; ruamel không biểu diễn được \r
        # trong block scalar nên mỗi dòng bị chèn thêm 1 dòng trống khi round-trip.
        # Chuẩn hoá về \n trước khi ghi.
        if "\r" in value:
            value = value.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in value:
            return LiteralScalarString(value)
    return value


def _deep_merge(target: CommentedMap, updates: dict[str, Any]) -> None:
    """Merge `updates` vào `target` tại chỗ, giữ comment của các key không đổi."""
    for key, value in updates.items():
        if isinstance(value, dict):
            child = target.get(key)
            if not isinstance(child, CommentedMap):
                child = CommentedMap()
                target[key] = child
            _deep_merge(child, value)
        else:
            target[key] = _coerce(value)


def _dump(path: Path, data: CommentedMap) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)


def _ebooks_map(data: CommentedMap) -> CommentedMap:
    """Lấy (tạo nếu chưa có) khối `ebooks:` trong file gộp."""
    ebooks = data.get("ebooks")
    if not isinstance(ebooks, CommentedMap):
        ebooks = CommentedMap()
        data["ebooks"] = ebooks
    return ebooks


def update_ebook(path: str | Path, slug: str, updates: dict[str, Any]) -> None:
    """Merge `updates` vào `ebooks.<slug>` của file gộp, giữ comment + các khối khác.

    Chỉ chạm đúng section của ebook này — `defaults`, `sources`, ebook khác giữ nguyên.
    """
    path = Path(path)
    data = _load(path)
    ebooks = _ebooks_map(data)
    item = ebooks.get(slug)
    if not isinstance(item, CommentedMap):
        item = CommentedMap()
        ebooks[slug] = item
    _deep_merge(item, updates)
    _dump(path, data)


def add_ebook(
    path: str | Path,
    slug: str,
    *,
    name: str = "",
    title: str = "",
    author: str = "",
    toc_url: str = "",
    engine: str = "http",
    preset: dict[str, Any] | None = None,
) -> None:
    """Thêm 1 ebook vào `ebooks.<slug>` với CHỈ phần override tối thiểu.

    Phần dùng chung (prompt, style, output...) do `defaults:` lo, không lặp lại.
    """
    path = Path(path)
    data = _load(path)
    ebooks = _ebooks_map(data)

    novel = CommentedMap()
    novel["slug"] = slug
    if title:
        novel["title"] = title
    if author:
        novel["author"] = author
    # Ghi 1 lần khi tạo ebook — không cho sửa qua UI (xem spec ebook-metadata
    # "Auto-recorded date added" / "Stable urn:uuid identifier").
    novel["date_added"] = date.today().isoformat()
    novel["identifier"] = f"urn:uuid:{uuid.uuid4()}"

    crawl = CommentedMap()
    crawl["engine"] = engine
    if toc_url:
        crawl["toc_url"] = toc_url
    if preset:
        # Bỏ "engine": form đã gửi engine người dùng chọn — không cho preset đè lại.
        for k, v in preset.items():
            if k in {"name", "url", "domains", "engine"}:
                continue
            crawl[k] = _coerce(v)

    item = CommentedMap()
    if name:
        item["name"] = name
    item["novel"] = novel
    item["crawl"] = crawl
    ebooks[slug] = item
    _dump(path, data)


def ensure_identifier(path: str | Path, slug: str, current: str) -> str:
    """Trả `current` nếu đã có, ngược lại sinh + lưu 1 urn:uuid mới (ổn định
    qua các lần build sau — xem spec ebook-metadata 'Identifier stable
    across rebuilds'). Dùng cho ebook tạo trước khi field này tồn tại."""
    if current:
        return current
    new_id = f"urn:uuid:{uuid.uuid4()}"
    update_ebook(path, slug, {"novel": {"identifier": new_id}})
    return new_id


def remove_ebook(path: str | Path, slug: str) -> None:
    """Xóa `ebooks.<slug>` khỏi file gộp (giữ nguyên các khối còn lại)."""
    path = Path(path)
    data = _load(path)
    ebooks = data.get("ebooks")
    if isinstance(ebooks, CommentedMap) and slug in ebooks:
        del ebooks[slug]
        _dump(path, data)


def save_library(path: str | Path, library: LibraryConfig) -> None:
    """Đồng bộ danh sách ebook trong khối `ebooks:`: cập nhật `name`, xóa key đã gỡ.

    KHÔNG dựng lại từ đầu để tránh xóa mất phần override (novel/crawl/translate)
    inline của từng ebook trong file gộp.
    """
    path = Path(path)
    data = _load(path)
    ebooks = _ebooks_map(data)
    for slug in list(ebooks.keys()):
        if slug not in library.ebooks:
            del ebooks[slug]
    for slug, entry in library.ebooks.items():
        item = ebooks.get(slug)
        if not isinstance(item, CommentedMap):
            item = CommentedMap()
            ebooks[slug] = item
        if entry.name:
            item["name"] = entry.name
    _dump(path, data)
