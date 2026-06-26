## ADDED Requirements

### Requirement: Scrapling là engine crawl duy nhất

Hệ thống CHỈ hỗ trợ Scrapling làm engine crawl. Config `crawl.engine` mặc định là `scrapling` và không chấp nhận giá trị khác.

#### Scenario: Engine mặc định là scrapling
- **WHEN** người dùng không khai báo `crawl.engine` trong config
- **THEN** hệ thống dùng ScraplingCrawler với mode mặc định `fetcher`

#### Scenario: Engine cũ bị từ chối
- **WHEN** người dùng khai báo `crawl.engine: http` hoặc `crawl.engine: crawl4ai`
- **THEN** `make_crawler` raise ValueError với thông báo migration rõ ràng

### Requirement: Cấu hình Scrapling qua block riêng

Config Scrapling được gom trong `crawl.scrapling:` block thay vì field rải rác.

#### Scenario: Cấu hình scrapling block đầy đủ
- **WHEN** config có `crawl.scrapling: { mode: stealthy, solve_cloudflare: true }`
- **THEN** ScraplingCrawler dùng mode `stealthy` và bật `solve_cloudflare`

#### Scenario: Mặc định khi không khai báo scrapling block
- **WHEN** config không có `crawl.scrapling:` block
- **THEN** ScraplingCrawler dùng mode `fetcher` (mặc định), `solve_cloudflare: false`, `network_idle: false`, `impersonate: ""`

### Requirement: Hỗ trợ 3 Scrapling mode

ScraplingCrawler hỗ trợ 3 mode: `fetcher`, `stealthy`, `dynamic`.

#### Scenario: Mode fetcher — HTTP thuần
- **WHEN** `crawl.scrapling.mode` là `fetcher`
- **THEN** ScraplingCrawler dùng `Fetcher` class, có thể set `impersonate` để giả TLS fingerprint, không cần headless

#### Scenario: Mode stealthy — bypass Cloudflare
- **WHEN** `crawl.scrapling.mode` là `stealthy`
- **THEN** ScraplingCrawler dùng `StealthyFetcher` class, headless mặc định, có thể bật `solve_cloudflare` và `network_idle`

#### Scenario: Mode dynamic — full Playwright
- **WHEN** `crawl.scrapling.mode` là `dynamic`
- **THEN** ScraplingCrawler dùng `DynamicFetcher` class, headless mặc định, có `network_idle`

### Requirement: Loại bỏ field cũ khỏi CrawlConfig

CrawlConfig không còn chứa field chỉ dùng cho engine `http` hoặc `crawl4ai`.

#### Scenario: Http-only fields bị loại bỏ
- **WHEN** config chứa `crawl.toc_selector`, `crawl.encoding`, `crawl.user_agent`, `crawl.title_selector`, `crawl.author_selector`, `crawl.desc_selector`, `crawl.cover_selector`, `crawl.chapter_title_selector`
- **THEN** các field này không còn được CrawlConfig định nghĩa; `load_config` bỏ qua hoặc báo warning

#### Scenario: Crawl4ai-only fields bị loại bỏ
- **WHEN** config chứa `crawl.js_code`, `crawl.magic`, `crawl.stealth`
- **THEN** các field này không còn được CrawlConfig định nghĩa; `load_config` bỏ qua hoặc báo warning

#### Scenario: Content selector vẫn được giữ
- **WHEN** config chứa `crawl.content_selector`
- **THEN** CrawlConfig vẫn nhận field này, ScraplingCrawler dùng để trích nội dung chương

### Requirement: Dependency chỉ còn scrapling

`requirements.txt` chỉ giữ Scrapling làm crawl dependency bắt buộc. `requests`, `beautifulsoup4`, `crawl4ai` được gỡ bỏ.

#### Scenario: Install chỉ scrapling
- **WHEN** người dùng chạy `pip install scrapling[fetchers] && scrapling install`
- **THEN** hệ thống crawl hoạt động đầy đủ, không cần cài thêm package crawl nào khác
