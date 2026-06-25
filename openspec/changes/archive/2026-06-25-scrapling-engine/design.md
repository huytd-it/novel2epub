## Context

Dự án novel2epub có kiến trúc crawl engine rõ ràng dựa trên `Crawler` Protocol:

```python
class Crawler(Protocol):
    def fetch_toc(self) -> TocResult: ...
    def fetch_chapter(self, ch: Chapter) -> str: ...
    def sleep(self) -> None: ...
    def close(self) -> None: ...
```

Factory `make_crawler(cfg: CrawlConfig)` dispatch theo `cfg.engine`. Hiện có 2 engine:
- `HttpCrawler` — requests + BeautifulSoup, crawl trang tĩnh.
- `Crawl4AICrawler` — Crawl4AI (AsyncWebCrawler + Playwright), render JS.

Cả hai đều hỗ trợ pagination qua hàm shared `fetch_chapter_paginated()`, metadata extraction, AI fallback, retry/backoff, và strip_patterns.

Scrapling cung cấp 3 fetcher class:
- `Fetcher` — HTTP thuần, giả lập TLS fingerprint.
- `StealthyFetcher` — Browser headless stealth, bypass Cloudflare Turnstile.
- `DynamicFetcher` — Playwright automation đầy đủ.

Tất cả trả về `Adaptor` object (tương tự BeautifulSoup) có CSS/XPath selectors.

## Goals / Non-Goals

**Goals:**
- Thêm `engine: scrapling` như option thứ 3 trong `CrawlConfig.engine`, hoạt động song song với http và crawl4ai.
- `ScraplingCrawler` implement đầy đủ Crawler Protocol: fetch_toc, fetch_chapter (bao gồm pagination), sleep, close.
- Tận dụng `StealthyFetcher` để bypass anti-bot (Cloudflare) — đây là lý do chính chọn Scrapling.
- Hỗ trợ cấu hình scrapling-specific qua `CrawlConfig` fields (mode, solve_cloudflare, impersonate).
- Lazy import — chỉ import scrapling khi user chọn engine scrapling, không ảnh hưởng ai dùng http/crawl4ai.
- Web UI hiển thị option scrapling trong dropdown engine và fields tương ứng.
- Optional dependency: `pip install "novel2epub[scrapling]"`.

**Non-Goals:**
- Không migrate user hiện tại khỏi http/crawl4ai. Đây là engine bổ sung, không thay thế.
- Không dùng Scrapling Spider framework (dự án dùng pattern crawl danh sách URL cố định, không cần spider đệ quy).
- Không tích hợp Scrapling MCP server hoặc adaptive element tracking (quá phức tạp cho phase 1).
- Không hỗ trợ Scrapling proxy rotation tích hợp (user có thể cấu hình proxy riêng sau).

## Decisions

### 1. ScraplingCrawler class tách biệt, cùng file `crawler.py`

**Quyết định**: Tạo `ScraplingCrawler` class trong `novel2epub/crawler.py`, cạnh `HttpCrawler` và `Crawl4AICrawler`.

**Lý do**: Giữ cùng file với 2 engine kia để dễ bảo trì (cùng import `TocResult`, `Chapter`, helper functions). File crawler.py đã ~790 dòng, thêm ~180 dòng cho `ScraplingCrawler` vẫn chấp nhận được.

**Thay thế xem xét**: Tách mỗi engine ra file riêng (crawler_http.py, crawler_scrapling.py) — tốt hơn về mặt tổ chức nhưng đòi hỏi refactor lớn không cần thiết lúc này.

### 2. Scrapling mode: mặc định `stealthy`, cấu hình qua `scrapling_mode`

**Quyết định**: Thêm field `scrapling_mode: str = "stealthy"` vào `CrawlConfig` (giá trị: `fetcher`, `stealthy`, `dynamic`). Mặc định `stealthy` vì đó là lý do chính chọn Scrapling.

**Lý do**: 3 Scrapling fetcher class có use case khác nhau:
- `fetcher`: HTTP nhanh, giả lập TLS — dùng khi site không chặn quá mạnh.
- `stealthy`: Browser stealth, bypass Cloudflare — use case chính.
- `dynamic`: Full Playwright — khi cần JS interaction phức tạp.

### 3. Parse HTML bằng Scrapling Adaptor (CSS selectors)

