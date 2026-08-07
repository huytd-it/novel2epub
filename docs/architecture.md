# Kiến Trúc Hệ Thống

## Tổng Quan

novel2epub là ứng dụng Python có hai giao diện dùng chung domain logic:

- `novel2epub/`: pipeline, crawler, translator, storage, EPUB và tích hợp ngoài.
- `app/`: FastAPI, Jinja2 Web UI, job queue và scheduler.
- `scripts/`: khởi tạo và migration dữ liệu.
- `tests/`: kiểm thử unit, integration và route.

CLI được định nghĩa trong `novel2epub/cli.py`; Web UI khởi tạo tại `app/main.py`. Cả hai đọc cùng SQLite DB thông qua `config.py`, `db.py` và `storage.py`.

## Pipeline

1. `fetch-toc` đọc metadata và danh sách chương, sau đó cập nhật manifest trong DB.
2. `crawl` tải nội dung nguồn cho các chương chưa có raw hoặc phạm vi được chọn.
3. `translate` tạo snapshot dịch máy và bản dịch có thể biên tập.
4. `cleanup-han` tùy chọn dùng AI biên tập để xử lý ký tự Hán còn sót.
5. `build` đóng gói các chương hợp lệ thành EPUB.
6. `publish-reader` tùy chọn đồng bộ chương thay đổi sang novel-reader.

Các bước idempotent theo trạng thái chương. Cờ `force`, phạm vi và bộ lọc cho phép chủ động chạy lại.

## Lưu Trữ

SQLite là nguồn sự thật duy nhất. `Storage` cung cấp API tương thích cho manifest và nội dung chương nhưng dữ liệu thực tế nằm trong DB, không còn dùng `raw/*.md`, `translated/*.md` hoặc sidecar JSON làm runtime storage.

Các nhóm dữ liệu chính:

- `settings`, `sources`, `ebooks`: cấu hình ba tầng.
- `chapters`: URL, tiêu đề, raw, snapshot MT, bản biên tập và metadata.
- `glossary_entries`, `idioms`, `characters`, `character_relations`: ngữ cảnh dịch.
- Bảng queue, automation và trạng thái thư viện: vận hành Web UI.

EPUB và file backup là output bên ngoài DB.

## Cấu Hình Hiệu Lực

```text
defaults -> source preset -> ebook overrides
```

Source preset chỉ cung cấp thiết lập crawl. Override của ebook có ưu tiên cao nhất. `translate` và `ai` có thể cấu hình riêng theo ebook; defaults là fallback. Các field kết nối Reader (`url`, `service_key`, `timeout_seconds`, `batch_size`) luôn global để secret chỉ nằm một nơi.

## Crawl

`crawler.py` chỉ dùng Scrapling:

- `fetcher`: HTTP/TLS fingerprint, nhanh và nhẹ.
- `stealthy`: Camoufox, phù hợp anti-bot và Cloudflare.
- `dynamic`: browser Playwright đầy đủ cho trang cần JavaScript.

Pipeline bổ sung rate limiter theo domain, adaptive concurrency, retry/backoff và giới hạn worker. Mục lục và nội dung chương đều có thể phân trang.

## Dịch

`translator.py` chọn backend từ cấu hình:

- `openai`: API tương thích OpenAI.
- `hachimimt`: model CTranslate2 cục bộ.
- `google`: deep-translator.
- `libretranslate`: LibreTranslate HTTP API.
- `none`: giữ nguyên nội dung.

Nếu `source_language=vi`, pipeline dùng passthrough bất kể backend đã chọn. OpenAI translator kết hợp glossary, idiom, genre, nhân vật và quan hệ theo mốc chương vào prompt.

## Web UI Và Job Queue

FastAPI render giao diện Jinja2 và cung cấp API nội bộ. `JobQueue` chia worker thành nhóm `crawl` và `translate`; job dùng cả hai nhóm như `run` hoặc `build` chờ tài nguyên phù hợp để tránh ghi chồng trạng thái ebook.

