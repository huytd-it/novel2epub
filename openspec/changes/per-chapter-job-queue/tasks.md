## 1. Route batch action — per-chapter jobs

- [x] 1.1 Xóa hàm `_group_by_char_budget` trong `app/routes/jobs.py`
- [x] 1.2 Sửa action `translate` trong `start_ebook_chapter_action`: bỏ grouping, mỗi chapter = 1 job (giống crawl)
- [x] 1.3 Sửa action `cleanup-han` trong `start_ebook_chapter_action`: chuyển từ `start_custom` monolithic sang N job per-chapter `queue.enqueue`
- [x] 1.4 Thêm checkbox "Gộp batch" cho cleanup-han: khi tick, gom tất cả selected vào 1 job duy nhất (giữ nguyên `start_custom` cũ làm fallback)

## 2. Route action đơn lẻ — queue.enqueue thay start_custom

- [x] 2.1 Sửa `ebook_chapter_action` (`app/routes/chapters.py:214`): thay `start_custom` → `queue.enqueue`, xóa check `started` và HTTP 409
- [x] 2.2 Sửa `ebook_chapter_delete_translation` (`app/routes/chapters.py:236`): thay `start_custom` → `queue.enqueue`, xóa HTTP 409
- [x] 2.3 Sửa `ebook_chapter_ai` (`app/routes/chapters.py:354`): thay `start_custom` → `queue.enqueue`, xóa HTTP 409

## 3. Template — xóa disabled, thêm queue badge

- [x] 3.1 Template `ebook.html`: xóa `disabled` attribute trên các nút action dựa vào `job.running`
- [x] 3.2 Template `chapter.html`: xóa `disabled` attribute trên nút action đơn lẻ
- [x] 3.3 Thêm queue status badge (số pending/running) cạnh nhóm nút crawl và dịch trong TOC, lấy dữ liệu từ `/api/queue` snapshot

## 4. Queue UI — bulk clear/retry failed

- [x] 4.1 Thêm API `POST /api/queue/bulk-clear-failed` xóa tất cả job failed trong 1 category
- [x] 4.2 Thêm API `POST /api/queue/bulk-retry-failed` retry tất cả job failed trong 1 category
- [x] 4.3 Template `queue.html`: thêm nút "Xóa failed" và "Retry failed" cho từng category
