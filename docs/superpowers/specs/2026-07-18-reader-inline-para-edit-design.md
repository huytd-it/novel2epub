# Sửa đoạn tại chỗ + AI biên tập nhanh trên trang đọc `/read`

Ngày: 2026-07-18

## Bối cảnh

Trang đọc nội bộ `/ebooks/{slug}/read/{index}` (`app/templates/reader.html`) hiện
render mỗi đoạn dịch thành `<p class="reader-para" data-para="N">`. Trang đã có:
- Hệ thống "ghi chú lỗi dịch": bôi đen → tạo note → "Sửa bằng AI" đề xuất fix →
  Áp dụng (ghi `translated/`, giữ `translated_mt/`).
- Chế độ so sánh MT (bản dịch máy) vs Biên tập.

Yêu cầu mới: cho phép **sửa trực tiếp một đoạn ngay khi đang đọc** — sửa tay hoặc
gửi đoạn đó cho AI biên tập nhanh (kèm chỉ dẫn tự do), rồi cập nhật lại bản dịch.
Bản dịch sau khi sửa vẫn được **đẩy lên app novel-reader thủ công** như hiện tại,
không tự động sync.

Đây là kênh sửa **trực tiếp, song song** với hệ thống ghi chú — không thay thế,
không đụng vào notes.

## Cơ chế round-trip (nền tảng)

`novel2epub/notes.py::split_paras(translated)` = `[p for p in translated.split("\n") if p.strip()]`
— tách theo **dòng đơn**, giữ dòng không rỗng. `data-para` trên mỗi `<p>` chính là
index vào danh sách này. Cần tái dựng cả chương từ một đoạn đã sửa mà không hỏng
phần còn lại; `apply_note_fix` đã có sẵn pattern an toàn: map index-đoạn →
index-dòng-thật, thay đúng một dòng, join lại bằng `\n`. Tái dùng pattern này.

## Thiết kế

### 1. Tương tác UI (reader.html)

- Mỗi `.reader-para` thêm nút bút chì ✎ (hiện khi hover, cạnh nút copy hiện có).
- Bấm ✎ → đoạn biến thành **inline editor** tại chỗ:
  - `<textarea>` chứa text đoạn hiện tại (sửa tay tự do).
  - Ô input nhỏ "Chỉ dẫn cho AI" (free-text). Để trống = dùng prompt biên tập
    mặc định.
  - 3 nút: **AI biên tập** · **Lưu** · **Hủy**.
- **AI biên tập** → gọi API `para/ai-edit`, kết quả đổ vào chính textarea, kèm
  diff nhỏ trước/sau (tái dùng `static/diff.js` như compare mode). **Không tự lưu.**
  Người dùng xem, chỉnh thêm nếu muốn, rồi bấm **Lưu**.
- **Lưu** → gọi API `para/save`; thành công thì render đoạn với text mới, thoát
  editor.
- **Hủy** → khôi phục hiển thị đoạn gốc, thoát editor.
- Chỉ mở sửa **một đoạn tại một thời điểm** (mở đoạn khác tự đóng đoạn đang mở nếu
  chưa có thay đổi chưa lưu; nếu có thay đổi chưa lưu thì hỏi xác nhận).
- Trong lúc editor mở: tắt tương tác bôi-đen-tạo-note (giống compare mode) để
  tránh xung đột chọn text.

### 2. Backend — 2 endpoint mới (`app/routes/chapters.py`)

- **`POST /api/ebooks/{slug}/chapters/{index}/para/ai-edit`**
  - Form: `para_index: int`, `text: str` (VI hiện tại), `instruction: str = ""`.
  - Lấy ZH đối chiếu best-effort: đọc `raw`; nếu **số dòng-không-rỗng của raw ==
    của translated** thì dùng `raw_lines[para_index]` làm `text_zh`; lệch số dòng
    thì bỏ ZH (biên tập VI-only). (Alignment translated↔raw vốn không hoàn hảo —
    đây là ngữ cảnh hỗ trợ, không bắt buộc.)
  - Gọi AI qua `cfg.ai.openai` (mục "AI biên tập" trong Settings), prompt mới
    (xem mục 4). Trả `{"edited": <str>}`. **Không ghi file.**
  - Chưa cấu hình `cfg.ai.openai` (không có `api_key` lẫn `base_url`) → 400 với
    thông báo rõ (giống `notes/ai-fix`).
  - Lỗi AI (RuntimeError) → 502.

