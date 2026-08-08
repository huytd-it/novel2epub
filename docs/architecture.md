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

`translator.py` chọn backend từ cấu hình (`make_translator`):

- `openai`: API tương thích OpenAI (`OpenAITranslator`).
- `localmt`: model CTranslate2 cục bộ (`LocalMTTranslator`, package `novel2epub.hachimimt`).
- `none`: giữ nguyên nội dung.

`google` và `libretranslate` đã gỡ; config cũ được migrate → `openai` khi load và bởi DB migration v12 (`hachimimt`/`moxhimt` → `localmt`). Legacy `hachimimt`/`moxhimt` vẫn được `make_translator` nhận như alias phòng thủ.

Nếu `source_language=vi`, pipeline dùng passthrough bất kể backend đã chọn. OpenAI translator kết hợp glossary, idiom, genre, nhân vật và quan hệ theo mốc chương vào prompt. Sau dịch, clear Hán mặc định dùng Local MT (`cleanup_han.engine=local_mt`), có thể đổi sang `openai`.

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

### Nguồn, Lưu Trữ, Automation, WireGuard, Dashboard

Năm trang này khác nhóm Glossary/Nhân vật/Idioms ở chỗ hầu hết CHƯA có JSON
API — route cũ chỉ render Jinja2 và nhận `Form(...)` trả `RedirectResponse`.
`app/routes/webui.py` bổ sung một khối `GET/POST /api/ui/{storage,automation,
wireguard,sources}` cho mỗi trang, theo đúng pattern đã lập ở mục Cài Đặt: gọi
THẲNG hàm xử lý thuần đã có (`purge_raw`, `add_automation`, `wg.activate_profile`,
`save_preset`, ...) thay vì viết lại logic, và tái dùng cả helper riêng
(`_preset_usage`, `_load_validation` từ `sources.py`) — route cũ vẫn chạy y
nguyên. Riêng **Dashboard không cần gì mới**: `/api/dashboard` đã là JSON đầy
đủ (`app/routes/dashboard.py`) từ trước khi có SPA, nằm sẵn dưới `/api` nên đã
CORS + auth-eligible.

WireGuard's `import` là multipart (`UploadFile`) — client gọi thẳng `fetch`
với `FormData` (xem `useImportWireGuardProfile` trong `frontend/src/lib/
wireguard.ts`) vì lớp `api.post()` dùng chung chỉ hỗ trợ JSON/form-urlencoded.

**Sources bị thu hẹp phạm vi có chủ đích**: form preset legacy có ~30 trường
(gồm cả selector AI-detect và prompt AI-glossary/cleanup/eval); SPA chỉ port
đúng bộ trường mà form `Form(...)` cũ THỰC SỰ nhận (`_SOURCE_EDITABLE_FIELDS`
trong `webui.py`, khớp `BASIC_FIELDS`/`SELECTOR_FIELDS`/`CRAWL_FIELDS` trong
`SourcesPage.tsx`) — CRUD, test dry-run, nhân bản, xóa đầy đủ. Wizard "Phân
tích bằng AI" (đề xuất selector) và nhập YAML hàng loạt vẫn ở giao diện cũ,
link rõ trên trang.

### Trang Chương — Một Trang Cho Mọi Việc Của Một Chương

`/app/ebooks/{slug}/chapters/{index}` gộp cả bốn thứ từng nằm rải rác: đọc,
sửa từng đoạn, đối chiếu 3 cột, và duyệt bản nháp AI. Trước đây là hai trang
riêng (`ReaderPage` + `ChapterComparePage`) trỏ vào hai endpoint khác nhau —
mở cùng một chương ở hai chỗ, mỗi chỗ thấy một nửa sự thật. `/read/:index`
cũ redirect sang đây để link đã lưu không chết.

`GET /api/ui/ebooks/{slug}/chapters/{index}` trả TẤT CẢ trong một request:
nội dung đọc/sửa, khung đối chiếu, trạng thái hai nhánh, và danh sách bản
nháp AI.

**Ba luồng tách bạch trên UI** (`BranchBar`), vì chúng đọc nguồn khác nhau và
hành xử khác nhau:

