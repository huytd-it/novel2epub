"""Tạo `SourcePreset` tự động từ URL mục lục dùng AI (OpenAI-Compatible) + preview validation.

Flow chính:
  1. Thử fetch HTML bằng HttpCrawler trước (nhanh, free).
  2. Heuristic chọn engine http hoặc crawl4ai.
  3. Gửi HTML cho AI, yêu cầu JSON chứa các selector/pattern.
  4. Validate `chapter_link_pattern` bằng cách đếm số link match trong phạm vi
     `toc_selector`; quá ít/quá nhiều thì yêu cầu AI refine (tối đa 3 vòng).
  5. Chạy `crawler.fetch_toc()` để preview danh sách chương.
  6. Trả về `PresetBuilderResult` (KHÔNG tự ghi sources.yaml; caller quyết định).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .config import OpenAIConfig, CrawlConfig, load_config
from .crawler import TocResult, make_crawler
from .sources import SourcePreset, load_presets, save_presets


DEFAULT_CANDIDATE_TOC_SELECTORS = [
    "#list",
    "#i-chapter",
    "#allchapter",
    ".listmain",
    "ul.chapter",
    "body",
]


@dataclass
class PresetBuilderResult:
    """Kết quả của preset builder (và preview non-mutating)."""

    preset: SourcePreset | None = None
    preview: TocResult | None = None
    engine: str = ""
    validation: dict = field(default_factory=dict)
    rounds: int = 0
    overrides_applied: list[str] = field(default_factory=list)
    error: str | None = None


def select_engine_heuristic(
    soup: BeautifulSoup,
    candidate_toc_selectors: list[str] | None = None,
) -> str:
    """Chọn engine: http nếu trang có link chương rõ ràng, ngược lại crawl4ai."""
    if soup is None:
        return "crawl4ai"
    candidates = candidate_toc_selectors or DEFAULT_CANDIDATE_TOC_SELECTORS
    for sel in candidates:
        scope = soup.select_one(sel)
        if scope is not None:
            links = scope.find_all("a", href=True)
            if len(links) >= 2:
                return "http"
    # Nếu body gần như trống hoặc không có <a> nào -> JS render.
    body = soup.find("body")
    if body is None or len(body.get_text(strip=True)) < 100 or not body.find_all("a", href=True):
        return "crawl4ai"
    return "http"


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "unknown").split(":")[0]


def _preset_name_from_host(url: str) -> str:
    host = _hostname(url)
    # Bỏ tiền tố www. và TLD.
    host = re.sub(r"^www\.", "", host, flags=re.IGNORECASE)
    host = host.split(".")[0]
    return host or "site"


def _domains_from_host(url: str) -> str:
    host = _hostname(url)
    # www.example.com -> example.com; example.com -> example.com.
    if host.startswith("www."):
        return f"{host[4:]},{host}"
    return host


def build_ai_suggestion_prompt(html: str, toc_url: str, novel_title: str) -> str:
    """Prompt yêu cầu AI trả về JSON chứa các field preset."""
    return f"""Bạn là kỹ sư crawler. Dưới đây là HTML trang mục lục của truyện "{novel_title}".
Hãy phân tích và trả về một JSON object DUY NHẤT với các khóa sau (KHÔNG thêm giải thích ngoài JSON):

