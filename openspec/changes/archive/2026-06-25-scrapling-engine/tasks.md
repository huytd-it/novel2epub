## 1. Config & Dependencies

- [x] 1.1 Thêm `scrapling[fetchers]` vào optional dependency group `[scrapling]` và `[all]` trong `pyproject.toml`
- [x] 1.2 Thêm fields scrapling-specific vào `CrawlConfig` trong `novel2epub/config.py`: `scrapling_mode: str = "stealthy"`, `solve_cloudflare: bool = False`, `network_idle: bool = True`, `impersonate: str = ""`
- [x] 1.3 Thêm fields tương ứng vào `SourcePreset` trong `novel2epub/sources.py`: `scrapling_mode`, `solve_cloudflare`, `network_idle`, `impersonate`
- [x] 1.4 Cập nhật `_coerce()` trong `sources.py` để xử lý type conversion cho fields mới (bool cho `solve_cloudflare`/`network_idle`)

## 2. ScraplingCrawler Core

- [x] 2.1 Tạo class `ScraplingCrawler` trong `novel2epub/crawler.py` với `__init__(self, cfg: CrawlConfig)` — lazy import scrapling, tạo session theo `scrapling_mode` (Fetcher/Stealthy/Dynamic)
- [x] 2.2 Implement `ScraplingCrawler._fetch_page(url)` — fetch 1 URL bằng Scrapling session, trả về response (Adaptor object). Xử lý HTTP 429 → raise `RateLimitError`
- [x] 2.3 Implement helper `ScraplingCrawler._extract_meta(page)` — extract title, author, description, cover_url từ meta tags và CSS selectors (tương tự `HttpCrawler._extract_meta`)
- [x] 2.4 Implement `ScraplingCrawler.fetch_toc()` — fetch trang TOC, parse chapter links theo `toc_selector`/`chapter_link_pattern`, trả về `TocResult`
- [x] 2.5 Implement `ScraplingCrawler._extract_text(page)` — extract nội dung chương từ `content_selector` (fallback common selectors), clean thẻ script/style/a, trả về text
- [x] 2.6 Implement `ScraplingCrawler._fetch_chapter_single(ch)` — fetch 1 chương, extract text, hỗ trợ AI fallback
- [x] 2.7 Implement `ScraplingCrawler.fetch_chapter(ch)` — dispatch giữa single và paginated (dùng `fetch_chapter_paginated()` shared)
- [x] 2.8 Implement `ScraplingCrawler._ai_fallback_extract(url)` — lấy raw HTML từ response, gọi AI CLI extract
- [x] 2.9 Implement `ScraplingCrawler._clean(text)` — áp dụng `strip_patterns`, normalize newlines
- [x] 2.10 Implement `ScraplingCrawler.sleep()` và `ScraplingCrawler.close()`

## 3. Factory & Wiring

- [x] 3.1 Mở rộng `make_crawler()` trong `crawler.py` để xử lý `engine == "scrapling"` → return `ScraplingCrawler(cfg)`
- [x] 3.2 Cập nhật error message của `make_crawler()` để include "scrapling" trong danh sách engine hợp lệ
- [x] 3.3 Cập nhật comment `engine:` trong `CrawlConfig` để ghi nhận `scrapling` là option

## 4. Web UI

- [x] 4.1 Cập nhật template `sources.html` — thêm `scrapling` vào dropdown engine
- [x] 4.2 Thêm form fields cho scrapling-specific options: `scrapling_mode` dropdown (fetcher/stealthy/dynamic), `solve_cloudflare` checkbox, `network_idle` checkbox, `impersonate` text input
- [x] 4.3 Cập nhật route `save_source_preset()` trong `app/routes/sources.py` để nhận và lưu fields mới
- [x] 4.4 Thêm JS show/hide scrapling fields theo engine selection (tương tự logic hiện có cho crawl4ai fields)

## 5. Example Config & Documentation

- [x] 5.1 Thêm 1 ví dụ source preset dùng engine scrapling vào `novel2epub.example.yaml` (vd cho một site có Cloudflare)
- [x] 5.2 Cập nhật comment trong `novel2epub.example.yaml` defaults block về engine scrapling
- [x] 5.3 Cập nhật AGENTS.md (mục Crawl Engines table) thêm engine scrapling

## 6. Tests

- [x] 6.1 Viết unit test cho `ScraplingCrawler.__init__` — verify lazy import và ImportError message khi chưa cài scrapling
- [x] 6.2 Viết unit test cho `ScraplingCrawler.fetch_toc()` — mock Scrapling response, verify TocResult output
- [x] 6.3 Viết unit test cho `ScraplingCrawler.fetch_chapter()` — mock response, verify text extraction + clean
- [x] 6.4 Viết unit test cho `ScraplingCrawler.fetch_chapter()` với pagination — verify delegation cho `fetch_chapter_paginated()`
- [x] 6.5 Viết unit test cho `make_crawler()` với `engine="scrapling"` — verify trả về ScraplingCrawler
- [x] 6.6 Viết unit test cho `SourcePreset` với scrapling fields — verify `crawl_overrides()` bao gồm fields mới
- [x] 6.7 Verify rằng tests hiện tại (http, crawl4ai) vẫn pass không bị ảnh hưởng