| Luồng | Đọc từ | Ghi vào | Hoàn tác |
| --- | --- | --- | --- |
| Dịch Local MT | bản gốc | thẳng vào nhánh `local_mt` | không |
| Dịch AI | bản gốc | thẳng vào nhánh `ai` | không |
| Biên tập AI | bản dịch đang có | bản nháp chờ duyệt | có — bỏ nháp |

Gộp chúng vào một nút "AI" là chỗ dễ mất dữ liệu nhất: "dịch" ghi đè thẳng
còn "biên tập" thì không, nên hai việc phải nằm ở hai nhóm nút có nhãn khác
nhau. Bulk action ở trang Ebook (`BatchBar`) chia đúng ba nhóm này.

**Đánh số đoạn của khung đọc là `notes.split_paras`** (từng DÒNG không rỗng) —
KHÁC với `app/chapter_compare.py` (theo KHỐI, xem mục bên dưới). Payload trả
CẢ HAI (`translated_paras` và `paragraphs`); đây là chỗ dễ lẫn nhất trong
codebase nên hai khoá được đặt tên khác hẳn nhau và có comment ở cả hai đầu.

**Sửa tại chỗ**: bấm một đoạn (chế độ Sửa) đổi `<p>` thành `<textarea>`, lưu
qua `POST .../para/save` khi rời ô. `commit()` đọc giá trị THẲNG từ
`e.target.value` tại thời điểm blur, không tin vào state React đóng gói
trong closure — gõ xong rồi rời ô ngay trong cùng một khung xử lý sự kiện có
thể khiến closure của `onBlur` còn thấy state CŨ vì React chưa kịp
re-render giữa hai sự kiện `input` và `blur`. Cùng lý do, ô sửa tiêu đề
chương và ô sửa nội dung ghi chú trong `NotesPanel` cũng đọc trực tiếp từ
event thay vì state.

**Ghi chú lỗi dịch**: bôi đen văn bản → popover tạo ghi chú qua
`POST /api/ebooks/{slug}/notes` (đã là JSON từ trước, không cần API mới).
Đánh dấu `<mark>` trong văn bản đọc bằng cách tìm `note.selected_text` như
substring trong đoạn tương ứng (`para_index`) — đơn giản hơn cách legacy
dùng Range API thao tác trực tiếp DOM, đủ dùng cho phần lớn trường hợp
nhưng không xử lý được đoạn văn bản trùng lặp nhiều lần trong cùng đoạn.

**Highlight khác biệt**: `lib/diff.ts` diff theo TỪ (LCS), không theo ký tự —
tiếng Việt có dấu nên diff mức ký tự vỡ vụn giữa chữ và đọc không ra gì. Khung
đối chiếu tô cột "Dịch máy" phần bị bỏ và cột "Bản hiện tại" phần được thêm;
mỗi cột chỉ tô phần của mình để đọc dọc vẫn thành câu hoàn chỉnh. Bất biến
quan trọng nhất: ghép `same`+`del` phải ra đúng chuỗi trước, `same`+`add` ra
đúng chuỗi sau — hiển thị diff không được làm mất chữ nào.

**Chưa port từ trang Jinja2 cũ** (link "Công cụ khác" trỏ sang bản cũ):
TTS (Edge TTS), dịch nhanh bằng NMT cục bộ (HachimiMT chọn-để-dịch), dọn Hán
tự bằng Local MT, các thao tác AI theo đoạn (`parapolish`, `paraexplain`,
`ai-edit`), tìm-và-thay-thế hàng loạt trong toàn sách, dịch lại tiêu đề.

### Thể Loại Trong Prompt Biên Tập

`glossary_ai.rewrite_chapter(..., genre=...)` chèn luật xưng hô/mức Hán Việt
của thể loại (`novel2epub/genre.py`) vào `REWRITE_PROMPT`. `POST
/api/ui/ebooks/{slug}/rewrite` nhận `genre` để ghi đè cho RIÊNG lần chạy đó,
không đụng `translate.genre` của ebook.

Lý do tồn tại: Local MT dịch tiên hiệp/cổ đại khá sát nghĩa nhưng hay lệch hệ
xưng hô (ra "tôi/cậu" thay vì "ta/ngươi"). Nắn lại ở bước biên tập rẻ hơn
nhiều so với đổi cấu hình rồi dịch lại cả truyện.

### Giao Diện Mặc Định