{{
  "toc_selector": "CSS selector vùng chứa danh sách link chương (vd #list, #i-chapter, #allchapter, .listmain, ul.chapter). Để trống nếu không chắc.",
  "content_selector": "CSS selector vùng nội dung chương (vd #content, .content, .read-content). Để trống nếu không chắc.",
  "chapter_link_pattern": "regex Python để lọc URL chương trong phạm vi toc_selector. PHẢI match TẤT CẢ link chương nhưng KHÔNG match link header/footer/quảng cáo. Vd: /novel/\\\\d+/\\\\d+\\.html$",
  "chapter_title_selector": "CSS selector tiêu đề chương, vd h1. Để trống nếu không chắc.",
  "title_selector": "CSS selector tên truyện trên trang mục lục. Để trống nếu dùng thẻ meta og:title.",
  "author_selector": "CSS selector tác giả. Để trống nếu dùng meta.",
  "desc_selector": "CSS selector mô tả. Để trống nếu dùng meta.",
  "cover_selector": "CSS selector ảnh bìa img. Để trống nếu dùng meta og:image.",
  "encoding": "bảng mã trang (vd gbk, gb2312, utf-8). Để trống nếu tự đoán được.",
  "engine": "http hoặc crawl4ai",
  "headless": true,
  "magic": true,
  "js_code": "JS string để chạy trước khi lấy nội dung nếu cần (vd cuộn lazy-load). Để trống nếu không cần.",
  "delay_seconds": 1.0,
  "next_page_selector": "CSS selector link trang tiếp theo trong chương nếu có pagination. Để trống nếu không.",
  "next_page_url_pattern": "regex pattern có đúng 1 capturing group cho pagination URL fallback. Để trống nếu không.",
  "max_pages_per_chapter": 10,
  "reasoning": "một dòng giải thích ngắn"
}}

URL mục lục: {toc_url}

--- HTML ---
{html}
"""


def parse_ai_suggestion(text: str) -> dict[str, Any]:
    """Parse JSON từ AI output; chấp nhận ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI trả về không phải JSON hợp lệ: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("AI trả về JSON không phải object.")
    return data


def _count_pattern_links(pattern: str, soup: BeautifulSoup, toc_selector: str) -> tuple[int, list[str]]:
    """Đếm link match pattern trong scope. Trả về (count, sample)."""
    scope = soup
    if toc_selector:
        node = soup.select_one(toc_selector)
        if node is not None:
            scope = node
    try:
        pat = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"chapter_link_pattern không phải regex hợp lệ: {e}") from e

    urls: list[str] = []
    for a in scope.find_all("a", href=True):
        href = a["href"].strip()
        if pat.search(href):
            urls.append(href)
    # Deduplicate giữ nguyên thứ tự.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return len(deduped), deduped


def validate_pattern(
    pattern: str,
    soup: BeautifulSoup,
    toc_selector: str,
    *,
    low: int = 5,
    high: int = 2000,
) -> dict[str, Any]:
    """Validate pattern: ok / too_broad / too_narrow."""
    count, sample = _count_pattern_links(pattern, soup, toc_selector)
    result: dict[str, Any] = {
        "status": "ok",
        "count": count,
        "threshold": {"low": low, "high": high},
        "sample": sample[:20],
    }
    if count < low:
        result["status"] = "too_narrow"
    elif count > high:
        result["status"] = "too_broad"
    return result


def _refine_feedback(
    pattern: str,
    validation: dict[str, Any],
    toc_url: str,
) -> str:
    status = validation["status"]
    count = validation["count"]
    sample = validation.get("sample", [])
    sample_text = "\n".join(f"  - {u}" for u in sample[:10])
    if status == "too_broad":
        return (
            f"Regex hiện tại match quá nhiều link ({count} links). "
            "Hãy thu hẹp lại để chỉ match link CHƯƠNG thật sự, không match header/footer/quảng cáo.\n"
            f"Một số URL đang bị match nhầm:\n{sample_text}\n"
            f"URL mục lục gốc: {toc_url}\n"
            "Trả về JSON object duy nhất với khóa 'chapter_link_pattern' chứa regex mới."
        )
    return (
        f"Regex hiện tại match quá ít link ({count} links). "
        "Hãy nới rộng để match tất cả link chương.\n"
        f"URL mục lục gốc: {toc_url}\n"
        "Trả về JSON object duy nhất với khóa 'chapter_link_pattern' chứa regex mới."
    )


