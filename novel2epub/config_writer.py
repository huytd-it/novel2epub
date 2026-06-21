"""Ghi cấu hình YAML mà KHÔNG làm mất comment.

`load_config`/`load_library` trong config.py chỉ đọc (PyYAML). Module này thêm lớp
*ghi* riêng bằng ruamel.yaml (round-trip) để khi web UI sửa config thì các comment
hướng dẫn trong file vẫn được giữ nguyên. Chỉ merge đúng các key form gửi lên, không
dump lại toàn bộ object Config (tránh ghi đè đường dẫn glossary đã resolve tuyệt đối).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

from .config import LibraryConfig

# config.example.yaml nằm ở gốc repo (cha của package novel2epub/).
EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "config.example.yaml"


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


def _coerce(value: Any) -> Any:
    """String nhiều dòng -> block scalar literal cho dễ đọc trong file."""
    if isinstance(value, str) and "\n" in value:
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


def update_config_file(path: str | Path, updates: dict[str, Any]) -> None:
    """Load file config hiện có (giữ comment), merge `updates`, ghi lại cùng path."""
    path = Path(path)
    data = _load(path)
    _deep_merge(data, updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)


def scaffold_config_file(
    dest: str | Path,
    *,
    slug: str,
    title: str = "",
    author: str = "",
    toc_url: str = "",
    engine: str = "http",
    preset: dict[str, Any] | None = None,
) -> None:
    """Tạo config mới từ config.example.yaml (giữ comment làm tài liệu) rồi áp giá trị."""
    dest = Path(dest)
    if EXAMPLE_CONFIG.exists():
        data = _yaml().load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    else:
        data = CommentedMap()

    updates: dict[str, Any] = {
        "novel": {"slug": slug},
        "crawl": {"engine": engine},
    }
    if title:
        updates["novel"]["title"] = title
    if author:
        updates["novel"]["author"] = author
    if toc_url:
        updates["crawl"]["toc_url"] = toc_url
    if preset:
        updates["crawl"].update({k: v for k, v in preset.items() if k not in {"name"}})

    _deep_merge(data, updates)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)


def save_library(path: str | Path, library: LibraryConfig) -> None:
    """Ghi danh sách ebook vào library.yaml, giữ comment nếu file đã có."""
    path = Path(path)
    data = _load(path)
    ebooks = CommentedMap()
    for slug, entry in library.ebooks.items():
        item = CommentedMap()
        if entry.name:
            item["name"] = entry.name
        if entry.config:
            item["config"] = entry.config
        ebooks[slug] = item
    data["ebooks"] = ebooks
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)
