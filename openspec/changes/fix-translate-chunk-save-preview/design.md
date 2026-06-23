## Context

`novel2epub` dịch sáng tiếng Việt theo pipeline: crawl raw → translate → build
EPUB. Bước `translate` chia chương dài thành nhiều chunk (mặc định ≤6000 ký tự,
overlap theo đoạn văn) để tránh prompt quá tải cho AI CLI. Hiện tại translator
chỉ trả về toàn bộ bản dịch khi chunk cuối xong, và `_translate_one` (`novel2epub/pipeline.py:580`)
ghi `translated/{stem}.md` đúng một lần ở cuối. Hai hậu quả đã nêu trong
proposal:

1. UI preview (`/chapters/{idx}`) đợi job kết thúc mới reload nên người dùng
   thấy textarea trống suốt thời gian dịch dù đã có dữ liệu hợp lệ trên RAM.
2. Job bị crash giữa chừng (timeout CLI, OOM, mất mạng) mất sạch thành quả vì
   chưa kịp flush xuống đĩa.

Trang `chapter.html` đã có poll loop 1.5s gọi `/api/status` (`app/templates/chapter.html:530`)
và `location.reload()` khi `anyJustFinished` (line 570) — có sẵn khung để
mở rộng thành "poll cả nội dung dịch".

## Goals / Non-Goals

**Goals:**

- Mỗi chunk dịch xong được ghi xuống `translated/{stem}.md` ngay, cho cả
  sequential và parallel pipeline.
- Lần chạy kế tiếp phân biệt được "dịch xong" (`complete: true`) với "dịch dở
  rồi job chết" (file có nhưng `complete` thiếu/`false`).
- UI preview tự cập nhật textarea + khung preview trong khi job đang chạy,
  không cần user F5 / click reload.
- Không phá back-compat: thư viện EPUB đã dịch (có file `translated/*.md` nhưng
  không có meta `complete`) vẫn được coi là hoàn tất.

**Non-Goals:**

- Không thay đổi logic chia chunk (`_split_into_chunks`) hay
  `_translate_chunk` (retry khi còn sót Hán).
- Không thêm partial-resume: nếu job chết giữa chừng, lần chạy kế sẽ dịch lại
  từ đầu, không ghép nối với phần đã có.
- Không đổi ngữ nghĩa cache ở các bước khác (crawl, build) — chỉ chạm
  `has_translated` cho bước translate.
- Không đổi `Translator` Protocol ở mức caller bắt buộc (vẫn là duck-typed
  method `translate(text)`); `on_chunk` chỉ là kwarg optional.
- Không thêm WebSocket / SSE: poll HTTP đơn giản đủ cho cadence 1.5s, khớp
  với poll status hiện có.

## Decisions

### D1. `on_chunk` là keyword-only callback, không phải event bus

`CLITranslator.translate(self, text: str, *, on_chunk: Callable[[int, int, str, bool], None] | None = None) -> str`.

- **Tại sao callback**: pipeline đã có quyền kiểm soát `Storage` và
  `Chapter`; truyền callable giữ coupling tại chỗ, không cần sinh event bus
  cho tính năng đơn lẻ.
- **Tại sao keyword-only**: tránh nhầm vị trí khi sau này thêm options
  (`on_chunk`, `on_retry`, ...); vẫn tương thích với mọi caller hiện tại
  (`translator.translate(text)` không đổi).
- **Tại sao truyền `chunk_text` riêng lẻ (không phải cả chương)**: pipeline
  cần ghi **từng phần**, không cần ghép trước rồi ghi (vì ghép trước tốn
  RAM + vẫn phải đợi chunk cuối mới ghi được).
- **Tại sao `is_final` thay vì chỉ check `index == total`**: giúp callback
  phân biệt được "chunk cuối thật" với "chapter chỉ có 1 chunk" mà không
  phải if-them; cũng giúp khi tương lai muốn làm thêm hành vi lúc kết thúc
  (đánh dấu complete, log "xong chương") không phải đổi signature.
- **Đã xét, bỏ**: ghi từng chunk từ phía translator (translator gọi
  `storage.write_*`). Lý do bỏ: translator không nên biết về `Storage` /
  `Chapter` (hiện tại thuần `text -> str`); vi phạm separation of concerns
  và khó test.

### D2. Ghi append (không rewrite) từng chunk

Callback trong `_translate_one`:
- Chunk 1 (index 1): `translated_path(ch).write_text(chunk_text, encoding="utf-8")` — tạo file mới.
- Chunk 2..N: `translated_path(ch).open("a", encoding="utf-8")` rồi ghi
  `\n{chunk_text}` (thêm newline ngăn cách để tránh dính ký tự cuối chunk
  trước với ký tự đầu chunk sau khi `_split_into_chunks` không kết thúc
  bằng newline).

