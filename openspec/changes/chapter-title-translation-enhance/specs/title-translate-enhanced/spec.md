## ADDED Requirements

### Requirement: Chọn engine và model khi dịch tiêu đề
Hệ thống SHALL cho phép người dùng chọn translate engine (OpenAI, Google, HachimiMT) và model cụ thể khi thực hiện chức năng "Dịch lại tiêu đề".

#### Scenario: Hiển thị dropdown engine và model
- **WHEN** người dùng nhìn thấy phần "Dịch lại tiêu đề" trong trang chapter
- **THEN** hệ thống SHALL hiển thị dropdown để chọn engine và dropdown model tương ứng

#### Scenario: Lưu lại lựa chọn engine/model
- **WHEN** người dùng chọn engine và model rồi bấm "Dịch lại tiêu đề"
- **THEN** hệ thống SHALL gửi engine và model đã chọn đến API endpoint

#### Scenario: Default engine từ config
- **WHEN** trang chapter được load
- **THEN** hệ thống SHALL mặc định chọn engine từ config `translate.type` và model từ config tương ứng

### Requirement: Tạo description giải thích tên chương
Hệ thống SHALL cho phép tạo description giải thích vì sao chương được đặt tên như vậy, dựa vào nội dung chapter + raw title.

#### Scenario: Tạo description từ nội dung
- **WHEN** người dùng bấm "Tạo description" hoặc chọn option khi dịch tiêu đề
- **THEN** hệ thống SHALL gửi raw title và nội dung chapter đã dịch đến AI để tạo description

#### Scenario: Hiển thị description kết quả
- **WHEN** AI trả về description
- **THEN** hệ thống SHALL hiển thị description trong trường `title_note` hoặc một khu vực riêng

#### Scenario: Description bằng tiếng Việt
- **WHEN** tạo description
- **THEN** hệ thống SHALL đảm bảo description bằng tiếng Việt, giải thích nguồn gốc/cảnh nghĩa của tên chương

### Requirement: Preview prompt template
Hệ thống SHALL cho phép người dùng xem trước và tùy chỉnh prompt template khi dịch tiêu đề.

#### Scenario: Hiển thị prompt preview
- **WHEN** người dùng bấm "Xem prompt" hoặc toggle "Custom prompt"
- **THEN** hệ thống SHALL hiển thị textarea chứa prompt template hiện tại

#### Scenario: Custom prompt template
- **WHEN** người dùng chỉnh sửa prompt trong textarea
- **THEN** hệ thống SHALL sử dụng prompt đã chỉnh sửa khi gọi AI

#### Scenario: Reset prompt về mặc định
- **WHEN** người dùng bấm "Reset prompt"
- **THEN** hệ thống SHALL khôi phục prompt template về mặc định

### Requirement: Hỗ trợ nhiều engine cho dịch tiêu đề
Hệ thống SHALL mở rộng `step_retranslate_title` để hỗ trợ các engine ngoài OpenAI.

#### Scenario: Dịch tiêu đề với Google Translate
- **WHEN** người dùng chọn engine = "google" khi dịch tiêu đề
- **THEN** hệ thống SHALL sử dụng Google Translate backend (nếu có thể, hoặc fallback với note)

#### Scenario: Dịch tiêu đề với HachimiMT
- **WHEN** người dùng chọn engine = "hachimimt" khi dịch tiêu đề
- **THEN** hệ thống SHALL sử dụng HachimiMT backend

#### Scenario: Fallback khi engine không hỗ trợ
- **WHEN** selected engine không hỗ trợ dịch tiêu đề (thiếu context, prompt-based)
- **THEN** hệ thống SHALL hiển thị thông báo và đề xuất chuyển sang OpenAI