`AutomationScheduler` kiểm tra cron định kỳ và enqueue toàn bộ chuỗi bước như một job tuần tự. Lịch bị lỡ khi máy tắt được chạy bù tối đa một lần.

## Giao Diện SPA (`frontend/`)

Giao diện đang được chuyển dần từ Jinja2 sang một SPA React. Hai giao diện chạy
song song: route Jinja2 cũ giữ nguyên đường dẫn, SPA phục vụ tại `/app`.

- Stack: Vite + React + TypeScript + TanStack Query + react-router, Tailwind v4
  với daisyUI, icon Phosphor qua `react-icons`.
- Build: `npm --prefix frontend run build` xuất ra `app/webui/`. `app/main.py`
  chỉ gắn mount `/app` khi thư mục đó có `index.html`, nên thiếu bundle thì
  server vẫn chạy bình thường với UI cũ.
- Dev: `npm --prefix frontend run dev` (cổng 5183) proxy mọi lời gọi API sang
  uvicorn ở 8011.
- API riêng của SPA nằm dưới `/api/ui/` trong `app/routes/webui.py`, tách khỏi
  `/api/v1/` (hợp đồng công khai cho readest) và `/api/` (endpoint nội bộ đã
  có). Router này chỉ đọc lại domain logic sẵn có, không sửa route cũ.
- Toàn bộ `/api/*` và `/opds/*` đi qua hai middleware trong `app/main.py`:
  `api_token_gate` đòi token khi client không phải localhost, `opds_api_cors`
  gắn header CORS cho origin đã cấu hình. Thứ tự đăng ký là có chủ đích —
  Starlette chạy middleware đăng ký sau ở vòng ngoài, nên CORS bọc ngoài auth
  và response 401 vẫn đọc được từ frontend khác origin. Route web UI (kể cả
  `/settings/api`, nơi token hiện cleartext) nằm ngoài cả hai.
- Dải chương (`GET /api/ui/library`) gửi trạng thái từng chương dạng run-length
  (`e120,m40,n1500`): trạng thái gần như luôn liên tục theo lô crawl/dịch nên
  payload nhỏ hơn hai bậc so với gửi cả mảng, mà vẫn chính xác từng chương.
- Bảng chương (`GET /api/ui/ebooks/{slug}/chapters`) lọc và phân trang phía
  server, uỷ quyền cho `apply_chapter_query` — cùng hàm mà thao tác hàng loạt
  dùng, nên "chọn tất cả kết quả đang lọc" trỏ đúng tập chương backend sẽ xử
  lý. Response kèm `indexes` (toàn bộ index khớp) để nút chọn-tất-cả không
  phải tải hết từng dòng.

### Hai Cách Đánh Số Đoạn — Đừng Trộn

Có HAI cách chia đoạn trong hệ thống, và chúng không tương đương:

| Nơi dùng | Hàm | Đơn vị |
| --- | --- | --- |
| Reader, ghi chú, `para/save` | `notes.split_paras` | từng DÒNG không rỗng |
| Khung so sánh 3 cột | `app/chapter_compare.align_paragraphs` | KHỐI (cách bởi dòng trống), các dòng trong khối gộp lại |

Một khối "lời dẫn + lời thoại" là **1 hàng** ở khung so sánh nhưng là **2 đoạn**
với `para/save`. Lấy chỉ số hàng của khung so sánh gọi sang `para/save` sẽ ghi
đè nhầm dòng và không có lỗi nào nổ ra.

Vì vậy trang so sánh (`/app/ebooks/{slug}/chapters/{index}`) chỉ ĐỌC ở ba cột;
muốn sửa thì hoặc ghi toàn văn qua
`POST /api/ui/ebooks/{slug}/chapters/{index}/translated` (giữ nguyên từng ký tự
xuống dòng), hoặc mở Reader để sửa theo đoạn bằng đúng cách đánh số của nó.
`tests/test_chapter_compare.py` chốt lại sự khác biệt này.

