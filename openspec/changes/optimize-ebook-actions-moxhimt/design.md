## Context

Giao diện `ebook.html` hiện dùng 1 bulk-bar với dropdown action + targeting mode (checked/range) + range_start/range_end inputs. Khi người dùng muốn crawl/dịch các chương đã tick, phải: tick dòng → chọn action → chọn target → bấm Chạy. Luồng này rườm rà.

Backend MoxhiMT (CTranslate2 + SentencePiece) đã hoạt động không dùng prompt — `MoxhiMTTranslator.translate()` nhận text gốc, tokenize, chạy inference, detokenize. Không có `_build_prompt()`. Endpoint translate-meta hiện tại dùng chung `step_translate_meta()` gọi `translator.translate_title()` → với moxhimt, `translate_title()` gọi `self.translate(text)` — không dùng prompt.

## Goals / Non-Goals

**Goals:**
- Bỏ bulk-bar, thay bằng các nút riêng: "Crawl selected", "Dịch selected", "Dịch meta selected"
- Các nút chỉ hoạt động với dòng đã tick (checked_indexes), không còn range mode
- Thêm nút "Dịch metadata (AI)" riêng trong action group meta-card
- Xác nhận MoxhiMTTranslator không dùng prompt qua kiểm tra code
- Backend: endpoint mới `POST /ebooks/{slug}/jobs/translate-meta-selected` tái sử dụng `step_translate_selected` với `force=True`
- Giữ nguyên các nút row-action hiện có (Crawl/Dịch trên từng dòng)

**Non-Goals:**
- Không thay đổi cơ chế crawl console, crawl-range, fetch-toc
- Không thay đổi pipeline (`step_crawl_selected`, `step_translate_selected`)
- Không thay đổi `MoxhiMTTranslator` code
- Không thêm chức năng mới ngoài translate-meta-selected

## Decisions

### 1. Thay bulk-bar bằng 3 form/nút riêng
- Mỗi nút là một `<form method="post">` riêng với `action` khác nhau, cùng gửi `checked_indexes[]`
- `setJobButtonsDisabled()` cần cập nhật selector để bắt các nút mới
- `jobCategoryFor()` cần cập nhật vì không còn `bulk-action-form`

### 2. Endpoint translate-meta-selected
- `POST /ebooks/{slug}/jobs/translate-meta-selected`
- Nhận `checked_indexes: list[int]`
- Gọi `step_translate_selected(cfg, log, force=True, selected_indexes=checked_indexes)` — `force=True` để dịch lại metadata (title/author/description) cho cả chương đã dịch
- `_translate_meta_inplace()` được gọi trong `step_translate_selected()` trước khi dịch nội dung → metadata luôn được cập nhật

### 3. Xác nhận MoxhiMT không dùng prompt + rule-based title normalization
- `MoxhiMTTranslator.translate()` dòng 349–600: không có `_build_prompt()`, không đọc `openai.prompt_template`
- Bug xác nhận: `translate_title("第1章")` → NMT hallucinate ra văn bản vô nghĩa (dài 900+ ký tự)
- Giải pháp: thêm `_normalize_title()` xử lý pattern phổ biến bằng regex trước khi fallback sang NMT:
  - `第(\d+)章` → `Chương \1`
  - `第[一二三十...]+章` → convert Hán tự → số → `Chương N`
  - `序章` / `楔子` → `Mở đầu`
  - Không match → fallback `_translate_line()`

### 4. Bỏ targeting_mode và range_* khỏi UI
- UI chỉ dùng `targeting_mode=checked` mặc định
- Các hidden input range_* có thể bỏ
- Backend `chapter-action` endpoint vẫn giữ các tham số cho back-compat

### 5. UI layout
```
Trước bulk-bar:
  [checkbox] Action: [Crawl ▼] Target: [Checked ▼] Từ [ ] Đến [ ] ☐ Override
  [Đã tick 0 chương] [Chạy]

Sau:
  [Crawl selected] [Dịch selected] [Dịch meta selected] ☐ Override
  [Đã tick 0 chương]
```

## Risks / Trade-offs

- **Xóa range mode**: Người dùng mất khả năng chọn phạm vi số (không tick). Nếu cần range, vẫn có thể dùng `input[type=checkbox]` select-all hoặc tick thủ công. Hoặc giữ lại crawl-range panel cho use-case đặc thù.
- **Nút trùng với row-action**: Row-action trên mỗi dòng vẫn giữ — selected-action là batch, row-action là single. Không xung đột.
- **Endpoint mới cần auth**: Đã có job system, không cần thêm.
- **`force=True` trong translate-meta-selected**: Nếu người dùng tick chương đã dịch, nó sẽ dịch lại. Có checkbox Override riêng để quyết định.
