## ADDED Requirements

### Requirement: Chọn nhiều chương bằng checkbox
Hệ thống SHALL cho phép người dùng chọn nhiều chương thông qua checkbox trên danh sách chapters hoặc trong giao diện chapter.

#### Scenario: Hiển thị checkbox selection
- **WHEN** người dùng xem danh sách chapters (table view)
- **THEN** hệ thống SHALL hiển thị checkbox ở mỗi dòng chương và checkbox "Select all" ở header

#### Scenario: Chọn/bỏ chọn nhiều chương
- **WHEN** người dùng tick/untick checkbox của từng chương
- **THEN** hệ thống SHALL cập nhật counter số chương đã chọn

#### Scenario: Select all / Deselect all
- **WHEN** người dùng tick/untick checkbox "Select all"
- **THEN** hệ thống SHALL tick/untick tất cả checkbox chương

### Requirement: Thực hiện thao tác hàng loạt
Hệ thống SHALL cho phép thực hiện các thao tác trên nhiều chương đã chọn cùng lúc.

#### Scenario: Dịch tiêu đề hàng loạt
- **WHEN** người dùng chọn nhiều chương và bấm "Dịch tiêu đề hàng loạt"
- **THEN** hệ thống SHALL gọi API batch để dịch tiêu đề cho tất cả chương đã chọn

#### Scenario: Glossary suggest hàng loạt
- **WHEN** người dùng chọn nhiều chương và bấm "Glossary suggest hàng loạt"
- **THEN** hệ thống SHALL gọi API batch để AI gợi ý glossary cho tất cả chương đã chọn

#### Scenario: Hiển thị tiến trình batch
- **WHEN** batch operation đang chạy
- **THEN** hệ thống SHALL hiển thị progress bar và số chương đã xử lý/tổng số

#### Scenario: Hủy batch operation
- **WHEN** người dùng bấm "Hủy" trong khi batch đang chạy
- **THEN** hệ thống SHALL dừng xử lý các chương còn lại và hiển thị kết quả những chương đã xử lý

### Requirement: API endpoint cho batch operations
Hệ thống SHALL cung cấp REST API endpoint để thực hiện batch operations.

#### Scenario: POST /api/ebooks/{slug}/batch/translate-titles
- **WHEN** gửi POST request với body `{indexes: [1,2,3], engine: "openai", model: "gpt-4"}`
- **THEN** hệ thống SHALL trả về `{job_id, total, started}` và chạy background job

#### Scenario: POST /api/ebooks/{slug}/batch/suggest-glossary
- **WHEN** gửi POST request với body `{indexes: [1,2,3]}`
- **THEN** hệ thống SHALL trả về `{job_id, total, started}` và chạy background job

#### Scenario: GET /api/jobs/{job_id}/status
- **WHEN** poll status của batch job
- **THEN** hệ thống SHALL trả về `{running, completed, total, errors: []}`
