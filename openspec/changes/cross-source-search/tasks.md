## 1. Mở rộng SourcePreset

- [x] 1.1 Thêm các field search vào `SourcePreset` trong `novel2epub/sources.py`: `search_url_pattern`, `search_result_selector`, `search_title_selector`, `search_author_selector`, `search_link_selector`, `search_cover_selector`, `max_search_results` (default 5)
- [x] 1.2 Cập nhật `_coerce()` trong `sources.py` để xử lý type coercion cho các field mới (int cho `max_search_results`)
- [x] 1.3 Cập nhật `novel2epub.example.yaml` với search config mẫu cho các source đã biết (sto9, aixdzs, qidian, 69shuba)

## 2. Core Search Module

- [x] 2.1 Tạo `novel2epub/search.py` với `SearchResult` dataclass (title, author, url, source_name, cover_url, chapter_count, description)
- [x] 2.2 Triển khai `SourceSearcher` class: nhận source preset + query, fetch search page, parse kết quả bằng CSS selectors
- [x] 2.3 Triển khai `search_all()` function: nhận list presets + query, dùng `ThreadPoolExecutor` tìm kiếm song song, trả về list `SearchResult`
- [x] 2.4 Xử lý lỗi per-source: timeout, anti-bot, parse error → skip source đó, ghi log
- [x] 2.5 Tùy chọn fetch metadata từ trang kết quả (tác giả, số chương) bằng cách re-use `_extract_meta()` pattern

## 3. LibreTranslate Backend

- [x] 3.1 Thêm `LibreTranslateConfig` dataclass trong `novel2epub/config.py`: `base_url`, `api_key`, `source_language`, `target_language`
- [x] 3.2 Thêm field `libretranslate: LibreTranslateConfig` vào `TranslateConfig`
- [x] 3.3 Triển khai `LibreTranslateTranslator` class trong `novel2epub/translator.py`: gọi `POST /translate` API, xử lý response
- [x] 3.4 Đăng ký `libretranslate` trong `make_translator()` factory function
- [x] 3.5 Cập nhật `novel2epub.example.yaml` với LibreTranslate config mẫu

## 4. Search API Endpoint

- [x] 4.1 Thêm `POST /library/ebooks/search` trong `app/routes/library.py`: nhận `query` (form), optional `sources` (comma-separated), trả JSON array `SearchResult`
- [x] 4.2 Tái sử dụng `search_all()` từ `novel2epub/search.py` trong endpoint handler
- [x] 4.3 Xử lý lỗi: không có search config → trả `{"error": "..."}`, tất cả search lỗi → trả error

## 5. Tích hợp vào Giao diện "Thêm ebook mới"

- [x] 5.1 Cập nhật `app/routes/templates/index.html`: thêm 2 tab "Tìm theo tên" và "Nhập URL" vào form thêm ebook
- [x] 5.2 Tab "Tìm theo tên": ô nhập query + nút "Tìm kiếm" + vùng hiển thị kết quả (title, author, source, cover, chapters, nút "Chọn")
- [x] 5.3 JS handler: khi click "Chọn" trên kết quả → tự động điền `toc_url` và gọi preview API để hiển thị metadata
- [x] 5.4 Checkbox "Dịch metadata" trong tab search: khi tick, gọi preview với translate flag
- [x] 5.5 Tab "Nhập URL": giữ nguyên form hiện tại (input toc_url + nút Preview)
- [x] 5.6 Cả hai tab đều dùng chung nút "Tạo ebook" → `POST /library/ebooks`

## 6. CLI Command

- [x] 6.1 Thêm subcommand `search` vào `novel2epub/cli.py` với args: `query`, `--sources` (optional), `--limit` (default 5), `--format` (text/json), `--select` (chọn kết quả), `--translate` (dịch metadata)
- [x] 6.2 Triển khai output formatter: text format `[source] title — author — url`, json format xuất JSON array
- [x] 6.3 Triển khai flow `--select`: crawl metadata → optionally translate → tạo ebook config
- [x] 6.4 Xử lý trường hợp không có source nào có search config → báo lỗi

## 7. Testing

- [x] 7.1 Viết unit test cho `SourceSearcher` với mock HTML response
- [x] 7.2 Viết unit test cho `search_all()` với mock presets
- [x] 7.3 Viết unit test cho `LibreTranslateTranslator` với mock HTTP response
- [x] 7.4 Viết unit test cho `POST /library/ebooks/search` endpoint
- [x] 7.5 Viết integration test cho CLI `search` command (bao gồm `--select` và `--translate`)
