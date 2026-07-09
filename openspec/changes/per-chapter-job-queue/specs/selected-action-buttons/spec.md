## MODIFIED Requirements

### Requirement: Các nút selected action hiển thị queue status thay vì bị disabled

Hệ thống SHALL hiển thị badge queue status (số job pending/running) bên cạnh các nút selected action thay vì disabled chúng khi có job cùng category đang chạy. Tất cả nút selected action SHALL luôn ở trạng thái enabled, cho phép người dùng xếp hàng nhiều batch liên tiếp.

#### Scenario: Crawl selected vẫn enabled khi đang crawl
- **WHEN** job crawl đang chạy
- **THEN** nút "Crawl selected" vẫn enabled
- **THEN** nút "Dịch selected" và "Dịch meta selected" vẫn enabled
- **THEN** badge hiển thị số job crawl đang pending/running

#### Scenario: Người dùng bấm crawl selected liên tiếp
- **WHEN** người dùng bấm "Crawl selected" lần 1 (3 chương)
- **THEN** 3 job được enqueue
- **WHEN** người dùng bấm "Crawl selected" lần 2 (2 chương khác) ngay sau đó
- **THEN** 2 job nữa được enqueue vào sau, không bị từ chối

## REMOVED Requirements

### Requirement: Các nút selected action bị disabled khi job cùng category đang chạy
**Reason**: Với job queue, không còn lý do để block người dùng. Mọi action đều được enqueue và xử lý lần lượt. Disabled button gây khó chịu và làm giảm năng suất.
**Migration**: Template `ebook.html` xóa `disabled` attribute dựa trên `job.running`. Thêm badge queue status từ `/api/queue` snapshot.
