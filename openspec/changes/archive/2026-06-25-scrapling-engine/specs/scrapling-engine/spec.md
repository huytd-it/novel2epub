## ADDED Requirements

### Requirement: Engine scrapling trong CrawlConfig
`CrawlConfig.engine` SHALL accept giá trị `"scrapling"` bên cạnh `"http"` và `"crawl4ai"`. Khi `engine` là `"scrapling"`, `make_crawler()` SHALL trả về một instance `ScraplingCrawler`.

#### Scenario: Khởi tạo crawler với engine scrapling
- **WHEN** `CrawlConfig.engine == "scrapling"`
- **THEN** `make_crawler(cfg)` trả về `ScraplingCrawler` instance implement đầy đủ `Crawler` Protocol

#### Scenario: Engine không hợp lệ
- **WHEN** `CrawlConfig.engine` là giá trị không phải "http", "crawl4ai", "scrapling"
- **THEN** `make_crawler()` raise `ValueError` với message chỉ rõ các giá trị hợp lệ bao gồm "scrapling"

### Requirement: Scrapling mode configuration
`CrawlConfig` SHALL có field `scrapling_mode: str` với giá trị mặc định `"stealthy"`. Giá trị hợp lệ: `"fetcher"`, `"stealthy"`, `"dynamic"`.

#### Scenario: Mode stealthy (mặc định)
- **WHEN** `scrapling_mode == "stealthy"` (hoặc để trống)
- **THEN** `ScraplingCrawler` sử dụng `StealthyFetcher`/`StealthySession` để fetch

#### Scenario: Mode fetcher
- **WHEN** `scrapling_mode == "fetcher"`
- **THEN** `ScraplingCrawler` sử dụng `Fetcher`/`FetcherSession` (HTTP thuần, TLS fingerprint)

#### Scenario: Mode dynamic
- **WHEN** `scrapling_mode == "dynamic"`
- **THEN** `ScraplingCrawler` sử dụng `DynamicFetcher`/`DynamicSession` (full Playwright)

### Requirement: Scrapling-specific config fields
`CrawlConfig` SHALL có các field bổ sung cho engine scrapling:
- `solve_cloudflare: bool = False` — bật bypass Cloudflare Turnstile (chỉ stealthy mode)
- `network_idle: bool = True` — chờ network idle (stealthy/dynamic mode)
- `impersonate: str = ""` — giả lập browser TLS fingerprint (fetcher mode)

#### Scenario: solve_cloudflare bật với stealthy mode
- **WHEN** `engine == "scrapling"` và `scrapling_mode == "stealthy"` và `solve_cloudflare == True`
- **THEN** `ScraplingCrawler` truyền `solve_cloudflare=True` cho `StealthyFetcher.fetch()`

#### Scenario: Các fields chỉ áp dụng cho scrapling
- **WHEN** `engine != "scrapling"`
- **THEN** các field `scrapling_mode`, `solve_cloudflare`, `network_idle`, `impersonate` bị bỏ qua, không ảnh hưởng hoạt động

### Requirement: ScraplingCrawler fetch_toc
`ScraplingCrawler.fetch_toc()` SHALL fetch trang TOC URL, parse HTML bằng Scrapling Adaptor, extract metadata (title, author, description, cover_url) và danh sách chapter links. SHALL trả về `TocResult` với cùng cấu trúc như `HttpCrawler.fetch_toc()`.

#### Scenario: Fetch TOC thành công
- **WHEN** gọi `ScraplingCrawler.fetch_toc()` với trang TOC hợp lệ
- **THEN** trả về `TocResult` với danh sách `chapters`, `title`, `author`, `description`, `cover_url`, `metadata_missing`

#### Scenario: TOC với toc_selector
- **WHEN** `CrawlConfig.toc_selector` không rỗng
- **THEN** chỉ tìm chapter links trong phạm vi element khớp `toc_selector`

#### Scenario: TOC với chapter_link_pattern
- **WHEN** `CrawlConfig.chapter_link_pattern` được đặt
- **THEN** chỉ giữ links có URL khớp regex pattern

