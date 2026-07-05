## ADDED Requirements

### Requirement: Propagate preset update sang ebook
Khi source preset được lưu (update), hệ thống SHALL tự động cập nhật crawl config cho mọi ebook tham chiếu preset đó. Chỉ cập nhật field ebook CHƯA override.

#### Scenario: Preset update field ebook chưa override
- **WHEN** preset "aixdzs" được update `delay_seconds: 2.0` (từ 1.0)
- **VÀ** ebook "truyen-abc" có `source: aixdzs`, không có `delay_seconds` trong crawl block
- **THEN** ebook "truyen-abc" crawl config SHALL có `delay_seconds: 2.0` (từ preset mới)

#### Scenario: Preset update field ebook đã override
- **WHEN** preset "aixdzs" được update `content_selector: ".new-css"` (từ ".content")
- **VÀ** ebook "truyen-abc" có `source: aixdzs` VÀ `content_selector: ".custom"` trong crawl block
- **THEN** ebook "truyen-abc" SHALL giữ nguyên `content_selector: ".custom"` — KHÔNG bị ghi đè

#### Scenario: Propagate cho nhiều ebook cùng source
- **WHEN** preset "aixdzs" được update
- **VÀ** có 3 ebook có `source: aixdzs`
- **THEN** cả 3 ebook SHALL được kiểm tra và cập nhật field tương ứng (theo rule override ở trên)

#### Scenario: Không có ebook nào dùng preset
- **WHEN** preset "aixdzs" được update nhưng không ebook nào có `source: aixdzs`
- **THEN** hệ thống SHALL lưu preset như bình thường, không có ebook nào bị ảnh hưởng

### Requirement: Sync ebook crawl settings về source preset
Ebook settings UI SHALL cung cấp nút "Lưu vào nguồn" để cập nhật source preset từ crawl settings hiện tại của ebook.

#### Scenario: Nút "Lưu vào nguồn" hiển thị
- **WHEN** user mở ebook settings tab Nguồn, ebook có field `source`
- **THEN** UI SHALL hiển thị nút "Lưu vào nguồn" (hoặc equivalent)

#### Scenario: Nút không hiển thị khi không có source
- **WHEN** user mở ebook settings tab Nguồn, ebook KHÔNG có field `source`
- **THEN** UI SHALL KHÔNG hiển thị nút "Lưu vào nguồn"

#### Scenario: Sync ebook → preset
- **WHEN** user nhấn "Lưu vào nguồn" với ebook có `source: aixdzs`
- **VÀ** ebook crawl config có `content_selector: ".custom"` (override)
- **THEN** preset "aixdzs" SHALL được update `content_selector` = `".custom"`
- **VÀ** các ebook khác có `source: aixdzs` (không override field này) SHALL nhận giá trị mới

#### Scenario: Confirm trước khi sync
- **WHEN** user nhấn "Lưu vào nguồn"
- **THEN** UI SHALL hiển thị confirm dialog liệt kê field sẽ thay đổi trong preset trước khi thực hiện

### Requirement: Validate source name khi gán
Hệ thống SHALL validate rằng source name tồn tại trước khi gán cho ebook.

#### Scenario: Gán source hợp lệ
- **WHEN** user gán `source: aixdzs` cho ebook, preset "aixdzs" tồn tại
- **THEN** ebook config SHALL được lưu với `source: aixdzs`

#### Scenario: Gán source không tồn tại
- **WHEN** user gán `source: nonexistent` cho ebook, preset "nonexistent" không tồn tại
- **THEN** hệ thống SHALL hiển thị lỗi "Nguồn 'nonexistent' không tồn tại"

### Requirement: Chặn xóa preset đang được ebook tham chiếu
Logic chặn xóa preset hiện tại SHALL hoạt động chính xác với model reference (không cần brute-force so sánh field).

#### Scenario: Preset đang được dùng
- **WHEN** user xóa preset "aixdzs" và có ebook có `source: aixdzs`
- **THEN** hệ thống SHALL chặn xóa và hiển thị danh sách ebook đang dùng

#### Scenario: Preset không được dùng
- **WHEN** user xóa preset "aixdzs" và không ebook nào có `source: aixdzs`
- **THEN** hệ thống SHALL cho phép xóa

### Requirement: Preset usage tracking chính xác
`_preset_usage()` SHALL xác định ebook nào dùng preset nào bằng cách đọc field `source` trong ebook config, KHÔNG brute-force so sánh field.

#### Scenario: Usage từ field source
- **WHEN** ebook "truyen-abc" có `source: aixdzs`
- **THEN** `_preset_usage()` SHALL trả "aixdzs" → ["truyen-abc"]

#### Scenario: Ebook không có source field
- **WHEN** ebook "truyen-xyz" không có field `source`
- **THEN** ebook này KHÔNG xuất hiện trong usage map của bất kỳ preset nào