- **Tại sao append**: mỗi chunk đã được `_split_into_chunks` cắt theo ranh
  giới đoạn văn (`\n`), nhưng ranh giới đó có thể nằm giữa `\n` và ký tự
  đầu đoạn — nối trực tiếp hai chunk có nguy cơ dính chữ. Thêm `\n` giữa
  các chunk là cheap insurance, và bản dịch cuối vẫn khớp với output cũ
  (cũng join bằng `"\n"` trong `CLITranslator.translate:254`).
- **Đã xét, bỏ**: dùng temp file rồi rename atomic. Lý do bỏ: thêm
  complexity, không cần atomicity vì file được ghi từ process duy nhất
  (callback chạy trong luồng pipeline); nếu muốn có thể thêm sau.

### D3. Per-stem lock cho parallel writes

`_translate_chapters_parallel` chia chapter cho N workers bằng
`ThreadPoolExecutor`. Một chapter luôn chỉ có 1 worker dịch (vì
`pool.map(_work, chapters)` ánh xạ 1-1), nhưng chính `_translate_one` bên
trong worker lại gọi `translator.translate(raw, on_chunk=cb)` — callback
chạy trên cùng luồng worker đó, nên không có race condition giữa các
worker khác nhau. Lock chỉ cần nếu sau này 1 chapter bị chia cho nhiều
worker (không xảy ra ở code hiện tại).

- **Quyết định**: KHÔNG thêm lock. Callback chạy tuần tự trong worker, mỗi
  worker chỉ xử lý 1 chapter tại 1 thời điểm. (Nếu tương lai có ai đó cho
  `_translate_one` chạy concurrent trong cùng 1 chapter thì spec sẽ phải
  sửa.)
- **Đã xét, bỏ**: dùng `threading.Lock` global hoặc per-stem. Không cần
  thiết, thêm overhead.

### D4. Cache "complete" flag qua meta, không phải file marker

`complete` lưu trong `translation_meta/{stem}.json` thay vì tạo file
`translated/{stem}.done` rỗng.

- **Tại sao meta**: meta đã tồn tại cho mỗi chapter (lưu `warnings`,
  `length_raw`, `generated_at`...). Thêm 1 key JSON rẻ hơn tạo file mới
  và giữ nguyên thư mục `translated/` chỉ chứa file `.md`.
- **Back-compat rule**: `has_translated(ch)` = file exists AND
  (meta missing OR meta["complete"] == True). Meta missing được coi là
  complete để tôn trọng dữ liệu cũ. Meta tồn tại nhưng `complete` key
  missing/false = partial = re-translate.
- **Đã xét, bỏ**: sentinel file `translated/{stem}.done`. Lý do bỏ: 1 file
  mới = 1 IO pattern mới cần test + race với job song song; meta key gọn hơn.

### D5. Endpoint trả JSON, không phải HTML

`GET /api/ebooks/{slug}/chapters/{index}/translated` trả JSON thay vì
render lại cả trang chapter (chỉ cần textarea + preview). Lý do:

- Polling 1.5s/lần × N chapters cùng mở = bớt tải server so với render
  Jinja2 mỗi lần.
- JSON gọn, dễ so sánh `mtime` ở client để biết có cần cập nhật DOM không.
- Tránh nhầm với route `/ebooks/{slug}/chapters/{index}` (trang HTML đầy
  đủ) — endpoint có prefix `/api/` rõ ràng là JSON cho máy.

### D6. Poll `mtime` thay vì poll nguyên `text`

Client lưu `lastMtime`; mỗi lần poll, nếu `mtime` mới ≠ `lastMtime` thì
mới fetch `text` (server vẫn trả cả `text` trong cùng response để đơn
giản — gọi 1 lần/cycle, không 2 lần). Nếu `mtime` không đổi thì client
bỏ qua update DOM.

- **Tại sao `mtime`**: filesystem mtime thay đổi khi file được ghi, dùng
  làm "version" rẻ và chính xác. Không cần hashing nội dung.
- **Đã xét, bỏ**: server trả `etag`/`Last-Modified` header rồi client dùng
  `If-Modified-Since`. Phức tạp hơn, không có lợi ích thực tế vì payload
  JSON đã nhỏ (vài KB cho 1 chapter).

### D7. Không cập nhật textarea khi user đang focus

Poll update chỉ sửa `#translated-preview` (khung read-only dùng
`<div class="raw-view">`), không ghi đè `<textarea>` nếu user đang focus
vào nó. Sau khi job kết thúc, `location.reload()` vẫn chạy (giữ hành vi
cũ) — nhưng nếu user đã sửa tay, dữ liệu sửa sẽ được giữ trong form
state của browser (server là source of truth mỗi reload).

- **Lý do**: người dùng có thể đang sửa chính tả ngay trong khi job dịch
  chunk tiếp theo; ghi đè textarea sẽ xóa selection + vị trí con trỏ +
  lịch sử undo.
