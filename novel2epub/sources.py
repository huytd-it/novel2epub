"""Thư viện 'site preset' dùng lại: gom các field crawl đặc thù theo website
(selector, pattern...) để tái sử dụng khi thêm ebook mới hoặc cập nhật
nguồn của một ebook. Không chứa `toc_url` vì đó là đặc thù từng truyện.

Lưu trong bảng `sources` của DB thống nhất (trước đây là khối `sources:`
round-trip ruamel trong `sources.yaml`).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import get_thread_connection


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
    toc_next_page_selector: str = ""
    toc_max_pages: int = 5
    # Regex lines matching these patterns sẽ bị xoá khỏi text chương (loại bỏ ads/junk).
    strip_patterns: list[str] = field(default_factory=list)
    scrapling_mode: str = "stealthy"
    solve_cloudflare: bool = False
    network_idle: bool = True
    impersonate: str = ""
    # Proxy URL cho request crawl nguồn này (http://... | socks5://host:port).
    proxy: str = ""
    # DNS-over-HTTPS (Cloudflare DoH) — chỉ scrapling_mode stealthy/dynamic.
    dns_over_https: bool = False
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
    # ----- AI glossary/analysis configuration -----
    ai_glossary_enabled: bool = False
    ai_glossary_extract_prompt: str = ""
    ai_glossary_merge_prompt: str = ""
    ai_cleanup_enabled: bool = False
    ai_cleanup_prompt: str = ""
    ai_eval_enabled: bool = False
    ai_eval_prompt: str = ""

    def crawl_overrides(self) -> dict[str, Any]:
        """Dict áp lên nhánh `crawl` của config (bỏ name, url, domains,
        engine, search_*, và field chỉ dùng trong source preset mà không
        thuộc CrawlConfig: metadata selectors, legacy browser settings)."""
        data = asdict(self)
        # Field không thuộc CrawlConfig — chỉ là metadata source preset
        _source_only = {
            "name", "url", "domains", "engine",
            "toc_selector", "chapter_title_selector", "title_selector",
            "author_selector", "desc_selector", "cover_selector",
            "encoding", "user_agent", "magic", "js_code",
            "max_search_results",
            "ai_glossary_enabled", "ai_glossary_extract_prompt", "ai_glossary_merge_prompt",
            "ai_cleanup_enabled", "ai_cleanup_prompt",
            "ai_eval_enabled", "ai_eval_prompt",
        }
        for key in _source_only:
            data.pop(key, None)
        return {k: v for k, v in data.items() if not k.startswith("search_")}

    def to_crawl_config(self, toc_url: str = "", mode_override: str = ""):
        """Dựng `CrawlConfig` từ preset để fetch/crawl một `toc_url`.

        Chuyển các field scrapling phẳng (scrapling_mode, solve_cloudflare,
        network_idle, impersonate, proxy, dns_over_https) sang `ScraplingConfig`
        lồng của CrawlConfig. `mode_override` (nếu có) ép chế độ scrapling —
        dùng khi người dùng chọn tay lúc Thêm ebook. Gộp logic trước đây lặp ở
        route test nguồn để mọi nơi fetch nguồn dùng chung 1 đường.
        """
        from .config import CrawlConfig, ScraplingConfig

        overrides = self.crawl_overrides()
        overrides.pop("chapter_link_pattern", None)
        scrapling_kwargs: dict[str, Any] = {}
        legacy_mode = overrides.pop("scrapling_mode", None)
        if legacy_mode is not None:
            scrapling_kwargs["mode"] = legacy_mode
        for legacy_key in ("solve_cloudflare", "network_idle", "impersonate", "proxy", "dns_over_https"):
            val = overrides.pop(legacy_key, None)
            if val is not None:
                scrapling_kwargs[legacy_key] = val
        crawl_cfg = CrawlConfig(
            toc_url=toc_url,
            chapter_link_pattern=self.chapter_link_pattern,
            **overrides,
        )
        if scrapling_kwargs:
            crawl_cfg.scrapling = ScraplingConfig(**scrapling_kwargs)
        if mode_override:
            crawl_cfg.scrapling.mode = mode_override
        return crawl_cfg

    def __post_init__(self) -> None:
        # Tự suy `domains` từ `url` khi để trống, để detect_preset vẫn dùng được.
        if self.url and not self.domains:
            host = urlparse(self.url).hostname or ""
            if host.startswith("www."):
                host = host[4:]
            self.domains = host


_FIELD_NAMES = {f.name for f in fields(SourcePreset)}


def _coerce(name: str, value: Any) -> Any:
    if name in {"headless", "magic", "solve_cloudflare", "network_idle", "dns_over_https", "ai_glossary_enabled", "ai_cleanup_enabled", "ai_eval_enabled"}:
        return bool(value)
    if name == "delay_seconds":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0
    if name in {"max_pages_per_chapter", "toc_max_pages"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10 if name == "max_pages_per_chapter" else 5
    if name in {"concurrency_cap", "max_search_results"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 5 if name == "max_search_results" else 0
    return "" if value is None else value


def load_presets(path: str | Path) -> dict[str, SourcePreset]:
    """Đọc bảng `sources` của DB tại `path`."""
    db_path = Path(path).resolve()
    if not db_path.exists():
        return {}
    conn = get_thread_connection(db_path)
    presets: dict[str, SourcePreset] = {}
    for r in conn.execute("SELECT name, data_json FROM sources ORDER BY name"):
        item = json.loads(r["data_json"] or "{}")
        data = {k: _coerce(k, v) for k, v in item.items() if k in _FIELD_NAMES}
        data["name"] = r["name"]
        presets[r["name"]] = SourcePreset(**data)
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


# Key lồng trong `crawl.scrapling` → tên field PHẲNG tương ứng của SourcePreset.
# `preset.crawl_overrides()` trả tên phẳng (`scrapling_mode`), còn ebook override
# ghi kiểu lồng (`{"scrapling": {"mode": ...}}`) — không quy đổi thì so sánh trượt.
SCRAPLING_FIELD_MAP = {
    "mode": "scrapling_mode",
    "solve_cloudflare": "solve_cloudflare",
    "network_idle": "network_idle",
    "impersonate": "impersonate",
    "proxy": "proxy",
    "dns_over_https": "dns_over_https",
}


# Tên PHẲNG (SourcePreset / legacy defaults.crawl) → key lồng trong `crawl.scrapling`.
_FLAT_SCRAPLING_TO_NESTED = {v: k for k, v in SCRAPLING_FIELD_MAP.items()}


def neutralize_defaults_crawl(
    defaults_crawl: dict[str, Any],
    preset: SourcePreset | None,
) -> dict[str, Any]:
    """Override tối thiểu để ebook (sau khi xoá override riêng) resolve ra ĐÚNG
    "preset + mặc định dataclass" — bất chấp khối `crawl` còn sót trong
    defaults (config chung cũ, vd `content_selector: "#content"`).

    `load_config` merge `defaults.crawl` bên dưới preset/override, nên key nào
    defaults có mà preset KHÔNG phủ sẽ rò vào ebook — làm nút Reset "về
    nguồn/mặc định" không chính xác. Hàm trả dict các key rò rỉ đó với giá trị
    MẶC ĐỊNH (dataclass) để ghi vào override của ebook, trung hoà đúng chỗ rò
    mà không đụng config chung (ebook khác giữ nguyên). Hàm thuần.
    """
    from .config import CrawlConfig, CrawlRetryConfig, ScraplingConfig

    covered = set(preset.crawl_overrides()) if preset else set()
    base = CrawlConfig()
    s_base = ScraplingConfig()
    out: dict[str, Any] = {}
    scrapling_out: dict[str, Any] = {}
    for key, val in (defaults_crawl or {}).items():
        if key == "toc_url":
            continue  # định danh ebook — caller tự giữ
        if key == "scrapling" and isinstance(val, dict):
            for nk, nv in val.items():
                flat = SCRAPLING_FIELD_MAP.get(nk, nk)
                if flat in covered or not hasattr(s_base, nk):
                    continue
                dv = getattr(s_base, nk)
                if nv != dv:
                    scrapling_out.setdefault(nk, dv)
            continue
        if key == "retry" and isinstance(val, dict):
            r_base = CrawlRetryConfig()
            sub = {rk: getattr(r_base, rk) for rk, rv in val.items()
                   if hasattr(r_base, rk) and rv != getattr(r_base, rk)}
            if sub:
                out["retry"] = sub
            continue
        if key in _FLAT_SCRAPLING_TO_NESTED:
            # Key scrapling phẳng legacy trong defaults (`scrapling_mode`...) —
            # load_config vẫn map vào ScraplingConfig nên phải trung hoà dạng lồng.
            if key in covered:
                continue
            nk = _FLAT_SCRAPLING_TO_NESTED[key]
            dv = getattr(s_base, nk)
            if val != dv:
                scrapling_out.setdefault(nk, dv)
            continue
        if key in covered:
            continue
        if not hasattr(base, key):
            continue  # key legacy bị load_config bỏ qua — không cần trung hoà
        dv = getattr(base, key)
        if val != dv:
            out[key] = dv
    if scrapling_out:
        out["scrapling"] = scrapling_out
    return out


def strip_preset_defaults(
    crawl_over: dict[str, Any],
    preset: SourcePreset,
) -> tuple[dict[str, Any], list[str]]:
    """Bỏ khỏi ``crawl_over`` những key có giá trị TRÙNG KHÍT preset.

    Ebook gắn source chỉ nên lưu field nó CỐ Ý override; field trùng preset là
    thừa và có hại — nó đóng băng ebook ở giá trị preset tại thời điểm ghi,
    khiến preset sửa về sau không còn tác dụng.

    ``toc_url`` không bao giờ bị bỏ: `SourcePreset` không có field này nên nó
    không xuất hiện trong ``preset.crawl_overrides()``.

    Trả ``(crawl_over đã lọc, danh sách key đã bỏ)``. Key lồng báo dạng
    ``"scrapling.mode"``. Hàm thuần, idempotent.
    """
    preset_vals = preset.crawl_overrides()
    cleaned: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in crawl_over.items():
        if key == "scrapling" and isinstance(value, dict):
            nested: dict[str, Any] = {}
            for nk, nv in value.items():
                flat = SCRAPLING_FIELD_MAP.get(nk, nk)
                if flat in preset_vals and preset_vals[flat] == nv:
                    removed.append(f"scrapling.{nk}")
                else:
                    nested[nk] = nv
            if nested:
                cleaned[key] = nested
            continue
        if key in preset_vals and preset_vals[key] == value:
            removed.append(key)
        else:
            cleaned[key] = value
    return cleaned, removed


# UPSERT THẬT (ON CONFLICT DO UPDATE) — tuyệt đối KHÔNG dùng INSERT OR REPLACE
# cho bảng `sources`: OR REPLACE xoá row cũ rồi chèn lại, và trên DB tạo từ
# schema cũ (ebooks còn FK `source_preset → sources(name) ON DELETE SET NULL`)
# cú xoá ngầm đó lặng lẽ GỠ NGUỒN khỏi mọi ebook đang gắn preset — chính là bug
# "Lưu vào nguồn" đẩy được giá trị nhưng ebook mất liên kết nguồn.
_UPSERT_SOURCE_SQL = """
    INSERT INTO sources (name, data_json) VALUES (?, ?)
    ON CONFLICT(name) DO UPDATE SET
        data_json = excluded.data_json,
        updated_at = datetime('now')
