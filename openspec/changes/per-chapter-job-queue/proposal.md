## Why

Hiện tại các action batch (crawl/dịch/cleanup Hán) không đồng nhất về cách chia job: crawl đã là per-chapter, dịch bị gom nhóm theo char budget, cleanup Hán là 1 job monolithic. Action đơn lẻ (single chapter) dùng `start_custom` và trả 409 nếu có job khác đang chạy, đồng thời các nút bị disabled — người dùng không thể xếp hàng nhiều thao tác. Cần thống nhất tất cả về mô hình per-chapter job queue để mỗi chương là 1 job độc lập, không bao giờ block, dễ dàng thấy lỗi từng chương và clear/retry.

## What Changes

- **Dịch**: bỏ `_group_by_char_budget`, mỗi chương = 1 job riêng lẻ trong queue
- **Cleanup Hán**: từ 1 job monolithic chuyển thành N job per-chapter trong queue, với tùy chọn batch
- **Action đơn lẻ** (`ebook_chapter_action`): thay `start_custom` (trả 409) bằng `queue.enqueue` — nút không bao giờ disabled
- **UI/Template**: xóa logic disable nút dựa trên trạng thái job đang chạy (thay bằng queue status indicator nếu cần)
- **Queue UI**: thêm nút "Xóa tất cả failed" và "Retry tất cả failed" cho từng category

## Capabilities

### New Capabilities
- `per-chapter-jobs`: Tất cả action batch (crawl, dịch, cleanup Hán, xóa bản dịch) đều tạo N job per-chapter trong queue, mỗi job độc lập có thể bị cancel/retry/delete riêng. Chapter indexes được lưu trong `job.chapter_indexes`.
- `never-block-ui`: Nút action không bao giờ bị disabled vì job khác đang chạy. Mọi request đều được enqueue, không trả 409. Người dùng có thể bấm liên tục các action khác nhau và chúng tự xếp hàng.

### Modified Capabilities
- `selected-action-buttons`: **BREAKING** — xóa requirement "Các nút selected action bị disabled khi job cùng category đang chạy". Thay bằng: nút luôn enabled, mỗi lần bấm tạo job mới trong queue. Thêm indicator hiển thị số job pending/running thay vì disable.

## Impact

- `app/routes/jobs.py`: sửa `start_ebook_chapter_action` (hàm translate, cleanup-han), xóa `_group_by_char_budget`
- `app/routes/chapters.py`: sửa `ebook_chapter_action`, `ebook_chapter_delete_translation`, `ebook_chapter_ai` — thay `start_custom` → `queue.enqueue`
- Templates: `ebook.html` (nút TOC), `chapter.html` (nút single action) — xóa logic disabled, thêm queue status indicator
- `novel2epub/pipeline.py`: `step_cleanup_han_selected` đã hỗ trợ `selected_indexes` — không cần đổi