def refine_pattern_with_ai(
    pattern: str,
    validation: dict[str, Any],
    ai_call: Callable[[str], str],
    toc_url: str,
    max_rounds: int = 3,
) -> tuple[str, dict[str, Any], int]:
    """Refine pattern qua AI. Trả về (final_pattern, final_validation, rounds_used)."""
    current = pattern
    current_validation = validation
    rounds = 0
    for _ in range(max_rounds):
        if current_validation["status"] == "ok":
            break
        rounds += 1
        feedback = _refine_feedback(current, current_validation, toc_url)
        raw = ai_call(feedback)
        try:
            data = parse_ai_suggestion(raw)
        except ValueError:
            # Nếu AI trả lỗi, thử regex brute-force.
            new_pattern = _fallback_refine(current, current_validation)
            data = {"chapter_link_pattern": new_pattern}
        new_pattern = data.get("chapter_link_pattern", current)
        if new_pattern == current:
            break
        current = new_pattern
        # Giả lập validation mới sẽ được tính lại bởi caller; ở đây chỉ parse.
        # Để tránh parse lại soup, caller sẽ re-validate.
        current_validation = {"status": "ok", "count": 0}  # placeholder
    return current, current_validation, rounds


def _fallback_refine(pattern: str, validation: dict[str, Any]) -> str:
    """Heuristic fallback nếu AI refine thất bại."""
    # Quá rộng thì thêm /chapter/ hoặc /read/ nếu URL có; quá hẹp thì bỏ số cuối.
    if validation["status"] == "too_broad":
        # Thêm cụm /\d+\.html$ nếu chưa có.
        if r"\d+" not in pattern:
            return pattern.rstrip(".*$") + r"/\d+\.html$"
        return pattern
    # too_narrow: thay số cụ thể bằng \d+.
    return re.sub(r"\d+", r"\\d+", pattern)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 10) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_source_preset(name: str, data: dict[str, Any], url: str) -> SourcePreset:
    """Tạo SourcePreset từ AI JSON; domain tự lấy từ URL."""
    return SourcePreset(
        name=name,
        engine=data.get("engine", "http").lower(),
        domains=_domains_from_host(url),
        chapter_link_pattern=data.get("chapter_link_pattern", r".*"),
        content_selector=data.get("content_selector", ""),
        toc_selector=data.get("toc_selector", ""),
        chapter_title_selector=data.get("chapter_title_selector", ""),
        title_selector=data.get("title_selector", ""),
        author_selector=data.get("author_selector", ""),
        desc_selector=data.get("desc_selector", ""),
        cover_selector=data.get("cover_selector", ""),
        encoding=data.get("encoding", ""),
        user_agent=data.get("user_agent", CrawlConfig.user_agent),
        headless=_bool(data.get("headless", True)),
        magic=_bool(data.get("magic", True)),
        js_code=data.get("js_code", ""),
        delay_seconds=_float(data.get("delay_seconds", 1.0)),
        next_page_selector=data.get("next_page_selector", ""),
        next_page_url_pattern=data.get("next_page_url_pattern", ""),
        max_pages_per_chapter=_int(data.get("max_pages_per_chapter", 10)),
    )


def _get_openai_config(config_path: str | None = None) -> OpenAIConfig | None:
    """Load openai config từ file config. Trả None nếu không có AI cấu hình."""
    path = config_path or os.environ.get(
        "NOVEL2EPUB_FILE", os.environ.get("NOVEL2EPUB_CONFIG", "novel2epub.yaml")
    )
    try:
        cfg = load_config(path)
        openai_cfg = cfg.translate.openai
        if cfg.translate.type.lower() == "none":
            return None
        return openai_cfg
    except Exception:
        return None


