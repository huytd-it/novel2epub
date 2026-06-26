## 1. Dọn config.py

- [ ] 1.1 Xoá field cũ khỏi CrawlConfig: `toc_selector`, `chapter_title_selector`, `title_selector`, `author_selector`, `desc_selector`, `cover_selector`, `encoding`, `user_agent`, `js_code`, `magic`, `stealth`
- [ ] 1.2 Giữ `headless` (Scrapling stealthy/dynamic cần), `ai_fallback`, `ai_fallback_max_html`
- [ ] 1.3 Thêm dataclass `ScraplingConfig` với fields: `mode` (default `"fetcher"`), `solve_cloudflare`, `network_idle`, `impersonate`
- [ ] 1.4 Thay `scrapling_mode`/`solve_cloudflare`/`network_idle`/`impersonate` trong CrawlConfig bằng `scrapling: ScraplingConfig`
- [ ] 1.5 Đổi `engine` default từ `"http"` thành `"scrapling"`
- [ ] 1.6 Cập nhật `default_concurrency_cap()` — engine luôn là scrapling, chỉ phân biệt theo mode
- [ ] 1.7 Xoá warning block `crawl.engine == "crawl4ai"` trong `load_config`
- [ ] 1.8 Cập nhật docstring/comments trong CrawlConfig

## 2. Dọn crawler.py

- [ ] 2.1 Xoá class `HttpCrawler` và toàn bộ code liên quan (~220 dòng)
- [ ] 2.2 Xoá class `Crawl4AICrawler` và helper `_log_crawl4ai_failure`, `_crawl4ai_success` (~200 dòng)
- [ ] 2.3 Cập nhật `ScraplingCrawler.__init__` đọc config từ `cfg.scrapling.mode` thay vì `cfg.scrapling_mode`
- [ ] 2.4 Cập nhật `ScraplingCrawler._fetch_page` dùng `cfg.scrapling.*` (solve_cloudflare, network_idle, impersonate)
- [ ] 2.5 Cập nhật `make_crawler()` — chỉ chấp nhận `engine == "scrapling"`, xoá nhánh http/crawl4ai, báo lỗi rõ cho engine cũ
- [ ] 2.6 Xoá docstring đầu file liệt kê 3 engine
- [ ] 2.7 Xoá import `requests` nếu không còn dùng chỗ khác

## 3. Dọn pipeline.py

- [ ] 3.1 Xoá `_emit_crawl_config` in dòng `headless/magic/stealth` (crawl4ai-specific)
- [ ] 3.2 Xoá / cập nhật comment về `Crawl4AICrawler` trong `_crawl_chapters_parallel`
- [ ] 3.3 Kiểm tra không còn import nào trỏ tới HttpCrawler/Crawl4AICrawler

## 4. Dọn sources.py và web UI

- [ ] 4.1 Xoá module `novel2epub/sources.py`
- [ ] 4.2 Xoá route `app/routes/sources.py` — chuyển hướng `/sources` về `/`
- [ ] 4.3 Xoá template `app/templates/sources.html`
- [ ] 4.4 Cập nhật `app/main.py` — bỏ import sources router
- [ ] 4.5 Cập nhật `app/templates/base.html` — bỏ nav link "Nguồn"
- [ ] 4.6 Cập nhật `app/deps.py` — xoá `load_presets`, xoá `SOURCES_PATH`
- [ ] 4.7 Cập nhật `app/routes/library.py` — xoá `detect_preset`/`preset_matches_url`

## 5. Dọn preset_builder.py và route

- [ ] 5.1 Xoá module `novel2epub/preset_builder.py`
- [ ] 5.2 Xoá route `app/routes/preset_builder.py`
- [ ] 5.3 Xoá template `app/templates/preset_builder.html`
- [ ] 5.4 Cập nhật `app/main.py` — bỏ import preset_builder router
- [ ] 5.5 Cập nhật `novel2epub/cli.py` — xoá lệnh `preset-build`/`preset-preview`

## 6. Dọn requirements.txt và dependencies

- [ ] 6.1 Gỡ `requests` khỏi `requirements.txt`
- [ ] 6.2 Gỡ `beautifulsoup4` khỏi `requirements.txt`
- [ ] 6.3 Gỡ `crawl4ai` khỏi `requirements.txt`
- [ ] 6.4 Đảm bảo `scrapling[fetchers]` có trong `requirements.txt`

## 7. Cập nhật novel2epub.example.yaml

- [ ] 7.1 Xoá toàn bộ preset dùng `engine: http` và `engine: crawl4ai`
- [ ] 7.2 Giữ lại preset dùng `engine: scrapling`, cập nhật format `scrapling:` block
- [ ] 7.3 Thêm preset mẫu cho 3 scrapling mode (fetcher/stealthy/dynamic)
- [ ] 7.4 Cập nhật defaults: `engine: scrapling`, bỏ field cũ
- [ ] 7.5 Xoá block `sources:` nếu không còn preset scrapling nào

## 8. Cập nhật test

- [ ] 8.1 Xoá/cập nhật `tests/test_crawler_meta.py` — xoá test HttpCrawler, test make_crawler mới
- [ ] 8.2 Xoá/cập nhật `tests/test_refactor_toc.py` — xoá test HttpCrawler
- [ ] 8.3 Xoá/cập nhật `tests/test_chapter_pagination.py` — xoá test HttpCrawler pagination
- [ ] 8.4 Xoá/cập nhật `tests/test_crawl_retry.py` — xoá test HttpCrawler rate limit
- [ ] 8.5 Xoá `tests/test_sources_ui.py`, `tests/test_sources_management.py`
- [ ] 8.6 Xoá `tests/test_preset_builder.py`
- [ ] 8.7 Cập nhật `tests/test_scrapling.py` — bỏ import HttpCrawler
- [ ] 8.8 Cập nhật `tests/test_add_ebook_flow.py` — bỏ import từ sources
- [ ] 8.9 Cập nhật `tests/test_config_writer.py` — bỏ import từ sources
- [ ] 8.10 Cập nhật `tests/test_config.py` — sửa test dùng engine cũ
- [ ] 8.11 Cập nhật `tests/test_crawl_throttle.py` — sửa test default_concurrency_cap
- [ ] 8.12 Thêm test cho ScraplingConfig defaults và mode parsing
- [ ] 8.13 Thêm test cho `make_crawler` từ chối engine cũ

## 9. Viết lại README.md

- [ ] 9.1 Viết lại README đơn giản, tập trung vào Scrapling engine duy nhất
- [ ] 9.2 Cập nhật hướng dẫn cài đặt: chỉ cần `scrapling[fetchers]`
- [ ] 9.3 Cập nhật bảng cấu hình crawl — chỉ còn scrapling 3 mode
- [ ] 9.4 Xoá phần so sánh engine, xoá mẹo "khi nào dùng crawl4ai"
- [ ] 9.5 Bỏ section "Quản lý nguồn (site preset)" và "Crawl console" liên quan nhiều engine
- [ ] 9.6 Thêm migration guide cho người dùng engine cũ
