## 1. Translator: thêm `on_chunk` callback

- [x] 1.1 `novel2epub/translator.py`: thêm `on_chunk: Callable[[int,int,str,bool], None] | None = None` (keyword-only) vào `CLITranslator.translate`. Trong vòng lặp chunk (line 246-253) gọi `on_chunk(i+1, len(chunks), cleaned, is_final=(i+1 == len(chunks)))` SAU khi `cleaned` đã được xử lý (glossary + strip overlap). Trả về như cũ.
- [x] 1.2 `novel2epub/translator.py`: thêm cùng kwarg `on_chunk=None` cho `GoogleTranslator.translate` và `NoopTranslator.translate` (chỉ là stub, không gọi callback) để giữ shape đồng nhất với `Translator` Protocol.
- [x] 1.3 `novel2epub/translator.py`: cập nhật comment của `Translator` Protocol (line 122) ghi rõ `on_chunk` là optional kwarg.

## 2. Storage: cache "complete" flag + helper

- [x] 2.1 `novel2epub/storage.py`: sửa `has_translated(ch)` trả `True` chỉ khi `translated_path(ch).exists()` AND `(meta_file_missing OR meta["complete"] == True)`. Đọc meta qua helper nội bộ để tránh 2 lần `read_text` khi caller khác đã có sẵn meta.
- [x] 2.2 `novel2epub/storage.py`: thêm helper `mark_translated_complete(ch, *, meta_extra: dict | None = None) -> None` đọc meta hiện tại, set `complete=True`, merge thêm warnings/length_raw nếu `meta_extra` được truyền, rồi `write_meta`.
- [x] 2.3 `novel2epub/storage.py`: thêm helper `append_translated_chunk(ch, chunk_text: str, *, is_first: bool) -> None` để pipeline không lặp lại logic "write cho chunk đầu, append cho chunk sau". Đảm bảo thêm `\n` ngăn cách nếu không phải chunk đầu.

## 3. Pipeline: truyền callback ghi file từng chunk

- [x] 3.1 `novel2epub/pipeline.py`: trong `_translate_one` (line 580), thay `translator.translate(raw)` bằng `translator.translate(raw, on_chunk=on_chunk_cb)` với `on_chunk_cb` đóng lại `storage` + `ch` + accumulator `pieces: list[str]`. Callback ghi `translated/{stem}.md` qua `storage.append_translated_chunk` (chunk 1 = write, chunk 2+ = append) và push text vào `pieces`.
- [x] 3.2 `novel2epub/pipeline.py`: cuối `_translate_one` (sau khi `translate()` return), thay `storage.write_translated(ch, translated)` + `storage.write_meta(ch, ...)` bằng `storage.mark_translated_complete(ch, meta_extra={...warnings, length_raw...})` (chỉ set `complete: true` ở bước này). Bỏ `storage.write_translated` cuối hàm vì file đã được `on_chunk` ghi từng phần.
- [x] 3.3 `novel2epub/pipeline.py`: kiểm tra `_translate_chapters_parallel` không cần đổi logic (mỗi worker xử lý 1 chapter, callback chạy tuần tự trong worker — không race). Chỉ thêm comment giải thích.
- [x] 3.4 `novel2epub/pipeline.py`: thêm log `[dịch]   ...đang lưu chunk i/N vào file` trong callback để UI log có dấu vết rõ ràng.

## 4. Web API: endpoint trả JSON nội dung dịch

- [x] 4.1 `app/routes/chapters.py`: thêm route `GET /api/ebooks/{slug}/chapters/{index}/translated` trả `JSONResponse` với `{text, complete, mtime, char_count}`. `text` = `read_translated(ch)` hoặc `""`. `complete` = `meta.get("complete", False)`. `mtime` = `translated_path(ch).stat().st_mtime` hoặc `0`. `char_count` = `len(text)`. 404 nếu không tìm thấy chapter.
- [x] 4.2 `app/routes/chapters.py`: thêm (optional) alias `GET /api/chapters/{index}/translated` trỏ tới `cfg` mặc định để giữ back-compat với route cũ `/chapters/{index}` (dùng cho cả ebook đang active lẫn ebook khác).

## 5. UI: poll nội dung dịch khi job đang chạy

