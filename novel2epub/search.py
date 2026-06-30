"""Tìm kiếm tiểu thuyết trên nhiều web source đã cấu hình search.

Module cung cấp `SourceSearcher` (tìm trên 1 source) và `search_all()` (tìm
song song trên nhiều source bằng ThreadPoolExecutor).
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urljoin

from .sources import SourcePreset

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    author: str = ""
    url: str = ""
    source_name: str = ""
    cover_url: str = ""
    chapter_count: int = 0
    description: str = ""


@dataclass
class SearchError:
    source_name: str
    message: str


@dataclass
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    errors: list[SearchError] = field(default_factory=list)


def _fetch_page(url: str, preset: SourcePreset) -> Any:
    """Fetch 1 URL bằng scrapling, trả về page object."""
    from scrapling.fetchers import Fetcher, StealthyFetcher

    mode = (preset.scrapling_mode or "fetcher").lower()
    kwargs: dict = {}
    if mode == "stealthy":
        kwargs["headless"] = preset.headless
        kwargs["network_idle"] = preset.network_idle
        if preset.solve_cloudflare:
            kwargs["solve_cloudflare"] = True
        page = StealthyFetcher.fetch(url, **kwargs)
    else:
        if preset.impersonate:
            kwargs["impersonate"] = preset.impersonate
        page = Fetcher.get(url, **kwargs)
    return page


def _sel_text(el: Any, selector: str) -> str:
    """Lấy text từ element con theo CSS selector."""
    if not selector:
        return ""
    results = el.css(selector)
    if not results:
        return ""
    node = results[0] if hasattr(results, '__getitem__') else results
    if hasattr(node, "get_all_text"):
        return node.get_all_text(strip=True)
    text = node.text if hasattr(node, 'text') else ""
    return text.strip() if text else ""


def _sel_attr(el: Any, selector: str, attr: str) -> str:
    """Lấy attribute từ element con theo CSS selector."""
    if not selector:
        return ""
    results = el.css(selector)
    if not results:
        return ""
    node = results[0] if hasattr(results, '__getitem__') else results
    return node.attrib.get(attr, "")


class SourceSearcher:
    """Tìm kiếm tiểu thuyết trên 1 source preset."""

    def __init__(self, preset: SourcePreset):
        self.preset = preset

    def search(self, query: str) -> list[SearchResult]:
        """Tìm kiếm trên source này, trả về danh sách kết quả."""
        if not self.preset.search_url_pattern:
            return []

        url = self.preset.search_url_pattern.replace("{query}", quote(query))
        page = _fetch_page(url, self.preset)

        if self.preset.search_result_selector:
            items = page.css(self.preset.search_result_selector)
        else:
            items = page.css("a[href]")

        if not items:
            items = []

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        limit = self.preset.max_search_results or 5

        for item in items:
            if len(results) >= limit:
                break

            title = _sel_text(item, self.preset.search_title_selector)
            if not title:
                if hasattr(item, "get_all_text"):
                    title = item.get_all_text(strip=True)
                else:
                    title = item.text.strip() if hasattr(item, 'text') and item.text else ""

            link = _sel_attr(item, self.preset.search_link_selector, "href")
            if not link:
                link = item.attrib.get("href", "")

            if not link or not title:
                continue

            full_url = urljoin(url, link)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            author = _sel_text(item, self.preset.search_author_selector)
            cover = _sel_attr(item, self.preset.search_cover_selector, "src")
            if cover:
                cover = urljoin(url, cover)

            results.append(SearchResult(
                title=title,
                author=author,
                url=full_url,
                source_name=self.preset.name,
                cover_url=cover,
            ))

        return results


def _enrich_metadata(result: SearchResult, preset: SourcePreset) -> SearchResult:
    """Fetch trang mục lục để lấy metadata đầy đủ (author, chapters, description)."""
    try:
        from .config import CrawlConfig
        from .crawler import ScraplingCrawler

        crawl_cfg = CrawlConfig(toc_url=result.url)
        overrides = preset.crawl_overrides()
        overrides.pop("chapter_link_pattern", None)
        overrides.pop("engine", None)
        for k, v in overrides.items():
            if hasattr(crawl_cfg, k) and v not in ("", None):
                setattr(crawl_cfg, k, v)

        crawler = ScraplingCrawler(crawl_cfg)
        try:
            toc = crawler.fetch_toc()
        finally:
            crawler.close()

        if toc.title and not result.title:
            result.title = toc.title
        if toc.author:
            result.author = toc.author
        if toc.description:
            result.description = toc.description
        if toc.cover_url:
            result.cover_url = toc.cover_url
        result.chapter_count = len(toc.chapters)
    except Exception as e:
        logger.debug("Không thể enrich metadata từ %s: %s", result.url, e)

    return result


def search_all(
    presets: dict[str, SourcePreset],
    query: str,
    *,
    source_names: list[str] | None = None,
    enrich: bool = False,
    max_workers: int = 5,
    delay_between: float = 0.0,
) -> SearchResponse:
    """Tìm kiếm song song trên nhiều source, trả về SearchResponse."""
    if source_names:
        active = {n: p for n, p in presets.items() if n in source_names and p.search_url_pattern}
    else:
        active = {n: p for n, p in presets.items() if p.search_url_pattern}

    if not active:
        return SearchResponse(errors=[SearchError(source_name="*", message="Không có source nào được cấu hình tìm kiếm")])

    response = SearchResponse()

    def _search_one(name: str, preset: SourcePreset) -> tuple[str, list[SearchResult], str]:
        try:
            searcher = SourceSearcher(preset)
            results = searcher.search(query)
            return name, results, ""
        except Exception as e:
            return name, [], str(e)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(active))) as executor:
        futures = {
            executor.submit(_search_one, name, preset): name
            for name, preset in active.items()
        }
        for future in as_completed(futures):
            name, results, error = future.result()
            if error:
                response.errors.append(SearchError(source_name=name, message=error))
                logger.warning("Search error on %s: %s", name, error)
            else:
                response.results.extend(results)

            if delay_between > 0:
                time.sleep(delay_between)

    if enrich:
        for result in response.results:
            preset = presets.get(result.source_name)
            if preset:
                _enrich_metadata(result, preset)

    response.results.sort(key=lambda r: (r.source_name, r.title))
    return response


def search_all_stream(
    presets: dict[str, SourcePreset],
    query: str,
    *,
    source_names: list[str] | None = None,
    enrich: bool = False,
    max_workers: int = 5,
):
    """Tìm kiếm song song, yields dict per source khi xong.

    Yields:
        {"event": "source_results", "data": {"source_name": ..., "results": [...]}}
        {"event": "source_error",    "data": {"source_name": ..., "error": ...}}
        {"event": "done",            "data": {"total": ...}}
    """
    if source_names:
        active = {n: p for n, p in presets.items() if n in source_names and p.search_url_pattern}
    else:
        active = {n: p for n, p in presets.items() if p.search_url_pattern}

    if not active:
        yield {"event": "done", "data": {"total": 0}}
        return

    def _search_one(name: str, preset: SourcePreset) -> tuple[str, list[SearchResult], str]:
        try:
            searcher = SourceSearcher(preset)
            results = searcher.search(query)
            return name, results, ""
        except Exception as e:
            return name, [], str(e)

    total = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, len(active))) as executor:
        futures = {
            executor.submit(_search_one, name, preset): name
            for name, preset in active.items()
        }
        for future in as_completed(futures):
            name, results, error = future.result()
            if error:
                yield {"event": "source_error", "data": {"source_name": name, "error": error}}
            else:
                if enrich:
                    preset = presets.get(name)
                    for r in results:
                        if preset:
                            _enrich_metadata(r, preset)
                total += len(results)
                items = [
                    {
                        "title": r.title,
                        "author": r.author,
                        "url": r.url,
                        "source_name": r.source_name,
                        "cover_url": r.cover_url,
                        "chapter_count": r.chapter_count,
                        "description": r.description,
                    }
                    for r in results
                ]
                yield {"event": "source_results", "data": {"source_name": name, "results": items}}

    yield {"event": "done", "data": {"total": total}}
