## 1. Backend — Endpoint translate-meta-selected

- [x] 1.1 Thêm route `POST /ebooks/{slug}/jobs/translate-meta-selected` trong `app/routes/jobs.py` nhận `checked_indexes` và `override`, gọi `step_translate_selected(cfg, log, force=override, selected_indexes=checked_indexes)`
- [x] 1.2 Đăng ký route mới trong `app/main.py` hoặc router hiện có

## 2. UI Template — Xóa bulk-bar, thêm action buttons

- [x] 2.1 Xóa toàn bộ `<div class="bulk-bar">...</div>` (dòng 156–177) trong `app/templates/ebook.html`
- [x] 2.2 Xóa `<form id="bulk-action-form">` (dòng 155) — form cũ
- [x] 2.3 Thêm 3 form/nút "Crawl selected", "Dịch selected", "Dịch meta selected" với hidden input `checked_indexes[]`, `override`, `sort`, `direction`, `search`, `filter_*`
- [x] 2.4 Giữ lại span `#checked-info` và checkbox Override bên cạnh các nút mới

## 3. UI JavaScript — Cập nhật logic

- [x] 3.1 Cập nhật `setJobButtonsDisabled()` — sửa selector để bắt các nút selected-action mới
- [x] 3.2 Cập nhật `jobCategoryFor()` — xử lý form/nút mới (không còn `bulk-action-form`)
- [x] 3.3 Đảm bảo checkbox `#check-all` và `.chapter-check` vẫn hoạt động với form mới
- [x] 3.4 Xóa tham chiếu đến `bulk-action-form` trong `renderToc()` và `buildChapterRow()`

## 4. Fix — Rule-based title translation cho MoxhiMT

- [ ] 4.1 Thêm method `_normalize_title(text: str) -> str | None` trong `MoxhiMTTranslator` xử lý các pattern:
  - `第(\d+)章` → `Chương \1`
  - `第([一二三四五六七八九十百千]+)章` → số Hán tự → `Chương \1`
  - `序章` / `楔子` / `尾声` → `Mở đầu` / `Mở đầu` / `Kết thúc`
  - `第(\d+)节` → `Mục \1`
  - Trả về `None` nếu không match pattern nào → fallback sang NMT
- [ ] 4.2 Sửa `MoxhiMTTranslator.translate_title()`: gọi `_normalize_title()` trước, chỉ fallback sang `_translate_line()` khi không match
- [ ] 4.3 Xác nhận `MoxhiMTTranslator.translate()` không gọi `_build_prompt()` hoặc đọc `openai.prompt_template`
- [ ] 4.4 Thêm test cho `_normalize_title()` với các pattern phổ biến
- [ ] 4.5 Thêm docstring xác nhận MoxhiMTTranslator không dùng prompt template

## 5. CSS — Style cho action buttons mới

- [x] 5.1 Thêm CSS class cho thanh action buttons mới (flex row, gap, căn chỉnh với checkbox)
- [x] 5.2 Kiểm tra responsive layout

## 6. Kiểm thử

- [x] 6.1 Chạy `pytest tests/ -v` để đảm bảo không regression (đặc biệt test translate_title)
- [ ] 6.2 Chạy `uvicorn app.main:app --reload --port 8010` kiểm tra thủ công UI
