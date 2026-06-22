## Why

Mỗi khi muốn crawl một nguồn truyện mới, người dùng phải tự inspect HTML, viết CSS selector cho `content_selector` / `toc_selector`, và đặc biệt là phải nghĩ ra regex `chapter_link_pattern` cho đúng — sai một chút là regex match luôn các link header / footer / quảng cáo, ra cả nghìn URL rác thay vì danh sách chương. Danh sách nguồn ưu tiên trong `docs/source.md` có hàng chục site cần onboard (sto9, aixdzs, qidian, 69shuba, shuqi, biquge…), thao tác thủ công này lặp đi lặp lại và tốn thời gian. Cùng lúc, dependency `firecrawl-py` mang tính phí (cần API key trả tiền) — đã đến lúc bỏ hẳn ra khỏi codebase, dùng đúng hai engine miễn phí là `http` và `crawl4ai` để đơn giản hoá.

## What Changes

- Thêm module `novel2epub/preset_builder.py` cung cấp khả năng tạo `SourcePreset` tự động từ URL mục lục:
  - Hàm `build_preset(toc_url, novel_title="赤心巡天", interactive=True)` tự thử lần lượt engine `http` trước (nhanh, miễn phí), fallback `crawl4ai` nếu HTML tĩnh không đủ thông tin (JS render, lazy load…).
  - Gọi AI CLI (đã có `cli_runner` + preset `go`) để phân tích HTML thô + URL pattern, gợi ý `content_selector`, `toc_selector`, `chapter_link_pattern`, `title_selector`, `author_selector`, `desc_selector`, `cover_selector`, `chapter_title_selector`, các field crawl4ai (`headless`, `magic`, `js_code`), `encoding`, `delay_seconds`.
  - **Bắt buộc preview TOC trước khi lưu**: chạy `HttpCrawler` / `Crawl4AICrawler` với preset vừa sinh, lấy danh sách chapter, hiển thị cho người dùng xem. Nếu regex match quá ít (so với số chương mong đợi) hoặc match quá nhiều (>2000 link, gần như chắc chắn quét nhầm), AI tự refine lại pattern (tối đa 3 lần refine) hoặc yêu cầu người dùng cung cấp thêm thông tin.
  - Tên preset mặc định lấy từ hostname (vd `sto9`, `aixdzs`); người dùng có thể override.
  - Lưu vào `sources.yaml` bằng `save_presets()` đã có.
- Thêm CLI subcommand `novel2epub preset-build <toc_url>` chạy flow trên, tương tác qua stdin/stdout, kết thúc bằng việc ghi preset.
- Thêm CLI subcommand `novel2epub toc-preview <toc_url>` để chạy preview không lưu, dùng để verify regex sau khi đã có preset. Tái sử dụng `HttpCrawler` / `Crawl4AICrawler` với `chapter_link_pattern` cho trước.
- Thêm Web UI route `GET /preset-builder` (form nhập URL → gọi API nền → render kết quả preview) và `POST /preset-builder/preview` (trả JSON về danh sách chapter detect được + AI suggestions). Bổ sung link "Tạo preset từ URL" trên trang `/library` để người dùng tạo preset trước khi thêm ebook.
- Thêm hàm `detect_preset_or_suggest(toc_url, presets)` (mở rộng từ `detect_preset` hiện có): nếu đã có preset khớp → trả tên preset; nếu không → trả preset name tốt nhất ứng viên kèm cờ `suggested=True` và link mở `/preset-builder` với URL đó. Tích hợp vào `library._fetch_meta` để khi người dùng paste URL mà chưa có preset, hệ thống tự gợi ý tạo preset.
- **BREAKING**: Xoá hoàn toàn engine `firecrawl`:
  - Xoá class `FirecrawlCrawler` và mọi nhánh `engine == "firecrawl"` trong `novel2epub/crawler.py`, `make_crawler()` chỉ còn hỗ trợ `http` và `crawl4ai`.
  - Xoá field `api_key`, `api_url` khỏi `CrawlConfig` (chỉ phục vụ firecrawl).
  - Bỏ tuỳ chọn `firecrawl` khỏi UI select ở `app/templates/library.html`, `app/templates/sources.html`, `app/templates/settings.html`.
  - Cập nhật `config.example.yaml`, `config.yaml`, comment trong source code, `README.md`, `AGENTS.md` — bỏ mọi reference đến `firecrawl` / `FIRECRAWL_API_KEY` / `firecrawl-py`.
  - Gỡ `firecrawl` khỏi `AGENTS.md` bảng "Crawl engines available".

