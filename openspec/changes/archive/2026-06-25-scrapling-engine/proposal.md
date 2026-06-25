## Why

Dự án hiện có 2 crawl engine: `http` (requests + BeautifulSoup) và `crawl4ai` (Playwright browser). Một số trang tiểu thuyết có anti-bot mạnh (Cloudflare Turnstile, fingerprint detection) mà cả hai engine đều gặp khó khăn. Scrapling (github.com/D4Vinci/Scrapling) cung cấp `StealthyFetcher` với fingerprint spoofing, bypass Cloudflare tích hợp sẵn, và adaptive element tracking — tất cả trong API đơn giản. Thêm Scrapling như engine thứ 3 giúp người dùng có thêm lựa chọn khi hai engine hiện tại không vượt qua được anti-bot.

## What Changes

- Thêm giá trị `engine: scrapling` vào `CrawlConfig` (bên cạnh `http` và `crawl4ai`).
- Tạo class `ScraplingCrawler` implement `Crawler` Protocol (fetch_toc, fetch_chapter, sleep, close).
- Mở rộng `make_crawler()` factory để khởi tạo `ScraplingCrawler` khi `engine == "scrapling"`.
- Thêm config fields cho Scrapling: `scrapling_mode` (fetcher/stealthy/dynamic), `solve_cloudflare`, `network_idle`, `impersonate`.
- Cập nhật `SourcePreset` để hỗ trợ engine `scrapling` cùng các field mới.
- Thêm `scrapling` vào danh sách optional dependency (`pip install "novel2epub[scrapling]"` hoặc gộp vào fetchers).
- Cập nhật Web UI form chọn engine để hiển thị option `scrapling`.
- Hỗ trợ pagination (`fetch_chapter_paginated`) với engine mới.
- Scrapling là optional — lazy import, chỉ cần cài khi user chọn `engine: scrapling`.

## Capabilities

### New Capabilities
- `scrapling-engine`: Engine crawl thứ 3 dùng thư viện Scrapling, cung cấp `StealthyFetcher`/`DynamicFetcher` với anti-bot bypass, fingerprint spoofing, adaptive element tracking, và proxy rotation tích hợp.

### Modified Capabilities
_(không có capability spec nào hiện hữu cần thay đổi ở cấp requirement)_

## Impact

- **Code**: `novel2epub/crawler.py` (thêm class `ScraplingCrawler`, mở rộng `make_crawler`), `novel2epub/config.py` (thêm fields), `novel2epub/sources.py` (thêm fields cho `SourcePreset`).
- **Web UI**: `app/routes/sources.py` form thêm engine option; templates hiển thị scrapling-specific fields.
- **Dependencies**: Thêm `scrapling[fetchers]` vào optional deps trong `pyproject.toml`. Yêu cầu chạy `scrapling install` để cài browser dependencies (tương tự `crawl4ai-setup`).
- **Config**: `novel2epub.example.yaml` thêm ví dụ source preset dùng engine scrapling. Không breaking — `engine: http` và `engine: crawl4ai` hoạt động y như trước.
- **Tests**: Thêm unit tests cho `ScraplingCrawler` (mock Scrapling fetchers).
