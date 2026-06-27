## ADDED Requirements

### Requirement: Source preset hỗ trợ search configuration
Source preset SHALL có các field optional để cấu hình tìm kiếm: `search_url_pattern` (URL template với `{query}` placeholder), `search_result_selector` (CSS selector cho container kết quả), `search_title_selector`, `search_author_selector`, `search_link_selector`, `search_cover_selector`.

#### Scenario: Source có search config
- **WHEN** source preset có `search_url_pattern` được cấu hình
- **THÌ** source đó sẽ được đưa vào danh sách search khi người dùng tìm kiếm

#### Scenario: Source không có search config
- **WHEN** source preset không có `search_url_pattern`
- **THÌ** source đó sẽ bị bỏ qua trong quá trình search, không báo lỗi

### Requirement: Tìm kiếm tiểu thuyết trên nhiều source
Hệ thống SHALL cho phép tìm kiếm tiểu thuyết theo tên trên tất cả (hoặc subset) các source presets đã cấu hình search.

#### Scenario: Tìm kiếm trên tất cả sources
- **WHEN** người dùng chạy `python -m novel2epub search "tên tiểu thuyết"`
- **THÌ** hệ thống tìm kiếm trên tất cả sources có search config, trả về kết quả gom từ tất cả sources

#### Scenario: Tìm kiếm trên source cụ thể
- **WHEN** người dùng chạy `python -m novel2epub search "tên tiểu thuyết" --sources sto9,aixdzs`
- **THÌ** hệ thống chỉ tìm kiếm trên các source được chỉ định

#### Scenario: Không có source nào có search config
- **WHEN** tất cả source presets đều không có `search_url_pattern`
- **THÌ** hệ thống thông báo lỗi rõ ràng: "Không có source nào được cấu hình tìm kiếm"

### Requirement: Tìm kiếm song song
Hệ thống SHALL tìm kiếm trên nhiều source cùng lúc bằng ThreadPoolExecutor.

#### Scenario: Tìm kiếm song song 5 source
- **WHEN** có 5 source có search config
- **THÌ** hệ thống gửi request đến cả 5 source đồng thời (giới hạn max_workers), tổng thời gian gần bằng thời gian source chậm nhất

#### Scenario: Một source bị lỗi
- **WHEN** một source trả về lỗi (timeout, anti-bot, HTTP error)
- **THÌ** source đó bị skip, các source khác vẫn tiếp tục, kết quả từ source lỗi hiển thị thông báo lỗi

### Requirement: Kết quả tìm kiếm đầy đủ thông tin
Kết quả tìm kiếm SHALL bao gồm: tiêu đề, tác giả (nếu có), URL trang mục lục, source name, cover image URL, số chương (nếu có thể trích xuất).

#### Scenario: Kết quả có đầy đủ metadata
- **WHEN** source trả về kết quả với link trang mục lục
- **THÌ** hệ thống fetch trang đó để lấy metadata (title, author, description, cover, chapter count)

#### Scenario: Kết quả thiếu metadata
- **WHEN** không thể trích xuất metadata từ trang kết quả
- **THÌ** hiển thị "N/A" cho field thiếu, không báo lỗi

### Requirement: Tích hợp search vào giao diện "Thêm ebook mới"
Giao diện thêm ebook mới SHALL có 2 tab: "Tìm theo tên" và "Nhập URL". Cả hai tab đều dẫn đến cùng một flow tạo ebook.

#### Scenario: Tab "Tìm theo tên"
- **WHEN** người dùng chọn tab "Tìm theo tên" trong form thêm ebook
- **THÌ** hiển thị ô nhập query, nút "Tìm kiếm", và vùng hiển thị kết quả

#### Scenario: Search và chọn kết quả
- **WHEN** người dùng nhập query và click "Tìm kiếm"
- **THÌ** hiển thị danh sách kết quả: title, author, source, cover, chapters. Mỗi kết quả có nút "Chọn"

#### Scenario: Chọn kết quả → điền form
- **WHEN** người dùng click "Chọn" trên một kết quả search
- **THÌ** `toc_url` tự động điền vào form, metadata (name, author, slug, cover) tự động preview, hiển thị nút "Tạo ebook"

#### Scenario: Tab "Nhập URL"
- **WHEN** người dùng chọn tab "Nhập URL"
- **THÌ** hiển thị form nhập `toc_url` như hiện tại, nút "Preview" → metadata → "Tạo ebook"

