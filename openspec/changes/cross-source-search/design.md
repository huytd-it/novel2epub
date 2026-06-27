## Context

novel2epub hiện tại hỗ trợ crawl từ nhiều nguồn web (sto9, aixdzs, qidian, 69shuba, shuqi...) thông qua hệ thống `SourcePreset`. Mỗi preset chứa CSS selectors, engine config, và domain matching. Người dùng phải tự tìm `toc_url` thủ công rồi cấu hình ebook.

Flow "Thêm ebook mới" hiện tại (`app/routes/library.py`):
1. `POST /library/ebooks/preview` — nhận `toc_url` → crawl metadata → trả JSON
2. `POST /library/ebooks` — nhận `slug/name/author/toc_url` → tạo ebook config

Giao diện thêm ebook nằm ở `index.html` — form nhập `toc_url` → preview → tạo.

Hệ thống translation hiện tại đã có: `OpenAITranslator` (tương thích LM Studio), `GoogleTranslator`, `HachimiMTTranslator`, `NoopTranslator`.

**Constraints**: Chỉ dùng engine `scrapling`. Mỗi source có cấu trúc HTML khác nhau nên cần selector linh hoạt cho trang tìm kiếm.

## Goals / Non-Goals

**Goals:**
- Tìm kiếm tiểu thuyết theo tên trên tất cả (hoặc subset) các source presets đã cấu hình
- Tìm kiếm song song trên nhiều source để giảm thời gian chờ
- **Tích hợp search vào giao diện "Thêm ebook mới" hiện có với 2 tab: "Tìm theo tên" và "Nhập URL"**
- **Cả hai tab đều dẫn đến cùng một flow: preview metadata → tạo ebook config**
- Tùy chọn dịch metadata sang tiếng Việt khi crawl từ search results
- Thêm LibreTranslate như backend translation mới
- Hỗ trợ cả CLI và Web UI

**Non-Goals:**
- Không xây dựng search engine/index nội bộ (dùng search page của từng website)
- Không lưu cache kết quả tìm kiếm (mỗi lần search là live)
- Không hỗ trợ tìm kiếm nâng cao (chỉ tìm theo tên/tiêu đề)
- Không tự động crawl chapters sau khi tìm (chỉ crawl metadata/TOC)
- Không tách search ra trang riêng — tích hợp vào giao diện add book hiện có

## Decisions

### 1. Search strategy: dùng trang tìm kiếm của mỗi website

**Quyết định**: Mỗi source preset sẽ có thêm `search_url_pattern` (URL template, ví dụ `https://sto9.com/search/?q={query}`) và `search_result_selector` (CSS selector cho link kết quả). Module search sẽ fetch URL này, parse HTML, và trích xuất thông tin.

**Lý do**: Tận dụng search engine có sẵn của mỗi website — không cần build index. Đơn giản, ít maintenance.

**Alternative đã bỏ**: Build local search index bằng whoosh/elasticsearch — quá phức tạp cho use case này.

### 2. Song song hóa bằng ThreadPoolExecutor

**Quyết định**: Dùng `concurrent.futures.ThreadPoolExecutor` để search trên nhiều source cùng lúc. Giới hạn 5 workers mặc định.

**Lý do**: Scrapling fetchers là blocking I/O. ThreadPoolExecutor đơn giản, tích hợp tốt với codebase hiện tại.

### 3. Search result enrichment: fetch thêm metadata từ trang kết quả

**Quyết định**: Sau khi có link kết quả, fetch trang đó để lấy metadata (tác giả, mô tả, số chương) bằng `_extract_meta()` hiện có.

**Lý do**: Trang kết quả tìm kiếm thường chỉ có title + link. Metadata đầy đủ cần fetch trang chi tiết.

### 4. Tích hợp vào giao diện "Thêm ebook mới" — 2 tab

**Quyết định**: Thay vì tạo trang `/search` riêng, tích hợp search vào giao diện thêm ebook hiện có (`index.html`). Form thêm ebook sẽ có 2 tab:

- **Tab "Tìm theo tên"**: Nhập query → gọi `POST /library/ebooks/search` → hiển thị kết quả (title, author, source, cover, chapters) → chọn kết quả → tự động điền `toc_url` vào form → preview metadata → tạo ebook
- **Tab "Nhập URL"**: Giữ nguyên flow hiện tại — nhập `toc_url` → preview → tạo ebook

Cả hai tab đều dùng chung endpoint `POST /library/ebooks` để tạo ebook. Tab search chỉ là cách khác để điền `toc_url`.

**Lý do**: Giữ UI đơn giản — không thêm trang mới. Người dùng có thể chọn cách phù hợp: biết URL thì nhập trực tiếp, không biết thì search.

**Alternative đã bỏ**: Tạo trang `/search` riêng → phân mảnh UX, người dùng phải chuyển qua lại giữa search và add book.

### 5. API search endpoint

**Quyết định**: Thêm `POST /library/ebooks/search` trong `app/routes/library.py`. Nhận `query` (form field), trả JSON array kết quả. Frontend gọi AJAX, hiển thị danh sách, người dùng click chọn → JS tự điền `toc_url` vào form chính.

**Lý do**: Tái sử dụng router library hiện có. Không cần tạo router mới.

### 6. Thêm LibreTranslate backend

**Quyết định**: Thêm `LibreTranslateTranslator` class trong `translator.py`, gọi HTTP API `POST /translate`. Cấu hình qua `translate.libretranslate.*`.

**Lý do**: LibreTranslate là self-hosted, miễn phí, phù hợp cho dịch metadata ngắn.

### 7. Translate metadata là optional

**Quyết định**: Tùy chọn translate metadata được điều khiển bởi checkbox "Dịch metadata" trong form thêm ebook (hiển thị khi dùng tab search). Mặc định: không dịch.

## Risks / Trade-offs

- **[Risk] Mỗi website có cấu trúc search page khác nhau** → Mitigation: Cho phép cấu hình selectors per source. Fallback: skip source không có search config.
- **[Risk] Anti-bot blocking khi search hàng loạt** → Mitigation: Dùng `delay_seconds` đã có. Giới hạn workers.
- **[Risk] Kết quả tìm kiếm không chính xác** → Mitigation: Hiển thị nhiều kết quả, cho người dùng chọn.
- **[Risk] LibreTranslate server không available** → Mitigation: Fallback sang Google Translate hoặc báo lỗi.
- **[Trade-off] Không cache kết quả search** → Mỗi lần search đều fetch live. Đổi lại: đơn giản.

## Migration Plan

1. Thêm search fields vào `SourcePreset` (backward compatible, optional)
2. Tạo `novel2epub/search.py`
3. Thêm `LibreTranslateTranslator` vào `translator.py`
4. Thêm `POST /library/ebooks/search` endpoint trong `library.py`
5. Cập nhật `index.html`: thêm tab "Tìm theo tên" vào form thêm ebook
6. Cập nhật `novel2epub.example.yaml` với search config mẫu

Không có breaking change.

## Open Questions

- Nên hiển thị bao nhiêu kết quả per source? (đề xuất: 5)
- Có nên cho phép người dùng chọn search trên subset sources?
- Rate limiting: dùng `delay_seconds` của preset hay default riêng?
