# Web chat — xuất/nhập dữ liệu cho AI trong EbookPage

Ngày: 2026-08-17
Trạng thái: đề xuất thiết kế, chưa duyệt

## 1. Bối cảnh

Backend đã có sẵn đường xuất/nhập biên tập thủ công qua AI: `POST /api/ebooks/{slug}/batch/export` xuất khối Markdown (`## idx:N` + prompt + glossary), `POST /batch/import` nhập lại kết quả với preview/confirm. EbookPage chưa có UI nào dùng chúng — chỉ có "Xuất CSV mục lục".

Người dùng muốn, ngay trong EbookPage: xuất một khối Markdown gồm **chương đã chọn + glossary detect trong các chương đó** cùng một prompt, dán vào AI web chat, rồi dán kết quả về để nhập. Đồng thời chọn được **prompt profile** — chọn giữa các prompt hiện có (không dựng hệ thống profile mới).

## 2. Phạm vi

### Thuộc phạm vi

- Backend: `_do_export` nhận `prompt_profile` (`config` | `static` | `glossary`), glossary **luôn** lọc theo chương đã chọn trong đường xuất web chat.
- Frontend: nút "Web chat" trong `BatchBar` của `EbookPage.tsx` → modal Xuất/Nhập.
- Tests cho hành vi mới.

### Không thuộc phạm vi

- Hệ thống prompt profile lưu trữ/đặt tên — chỉ chọn giữa prompt hiện có.
- Đường `batch/translate` (job queue) — giữ nguyên hành vi config-driven.
- GlossaryPage / IdiomsPage — không đổi.
- Đổi format export (`bulk_transfer.py`) — không đụng.

## 3. Backend — `app/routes/chapters.py`

`_do_export(slug, indexes, source, prompt_profile="config")`:

| source | prompt_profile | Prompt | Nội dung |
|---|---|---|---|
| `raw` | `config` | `build_translate_prompt_from_cfg(cfg)` | chương raw + glossary + nhân vật (hành vi hiện tại) |
| `raw` | `static` | `TRANSLATE_PROMPT` | như trên |
| `translated` | (bỏ qua) | `EDIT_PROMPT` | chương translated + glossary + nhân vật |
| `glossary` | (bỏ qua) | `GLOSSARY_CLEAN_PROMPT` | **chỉ** khối `GLOSSARY:` — các mục detect trong chương đã chọn |

- Glossary trong đường xuất web chat **luôn** được lọc bằng `_filter_glossary_for_batch(glossary, items)` — bỏ điều kiện `cfg.translate.glossary_filter`. Người dùng yêu cầu rõ "dữ liệu detect glossary có trong chương".
- Với `source="glossary"`, items lấy từ nội dung **translated** (glossary là về thuật ngữ bản dịch); chương chưa dịch bị skip. Trả về `{text, count, source}`.
- Endpoint `GET /export` và `POST /batch/export` nhận thêm field `prompt_profile` (mặc định `"config"`).
- `_EXPORT_PROMPTS` mở rộng để nhận `source="glossary"` qua route validation.

## 4. Frontend — `EbookPage.tsx`

- `icons.tsx`: thêm `PiChats as IconChat`.
- `BatchBar`: thêm nút **"Web chat"** (mở modal, tắt khi không chọn chương — đặt cạnh "Chuẩn hóa TOC").
- Component cục bộ `WebChatDialog` trong `EbookPage.tsx`, 2 tab:

### Tab Xuất

- Dropdown **Prompt profile**:
  - `Dịch — Config truyện` → `source=raw&prompt_profile=config`
  - `Dịch — Prompt mặc định` → `source=raw&prompt_profile=static`
  - `Biên tập bản dịch` → `source=translated`
  - `Dọn glossary` → `source=glossary`
- Đổi profile → gọi export → textarea readonly hiện khối Markdown + dòng báo `skipped` (chương thiếu raw/dịch).
- Nút "Sao chép" (clipboard).

### Tab Nhập

- Profile chương: dán kết quả AI → "Xem trước" → `POST /batch/import` `mode=preview` → hiện summary (matched / unknown / missing / extra / glossary_new) → "Xác nhận" → `mode=confirm` → toast + `onDone` (refresh).
- Profile "Dọn glossary": dán khối `GLOSSARY:` → nút "Nhập vào glossary" → `POST /glossary/import` → toast (giống GlossaryPage). Không có preview.
- Tab Nhập nhớ profile đã xuất; nếu người dùng đổi profile ở tab Xuất thì nhập theo profile mới.

## 5. Xử lý lỗi

- Export/import thất bại → hiện `error.message` bằng toast (pattern `ApiError` hiện có).
- Import preview 400 ("Không tìm thấy marker chương nào") → hiện thông báo trong modal, không đóng.

## 6. Test — `tests/test_bulk_transfer_api.py`

- `source=raw` + `prompt_profile=static` → văn bản chứa `TRANSLATE_PROMPT`, `prompt_profile=config` → prompt từ config.
- `source=glossary` → chỉ có khối `GLOSSARY:`, đúng các mục detect trong chương; chương chưa dịch bị skip; `count` đúng.
- Glossary luôn lọc theo chương đã chọn khi `glossary_filter=False`.

## 7. Rủi ro

| # | Rủi ro | Xử lý |
|---|---|---|
| 1 | Đổi hành vi lọc glossary làm khác đường cũ | Chỉ đổi trong `_do_export` khi gọi web chat; đường job `_run_batch_translate` giữ nguyên theo config |
| 2 | EbookPage.tsx đã 1117 dòng, thêm modal tăng thêm | Chấp nhận cho đúng phạm vi; modal là component cục bộ, tách file khi thực sự cần |