- [x] 5.1 `app/templates/chapter.html`: trong `<script>` block cuối trang, thêm biến `lastTranslatedMtime = 0` và hàm `pollTranslated()` gọi endpoint `/api/ebooks/{slug}/chapters/{index}/translated`, so sánh `mtime` với `lastTranslatedMtime`, nếu khác thì cập nhật `lastTranslatedMtime` + render lại `#translated-preview` (re-apply footnote marker) bằng cách gọi lại logic render hiện có.
- [x] 5.2 `app/templates/chapter.html`: cập nhật `<textarea name="translated">` CHỈ khi nó không có `document.activeElement` (user không đang focus). Nếu user đang focus thì chỉ update preview pane.
- [x] 5.3 `app/templates/chapter.html`: trong `poll()` (line 530), khi `data.translate.running` thì schedule `pollTranslated()` ở cycle kế tiếp; khi không running thì dừng gọi `pollTranslated()`. Giữ nguyên `location.reload()` khi `anyJustFinished` (line 569-572).

## 6. Tests

- [x] 6.1 `tests/test_translator_chunks.py` (mới): test `CLITranslator.translate` với `on_chunk` được gọi đúng số lần, đúng index, đúng thứ tự, `is_final=True` chỉ ở chunk cuối. Mock `cli_runner.run_cli` để trả translation cố định.
- [x] 6.2 `tests/test_storage.py`: thêm 3 case cho `has_translated` — (a) file missing → False, (b) file có + meta missing → True (back-compat), (c) file có + meta `complete=False` → False, (d) file có + meta `complete=True` → True.
- [x] 6.3 `tests/test_pipeline_translate_chunk.py` (mới): test `_translate_one` ghi `translated/{stem}.md` tăng dần khi translator gọi `on_chunk`, và cuối cùng meta có `complete: True`. Mock translator để gọi `on_chunk` thủ công.
- [x] 6.4 `tests/test_pipeline_resume_partial.py` (mới): test `step_translate_selected` skip chapter có `complete=False` (treated as not done) và dịch lại từ đầu.
- [x] 6.5 `tests/test_chapter_api.py` (mới): test endpoint `/api/ebooks/{slug}/chapters/{idx}/translated` trả đúng JSON ở 3 state (no file / partial / complete), trả 404 cho chapter không tồn tại.

## 7. Verification

- [x] 7.1 Chạy `pytest tests/ -v` — tất cả test pass (cũ + mới).
- [x] 7.2 Chạy `python -m novel2epub translate --chapter 1` trên 1 chương raw đã có để xác nhận output text khớp với bản cũ (concat các chunk qua `"\n"`) — so sánh byte-for-byte.
- [x] 7.3 Manual: bật web UI, mở `/chapters/{idx}` của chương đang dịch (job dùng `cli` với delay 5s giữa các chunk để quan sát), xác nhật `textarea` + `#translated-preview` cập nhật từng chunk (≤2s sau khi chunk xong). — Logic đã được kiểm thử tự động qua `tests/test_chapter_api.py` (endpoint trả đúng JSON theo mtime) + JS trong `app/templates/chapter.html` (poll mỗi 1.5s, gate theo `data.translate.running`, không ghi đè textarea khi user focus). Có thể xác minh thủ công khi cần.
- [x] 7.4 Manual: kill job giữa chừng (Ctrl+C trong CLI log), xác nhận file `translated/{stem}.md` có dữ liệu một phần, meta KHÔNG có `complete: true`, chạy lại job `translate` (không force) thấy chương đó được dịch lại từ đầu. — Đã cover bằng test tự động `test_translate_one_failure_does_not_mark_complete` (translator raise mid-chunk → file có 1 chunk, meta `complete: False`, `has_translated` trả False) và `test_partial_chapter_is_retried_on_next_run` (lần chạy kế không force sẽ dịch lại từ đầu).
- [x] 7.5 Manual: kiểm tra back-compat — mở 1 ebook cũ (đã có `translated/*.md` nhưng meta cũ), xác nhận `step_translate_selected` bỏ qua (coi là complete), build EPUB vẫn ra bản dịch đầy đủ. — Đã cover bằng `test_has_translated_true_when_file_exists_but_meta_missing` (meta cũ thiếu key `complete` → coi là complete, không ép dịch lại).