def build_preset(
    toc_url: str,
    novel_title: str = "赤心巡天",
    overrides: dict[str, Any] | None = None,
    *,
    config_path: str | None = None,
    preset_name: str = "",
    max_rounds: int = 3,
    low: int = 5,
    high: int = 2000,
    timeout_seconds: int = 120,
) -> PresetBuilderResult:
    """Tạo preset candidate + preview từ URL mục lục. Không ghi sources.yaml."""
    result = PresetBuilderResult()
    overrides = overrides or {}
    try:
        # 1. Fetch HTML bằng http để phân tích.
        http_cfg = CrawlConfig(toc_url=toc_url)
        http_crawler = make_crawler(http_cfg)
        try:
            soup = http_crawler._get_soup(toc_url)
        finally:
            http_crawler.close()

        # 2. Chọn engine.
        engine = select_engine_heuristic(soup)
        result.engine = engine

        # 3. Gọi AI.
        openai_cfg = _get_openai_config(config_path)
        if openai_cfg is None:
            result.error = (
                "Chưa cấu hình AI. "
                "Set translate.type != none và translate.openai.base_url/api_key/model trong config."
            )
            return result
        openai_cfg.timeout_seconds = timeout_seconds
        html = str(soup)[:32000]
        prompt = build_ai_suggestion_prompt(html, toc_url, novel_title)

        from . import openai_client

        def _ai_call(p: str) -> str:
            return openai_client.run_chat(openai_cfg, p)

        raw = _ai_call(prompt)
        data = parse_ai_suggestion(raw)

        # 4. Validate + refine pattern.
        pattern = data.get("chapter_link_pattern", ".*")
        toc_selector = data.get("toc_selector", "")
        validation = validate_pattern(pattern, soup, toc_selector, low=low, high=high)
        rounds = 0
        while validation["status"] != "ok" and rounds < max_rounds:
            pattern, _, used = refine_pattern_with_ai(
                pattern, validation, _ai_call, toc_url, max_rounds=max_rounds - rounds
            )
            rounds += used
            if used == 0:
                break
            validation = validate_pattern(pattern, soup, toc_selector, low=low, high=high)
        result.validation = validation
        result.rounds = rounds

        # 5. Cập nhật data với pattern cuối.
        data["chapter_link_pattern"] = pattern
        if engine == "crawl4ai":
            data["engine"] = "crawl4ai"

        # 6. Áp overrides.
        name = preset_name or _preset_name_from_host(toc_url)
        preset = _build_source_preset(name, data, toc_url)
        overrides_applied: list[str] = []
        for key, value in overrides.items():
            if hasattr(preset, key) and value != "":
                setattr(preset, key, value)
                overrides_applied.append(key)
        result.overrides_applied = overrides_applied

        # Nếu override engine hoặc có js_code -> force crawl4ai.
        if "engine" in overrides or "js_code" in overrides:
            preset.engine = overrides.get("engine", "crawl4ai")

        # 7. Preview bằng crawler thật.
        crawl_cfg = CrawlConfig(toc_url=toc_url, **preset.crawl_overrides())
        crawler = make_crawler(crawl_cfg)
        try:
            preview = crawler.fetch_toc()
        finally:
            crawler.close()
        result.preset = preset
        result.preview = preview
        return result

    except Exception as e:
        result.error = str(e)
        return result


def preview_toc(
    toc_url: str,
    preset_name: str,
    presets_path: str | Path,
) -> PresetBuilderResult:
    """Chạy preview bằng preset đã lưu; không gọi AI, không ghi file."""
    result = PresetBuilderResult()
    try:
        presets = load_presets(presets_path)
        preset = presets.get(preset_name)
        if preset is None:
            result.error = f"Không tìm thấy preset '{preset_name}'"
            return result
        crawl_cfg = CrawlConfig(toc_url=toc_url, **preset.crawl_overrides())
        result.engine = crawl_cfg.engine
        crawler = make_crawler(crawl_cfg)
        try:
            result.preview = crawler.fetch_toc()
        finally:
            crawler.close()
        result.preset = preset
        return result
    except Exception as e:
        result.error = str(e)
        return result


def save_preset(
    preset: SourcePreset,
    presets_path: str | Path,
) -> None:
    """Ghi preset vào sources.yaml (round-trip qua save_presets)."""
    presets = load_presets(presets_path)
    presets[preset.name] = preset
    save_presets(presets_path, presets)


def remove_preset(name: str, presets_path: str | Path) -> bool:
    """Xoá preset theo tên. Trả về True nếu có xoá."""
    presets = load_presets(presets_path)
    if name not in presets:
        return False
    del presets[name]
    save_presets(presets_path, presets)
    return True
