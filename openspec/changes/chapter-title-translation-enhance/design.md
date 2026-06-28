## Context

Hiện tại chức năng "Dịch lại tiêu đề" (`step_retranslate_title`) chỉ hoạt động với OpenAI, sử dụng prompt `_RETRANSLATE_TITLE_PROMPT` cứng. Tính năng giải thích từ ngữ (`paraexplain`) dùng prompt `_EXPLAIN_PROMPT` giải thích toàn bộ nội dung đoạn văn, gây nhiễu khi người dùng chỉ muốn hiểu từ riêng/thành ngữ.

Giao diện chapter.html hiện có:
- Nút "Dịch lại tiêu đề" đơn giản (không chọn engine/model)
- Nút 💡 "Giải thích từ ngữ" (giải thích cả đoạn)
- Form glossary suggest (chỉ 1 chương)

## Goals / Non-Goals

**Goals:**
- Cho phép chọn translate engine và model khi dịch tiêu đề
- Thêm option tạo description giải thích tên chương
- Thêm preview/custom prompt template
- Điều chỉnh giải thích từ ngữ tập trung vào tên riêng, thành ngữ
- Hỗ trợ batch operations cho nhiều chương

**Non-Goals:**
- Thay đổi backend translation (giữ nguyên existing backends)
- Thêm engine mới (chỉ hỗ trợ OpenAI, Google, HachimiMT hiện có)
- Sửa đổi cấu trúc storage/chapter manifest

## Decisions

### 1. UI cho engine/model selection

**Quyết định**: Thêm dropdown engine và model ngay trong section "Dịch lại tiêu đề", thay vì tạo form mới riêng biệt.

**Lý do**:
- Giữ nguyên UX hiện tại (người dùng quen với vị trí)
- Model dropdown update dynamic khi chọn engine (JS)
- Có thể dùng `<template>` hoặc `<datalist>` cho model suggestions

**Thay thế**: Tạo modal/popup riêng → phức tạp hơn, thừa vì chỉ cần 2 dropdown.

### 2. Prompt preview/custom

**Quyết định**: Thêm collapsible section `<details>` chứa textarea prompt template, có nút "Reset" và "Dịch lại" ngay trong section.

**Lý do**:
- `<details>` tiết kiệm không gian, chỉ mở khi cần
- Prompt mặc định được render từ server (template variable)
- Custom prompt gửi kèm request body

### 3. Backend cho multi-engine title translation

**Quyết định**: Mở rộng `step_retranslate_title` nhận thêm `engine` parameter. Nếu engine != openai, chuyển sang dùng translator backend tương ứng (Google/HachimiMT) nhưng với prompt đơn giản hơn (không context-based).

**Lý do**:
- Google/HachimiMT không hỗ trợ prompt-based → chỉ dịch literal
- Có thể thêm fallback message khi user chọn engine không phù hợp

### 4. Batch operations

**Quyết định**: Thêm batch API endpoints mới (`/api/ebooks/{slug}/batch/translate-titles`, `/api/ebooks/{slug}/batch/suggest-glossary`) chạy background job. UI thêm checkbox column trong chapter list và batch action bar.

**Lý do**:
- Tách riêng batch endpoints để không ảnh hưởng single-chapter endpoints
- Background job để không block UI
- Có thể mở rộng cho các thao tác khác sau

### 5. Term explain focused

**Quyết định**: Tạo `_EXPLAIN_TERMS_PROMPT` mới thay thế `_EXPLAIN_PROMPT`. Prompt mới chỉ yêu cầu: "Liệt kê các từ riêng Hán-Việt, thành ngữ, điển tích trong đoạn văn. Giải thích ngắn gọn từng từ. KHÔNG tóm tắt nội dung."

**Lý do**:
- Giữ nguyên API endpoint (`/paraexplain`) và UI flow
- Chỉ thay đổi prompt内容
- Thêm filter UI cho kết quả (tên riêng / thành ngữ / thuật ngữ)

## Risks / Trade-offs

- **[Risk]** Google/HachimiMT không support prompt → **Mitigation**: Hiển thị warning khi chọn engine không hỗ trợ context-based translation
- **[Risk]** Batch operations có thể fail giữa chừng → **Mitigation**: Lưu progress vào meta, có thể resume
- **[Risk]** Custom prompt có thể gây lỗi nếu format sai → **Mitigation**: Validate prompt trước khi send, có nút reset về mặc định
