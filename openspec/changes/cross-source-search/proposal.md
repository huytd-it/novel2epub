## Why

Hiện tại khi thêm ebook mới, người dùng phải tự tìm và nhập `toc_url` thủ công. Khi có nhiều source presets (sto9, aixdzs, qidian, 69shuba, shuqi...), việc kiểm tra từng nguồn rất tốn thời gian. Cần tích hợp tìm kiếm ngay vào giao diện "Thêm ebook mới" để người dùng có thể chọn giữa "Tìm theo tên" (search across sources) hoặc "Nhập URL" (như hiện tại), cả hai đều dẫn đến cùng một flow: preview metadata → tạo ebook.

## What Changes

- Thêm module `search.py` chứa logic tìm kiếm tiểu thuyết trên nhiều source
- Mỗi source preset sẽ có thêm trường `search_url_pattern` (URL template cho trang tìm kiếm) và `search_results_selector` (CSS selector cho kết quả)
- Triển khai tìm kiếm song song trên nhiều source với ThreadPoolExecutor
- Thêm CLI command `python -m novel2epub search "<tên tiểu thuyết>"`
- **Tích hợp search vào giao diện "Thêm ebook mới" hiện có (index.html) với 2 tab: "Tìm theo tên" và "Nhập URL"**
- **Tab "Tìm theo tên": nhập query → hiển thị kết quả search → chọn kết quả → preview metadata → tạo ebook**
- **Tab "Nhập URL": nhập toc_url → preview metadata → tạo ebook (giữ nguyên flow hiện tại)**
- **Cả hai tab đều dùng chung endpoint `POST /library/ebooks` để tạo ebook**
- Thêm backend `libretranslate` vào hệ thống translation (self-hosted API)
- Tùy chọn dịch metadata (title, author, description) sang tiếng Việt khi crawl từ search results

## Capabilities

### New Capabilities
- `cross-source-search`: Module tìm kiếm tiểu thuyết trên tất cả các web source đã cấu hình, tích hợp vào giao diện "Thêm ebook mới" với 2 chế độ: search by title và nhập URL. Hỗ trợ cả CLI và Web UI.

### Modified Capabilities
- (Không có capability hiện có nào thay đổi yêu cầu)

## Impact

- **Code mới**: `novel2epub/search.py` (core search logic)
- **Code sửa đổi**: `novel2epub/sources.py` (thêm search fields vào SourcePreset), `novel2epub/cli.py` (thêm search command), `app/main.py` (register search router nếu tách), `novel2epub.example.yaml` (thêm search config mẫu), `novel2epub/translator.py` (thêm LibreTranslate backend), `novel2epub/config.py` (thêm LibreTranslate config), `app/routes/library.py` (thêm search API endpoint), `app/routes/templates/index.html` (thêm tab search vào form thêm ebook)
- **Dependencies**: Không thêm dependency mới (dùng requests có sẵn cho LibreTranslate HTTP API)
- **API mới**: `POST /library/ebooks/search` (search across sources, trả JSON results), `POST /library/ebooks/preview` (giữ nguyên, nhận toc_url)
