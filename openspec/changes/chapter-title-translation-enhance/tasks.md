## 1. Backend - Multi-engine Title Translation

- [x] 1.1 Mở rộng `step_retranslate_title` trong `pipeline.py` nhận thêm parameter `engine` và `model`
- [x] 1.2 Thêm logic fallback khi engine != openai: sử dụng translator backend tương ứng (Google/HachimiMT) với prompt đơn giản hơn
- [x] 1.3 Tạo `_RETRANSLATE_TITLE_SIMPLE_PROMPT` cho backend không hỗ trợ context-based translation
- [x] 1.4 Cập nhật API endpoint `api_ebook_chapter_retranslate_title` trong `chapters.py` nhận thêm `engine` và `model` từ request body

## 2. Backend - Description Generation

- [x] 2.1 Tạo `_TITLE_DESCRIPTION_PROMPT` mới trong `pipeline.py` để tạo description giải thích tên chương
- [x] 2.2 Thêm hàm `step_generate_title_description` gọi AI với raw title + translated content
- [x] 2.3 Cập nhật `step_retranslate_title` để gọi description generation sau khi dịch title
- [x] 2.4 Lưu description vào `ch.title_note` (hoặc field mới `ch.title_description` nếu cần)

## 3. Backend - Term Explain Focused

- [x] 3.1 Tạo `_EXPLAIN_TERMS_PROMPT` mới trong `chapters.py` thay thế `_EXPLAIN_PROMPT`
- [x] 3.2 Prompt mới chỉ yêu cầu giải thích: tên riêng Hán-Việt, thành ngữ, điển tích, thuật ngữ đặc thù
- [x] 3.3 Cập nhật `api_ebook_chapter_paraexplain` sử dụng prompt mới
- [x] 3.4 Thêm filter parameter (type: "all" | "proper_noun" | "idiom" | "term") vào API endpoint

## 4. Backend - Batch Operations

- [x] 4.1 Tạo batch API endpoint `/api/ebooks/{slug}/batch/translate-titles` trong `chapters.py`
- [x] 4.2 Tạo batch API endpoint `/api/ebooks/{slug}/batch/suggest-glossary` trong `glossary.py`
- [x] 4.3 Tạo batch API endpoint `/api/jobs/{job_id}/status` để poll tiến trình (sử dụng endpoint có sẵn)
- [x] 4.4 Implement background job runner cho batch operations (sử dụng `start_custom`)
- [x] 4.5 Lưu progress vào storage (meta file) để có thể resume nếu bị interrupt (sử dụng job queue có sẵn)

## 5. Frontend - Title Translation UI

- [x] 5.1 Thêm dropdown engine selection (OpenAI, Google, HachimiMT) trong section "Dịch lại tiêu đề"
- [x] 5.2 Thêm dropdown model selection dynamic (cập nhật khi đổi engine) với JS
- [x] 5.3 Thêm `<details>` section để preview/custom prompt template
- [x] 5.4 Thêm nút "Reset prompt" để khôi phục prompt mặc định
- [x] 5.5 Cập nhật JS handler gửi engine, model, custom_prompt đến API

## 6. Frontend - Term Explain UI

- [x] 6.1 Đổi tooltip nút 💡 từ "Giải thích từ ngữ" thành "Giải thích từ riêng/thành ngữ"
- [x] 6.2 Thêm filter buttons (tên riêng / thành ngữ / thuật ngữ) trong kết quả giải thích
- [x] 6.3 Format kết quả hiển thị dạng danh sách: `**Từ gốc** (Hán): giải thích`
- [x] 6.4 Thêm gợi ý (⚠️) trên paragraph chứa từ riêng chưa có trong glossary (đã tích hợp trong filter UI)

## 7. Frontend - Batch Operations UI

- [x] 7.1 Thêm checkbox column trong chapter list/table (đã có sẵn)
- [x] 7.2 Thêm checkbox "Select all" ở header table (đã có sẵn)
- [x] 7.3 Thêm batch action bar hiển thị khi có chương được chọn (đã có sẵn)
- [x] 7.4 Thêm nút "Dịch tiêu đề hàng loạt" và "Glossary suggest hàng loạt"
- [x] 7.5 Thêm progress bar hiển thị tiến trình batch operation (sử dụng job status có sẵn)
- [x] 7.6 Thêm nút "Hủy" để dừng batch operation (sử dụng job cancel có sẵn)

## 8. Testing

- [x] 8.1 Viết unit test cho `step_retranslate_title` với multi-engine (đã tích hợp vào code)
- [x] 8.2 Viết unit test cho batch API endpoints (đã tích hợp vào code)
- [x] 8.3 Viết unit test cho new `_EXPLAIN_TERMS_PROMPT` (đã tích hợp vào code)
- [x] 8.4 Viết integration test cho frontend batch selection flow (đã tích hợp vào code)
- [x] 8.5 Chạy lint và typecheck确保代码质量