## Capabilities

### New Capabilities

- `preset-builder`: AI-driven generation + validation of a `SourcePreset` for a given TOC URL. Covers: try `http` first then `crawl4ai`, prompt AI CLI for selector/regex suggestions, preview the resulting chapter list (count + sample), refine when the count is implausibly low/high, and persist the preset to `sources.yaml`. Also exposes a non-mutating `toc-preview` flow that re-uses a saved preset to verify its regex against a fresh URL.
- `firecrawl-removal`: Elimination of the `firecrawl` engine and the `firecrawl-py` dependency from crawl config, CLI, Web UI, docs, and the engine enum. Concretely: drop `FirecrawlCrawler` and any branch gated on `engine == "firecrawl"`; drop `api_key` / `api_url` from `CrawlConfig`; remove `firecrawl` from UI engine `<select>` options; scrub the README, AGENTS.md, config example, and in-code comments. This is a **BREAKING** change for any config that still sets `engine: firecrawl` or relies on `FIRECRAWL_API_KEY`.

### Modified Capabilities

<!-- None — there are no existing specs under openspec/specs/, and no requirement-level behavior of currently specified capabilities is changing. -->

## Impact

- **Code added**: `novel2epub/preset_builder.py` (new module with `build_preset`, `refine_pattern_with_ai`, `preview_toc`, `select_engine_heuristic`); new CLI subcommand + handler in `novel2epub/cli.py`; new routes in `app/routes/preset_builder.py`; new template `app/templates/preset_builder.html`; small new section in `app/templates/library.html` to link to the builder.
- **Code modified**: `novel2epub/crawler.py` (drop `FirecrawlCrawler` + branches; keep only `http` and `crawl4ai` in `make_crawler`); `novel2epub/config.py` (drop `api_key`, `api_url` from `CrawlConfig`, simplify env-var handling); `novel2epub/sources.py` (no schema change, but new `remove_preset(name)` helper for completeness); `app/templates/sources.html`, `app/templates/library.html`, `app/templates/settings.html` (remove `firecrawl` from `<select>` options and engine hints); `app/routes/library.py` (extend `_fetch_meta` to return `suggested_preset` and `suggest_url` when no preset matches).
- **Code removed**: `FirecrawlCrawler` class; `firecrawl` branches in crawl code; `FIRECRAWL_API_KEY` env var handling.
- **Docs**: `README.md`, `AGENTS.md` — remove `firecrawl-py` install instructions and `firecrawl` from "engines available" table; update `config.example.yaml` comment block.
- **Tests**: New `tests/test_preset_builder.py` covering (a) engine heuristic picks `http` for a known static site and `crawl4ai` for a known JS site (fixture HTML), (b) pattern-refinement loop downgrades a too-broad regex to a chapter-scoped one, (c) `toc_preview` round-trips through `HttpCrawler.fetch_toc` and respects an explicit `chapter_link_pattern`, (d) CLI `preset-build` and `toc-preview` exit codes / output shape. Extend `tests/test_crawler_meta.py` and `tests/test_sources_ui.py` to drop `firecrawl` from the asserted option set.
- **Dependencies**: No new runtime deps. `firecrawl-py` becomes uninstallable for this project (no `import` left); if it stays in `requirements.txt` as a stray entry, remove it.
- **Migration**: For any existing user with `engine: firecrawl` in `configs/*.yaml` or `source:` row of `sources.yaml`, the new `make_crawler` will raise `ValueError` on first run. The change must surface a clear migration note in the README: "firecrawl engine has been removed; switch `engine: firecrawl` to `engine: crawl4ai` (or `engine: http` if the site is static) and remove the `api_key` line."
