## ADDED Requirements

### Requirement: Nút "Kiểm tra kết nối AI" trong tab Translate
Tab Translate SHALL có nút "Kiểm tra kết nối" bên cạnh field `model`. Khi click, gọi `GET /settings/ai/models?base_url=...&api_key=...` và hiển thị kết quả (danh sách model hoặc lỗi) inline bên dưới nút.

#### Scenario: Click kiểm tra kết nối thành công
- **WHEN** người dùng click "Kiểm tra kết nối"
- **THEN** gọi `GET /settings/ai/models` với `base_url` và `api_key` hiện tại
- **AND** hiển thị danh sách model trả về dưới dạng dropdown `<datalist>` và thông báo "Đã tìm thấy N model"
- **AND** tự động populate model list vào `<datalist id="model-options">`

#### Scenario: Click kiểm tra kết nối thất bại
- **WHEN** kết nối thất bại (lỗi mạng, 401...)
- **THEN** hiển thị thông báo lỗi màu đỏ: "Không thể kết nối: <error>"
- **AND** cho phép người dùng nhập model id thủ công

### Requirement: Nút "Thử crawl TOC" trong tab Crawl (placeholder)
Tab Crawl SHALL có nút "Thử crawl TOC" bên cạnh field `toc_url`. Khi click, hiển thị thông báo "Tính năng đang phát triển" (placeholder — không gọi API thật).

#### Scenario: Click nút thử crawl
- **WHEN** người dùng click "Thử crawl TOC"
- **THEN** hiển thị thông báo "Tính năng đang phát triển" phía dưới

### Requirement: Nút "Xem raw config" ở cuối mỗi tab
Cuối mỗi tab SHALL có link/button "Xem raw YAML" mở popup/section hiển thị raw YAML override của ebook hiện tại.

#### Scenario: Xem raw config
- **WHEN** người dùng click "Xem raw YAML"
- **THEN** hiển thị `<pre><code>` block chứa nội dung file YAML config namespace tương ứng
- **AND** có nút "Ẩn" để đóng