"""


def save_preset(path: str | Path, preset: SourcePreset) -> None:
    """Lưu đúng 1 preset bằng UPSERT — không ảnh hưởng preset khác."""
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    data = {k: v for k, v in asdict(preset).items() if k != "name"}
    with conn:
        conn.execute(_UPSERT_SOURCE_SQL, (preset.name, json.dumps(data, ensure_ascii=False)))


def delete_preset(path: str | Path, name: str) -> None:
    """Xóa đúng 1 preset theo name; nếu không tồn tại thì bỏ qua."""
    db_path = Path(path).resolve()
    if not db_path.exists():
        return
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute("DELETE FROM sources WHERE name = ?", (name,))


def save_presets(path: str | Path, presets: dict[str, SourcePreset]) -> None:
    """Ghi đè toàn bộ bảng `sources` bằng UPSERT per-row trong 1 transaction.

    Preset nào có trong DB nhưng không có trong dict sẽ bị xóa để đồng bộ.
    Dùng `save_preset()` để lưu 1 preset độc lập mà không xóa preset khác.
    """
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    names = list(presets.keys())
    with conn:
        for name, preset in presets.items():
            data = {k: v for k, v in asdict(preset).items() if k != "name"}
            conn.execute(_UPSERT_SOURCE_SQL, (name, json.dumps(data, ensure_ascii=False)))
        if names:
            placeholders = ",".join("?" * len(names))
            conn.execute(
                f"DELETE FROM sources WHERE name NOT IN ({placeholders})", names
            )
        else:
            conn.execute("DELETE FROM sources")
