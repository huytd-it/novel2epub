## ADDED Requirements

### Requirement: Endpoint POST /ebooks/{slug}/jobs/translate-meta-selected

Hệ thống SHALL cung cấp endpoint `POST /ebooks/{slug}/jobs/translate-meta-selected` nhận `checked_indexes: list[int]` và `override: bool`. Endpoint này SHALL gọi `step_translate_selected(cfg, log, force=override, selected_indexes=checked_indexes)`.

Việc gọi `step_translate_selected` (thay vì tạo hàm riêng) đảm bảo cả metadata (title/author/description) và nội dung chương đều được dịch — vì `_translate_meta_inplace()` được chạy đầu tiên trong `step_translate_selected`.

#### Scenario: Translate meta selected thành công
- **WHEN** người dùng tick 2 chương và bấm "Dịch meta selected"
- **THEN** endpoint nhận `checked_indexes=[3, 7]`
- **THEN** `step_translate_selected(cfg, log, force=False, selected_indexes=[3, 7])` được gọi

#### Scenario: Translate meta selected với override
- **WHEN** người dùng tick override + bấm "Dịch meta selected"
- **THEN** `step_translate_selected(cfg, log, force=True, selected_indexes=[...])` được gọi

### Requirement: Nút "Dịch meta selected" trong vùng TOC

Hệ thống SHALL hiển thị nút "Dịch meta selected" bên cạnh "Crawl selected" và "Dịch selected". Nút này SHALL gửi POST đến endpoint `/ebooks/{slug}/jobs/translate-meta-selected`.

#### Scenario: Nút translate-meta-selected hiển thị
- **WHEN** trang ebook được render với danh sách chương
- **THEN** nút "Dịch meta selected" hiển thị trong thanh action