### Bản Desktop (Tauri)

`frontend/src-tauri/` đóng gói cùng bundle thành app desktop đa nền tảng. Khác
biệt duy nhất so với bản web: Tauri nạp giao diện từ `tauri://` nên không suy ra
được server ở đâu — địa chỉ và token API nhập ở trang **Kết nối** và lưu trong
`localStorage`. Build desktop dùng `npm --prefix frontend run build:tauri`
(`--mode tauri`, base tương đối) rồi `npm --prefix frontend run tauri:build`.
Cần cài Rust toolchain.

## Trang Đọc

`/ebooks/{slug}/read/{index}` là trang đọc. Bôi đen văn bản mở thanh công cụ nổi: copy, dịch nhanh, thay thế, đọc từ đoạn này, ghi chú lỗi dịch.

- `POST /api/ebooks/{slug}/quick-translate`: dịch đoạn bôi đen bằng NMT cục bộ (HachimiMT/MoxhiMT), bất kể `translate.type` của ebook. Instance model được cache theo `model_key` và ebook trong tiến trình web để không dùng nhầm glossary.
- `POST /api/ebooks/{slug}/cleanup-han-local-mt`: chỉ dịch các vùng còn ký tự Hán, giữ nguyên phần tiếng Việt và tự chèn khoảng trắng tại ranh giới từ khi cần. Phạm vi chương chạy đồng bộ; phạm vi toàn sách chạy qua queue `translate`.
- Chế độ biên tập có nút hoàn tác/làm lại cho thay đổi đoạn và tiêu đề trong phiên đọc hiện tại. Mục lục có bộ lọc tiêu đề chạy hoàn toàn phía client; Reader không đăng ký phím tắt toàn cục.
- Chế độ biên tập còn có thể chèn/xóa đoạn: hover hoặc focus vào một đoạn hiện thanh công cụ nhỏ nổi bên phải (`+` chèn đoạn trống ngay sau, thùng rác xóa đoạn có xác nhận). `POST /chapters/{index}/para/insert` (`novel2epub.notes.insert_para`) chèn 1 dòng mới vào `translated/`; xóa tái dùng `para/save` với `new_text` rỗng (đã có sẵn). Thao tác chèn/xóa đổi số đoạn nên KHÔNG vào được undo/redo stack (chỉ sửa nội dung tại chỗ mới undo được).
- Mục lục (TOC sidebar) luôn hiển thị ở desktop (≥ 901px, không cần bấm mở); trên mobile vẫn thu gọn sau nút hamburger như cũ.
- Chuyển chương (nút trước/sau, dropdown, mục lục, kết quả tìm kiếm) tải qua AJAX (`GET /api/ebooks/{slug}/read/{index}/data`) thay vì tải lại trang — nhanh hơn khi đang biên tập nhiều chương liên tiếp. Chỉ áp dụng khi chương đích ĐÃ có bản dịch; chương chưa dịch/chưa crawl có khung trang khác hẳn (form trống, thiếu nút) nên client tự rơi về điều hướng tải lại trang bình thường. Các script phụ (ghi chú, biên tập, TTS, mục lục) đồng bộ theo qua custom event `n2e:chapter-changed` trên `document`.
- Thay thế có ba phạm vi: vùng đã chọn ghi thẳng qua `chapters/{index}/para/save`; toàn bộ chương và toàn bộ sách xem trước theo TỪNG ĐOẠN trước khi ghi. Tuỳ chọn "toàn bộ từ" bọc chuỗi tìm bằng `\b` và gửi như regex.
- Với phạm vi chương/sách, modal thay thế (mở từ thanh công cụ nổi khi bôi đen) có bước "Xem trước theo đoạn": `GET /glossary/find-preview` liệt kê từng đoạn khớp (kèm bản trước/sau), người dùng tick chọn từng đoạn muốn đổi hoặc bấm "Chọn tất cả", rồi `POST /glossary/apply-selected` chỉ ghi các đoạn đã chọn (có backup `before_find_replace` như `propagate`). Thanh tìm kiếm toàn truyện (nút "Thay trong chương này"/"Thay tất cả") vẫn là đường tắt ghi thẳng không qua xem trước, dùng `glossary/propagate` như cũ.
- `POST /api/tts`: tổng hợp giọng đọc bằng Edge TTS (`edge-tts`), trả mp3 cho từng đoạn. Trang đọc phát tuần tự, prefetch đoạn kế và tự chuyển chương khi hết bài. Dịch vụ Edge thỉnh thoảng trả stream rỗng nên endpoint thử lại tối đa 3 lần.