`/` redirect sang `/app/` khi bundle SPA đã build (`app/main.py`, đăng ký
TRƯỚC `ebooks.router` vì router đó cũng khai báo `/` và FastAPI khớp theo thứ
tự đăng ký). Trang Thư viện của Jinja2 lùi về `/library` — đúng tên cũ của nó
trước khi được gộp vào trang chủ — nên UI cũ vẫn vào được đầy đủ cho các tính
năng chưa port. Không chuyển cả Jinja2 xuống một tiền tố riêng: SPA còn link
sang nhiều trang cũ, và mọi href trong template đều là đường dẫn tuyệt đối.

### Trang Cài Đặt — Gọi Thẳng Hàm Xử Lý Form Cũ

`GET/POST /api/ui/ebooks/{slug}/settings[/{section}]` không viết lại logic lưu
cấu hình. Đọc thì phẳng hoá `cfg` theo ĐÚNG tên tham số `Form(...)` của
`save_novel`/`save_source`/`save_translate`/`save_ai`/`save_reader`/`save_output`
trong `app/routes/settings.py` — 83 trường, khoá JSON = tên tham số Form 1-1.
Ghi thì gọi THẲNG các hàm đó bằng Python (`fn(slug=slug, **payload)`), không
HTTP round-trip: những endpoint cũ trả `RedirectResponse` 303 sang trang
Jinja2, mà `fetch` mặc định đi theo redirect rồi tải cả trang HTML chỉ để vứt
đi, và nếu SPA chạy khác origin thì trang đích nằm ngoài `_CORS_PREFIXES` nên
bị chặn CORS. `Form(...)` chỉ là giá trị mặc định lúc FastAPI parse HTTP —
gọi hàm trực tiếp với keyword argument bỏ qua lớp đó hoàn toàn, không ảnh
hưởng gì tới route cũ.

`tests/test_ui_settings_contract.py` khoá lại sự khớp tên trường bằng
`inspect.signature` — thêm field vào form mà quên thêm vào API (hoặc ngược
lại) là ô đó hiện rỗng rồi ghi đè giá trị thật bằng rỗng lúc người dùng bấm
Lưu, không có lỗi nào nổ ra, nên bất biến này bắt buộc phải test.

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

### Glossary, Nhân Vật, Từ Điển Chung — Không Cần API Mới

Ba trang này port THUẦN FRONTEND: `app/routes/glossary.py`, `characters.py`,
`idioms.py` đã là JSON API đầy đủ từ trước khi port (chỉ route `GET` render
HTML là còn Jinja2), nằm dưới `/api/...` nên đã CORS + auth-eligible sẵn,
không cần chỉnh gì ở backend.

- **Glossary** (`/app/ebooks/{slug}/glossary`) — bảng autosave-per-ô, đề xuất
  đang chờ duyệt (từ auto-glossary lúc dịch) hiện thành hàng tô vàng ở TRANG
  ĐẦU của bảng chính (không phải tab riêng — khớp hành vi legacy), tab "Nghi
  vấn" hiển thị 3 nhóm đáng ngờ (`glossary_review.find_suspects`). Duyệt đề
  xuất enqueue MỘT job nền (category=translate) lan truyền thay đổi vào bản
  dịch cũ — kết quả xem ở trang Hàng đợi, không polling tại chỗ.
- **Nhân vật** (`/app/ebooks/{slug}/characters`) — bảng nhân vật + quan hệ CÓ
  HƯỚNG mở rộng dưới mỗi hàng (bấm mũi tên). Danh sách không phân trang phía
  server (ebook hiếm khi có quá vài trăm nhân vật) nên tìm kiếm lọc phía
  client. Tab "Đề xuất" duyệt nhân vật TRƯỚC quan hệ SAU — thứ tự bắt buộc,
  xem docstring `characters_pending_approve`.
- **Từ điển chung** (`/app/idioms`) — kho thành ngữ dùng chung MỌI truyện
  (không gắn slug), cùng pattern autosave với Glossary.

Cả ba dùng chung một pattern autosave: input cục bộ đồng bộ từ server qua
`useEffect`, lưu khi `onBlur` đọc thẳng `e.target.value` (không tin state
đóng gói closure — xem lý do ở mục Trang Đọc phía trên, cùng loại bug).

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
