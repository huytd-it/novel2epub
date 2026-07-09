## ADDED Requirements

### Requirement: Crawl batch tạo N job per-chapter

Hệ thống SHALL tạo 1 job riêng cho mỗi chapter khi người dùng chọn crawl nhiều chapter. Mỗi job gọi `step_crawl_selected(cfg, log, selected_indexes=[idx])` và có `lock_ebook=False` để các job crawl cùng ebook chạy song song.

#### Scenario: Crawl 3 chapter tạo 3 job
- **WHEN** người dùng tick 3 chapter (index 1, 5, 10) và bấm "Crawl selected"
- **THEN** hệ thống enqueue 3 job vào category "crawl", mỗi job có `chapter_indexes=[1]`, `[5]`, `[10]`
- **THEN** label mỗi job hiển thị "Crawl · {ebook_title} · {chapter_title}"
- **THEN** cả 3 job có thể chạy song song nếu số worker đủ

#### Scenario: Crawl chapter đơn lẻ từ trang chapter cũng tạo 1 job
- **WHEN** người dùng bấm "Crawl" từ trang chapter detail (POST `/ebooks/{slug}/chapters/{index}/action?action=crawl`)
- **THEN** hệ thống enqueue 1 job vào category "crawl" thay vì dùng `start_custom`

### Requirement: Dịch batch mỗi chapter = 1 job

Hệ thống SHALL tạo 1 job riêng cho mỗi chapter khi dịch batch (không còn gom nhóm theo char budget). Mỗi job gọi `step_translate_selected(cfg, log, selected_indexes=[idx])`.

#### Scenario: Dịch 5 chapter tạo 5 job
- **WHEN** người dùng tick 5 chapter và bấm "Dịch selected"
- **THEN** hệ thống enqueue 5 job vào category "translate", mỗi job có `chapter_indexes=[idx]`
- **THEN** không có logic `_group_by_char_budget` nào được gọi

#### Scenario: Dịch chapter đơn lẻ cũng tạo 1 job trong queue
- **WHEN** người dùng bấm "Dịch" từ trang chapter detail
- **THEN** hệ thống enqueue 1 job vào category "translate" thay vì dùng `start_custom`

### Requirement: Cleanup Hán batch tạo N job per-chapter (mặc định)

Hệ thống SHALL tạo 1 job riêng cho mỗi chapter khi cleanup Hán batch. Mỗi job gọi `step_cleanup_han_selected(cfg, log, selected_indexes=[idx])`. Người dùng có thể chọn gộp thành 1 job duy nhất qua checkbox "Gộp batch".

#### Scenario: Cleanup Hán 10 chapter mặc định tạo 10 job
- **WHEN** người dùng tick 10 chapter và bấm "Cleanup Hán selected" (không tick "Gộp batch")
- **THEN** hệ thống enqueue 10 job vào category "translate", mỗi job có `chapter_indexes=[idx]`

#### Scenario: Cleanup Hán gộp batch tạo 1 job
- **WHEN** người dùng tick "Gộp batch" và bấm "Cleanup Hán selected" với 10 chapter
- **THEN** hệ thống enqueue 1 job với `chapter_indexes=[...10 indexes]`, gọi `step_cleanup_han_selected(cfg, log, selected_indexes=[...])` với tất cả index

### Requirement: Job lưu chapter_indexes để hiển thị và trace

Hệ thống SHALL lưu `chapter_indexes` trong mỗi Job object khi enqueue. Queue UI SHALL hiển thị danh sách chapter indexes trong job detail.

#### Scenario: Job detail hiển thị chapter đã xử lý
- **WHEN** user xem job detail trong queue page
- **THEN** danh sách chapter indexes của job đó được hiển thị
