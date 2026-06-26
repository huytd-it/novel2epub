"""Thư viện 'site preset' dùng lại: gom các field crawl đặc thù theo website
(selector, pattern, engine...) để tái sử dụng khi thêm ebook mới hoặc cập nhật
nguồn của một ebook. Không chứa `toc_url`/`api_key` vì đó là đặc thù từng truyện.

Lưu trong khối `sources:` của file gộp novel2epub.yaml. Đọc–ghi round-trip để
giữ comment người dùng tự thêm.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    url: str = ""
    domains: str = ""
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
    next_page_selector: str = ""
    next_page_url_pattern: str = ""
    max_pages_per_chapter: int = 10
    # ----- chỉ dùng cho engine = "scrapling" -----
    scrapling_mode: str = "stealthy"
    solve_cloudflare: bool = False
    network_idle: bool = True
    impersonate: str = ""
    # Trần song song hóa cứng cho nguồn này (xem CrawlConfig.concurrency_cap).
    # 0 = dùng mặc định theo engine/scrapling_mode.
    concurrency_cap: int = 0

    def crawl_overrides(self) -> dict[str, Any]:
        """Dict áp lên nhánh `crawl` của config (bỏ `name`, `domains`)."""
        data = asdict(self)
        data.pop("name", None)
        data.pop("url", None)
        data.pop("domains", None)
        return data

    def __post_init__(self) -> None:
        # Tự suy `domains` từ `url` khi để trống, để detect_preset vẫn dùng được.
        if self.url and not self.domains:
            host = urlparse(self.url).hostname or ""
            if host.startswith("www."):
                host = host[4:]
            self.domains = host


_FIELD_NAMES = {f.name for f in fields(SourcePreset)}


def _coerce(name: str, value: Any) -> Any:
    if name in {"headless", "magic", "solve_cloudflare", "network_idle"}:
        return bool(value)
    if name == "delay_seconds":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0
    if name == "max_pages_per_chapter":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10
    if name == "concurrency_cap":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
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


def preset_matches_url(preset: SourcePreset, url: str) -> bool:
    """True nếu hostname của ``url`` chứa một trong các token `domains` của preset."""
    if not url or not preset.domains:
        return False
    hostname = urlparse(url).hostname or ""
    for d in preset.domains.split(","):
        d = d.strip()
        if d and d in hostname:
            return True
    return False


def detect_preset(url: str, presets: dict[str, SourcePreset]) -> str | None:
    """Tìm preset khớp với URL dựa trên trường `domains`.
    Ưu tiên pattern dài hơn (specific hơn).
    """
    if not url:
        return None
    hostname = urlparse(url).hostname or ""
    candidates: list[tuple[int, str]] = []
    for name, p in presets.items():
        if not p.domains:
            continue
        for d in p.domains.split(","):
            d = d.strip()
            if d and d in hostname:
                candidates.append((len(d), name))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][1]


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
        # Lưu toàn bộ field của SourcePreset ngoại trừ name.
        for k, v in asdict(preset).items():
            if k == "name":
                continue
            item[k] = v
        sources[name] = item
    data["sources"] = sources
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)
