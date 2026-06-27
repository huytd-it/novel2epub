## ADDED Requirements

### Requirement: Bulk-bar được thay thế bằng action buttons

Hệ thống SHALL xóa `.bulk-bar` (từ dòng 156 đến 177 trong `ebook.html` hiện tại). Thay vào đó, hệ thống SHALL hiển thị một thanh action chứa các button riêng biệt: "Crawl selected", "Dịch selected", "Dịch meta selected", checkbox "Ghi đè", và `#checked-info`.

#### Scenario: Action buttons hiển thị đúng vị trí
- **WHEN** trang ebook render với danh sách chương
- **THEN** thanh action hiển thị ngay dưới `.compact-toolbar` và trên `.table-wrap`

#### Scenario: Bulk-bar cũ không còn
- **WHEN** trang ebook render
- **THEN** không còn `<div class="bulk-bar">` trong DOM

### Requirement: Mỗi action button là một form riêng

Mỗi nút selected action SHALL là một `<form method="post">` riêng biệt, không dùng chung form `#bulk-action-form` cũ. Mỗi form SHALL chứa:
- `checked_indexes[]` (lấy từ checkbox đã tick qua JS)
- `override` nếu checkbox Override được tick

#### Scenario: Crawl selected form
- **WHEN** người dùng tick 2 chương và bấm "Crawl selected"
- **THEN** form gửi POST đến `/ebooks/{slug}/jobs/chapter-action`
- **THEN** body chứa `action=crawl`, `targeting_mode=checked`, `checked_indexes=[1,2]`

#### Scenario: Dịch selected form
- **WHEN** người dùng tick 3 chương và bấm "Dịch selected"
- **THEN** form gửi POST đến `/ebooks/{slug}/jobs/chapter-action`
- **THEN** body chứa `action=translate`, `targeting_mode=checked`, `checked_indexes=[4,5,6]`

### Requirement: hidden inputs sort/direction/search/filter gửi kèm

Mỗi action form SHALL gửi kèm `sort`, `direction`, `search`, `filter_raw`, `filter_translated`, `filter_missing` dạng hidden input để server tái tạo đúng danh sách chương.

#### Scenario: Hidden inputs đồng bộ với toolbar
- **WHEN** người dùng đổi sort thành "title" và direction thành "desc"
- **THEN** hidden inputs trong action forms có giá trị tương ứng

### Requirement: JavaScript setJobButtonsDisabled cập nhật

Hàm `setJobButtonsDisabled()` SHALL được cập nhật để disable/enable các nút selected action mới dựa trên trạng thái job. Selector SHALL bao gồm các form/nút mới.

#### Scenario: Crawl selected disabled khi crawl đang chạy
- **WHEN** job crawl running
- **THEN** nút "Crawl selected" disabled, các nút dịch vẫn enabled

### Requirement: jobCategoryFor cập nhật

Hàm `jobCategoryFor()` SHALL xác định đúng category cho các form/nút mới dựa trên action URL hoặc data attribute.

#### Scenario: jobCategoryFor cho crawl selected
- **WHEN** form action là `/ebooks/{slug}/jobs/chapter-action` và submitter value là "crawl"
- **THEN** category trả về "crawl"