**Quyết định**: Dùng `response.css()` và `response.xpath()` của Scrapling Adaptor để parse HTML, tương tự cách `HttpCrawler` dùng BeautifulSoup và `Crawl4AICrawler` dùng crawl4ai result.

**Lý do**: Scrapling Adaptor API tương thích Parsel/Scrapy nên quen thuộc. CSS selectors trong `CrawlConfig` (content_selector, toc_selector, etc.) dùng trực tiếp được.

### 4. Scrapling fields tái dùng headless, thêm fields riêng

**Quyết định**: Tái dùng các field chung đã có (`headless`, `content_selector`, `toc_selector`, `user_agent`, `encoding`). Thêm fields mới cho scrapling:
- `solve_cloudflare: bool = False` — bật bypass Cloudflare Turnstile (StealthyFetcher).
- `network_idle: bool = True` — chờ network idle trước khi scrape (StealthyFetcher/DynamicFetcher).
- `impersonate: str = ""` — giả lập browser cụ thể (vd "chrome", "firefox135").
- `scrapling_mode: str = "stealthy"` — chọn fetcher class.

**Lý do**: Tái dùng `headless` vì ngữ nghĩa giống nhau giữa crawl4ai và scrapling. Fields mới chỉ áp dụng cho scrapling nên đặt tên rõ ràng.

### 5. fetch_toc: parse HTML từ response, dùng CSS selectors như HttpCrawler

**Quyết định**: `ScraplingCrawler.fetch_toc()` fetch trang TOC, parse bằng Scrapling Adaptor CSS selectors, extract metadata từ meta tags (giống `HttpCrawler._extract_meta`).

**Lý do**: Scrapling trả về Adaptor object hỗ trợ `.css()`, `.find()` — có thể implement logic tương tự HttpCrawler nhưng dùng API Scrapling.

### 6. fetch_chapter: dùng `fetch_chapter_paginated()` shared

**Quyết định**: `ScraplingCrawler.fetch_chapter()` delegate cho `fetch_chapter_paginated()` giống 2 engine kia, truyền 3 closure: fetch_page, extract_text, next_page_url.

**Lý do**: Hàm `fetch_chapter_paginated()` là engine-agnostic, đã handle pagination logic (dedup URL, chapter boundary check, max pages). Không cần viết lại.

### 7. Session management: một Fetcher instance dùng lại

**Quyết định**: Trong `__init__`, tạo 1 Scrapling session (FetcherSession/StealthySession/DynamicSession tùy mode). Dùng lại xuyên suốt, `close()` đóng session.

**Lý do**: Tương tự `HttpCrawler` giữ `requests.Session` và `Crawl4AICrawler` giữ `AsyncWebCrawler`. Mở/đóng browser cho mỗi chương tốn quá nhiều thời gian.

### 8. SourcePreset: thêm fields mới

**Quyết định**: Thêm `scrapling_mode`, `solve_cloudflare`, `network_idle`, `impersonate` vào `SourcePreset` dataclass. `crawl_overrides()` tự bao gồm chúng.

**Lý do**: `SourcePreset` mirror `CrawlConfig` fields. Khi thêm field vào CrawlConfig, SourcePreset cần tương ứng để preset có thể cấu hình đầy đủ.

## Risks / Trade-offs

- **[Risk] Scrapling là thư viện mới (2024), API có thể thay đổi** → Mitigation: Pin version trong pyproject.toml, wrap API trong ScraplingCrawler class để cô lập thay đổi.

- **[Risk] Scrapling fetchers yêu cầu cài browser riêng (`scrapling install`)** → Mitigation: Document rõ trong README và example config. Lazy import + error message hướng dẫn cài đặt.

- **[Risk] Thêm nhiều config fields vào CrawlConfig/SourcePreset** → Mitigation: Fields mới có default hợp lý, chỉ ảnh hưởng khi `engine: scrapling`. Comment rõ "chỉ dùng cho engine = scrapling".

- **[Trade-off] ScraplingCrawler dùng sync API (Fetcher.get, StealthyFetcher.fetch)** → Accept: Pipeline hiện tại là sync (ThreadPoolExecutor cho parallel). Scrapling sync API phù hợp. Async support có thể thêm sau nếu pipeline chuyển async.

- **[Risk] StealthyFetcher cần Camoufox browser riêng** → Mitigation: Ghi rõ trong error message và docs. Fetcher mode (HTTP thuần) không cần browser.
