## Why

JobQueue chỉ cho phép 1 job translate chạy tại 1 thời điểm (1 worker mặc định cho category "translate"). Khi dịch ebook A, người dùng không thể bắt đầu dịch ebook B — nút translate trên Web UI bị disabled dù 2 ebook độc lập, không xung đột I/O. Cần nâng cấp queue để chạy song song translate trên nhiều ebook khác nhau.

## What Changes

- JobQueue cho phép nhiều job trong cùng category "translate" chạy đồng thời, tối đa theo số worker được cấu hình
- Thêm guard per-ebook: không cho 2 job translate chạy đồng thời trên **cùng 1 ebook** (tránh xung đột ghi file `translated/{stem}.md`)
- Web UI hiển thị trạng thái job theo từng ebook thay vì gộp chung category (nút translate cho ebook A vẫn active nếu đang chạy translate ebook B)
- Mặc định tăng worker cho category "translate" lên 2 (có thể cấu hình qua `workers` trong JobRunner)

## Capabilities

### New Capabilities
- `per-ebook-concurrency`: Cơ chế cho phép nhiều job translate trên các ebook khác nhau chạy song song, đồng thời chặn job trùng trên cùng 1 ebook

### Modified Capabilities
- Không có — đây là thay đổi implementation (JobQueue + Web UI), không thay đổi spec-level requirements

## Impact

- **app/queue.py**: Sửa `_can_start()` để kiểm tra slot worker còn trống + per-ebook lock. `_active` cần đếm đúng số worker đang chạy
- **app/job.py**: Mặc định workers={"translate": 2} cho phép 2 translate song song
- **app/routes/**: Các route kiểm tra `category_status("translate")` cần phân biệt theo ebook slug
- **app/routes/templates/**: Web UI hiển thị trạng thái translate per-ebook
- **novel2epub/storage.py**: Không thay đổi — mỗi ebook dùng `Storage` riêng với `data_dir/novel.slug` khác nhau, nên I/O đã cách ly
