"""Thư viện 'site preset' dùng lại: gom các field crawl đặc thù theo website
(selector, pattern, engine...) để tái sử dụng khi thêm ebook mới hoặc cập nhật
nguồn của một ebook. Không chứa `toc_url`/`api_key` vì đó là đặc thù từng truyện.

Lưu ở sources.yaml (override bằng env NOVEL2EPUB_SOURCES). Đọc–ghi round-trip để
giữ comment người dùng tự thêm.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .config import CrawlConfig


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


@dataclass
class SourcePreset:
    name: str
    engine: str = "http"
    chapter_link_pattern: str = r".*"
    content_selector: str = ""
    toc_selector: str = ""
    chapter_title_selector: str = ""
    title_selector: str = ""
    author_selector: str = ""
    desc_selector: str = ""
    cover_selector: str = ""
    encoding: str = ""
    user_agent: str = CrawlConfig.user_agent
    headless: bool = True
    magic: bool = True
    js_code: str = ""
    delay_seconds: float = 1.0

    def crawl_overrides(self) -> dict[str, Any]:
        """Dict áp lên nhánh `crawl` của config (bỏ `name`)."""
        data = asdict(self)
        data.pop("name", None)
        return data


_FIELD_NAMES = {f.name for f in fields(SourcePreset)}


def _coerce(name: str, value: Any) -> Any:
    if name in {"headless", "magic"}:
        return bool(value)
    if name == "delay_seconds":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0
    return "" if value is None else value


def load_presets(path: str | Path) -> dict[str, SourcePreset]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = _yaml().load(path.read_text(encoding="utf-8")) or {}
    presets: dict[str, SourcePreset] = {}
    for name, item in (raw.get("sources") or {}).items():
        data = {k: _coerce(k, v) for k, v in dict(item).items() if k in _FIELD_NAMES}
        data["name"] = name
        presets[name] = SourcePreset(**data)
    return presets


def save_presets(path: str | Path, presets: dict[str, SourcePreset]) -> None:
    path = Path(path)
    data: CommentedMap
    if path.exists():
        loaded = _yaml().load(path.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, CommentedMap) else CommentedMap()
    else:
        data = CommentedMap()
    sources = CommentedMap()
    for name, preset in presets.items():
        item = CommentedMap()
        for k, v in preset.crawl_overrides().items():
            item[k] = v
        sources[name] = item
    data["sources"] = sources
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)