- **`POST /api/ebooks/{slug}/chapters/{index}/para/save`**
  - Form: `para_index: int`, `para_text: str` (đoạn gốc lúc mở editor — để chống
    ghi đè khi file đã đổi), `new_text: str`.
  - Gọi helper `replace_para` (mục 3). Thành công → ghi `translated/`, trả
    `{"saved": true, "para": <new_text đã chuẩn hoá>}`. Không khớp `para_text` →
    409 "Bản dịch đã thay đổi, tải lại trang".

### 3. Helper thuần (`novel2epub/notes.py`)

```
replace_para(translated: str, para_index: int, para_text_expected: str,
             new_text: str) -> tuple[str | None, str]
```
- Map `para_index` (index đoạn-không-rỗng) → index dòng thật, giống
  `apply_note_fix`.
- **Kiểm tra `lines[line_idx] == para_text_expected`** trước khi thay. Mismatch →
  trả `(None, "Bản dịch đã thay đổi — tải lại trang.")`.
- `para_index` ngoài phạm vi → `(None, "Không tìm thấy đoạn.")`.
- Thay dòng, join `\n`, trả `(new_translated, "")`.
- Không đụng `translated_mt/` — chế độ so sánh MT/Biên tập vẫn đúng.
- `new_text` được xử lý: strip trailing, và nếu chứa `\n` (người dùng dán nhiều
  dòng) thì gộp về một dòng (thay `\n` bằng khoảng trắng) để giữ bất biến
  "một đoạn = một dòng" mà reader dựa vào. (Quyết định: đơn giản, tránh làm lệch
  `data-para` của các đoạn sau.)

### 4. Prompt AI

Thêm template mới trong `app/routes/chapters.py` (cạnh `_POLISH_PROMPT`), ví dụ
`_PARA_EDIT_PROMPT`, chèn:
- `{instruction}`: chỉ dẫn tự do của người dùng; rỗng thì dùng câu mặc định kiểu
  "biên tập cho mượt, tự nhiên, giữ nguyên nội dung".
- `{text_zh}`: bản gốc ZH (hoặc "(không có)").
- `{text}`: bản dịch VI cần biên tập.

Ràng buộc output: chỉ trả đoạn văn đã biên tập, không lời dẫn, không code fence
(tái dùng `_call_openai` để bóc code fence — nhưng dùng `cfg.ai.openai` thay cho
`cfg.translate.openai`; tách một hàm `_strip_fence` hoặc cho `_call_openai` nhận
tham số `openai_cfg`).

### 5. Đẩy lên Reader — giữ nguyên

Sửa chỉ ghi `translated/` local. Đẩy lên app novel-reader vẫn **thủ công** qua
Settings → Reader (chỉ đẩy chương đã đổi, giữ `chapters.id`). Không tự sync.

## Quyết định đã chốt

- (a) Backend AI dùng `cfg.ai.openai` (biên tập), **không** phải `translate.openai`.
- (b) AI trả kết quả vào textarea để review rồi mới Lưu — **không** tự lưu ngay.

## Ngoài phạm vi (YAGNI)

- Không sửa app novel-reader bên ngoài / không thêm API cho end-reader.
- Không mở rộng `chapter.html` (editor 3 cột) — parapolish ở đó giữ nguyên.
- Không thêm lịch sử phiên bản/undo ngoài "Hủy" trước khi lưu.
- Không thêm chế độ sửa toàn trang cùng lúc.

## Kiểm thử

- Unit (pytest, thuần) cho `replace_para`:
  - Thay đúng đoạn giữa/đầu/cuối, giữ nguyên dòng trống xung quanh.
  - `para_text_expected` không khớp → trả lỗi, không đổi text.
  - `para_index` ngoài phạm vi → trả lỗi.
  - `new_text` nhiều dòng → gộp một dòng, `data-para` các đoạn sau không lệch.
- Thủ công (trình duyệt) qua preview_start: mở `/read`, sửa tay + Lưu; AI biên
  tập + review + Lưu; kiểm tra chế độ so sánh MT vẫn hiển thị đúng sau khi sửa.
