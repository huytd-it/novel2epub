"""Thư viện 'site preset' dùng lại: gom các field crawl đặc thù theo website
(selector, pattern...) để tái sử dụng khi thêm ebook mới hoặc cập nhật
nguồn của một ebook. Không chứa `toc_url` vì đó là đặc thù từng truyện.

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




def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


@dataclass
class SourcePreset:
    name: str
    engine: str = "scrapling"
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
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    headless: bool = True
    magic: bool = True
    js_code: str = ""
    delay_seconds: float = 1.0
    next_page_selector: str = ""
    next_page_url_pattern: str = ""
    max_pages_per_chapter: int = 10
    # Regex lines matching these patterns sẽ bị xoá khỏi text chương (loại bỏ ads/junk).
    strip_patterns: list[str] = field(default_factory=list)
    scrapling_mode: str = "stealthy"
    solve_cloudflare: bool = False
    network_idle: bool = True
    impersonate: str = ""
    # Trần song song hóa cứng cho nguồn này (xem CrawlConfig.concurrency_cap).
    # 0 = dùng mặc định theo scrapling_mode.
    concurrency_cap: int = 0
    # ----- search configuration -----
    search_url_pattern: str = ""
    search_result_selector: str = ""
    search_title_selector: str = ""
    search_author_selector: str = ""
    search_link_selector: str = ""
    search_cover_selector: str = ""
    max_search_results: int = 5

    def crawl_overrides(self) -> dict[str, Any]:
        """Dict áp lên nhánh `crawl` của config (bỏ name, url, domains,
        engine, và các field search_*).."""
        data = asdict(self)
        for key in ("name", "url", "domains", "engine"):
            data.pop(key, None)
        return {k: v for k, v in data.items() if not k.startswith("search_")}

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
    if name in {"concurrency_cap", "max_search_results"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 5 if name == "max_search_results" else 0
    return "" if value is None else value


def load_presets(path: str | Path) -> dict[str, SourcePreset]:
    """Đọc file sources YAML standalone. File chứa trực tiếp các preset
    (không có key `sources:` bọc ngoài). Tương thích ngược: nếu file có
    key `sources:` thì vẫn đọc được."""
    path = Path(path)
    if not path.exists():
        return {}
    raw = _yaml().load(path.read_text(encoding="utf-8")) or {}
    # Hỗ trợ cả 2 format: standalone (raw = {name: preset, ...}) và
    # legacy có wrapper `sources:` (raw = {sources: {name: preset, ...}}).
    items = raw.get("sources") or raw
    presets: dict[str, SourcePreset] = {}
    for name, item in items.items():
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
    """Ghi file sources YAML standalone — mỗi preset là top-level key."""
    path = Path(path)
    data = CommentedMap()
    for name, preset in presets.items():
        item = CommentedMap()
        for k, v in asdict(preset).items():
            if k == "name":
                continue
            item[k] = v
        data[name] = item
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)
