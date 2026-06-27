## Why

Giao diện ebook hiện tại dùng một `bulk-bar` với dropdown action (Crawl/Dịch) kèm range và targeting mode phức tạp, gây nhầm lẫn và thao tác chậm. Đồng thời backend MoxhiMT — model NMT thuần (không dùng prompt) — vốn đã tối ưu cho zh→vi, nhưng các nhánh xử lý metadata (title/author/description) vẫn gọi `translate_title()` và `translate()` qua translator interface chung, cần kiểm tra không có prompt template nào rò rỉ vào luồng dịch moxhimt.

Người dùng muốn thao tác nhanh hơn: tick dòng → bấm nút hành động cụ thể (Crawl, Dịch, Dịch meta) thay vì chọn dropdown + bấm "Chạy".

## What Changes

- **BREAKING**: Bỏ `bulk-bar` (range + targeting_mode + dropdown action). Thay bằng các button riêng biệt: "Crawl selected", "Dịch selected", "Dịch meta selected" chỉ tác dụng lên dòng đã tick.
- Thêm nút "Dịch metadata (AI)" mới bên dưới action group **meta-card** riêng biệt khỏi action-group Dịch.
- Xác nhận `MoxhiMTTranslator` không sử dụng bất kỳ prompt template nào — nội dung gốc được đưa thẳng vào model NMT qua SentencePiece + CTranslate2.
- Backend: thêm endpoint mới `POST /ebooks/{slug}/jobs/translate-meta-selected` để dịch metadata cho các chương được tick (tái sử dụng `step_translate_selected` với `force=True` cho title/chapter).
- Thay đổi cơ chế gửi form: từ `chapter-action` bulk form sang các form riêng cho từng action, mỗi form chỉ gửi `checked_indexes`.

## Capabilities

### New Capabilities
- `selected-action-buttons`: Các nút hành động gắn với dòng đã tick, thay thế bulk-bar dropdown.
- `translate-meta-selected`: Dịch metadata (title chương) của các chương được chọn.
- `moxhimt-no-prompt-verification`: Kiểm tra và xác nhận backend MoxhiMT không dùng prompt template.

### Modified Capabilities
- `ebook-ui-layout`: Bố cục action group được tái tổ chức, bỏ bulk-bar, thêm translate-meta button cho selected chapters.

## Impact

- **UI template**: `app/templates/ebook.html` — xóa `.bulk-bar`, thêm các form/nút thay thế.
- **Routes**: `app/routes/jobs.py` — thêm endpoint `translate-meta-selected`. Có thể bỏ bớt tham số `targeting_mode` và `range_*` khỏi `chapter-action` nếu không còn dùng.
- **Pipeline**: `novel2epub/pipeline.py` — không cần thay đổi (tái sử dụng `step_translate_selected` và `step_crawl_selected`).
- **Translator**: Không thay đổi code — chỉ kiểm tra và xác nhận `MoxhiMTTranslator` không dùng prompt.
- **CSS**: Có thể cần style mới cho các action button trong `toc-region`.
