## Context

Hiện tại hệ thống job có 2 đường dẫn không đồng nhất:

- **Batch action** (`start_ebook_chapter_action`): crawl đã dùng `queue.enqueue` per-chapter, dịch dùng `queue.enqueue` nhưng gom nhóm theo `_group_by_char_budget` (8000 chars/group), cleanup Hán dùng `start_custom` monolithic
- **Single action** (`ebook_chapter_action`, `ebook_chapter_delete_translation`, `ebook_chapter_ai`): tất cả dùng `start_custom` → trả 409 nếu category bận, nút UI bị disabled

JobQueue (`app/queue.py`) đã hỗ trợ đầy đủ: N worker/category, `lock_ebook=False` cho phép nhiều job chạy song song cùng ebook, `chapter_indexes` để lưu danh sách chapter, pending persistence qua SQLite. Pipeline steps (`step_crawl_selected`, `step_translate_selected`, `step_cleanup_han_selected`) đều đã hỗ trợ `selected_indexes` — nhận list index và xử lý từng chapter tuần tự bên trong.

## Goals / Non-Goals

**Goals:**
- Thống nhất mọi action batch thành N job per-chapter trong queue, mỗi chapter = 1 job độc lập
- Mọi action đơn lẻ cũng dùng `queue.enqueue` thay vì `start_custom` — không bao giờ block
- Xóa logic disable nút dựa trên job status, thay bằng queue indicator (số job pending/running)
- Giữ nguyên khả năng cancel/retry/delete từng job, thêm bulk clear/retry failed

**Non-Goals:**
- Không thay đổi cấu trúc JobQueue hay cơ chế worker
- Không thay đổi logic bên trong pipeline steps
- Không thêm cơ chế dedup (tránh submit trùng chapter)
- Không thay đổi mechanism `lock_ebook` hay category isolation

## Decisions

### D1: Dịch — bỏ char budget grouping, 1 chapter = 1 job

**Chọn:** Xóa `_group_by_char_budget`. Mỗi chapter được dịch là 1 job riêng.

**Lý do:** Người dùng muốn thấy lỗi từng chương, không muốn 1 group 5 chương bị fail vì 1 chương lỗi. Trade-off: nhiều API call hơn (mỗi chương 1 round-trip) thay vì batch, nhưng job queue có thể tăng worker để bù lại throughput.

**Alternative:** Giữ group với toggle/threshold config. Bị từ chối bởi user — muốn per-chapter tuyệt đối.

### D2: route action đơn lẻ — `start_custom` → `queue.enqueue`

**Chọn:** Thay `request.app.state.job.start_custom(...)` bằng `request.app.state.job.queue.enqueue(...)` trong tất cả route action đơn lẻ.

**Lý do:** `start_custom` return False nếu category đang bận (dù queue còn slot worker), gây 409. `queue.enqueue` luôn append vào queue, worker tự pick khi rảnh. Không cần kiểm tra `started` nữa.

**Alternative:** Sửa `start_custom` để tự động fallback về enqueue. Bị từ chối vì làm phức tạp shim không cần thiết — nên gọi thẳng queue.

### D3: Cleanup Hán — per-chapter jobs, bỏ qua batch gộp nếu không tick option

**Chọn:** Mặc định 1 chapter = 1 job cleanup. Thêm checkbox "Gộp batch" (tùy chọn) để gom tất cả selected vào 1 job duy nhất (dùng `start_custom` cũ) cho trường hợp muốn tiết kiệm API call.

**Lý do:** Per-chapter là default để dễ debug. Batch gộp là fallback cho cleanup full ebook.

### D4: UI — xóa disabled, thêm queue badge

**Chọn:** Xóa logic `disabled` trên nút action dựa vào `job.running`. Thay bằng badge nhỏ hiển thị "X pending, Y running" cạnh mỗi nhóm nút (crawl/dịch). Nút luôn clickable.

**Lý do:** Với queue, không có lý do gì để disable — mọi action đều được xếp hàng. Badge cung cấp visibility thay vì block.

## Risks / Trade-offs

- **[Risk] Nhiều job nhỏ tăng overhead queue** → Job queue đã có pending persistence + history limit, N workers được tối ưu cho pattern này. Crawl đã chạy per-chapter ổn định.
- **[Risk] Không có dedup — user có thể submit 2 lần cùng 1 chapter** → Accept risk. Queue UI cho phép thấy và cancel job trùng. Có thể thêm dedup sau nếu cần.
- **[Risk] Dịch per-chapter = nhiều round-trip API hơn** → Bù lại bằng tăng worker count (người dùng tự điều chỉnh). Mỗi chapter vẫn được retry/cache riêng như cũ.
- **[Trade-off] Mất grouping efficiency của translate** → Đánh đổi lấy isolation và visibility. Với chapter dài (2000-6000 chars), chi phí gộp không đáng kể so với lợi ích debug.