## Reader Sync

Tích hợp Reader dùng Supabase PostgREST. Đồng bộ dựa trên hash nội dung và upsert theo `(book_id, index)`:

- Thêm chương chưa tồn tại.
- Cập nhật tiêu đề/nội dung đã đổi và giữ nguyên `chapters.id`.
- Bỏ qua chương không đổi hoặc chưa dịch.
- Không tự xóa chương trên Reader.

### Neo Đoạn Khi Đẩy Sang Reader

`reader.push_anchors` (mặc định **tắt**) đẩy kèm cột `chapter_contents.para_anchors` — nền móng để sau này sửa bản dịch ngược từ app đọc về Xưởng.

**Neo là gì.** `anchors[j]` là chỉ số trong `notes.split_paras(translated_text)` của **dòng thứ j** của `content`. Đơn vị là DÒNG không rỗng, đếm xuyên suốt cả chương:

```
content.split("\n")  (bỏ dòng rỗng)  ->  1:1 với anchors
```

**Vì sao đơn vị là dòng, không phải block.** `notes.replace_para` — hàm duy nhất ghi bản sửa — thao tác theo dòng. Nếu một đoạn hiển thị bên Reader gộp hai dòng nguồn thì lúc editor viết lại đoạn đó, không có cách nào tách kết quả về đúng hai dòng. Đơn vị sửa và đơn vị lưu bắt buộc 1:1.

Dòng trống trong `content` vẫn giữ nguyên vị trí nên thông tin "hai dòng này thuộc cùng một đoạn" (cặp lời dẫn + lời thoại) không mất — Reader dựa vào đó render sát nhau, y như `<br/>` trong EPUB.

**Vì sao không phải ánh xạ đồng nhất.** Hai chỗ làm neo lệch:

- Heading ĐẦU TIÊN bị bỏ khỏi `content` (trùng cột `title` bên Reader) nhưng vẫn chiếm một chỗ trong `split_paras` → mọi neo sau đó lệch 1.
- Heading còn lại mất dấu `#`, nên `content_line[j] != split_paras[anchors[j]]`. Neo trỏ đúng DÒNG, không hứa hai chuỗi bằng nhau.

Chương không có heading thì neo suy biến về ánh xạ đồng nhất — đó là mốc kiểm tra rẻ nhất khi nghi ngờ.

**Bật thế nào.** Chạy migration bên Supabase TRƯỚC:

```sql
alter table chapter_contents add column para_anchors jsonb;
```

Rồi mới tick `push_anchors` ở Cài đặt > Reader. Bật khi chưa có cột thì PostgREST trả 400 và hỏng cả lần đẩy.

Neo đi trong **cùng payload** với `content` (`reader_client.upsert_contents`). Không tách thành hai lần ghi: neo thuộc về một bản văn khác với nội dung là sai lệch âm thầm — không lỗi nào nổ ra, chỉ có bản sửa ghi nhầm đoạn.

Thiết kế đầy đủ của pipeline hai chiều: [spec 2026-08-07](superpowers/specs/2026-08-07-two-way-edit-pipeline-design.md).
