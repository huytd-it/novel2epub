## Why

Khi dịch một chương dài bị tách thành nhiều chunk (vd. 4 đoạn ~700 ký tự), translator
hiện chỉ trả về bản dịch đầy đủ khi **chunk cuối** hoàn tất, rồi `_translate_one`
mới ghi một lần vào `translated/{stem}.md`. Hai hệ quả:

1. Người dùng mở trang chương giữa chừng job dịch chỉ thấy textarea trống / dữ liệu
   cũ — không có phản hồi trực quan rằng "đoạn 1/4, 2/4… đã xong".
2. Nếu job bị chết giữa chừng (CLI timeout, OOM, mất mạng…), toàn bộ bản dịch
   của chương đó mất trắng vì chưa bao giờ được ghi ra đĩa, dù vài chunk đầu
   đã thành công.

Đồng thời UI preview hiện `location.reload()` đúng 1 lần khi job vừa kết thúc
(`app/templates/chapter.html:570`) — không có cơ chế poll nội dung `translated/`
trong khi job đang chạy, nên kể cả khi file đã được ghi, người dùng vẫn không
thấy cho tới lúc job xong.

## What Changes

- Translator (`CLITranslator`, `GoogleTranslator`) nhận thêm callback
  `on_chunk(index, total, chunk_text, is_final)`. Sau khi mỗi chunk được dịch
  xong, callback được gọi **trước khi** dịch chunk kế tiếp, với phần text đã
  dịch (đã clean + áp glossary).
- Pipeline (`_translate_one` + `step_translate_selected`) truyền callback ghi
  `translated/{stem}.md` từng chunk một (append sau khi tạo file rỗng cho chunk
  đầu). Khi chunk cuối xong, ghi meta với cờ `complete: true` để phân biệt với
  partial.
- `Storage.has_translated()` được cập nhật để coi chương "đã dịch xong" chỉ khi
  file `translated/{stem}.md` tồn tại **và** `meta["complete"] == true` (giữ
  back-compat: meta cũ không có key này được coi là complete, tránh phải dịch
  lại thư viện đã có).
- JobRunner ghi log cảnh báo khi `step_translate_selected` kết thúc nhưng để sót
  chapter có `translated/{stem}.md` không có `complete: true` (partial do job
  chết giữa chừng) — và bỏ qua chúng trong lần chạy kế tiếp nếu `force=False`.
- Thêm endpoint `GET /api/ebooks/{slug}/chapters/{index}/translated` trả JSON
  `{text, complete, mtime, char_count}`. Trang `chapter.html` trong khi job
  translate đang chạy sẽ poll endpoint này (cùng chu kỳ 1.5s với status poll)
  và cập nhật `<textarea name="translated">` + `#translated-preview` khi nội
  dung thay đổi (so sánh theo `mtime` / độ dài).
- Cache: lần chạy tiếp theo `step_translate_selected` sẽ bỏ qua các chapter
  có `translated/{stem}.md` nhưng meta thiếu `complete: true` (xem
  `Storage.has_translated` ở trên). Người dùng chọn "Dịch lại" (force) để dịch
  đè.

**BREAKING**: Không có API public bị thay đổi chữ ký. `Translator.translate()`
giữ nguyên signature `(text) -> str`; `on_chunk` là keyword-only optional
(`on_chunk=None`). `Storage.has_translated()` thay đổi ngữ nghĩa cache một
cách tinh tế nhưng không phá callers.

## Capabilities

### New Capabilities

- `translate-chunk-streaming`: Translator chunk gọi callback sau mỗi chunk đã
  dịch, pipeline ghi `translated/{stem}.md` từng phần và đánh dấu complete khi
  xong. UI preview poll nội dung file đang dịch dở để cập nhật textarea + khung
  preview.

### Modified Capabilities

- (không có — không có spec nào hiện tại đụng tới translator/storage contract
  ở mức REQUIREMENT; `chapter-pagination` chỉ nói về crawler)

## Impact

- `novel2epub/translator.py`: thêm `on_chunk` param vào `CLITranslator.translate`
  (+ cùng tên cho `GoogleTranslator.translate`, `NoopTranslator.translate` để
  giữ Protocol đối xứng). Gọi callback trong vòng lặp chunk.
- `novel2epub/pipeline.py`: `_translate_one` truyền callback ghi file từng
  chunk; cuối cùng ghi meta với `complete: true` thay vì meta dùng để build
  warnings. Sửa `_translate_chapters_parallel`/`_translate_chapters_sequential`
  để callback dùng chung an toàn giữa nhiều luồng.
- `novel2epub/storage.py`: `has_translated` kiểm tra meta `complete`. Thêm
  helper `mark_translated_complete(ch)` để pipeline gọi cuối hàm. Cập nhật
  `read_meta` back-compat (meta cũ → coi như complete).
- `app/routes/chapters.py`: thêm `GET /api/ebooks/{slug}/chapters/{index}/translated`
  trả JSON. Có thể thêm phiên bản không slug để giữ back-compat với route cũ.
- `app/templates/chapter.html`: trong poll loop, khi status translate đang
  chạy thì fetch endpoint trên và cập nhật `textarea#translated-area` +
  `#translated-preview` (re-render footnote marker cơ bản) nếu `mtime` thay
  đổi. Khi job vừa kết thúc (`anyJustFinished`) vẫn reload như cũ.
- Tests: thêm test cho `CLITranslator.translate(on_chunk=...)` (mock CLI),
  test cho `Storage.has_translated` với meta complete/missing, test cho
  `_translate_one` ghi file progressive.