### Requirement: ScraplingCrawler fetch_chapter
`ScraplingCrawler.fetch_chapter(ch)` SHALL fetch nội dung 1 chương, extract text từ vùng `content_selector`, clean text qua `strip_patterns`, và hỗ trợ pagination qua `fetch_chapter_paginated()`.

#### Scenario: Fetch chương đơn trang
- **WHEN** không có `next_page_selector` và `next_page_url_pattern`
- **THEN** fetch URL chương, extract text từ `content_selector`, trả về text đã clean

#### Scenario: Fetch chương nhiều trang (pagination)
- **WHEN** có `next_page_selector` hoặc `next_page_url_pattern`
- **THEN** delegate cho `fetch_chapter_paginated()` để ghép nội dung các trang

#### Scenario: AI fallback khi content rỗng
- **WHEN** extract text trả về rỗng và `ai_fallback == True` và `_cli_fallback is not None`
- **THEN** gọi AI CLI để trích xuất nội dung từ raw HTML

### Requirement: ScraplingCrawler sleep và close
`ScraplingCrawler` SHALL implement `sleep()` (chờ `delay_seconds`) và `close()` (đóng session/browser nếu có).

#### Scenario: Sleep giữa các chương
- **WHEN** gọi `sleep()` với `delay_seconds > 0`
- **THEN** chờ `delay_seconds` giây

#### Scenario: Close đóng tài nguyên
- **WHEN** gọi `close()`
- **THEN** đóng Scrapling session/browser, giải phóng tài nguyên

### Requirement: Lazy import Scrapling
Scrapling SHALL được import lazily — chỉ khi `engine == "scrapling"`. Nếu Scrapling chưa cài, SHALL raise `ImportError` với message hướng dẫn cài đặt.

#### Scenario: Scrapling chưa cài
- **WHEN** `engine == "scrapling"` nhưng package `scrapling` chưa cài
- **THEN** raise `ImportError` với message: "Chưa cài scrapling. Chạy: pip install scrapling[fetchers] && scrapling install"

#### Scenario: Engine khác không cần scrapling
- **WHEN** `engine == "http"` hoặc `engine == "crawl4ai"`
- **THEN** không import scrapling, không yêu cầu cài đặt

### Requirement: SourcePreset hỗ trợ scrapling fields
`SourcePreset` SHALL bao gồm các field: `scrapling_mode`, `solve_cloudflare`, `network_idle`, `impersonate` để preset có thể cấu hình đầy đủ cho engine scrapling.

#### Scenario: Preset với engine scrapling
- **WHEN** tạo `SourcePreset` với `engine="scrapling"` và `scrapling_mode="stealthy"` và `solve_cloudflare=True`
- **THEN** `crawl_overrides()` trả về dict chứa `engine`, `scrapling_mode`, `solve_cloudflare` và tất cả field khác

### Requirement: Web UI hỗ trợ engine scrapling
Form tạo/sửa source preset trong Web UI SHALL hiển thị `scrapling` trong dropdown engine và hiển thị các field scrapling-specific khi engine scrapling được chọn.

#### Scenario: Chọn engine scrapling trong form
- **WHEN** user chọn engine `scrapling` trong form source preset
- **THEN** hiển thị fields: `scrapling_mode`, `solve_cloudflare`, `network_idle`, `impersonate`

#### Scenario: Lưu preset scrapling
- **WHEN** user submit form với engine scrapling và các field scrapling-specific
- **THEN** preset được lưu với tất cả giá trị scrapling-specific vào `novel2epub.yaml`

### Requirement: Optional dependency
Scrapling SHALL là optional dependency, cài qua `pip install "novel2epub[scrapling]"` hoặc `pip install "novel2epub[all]"`.

#### Scenario: Cài đặt optional dependency
- **WHEN** chạy `pip install "novel2epub[scrapling]"`
- **THEN** package `scrapling[fetchers]` được cài cùng
