## ADDED Requirements

### Requirement: Trường `engine` dùng `<select>` với 3 option
Trường engine SHALL là `<select>` với 3 option: "http", "crawl4ai", "scrapling".

#### Scenario: Chọn engine sẽ toggle fieldset tương ứng
- **WHEN** người dùng chọn engine="crawl4ai" từ `<select>`
- **THEN** fieldset `engine-specific-http` và `engine-specific-scrapling` bị ẩn
- **AND** fieldset `engine-specific-crawl4ai` hiển thị

### Requirement: Trường `encoding` dùng `<select>` với các encoding phổ biến
Trường encoding SHALL là `<select>` với các option: "auto", "utf-8", "gbk", "gb2312", "big5", "euc-kr", "shift-jis".

#### Scenario: Select encoding
- **WHEN** người dùng mở dropdown encoding
- **THEN** thấy danh sách các encoding phổ biến
- **AND** option đang được chọn là giá trị hiện tại từ config

### Requirement: Trường `language` dùng `<select>` với ~20 ngôn ngữ
Trường language SHALL là `<select>` với các ngôn ngữ phổ biến: vi, zh-CN, en, ja, ko, fr, de, es, pt, ru, ar, hi, th, id, ms, tl, mn, my, lo, km.

#### Scenario: Select ngôn ngữ
- **WHEN** người dùng chọn ngôn ngữ từ dropdown
- **THEN** giá trị được lưu đúng mã ngôn ngữ 2-5 ký tự

### Requirement: Trường `tone` dùng `<select>` kết hợp custom text input
Trường tone SHALL là `<select>` với 6 option mẫu + 1 option "Tùy chỉnh..." cho phép nhập text tự do. Khi chọn "Tùy chỉnh...", input text hiện ra.

#### Scenario: Chọn tone từ danh sách
- **WHEN** người dùng chọn "mượt, tự nhiên, có chất cổ trang" từ dropdown
- **THEN** giá trị được set đúng

#### Scenario: Nhập tone tùy chỉnh
- **WHEN** người dùng chọn "Tùy chỉnh..."
- **THEN** một text input hiện ra bên cạnh để nhập tone custom

### Requirement: Trường `pronoun_policy`, `title_mode`, `han_viet_level` dùng `<select>`
Các trường SHALL chuyển từ `<input type="text">` sang `<select>`.

#### Scenario: Select pronoun_policy
- **WHEN** người dùng chọn pronoun_policy
- **THEN** các option: "contextual", "formal", "modern_casual", "Tùy chỉnh..."

#### Scenario: Select title_mode
- **WHEN** người dùng chọn title_mode
- **THEN** các option: "creative", "literal"

#### Scenario: Select han_viet_level
- **WHEN** người dùng chọn han_viet_level
- **THEN** các option: "balanced", "heavy", "light"

### Requirement: Trường `scrapling_mode` dùng `<select>`
Trường scrapling_mode (trong fieldset crawl4ai/scrapling) SHALL là `<select>` với 3 option: "stealthy", "fetcher", "dynamic".

#### Scenario: Select scrapling_mode
- **WHEN** engine = "scrapling"
- **THEN** field scrapling_mode hiển thị dạng select với 3 option

### Requirement: Engine-specific fields ẩn/hiện theo JS
Các fieldset chứa engine-specific fields SHALL có class `engine-specific` và data attribute `data-engine`. JS SHALL ẩn tất cả fieldset `.engine-specific` và chỉ hiện cái có `data-engine` khớp với giá trị `engine` đang chọn.

#### Scenario: Đổi engine từ http sang crawl4ai
- **WHEN** engine select thay đổi từ "http" sang "crawl4ai"
- **THEN** fieldset engine-specific-http bị ẩn
- **AND** fieldset engine-specific-crawl4ai hiển thị
- **AND** các field không engine-specific (URL, regex, max_chapters...) giữ nguyên
