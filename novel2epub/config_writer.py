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

# Field YAML-only deprecated — không có UI counterpart, config_writer không ghi.
# load_config vẫn đọc được (backward compat) nhưng không nên xuất hiện khi
# user tạo/sửa ebook qua web UI.
_DEPRECATED_CRAWL_FIELDS = frozenset({
    "ai_fallback", "ai_fallback_max_html", "concurrency_cap",
})
_DEPRECATED_TRANSLATE_FIELDS = frozenset({
    "glossary", "glossary_files", "profile", "genre",
})


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
    """Merge `updates` vào `target` tại chỗ, giữ comment của các key không đổi.

    Tự động lọc bỏ field deprecated khi ghi vào nhánh `crawl:` hoặc `translate:`.
    """
    for key, value in updates.items():
        if isinstance(value, dict):
            child = target.get(key)
            if not isinstance(child, CommentedMap):
                child = CommentedMap()
                target[key] = child
            deprecated = (
                _DEPRECATED_CRAWL_FIELDS if key == "crawl"
                else _DEPRECATED_TRANSLATE_FIELDS if key == "translate"
                else frozenset()
            )
            _deep_merge(child, {k: v for k, v in value.items() if k not in deprecated})
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


def update_defaults(path: str | Path, updates: dict[str, Any]) -> None:
    """Merge `updates` vào khối `defaults:` — cấu hình dùng chung cho MỌI ebook.

    Dùng cho `translate` (AI dịch) và `ai` (AI biên tập): các key top-level của
    `updates` cũng bị GỠ khỏi từng ebook trong `ebooks:` (bản copy per-ebook cũ)
    để file chỉ còn đúng 1 nơi giữ cấu hình này — `load_config` vốn đã bỏ qua
    override per-ebook cho các khối global.
    """
    path = Path(path)
    data = _load(path)
    defaults = data.get("defaults")
    if not isinstance(defaults, CommentedMap):
        defaults = CommentedMap()
        data["defaults"] = defaults
    _deep_merge(defaults, updates)
    ebooks = data.get("ebooks")
    if isinstance(ebooks, CommentedMap):
        for item in ebooks.values():
            if not isinstance(item, CommentedMap):
                continue
            for key in updates:
                item.pop(key, None)
    _dump(path, data)


def add_ebook(
    path: str | Path,
    slug: str,
    *,
    name: str = "",
    title: str = "",
    author: str = "",
    toc_url: str = "",
    preset: dict[str, Any] | None = None,
    source_name: str = "",
) -> None:
    """Thêm 1 ebook vào `ebooks.<slug>` với CHỈ phần override tối thiểu.

    Phần dùng chung (prompt, style, output...) do `defaults:` lo, không lặp lại.
    Nếu ``source_name`` được cung cấp, ghi field ``source`` thay vì copy
    preset fields vào crawl block (preset resolve sẽ tự động khi load config).
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
    if toc_url:
        crawl["toc_url"] = toc_url
    # Nếu có source_name, ghi field source (không copy preset fields).
    # Nếu không có source_name (legacy), copy preset fields như cũ.
    if source_name:
        pass  # preset fields resolve tự động khi load_config
    elif preset:
        for k, v in preset.items():
            if k in {"name", "url", "domains", "engine"}:
                continue
            crawl[k] = _coerce(v)

    item = CommentedMap()
    if name:
        item["name"] = name
    if source_name:
        item["source"] = source_name
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