#### Scenario: Cả hai tab tạo ebook giống nhau
- **WHEN** người dùng hoàn thành flow từ tab nào (search hoặc URL)
- **THÌ** đều gọi `POST /library/ebooks` với cùng params (slug, name, author, toc_url) để tạo ebook config

### Requirement: API search endpoint
Hệ thống SHALL có API endpoint `POST /library/ebooks/search` để tìm kiếm tiểu thuyết.

#### Scenario: Search API trả kết quả
- **WHEN** frontend gửi `POST /library/ebooks/search` với `query` form field
- **THÌ** trả về JSON array chứa kết quả tìm kiếm từ tất cả sources

#### Scenario: Search API với source cụ thể
- **WHEN** frontend gửi `POST /library/ebooks/search` với `query` và `sources` (comma-separated)
- **THÌ** chỉ tìm kiếm trên các source được chỉ định

#### Scenario: Search API lỗi
- **WHEN** không có source nào có search config hoặc tất cả search đều lỗi
- **THÌ** trả về JSON `{"error": "..."}` với thông báo lỗi

### Requirement: Tùy chọn dịch metadata sang tiếng Việt
Hệ thống SHALL cho phép dịch metadata (title, author, description) sang tiếng Việt khi crawl từ search results. Mặc định: không dịch.

#### Scenario: Bật dịch metadata từ Web UI
- **WHEN** người dùng tick checkbox "Dịch metadata" trước khi chọn kết quả search
- **THÌ** hệ thống dịch title, author, description sang tiếng Việt trước khi preview

#### Scenario: Bật dịch metadata từ CLI
- **WHEN** người dùng chạy `python -m novel2epub search "truyện" --select 1 --translate`
- **THÌ** hệ thống dịch metadata trước khi tạo ebook config

#### Scenario: Không bật dịch metadata
- **WHEN** checkbox "Dịch metadata" không được tick (mặc định)
- **THÌ** metadata được lưu nguyên bản tiếng Trung

#### Scenario: Dịch metadata thất bại
- **WHEN** backend translation gặp lỗi
- **THÌ** lưu metadata gốc, thông báo cảnh báo "Không thể dịch metadata"

### Requirement: LibreTranslate backend
Hệ thống SHALL hỗ trợ LibreTranslate như một backend translation mới.

#### Scenario: Cấu hình LibreTranslate
- **WHEN** người dùng cấu hình `translate.type: libretranslate` và `translate.libretranslate.base_url: http://localhost:5000`
- **THÌ** hệ thống sử dụng LibreTranslate API để dịch

#### Scenario: LibreTranslate với API key
- **WHEN** người dùng cấu hình `translate.libretranslate.api_key`
- **THÌ** hệ thống gửi API key trong header `Authorization: Bearer <key>`

#### Scenario: LibreTranslate server không available
- **WHEN** LibreTranslate server không phản hồi
- **THÌ** hệ thống báo lỗi rõ ràng, gợi ý kiểm tra server hoặc chuyển backend

### Requirement: CLI command tìm kiếm
CLI SHALL có command `search` với output rõ ràng.

#### Scenario: Search với output mặc định
- **WHEN** người dùng chạy `python -m novel2epub search "truyện"`
- **THÌ** in ra danh sách kết quả: `[source] title — author — url`

#### Scenario: Search với output JSON
- **WHEN** người dùng chạy `python -m novel2epub search "truyện" --format json`
- **THÌ** output là JSON array chứa tất cả kết quả

#### Scenario: Search và chọn kết quả
- **WHEN** người dùng chạy `python -m novel2epub search "truyện" --select 1 --translate`
- **THÌ** crawl kết quả #1, dịch metadata, tạo ebook config mới

### Requirement: Xử lý rate limiting và anti-bot
Hệ thống SHALL tôn trọng `delay_seconds` của mỗi source preset khi search.

#### Scenario: Rate limit giữa các request
- **WHEN** gửi nhiều request đến cùng một source
- **THÌ** chờ `delay_seconds` giữa mỗi request

#### Scenario: Bị chặn bởi anti-bot
- **WHEN** source trả về HTTP 429 hoặc anti-bot challenge
- **THÌ** bỏ qua source đó, hiển thị thông báo "Source bị chặn" trong kết quả