- **Khung preview** là DOM `<div>` không có focus, nên update an toàn —
  người dùng vẫn thấy tiến độ dịch.
- **Sau khi job xong**: reload toàn trang (giữ hành vi cũ) — đây là lúc
  load lại `textarea` với dữ liệu chính thức từ server, ghi đè mọi
  chỉnh sửa tạm thời (nếu user chưa bấm "Lưu bản dịch").

## Risks / Trade-offs

- **[R1] Job chết giữa chunk N → partial file không có `complete: true`**
  → next run sẽ bỏ qua (do `has_translated=False`) và dịch lại từ đầu.
  Mất work của N-1 chunk đã dịch. *Mitigation*: log cảnh báo rõ "Chapter X
  có file translated/0007.md nhưng thiếu complete=true — sẽ dịch lại", và
  document trong CHANGELOG rằng v1 chưa hỗ trợ resume từ partial.

- **[R2] UI poll mỗi 1.5s gây tải nhẹ** (mỗi tab mở = 1 request ~0.5-2KB
  JSON). *Mitigation*: chapter page chỉ poll khi status translate `running`
  (theo `data.translate.running`); ngay khi job idle thì dừng poll. Nếu
  nhiều tab cùng mở 1 chương thì mỗi tab tự poll, server trả JSON đã đọc
  sẵn từ disk — không tốn CPU.

- **[R3] Append có thể làm hỏng file nếu callback raise sau khi đã mở file
  write** (file trống + crash → lần sau dịch lại nhưng file trống 0 byte
  cũng bị coi là partial vì meta thiếu complete → tự re-translate đúng).
  *Mitigation*: nếu callback raise, `_translate_one` đã re-raise ra ngoài
  (`pipeline.py:603`); caller (sequential/parallel) đánh dấu
  `ch.last_action_status = "failed"`. Lần chạy kế sẽ skip-then-retry vì
  meta không có complete.

- **[R4] Concurrency giữa 2 ebook khác nhau** (cùng slug khác ebook) có
  thể đụng `translated/{stem}.md` nếu cùng đường dẫn. *Mitigation*: cấu
  trúc thư mục đã tách theo `<data_dir>/<slug>/translated/{stem}.md` nên
  slug khác nhau → file khác nhau; 2 job cùng slug được JobRunner chặn
  cùng slot `translate` (line 47 `app/job.py:47`) nên không chạy đồng
  thời.

- **[R5] Backward compat với `meta` cũ** — các file JSON cũ có
  `{"warnings": [...], "generated_at": ...}` không có key `complete`.
  `has_translated` phải treat-as-complete. *Mitigation*: rule rõ ràng
  trong `Storage.has_translated` (meta missing OR `complete == True`),
  có test cho cả 3 case (legacy / partial / complete).

- **[R6] Translator `Protocol` ở `translator.py:122` chỉ định nghĩa
  `translate(text) -> str`.** Nếu thêm `on_chunk` chỉ ở `CLITranslator`,
  `Protocol` không enforce nhưng code khác (vd. test) có thể check Protocol
  shape. *Mitigation*: cập nhật `Translator` Protocol comment + thêm
  `on_chunk` vào cả `NoopTranslator` và `GoogleTranslator` (chỉ là
  kwarg ignored) để shape đồng nhất.

## Migration Plan

Không cần migration script vì:

1. Meta cũ không có `complete` → `has_translated` coi là complete → không
   cần dịch lại gì cả.
2. File `translated/*.md` cũ vẫn là source-of-truth cho EPUB build (qua
   `Storage.read_translated`, không đụng `has_translated`).
3. UI: nếu user chưa refresh trang, cũ poll loop vẫn chạy như cũ;
   `on_chunk` không có trong translator (cho tới khi deploy bản mới) thì
   fallback về hành vi cũ (ghi 1 lần ở cuối) — back-compat tuyệt đối.

Rollback: nếu release bị lỗi, revert commit. Translator cũ không gọi
`on_chunk`, pipeline cũ không thấy `complete` key trong meta (mặc dù
pipeline mới có thể đã ghi `complete: true` ở vài chapter mới dịch) →
`has_translated` vẫn treat-as-complete (vì `complete=True` vẫn đúng
trong code cũ nếu đọc). Suy ra rollback an toàn.

## Open Questions

- **Q1**: Có nên giới hạn kích thước `text` trong JSON response (vd.
  chapter 50k ký tự)? Hiện tại proposal không cap. Sẽ đo thực tế khi
  implement: nếu >50KB thì cân nhắc thêm `?since_mtime=...` để trả
  `304 Not Modified` thay vì full payload.
- **Q2**: Có nên thêm nút "Xóa partial" trong trang chapter để user
  dọn nhanh file dở? Để ngoài scope change này, mở issue riêng nếu
  cần.
