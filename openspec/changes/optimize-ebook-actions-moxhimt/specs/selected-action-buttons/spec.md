## ADDED Requirements

### Requirement: Người dùng có thể crawl các chương đã tick

Hệ thống SHALL cung cấp nút "Crawl selected" trong vùng TOC, chỉ tác dụng lên các chương đã được tick checkbox. Nút SHALL gửi `POST /ebooks/{slug}/jobs/chapter-action` với `action=crawl`, `targeting_mode=checked`, và danh sách `checked_indexes`.

#### Scenario: Crawl selected thành công
- **WHEN** người dùng tick 3 chương và bấm "Crawl selected"
- **THEN** hệ thống gọi `step_crawl_selected(cfg, log, selected_indexes=[...])` với 3 index đã tick

#### Scenario: Crawl selected khi không có chương nào được tick
- **WHEN** người dùng bấm "Crawl selected" nhưng không tick chương nào
- **THEN** nút bị disabled hoặc form gửi mảng rỗng → server trả 400

### Requirement: Người dùng có thể dịch các chương đã tick

Hệ thống SHALL cung cấp nút "Dịch selected" trong vùng TOC, chỉ tác dụng lên các chương đã được tick checkbox. Nút SHALL gửi `POST /ebooks/{slug}/jobs/chapter-action` với `action=translate`, `targeting_mode=checked`, và danh sách `checked_indexes`.

#### Scenario: Dịch selected thành công
- **WHEN** người dùng tick 5 chương và bấm "Dịch selected"
- **THEN** hệ thống gọi `step_translate_selected(cfg, log, selected_indexes=[...])` với 5 index đã tick

### Requirement: Nút checked-info hiển thị số chương đã tick

Hệ thống SHALL giữ lại span `#checked-info` hiển thị "Đã tick X chương." và cập nhật real-time khi người dùng tick/bỏ tick.

#### Scenario: checked-info cập nhật khi tick
- **WHEN** người dùng tick 2 checkbox
- **THEN** `#checked-info` hiển thị "Đã tick 2 chương."

### Requirement: Checkbox Override cho selected actions

Hệ thống SHALL cung cấp checkbox "Ghi đè" bên cạnh các nút selected action. Khi tick, `override=true` được gửi cùng request.

#### Scenario: Override khi crawl selected
- **WHEN** người dùng tick override + bấm "Crawl selected"
- **THEN** request gửi `override=true` → `step_crawl_selected(cfg, log, force=True, selected_indexes=[...])`

### Requirement: Các nút selected action bị disabled khi job cùng category đang chạy

Hệ thống SHALL disable các nút "Crawl selected" khi crawl job đang chạy, và "Dịch selected"/"Dịch meta selected" khi translate job đang chạy.

#### Scenario: Crawl selected disabled khi đang crawl
- **WHEN** job crawl đang chạy
- **THEN** nút "Crawl selected" bị disabled
- **THEN** nút "Dịch selected" và "Dịch meta selected" vẫn enabled
