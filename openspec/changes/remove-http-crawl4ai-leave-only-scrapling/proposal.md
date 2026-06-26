## Why

Crawl engine hiện tại có 3 backend (`http`, `crawl4ai`, `scrapling`) nhưng trên thực tế:
- `http` (requests+BS4) không vượt được chặn cơ bản, dễ fail, selector cũng hoạt động được qua Scrapling `fetcher` mode.
- `crawl4ai` phụ thuộc Playwright nặng, hay lỗi build `lxml` trên Windows, không cần thiết vì Scrapling có `dynamic` mode tương đương.

Scrapling với 3 mode (`fetcher`/`stealthy`/`dynamic`) đã đáp ứng đủ mọi nhu cầu: HTTP nhẹ, stealth bypass Cloudflare, Playwright full JS. Việc giữ 3 engine dư thừa gây phức tạp config, code, test, và bảo trì.

## What Changes

- **BREAKING**: Xoá toàn bộ class `HttpCrawler` và `Crawl4AICrawler` khỏi `crawler.py`.
- **BREAKING**: `crawl.engine` chỉ chấp nhận `scrapling` (mặc định mới), không còn `http` / `crawl4ai`.
- **BREAKING**: Gỡ bỏ dependency `requests`, `beautifulsoup4`, `crawl4ai` khỏi `requirements.txt` và code imports.
- Xoá các setting chỉ dùng cho `http`/`crawl4ai` (`toc_selector`, `js_code`, `magic`, `stealth`, `chapter_title_selector`, `encoding`, `user_agent`, các `*_selector` metadata).
- Tinh chỉnh ScraplingCrawler: nâng `fetcher` mode thành default (thay `stealthy`), tăng `concurrency_cap` mặc định, bổ sung cấu hình `scrapling` block riêng cho gọn.
- Cập nhật `novel2epub.example.yaml`: tất cả preset dùng `engine: scrapling`, mỗi preset có `scrapling_mode` phù hợp.
- Viết lại README.md đơn giản hơn, chỉ tập trung vào Scrapling.
- **BREAKING**: Bỏ `sources` block (không còn cần site preset CRUD vì Scrapling xử lý mọi site bằng 1 engine) — tinh gọn config.

## Capabilities

### New Capabilities
- `scrapling-as-default`: Scrapling là engine duy nhất với 3 mode, cấu hình mới gọn nhẹ hơn.

### Modified Capabilities
*(Không có — vì thay đổi là loại bỏ engine cũ, không sửa requirement của capability hiện có.)*

## Impact

- **novel2epub/crawler.py**: Xoá ~500 dòng code (HttpCrawler, Crawl4AICrawler, các helper riêng). ScraplingCrawler còn lại, thêm cấu hình mới.
- **novel2epub/config.py**: Xoá field `CrawlConfig` chỉ dùng cho http/crawl4ai. Thêm `ScraplingConfig` block riêng.
- **novel2epub/pipeline.py**: Bỏ code xử lý song song từng engine riêng (đã dùng chung crawler interface).
- **novel2epub/sources.py**: Có thể bỏ hoặc simplify — không còn cần CRUD source preset vì chỉ còn 1 engine.
- **novel2epub.example.yaml**: Giảm từ ~300 dòng xuống ~100 dòng, chỉ còn preset scrapling.
- **requirements.txt**: Gỡ `requests`, `beautifulsoup4`, `crawl4ai`. Scrapling là dependency bắt buộc.
- **tests/**: Xoá/cập nhật test cho `HttpCrawler`, `Crawl4AICrawler`, `make_crawler`.
- **Web UI (app/)**: Ẩn field `engine` selector khỏi UI (hoặc để fixed là scrapling).
- **README.md**: Viết lại đơn giản, chỉ tập trung cài đặt + dùng Scrapling.
