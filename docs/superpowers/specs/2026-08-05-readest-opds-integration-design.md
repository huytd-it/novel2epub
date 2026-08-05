# Tích hợp readest — Giai đoạn 1: OPDS + EPUB có neo + API sửa đoạn

Ngày: 2026-08-05
Trạng thái: đã duyệt thiết kế, chờ lập kế hoạch triển khai

## 1. Bối cảnh

[readest](https://github.com/readest/readest) là trình đọc ebook mã nguồn mở (Next.js 16 + Tauri v2, render bằng foliate-js), chạy trên macOS/Windows/Linux/Android/iOS/Web. Mục tiêu của người dùng: đọc bản dịch của novel2epub trên điện thoại và desktop bằng readest, và về lâu dài sửa được bản dịch ngay trong lúc đọc.

Ba dữ kiện định hình thiết kế:

1. **readest đọc OPDS sẵn.** Nó nối được Calibre/Komga/Kavita qua OPDS, có hỗ trợ xác thực username/password, tải sách về thư viện cục bộ, và streaming qua OPDS-PSE. Nghĩa là mục tiêu "đọc" đạt được mà không cần sửa một dòng nào của readest.
2. **readest không có đường ghi ngược nội dung sách.** Cơ chế sync của nó (Readest Cloud, KOReader Sync, WebDAV, Google Drive, S3) chỉ đồng bộ tiến độ đọc, highlight, note, thống kê và cấu hình — không sửa được văn bản của sách. Muốn sửa bản dịch từ readest thì buộc phải fork.
3. **readest là AGPL-3.0.** Dùng riêng thì không phát sinh nghĩa vụ gì. Nếu về sau bản web của fork được phục vụ cho người khác qua mạng, điều khoản network của AGPL kích hoạt: phải công khai source của fork.

Vì vậy công việc chia làm hai giai đoạn. **Spec này chỉ bao giai đoạn 1.**

## 2. Phạm vi

### Thuộc phạm vi (GĐ1)

- Endpoint OPDS trong novel2epub để readest bản gốc nối vào đọc.
- Phục vụ file EPUB và ảnh bìa.
- Xác thực bằng token (Basic + Bearer), CORS cho bản readest web.
- Neo đoạn văn ổn định nhúng trong EPUB lúc build.
- API đọc/sửa đoạn văn — dựng ở GĐ1 để GĐ2 có nền, và để kiểm chứng cơ chế neo bằng dữ liệu thật trước khi bỏ công fork.

### Không thuộc phạm vi

- Fork readest, UI biên tập trong readest (GĐ2, spec riêng).
- Đồng bộ tiến độ đọc / highlight / note giữa readest và novel2epub.
- Tự build lại EPUB khi phát hiện bản dịch mới hơn file.
- Thay thế hoặc động chạm tới đường đẩy chương lên app `novel-reader` (Supabase) đang có — `reader_client.py`, `reader_sync.py`, `cfg.reader.*` giữ nguyên, không liên quan.
- Thay thế trang đọc nội bộ `app/templates/reader.html`.

## 3. Hiện trạng liên quan

| Thành phần | Trạng thái hiện tại |
|---|---|
| Lưu trữ | SQLite `novel2epub.db`, schema v7. Bảng `chapters(ebook_slug, idx)` với `raw_text`, `translated_text`, `translated_mt_text`, `meta_json`, `translated_updated_at`. Nội dung là Markdown nguyên khối, **không** còn file `.md`. |
| Quy mô | 6 ebook, 6016 chương, 751 chương đã dịch. Ebook lớn nhất 2907 chương. |
| Ảnh bìa | Bảng `ebook_covers(ebook_slug, ext, content BLOB, updated_at)`. |
| EPUB | `epub_builder.build_epub`, ghi ra `cfg.epub_path` (mặc định `{slug}.epub`). Tên file chương trong EPUB: `chap_{index:04d}.xhtml`. |
| Xác thực | **Không có.** Ứng dụng hiện chạy trần trên localhost. |
| Sửa đoạn | `notes.replace_para(translated, para_index, para_text_expected, new_text)` — neo theo vị trí, chống ghi đè bằng snapshot text. |

### Hai định nghĩa "đoạn văn" đang mâu thuẫn

Đây là rủi ro chính của thiết kế, cần nêu rõ:

- `notes.split_paras` = `[p for p in translated.split("\n") if p.strip()]` → **chỉ số dòng-không-rỗng**.
- `epub_builder._md_to_xhtml_body` tách theo `re.split(r"\n\s*\n", ...)` → **chỉ số block cách nhau bằng dòng trống**, rồi nối các dòng trong block bằng `<br/>`.

Trong dữ liệu thật hai con số này thường trùng, nhưng không phải luôn luôn: chương 1 của `bao-cao-dieu-tra-than-minh-6` có 161 dòng-không-rỗng nhưng chỉ 160 block — có một block chứa hai dòng. Nếu neo theo định nghĩa của `_md_to_xhtml_body` thì mọi đoạn sau block đó sẽ ghi lệch một bậc khi `replace_para` xử lý.

**Quyết định: toàn hệ thống dùng một định nghĩa duy nhất — `notes.split_paras` (chỉ số dòng-không-rỗng).** Lý do: đó là thứ `replace_para` dùng để ghi. Neo phải nói cùng ngôn ngữ với hàm ghi, không phải với hàm render.

## 4. Kiến trúc

### Module mới

| Module | Nhiệm vụ | Phụ thuộc |
|---|---|---|
| `novel2epub/opds.py` | **Thuần.** Dựng cây catalog OPDS từ list dict mô tả ebook, trả chuỗi XML. Không I/O, không DB, không FastAPI. | không |
| `novel2epub/api_auth.py` | **Thuần.** Phân giải header `Authorization` (Basic/Bearer) thành token, so khớp an toàn, quyết định miễn trừ localhost. | không |
| `app/routes/opds.py` | HTTP: các route `/opds/*` và `/api/v1/*`, đọc `Storage`, phục vụ file. | `opds.py`, `api_auth.py`, `Storage`, `deps` |

Tách logic thuần khỏi I/O theo đúng lối `bulk_transfer.py` và `reader_sync.py` đang dùng — test được không cần mạng lẫn DB.

### Sửa vào chỗ có sẵn

- `novel2epub/epub_builder.py` — `_md_to_xhtml_body` nhận thêm tham số neo.
- `novel2epub/pipeline.py` — `step_build_selected` truyền cờ "chương này có bản dịch hay không" xuống `build_epub`.
- `novel2epub/db.py` — thêm cột `settings.api_json`, `SCHEMA_VERSION` 7 → 8.
- `novel2epub/config.py` — dataclass `ApiConfig`.
- `app/main.py` — mount router, thêm CORS middleware.

Cấu hình đi vào khoá **`api`** riêng, **không** nhét vào `reader.*`. `reader.*` đang thuộc về app novel-reader Supabase; trộn hai thứ khác nhau vào một khoá sẽ làm rối cả trang Cài đặt lẫn code.

## 5. Neo đoạn văn

### Cơ chế

`_md_to_xhtml_body` giữ nguyên hình thức hiển thị, chỉ bọc thêm `<span>`:

```html
<p><span data-n2e-p="40">Dòng thứ nhất của block</span><br/><span data-n2e-p="41">Dòng thứ hai</span></p>
```

Vì sao dùng `<span>` chứ không tách thành nhiều `<p>`: giữ `<br/>` trong cùng một `<p>` là cách trình bày hiện tại. Tách ra sẽ đổi thụt đầu dòng (`text-indent: 1.5em`) và giãn cách của **mọi** EPUB đang có. Bọc span thì render y hệt, mà mỗi dòng vẫn có địa chỉ riêng.

Bộ đếm `data-n2e-p` chạy trên **các dòng không rỗng, xuyên suốt cả chương, kể cả heading**, để khớp chính xác `notes.split_paras`. Cụ thể: `split_paras` không loại bỏ dòng heading (`## Chương 1`), nên bộ đếm cũng phải tính heading vào — heading nhận `<h2 data-n2e-p="0">`.

Neo đầy đủ của một đoạn = `(slug, chapter_idx, para_index)`. `chapter_idx` suy ra từ tên file `chap_0041.xhtml` vốn đã có.

### Chương chưa dịch không được gắn neo

`step_build_selected` rơi về `raw_text` khi chương chưa có bản dịch:

```python
if storage.has_translated(ch):
    md = storage.read_translated(ch)
    ...
elif storage.has_raw(ch):
    md = storage.read_raw(ch)
```

Chương thuộc nhánh thứ hai chứa **văn bản Hán gốc**, trong khi API PATCH ghi vào `translated_text`. Gắn neo cho chúng sẽ khiến người dùng sửa từ readest và ghi đè lên một cột hoàn toàn khác.

Vì vậy `build_epub` nhận thêm cờ cho mỗi chương, và `_md_to_xhtml_body` **chỉ sinh `data-n2e-p` khi cờ bật**. Cách truyền: mở rộng phần tử của `chapters_html` từ `(chapter, title, md)` thành `(chapter, title, md, anchored: bool)`.

`build_epub` có 3 call site trong `pipeline.py` và được `tests/test_pipeline_meta.py` phủ. Để không phải sửa hết cùng lúc, hàm chấp nhận **cả tuple 3 lẫn 4 phần tử**; tuple 3 phần tử coi như `anchored=False`. Đây là tương thích ngược có chủ đích và tạm thời — kế hoạch triển khai phải có một bước dọn hết call site về tuple 4 phần tử rồi bỏ nhánh cũ, chứ không để nó nằm lại vĩnh viễn.

### Footnote không phá neo

`footnotes.annotate` chèn marker Private-Use ngay sau term bằng phép cắt chuỗi thuần (`text[:at] + marker + text[at:]`), **không bao giờ thêm hay bớt ký tự xuống dòng**. Chỉ số dòng-không-rỗng vì thế giữ nguyên qua bước annotate. Neo tính trước hay sau annotate đều ra cùng kết quả.

### Hệ quả: client không được lấy `expected` từ EPUB

Văn bản hiển thị trong readest **khác** `translated_text` ở hai điểm: đã qua `html.escape`, và marker footnote đã thành `<sup class="fn">…</sup>`. Nên `para_text_expected` gửi lên khi PATCH **phải** lấy từ `GET /api/v1/ebooks/{slug}/chapters/{idx}`, không được lấy từ DOM của trang đang đọc. Đây là ràng buộc bắt buộc với client GĐ2, cần ghi rõ trong tài liệu API.

### Đánh đổi đã chấp nhận

Neo theo **vị trí**, không phải ID bất biến. Nếu thêm hoặc xoá hẳn một đoạn giữa chương trên PC thì mọi neo phía sau lệch một bậc, và bản EPUB đã tải về máy điện thoại thành cũ. Khi đó `para_text_expected` sẽ không khớp và API trả 409 "bản dịch đã thay đổi" thay vì ghi bừa. Đây là hành vi cố ý.

Phương án ID bất biến (thêm cột `para_id` vào DB) bị loại: nó buộc phải đổi mô hình lưu trữ từ "Markdown nguyên khối" sang "bảng đoạn văn", kéo theo `translator.py`, `bulk_transfer.py`, `glossary`, `notes` và toàn bộ editor 3 cột. Cái giá đó không tương xứng với GĐ1.

## 6. API

### OPDS

Chọn **OPDS 1.2 (Atom XML)**. Lý do: Calibre, Komga và Kavita đều phục vụ bản này, mà readest nối được cả ba. Tài liệu readest không nói rõ nó dùng 1.2 hay 2.0.

> **Việc đầu tiên của kế hoạch triển khai là đọc code readest để xác minh bản OPDS và cách nó gửi xác thực — trước khi viết feed.** Nếu readest chỉ nói OPDS 2.0 (JSON) thì `opds.py` đổi hàm sinh output, phần còn lại của thiết kế không đổi.

| Endpoint | Việc |
|---|---|
| `GET /opds` | Feed điều hướng gốc |
| `GET /opds/books` | Feed acquisition — mỗi ebook một entry |
| `GET /opds/download/{slug}.epub` | File EPUB |
| `GET /opds/cover/{slug}` | Ảnh bìa, đọc BLOB từ `ebook_covers` |

Không phân trang: 6 ebook. Thêm phân trang khi nào thực sự có hàng trăm ebook.

Quy tắc về nội dung feed:

- `<updated>` của entry = **mtime của file EPUB**, không phải `max(translated_updated_at)`. readest quyết định tải lại dựa vào trường này, mà thứ nó tải là *file*. Dùng timestamp nội dung sẽ khiến nó tải lại một file y hệt.
- Ebook **chưa build EPUB thì không xuất hiện trong feed** — thà vắng mặt còn hơn hiện ra rồi tải về lỗi.
- Ebook đã archive (`ebooks.archived = 1`) không xuất hiện, thống nhất với hành vi của trang `/`.
- EPUB cũ hơn bản dịch vẫn được phục vụ nguyên trạng. Làm mới là việc của `/automation` đã có sẵn. **Không** tự build khi phát hiện cũ: build 2907 chương trong một request HTTP sẽ treo.

### API sửa đoạn

```
GET /api/v1/ebooks/{slug}/chapters/{idx}
→ 200 {"slug", "index", "title", "paragraphs": [{"index": 0, "text": "..."}, ...]}
```

`paragraphs` sinh bằng `notes.split_paras(storage.read_translated(ch))` — cùng hàm mà `replace_para` dùng, không viết lại.

```
PATCH /api/v1/ebooks/{slug}/chapters/{idx}/paragraphs/{para_index}
     {"text": "câu đã sửa", "expected": "nguyên văn đoạn lúc client đọc"}
→ 200 {"ok": true, "index": N, "text": "..."}
```

Gọi thẳng `notes.replace_para`, không viết lại logic.

`text` rỗng → **400**, không cho xoá đoạn qua API. `replace_para` khi nhận chuỗi rỗng sẽ xoá hẳn dòng đó *rồi đánh lại chỉ số mọi đoạn phía sau*; client đang giữ chỉ số cũ sẽ sửa nhầm đoạn ở lần gọi kế tiếp. Xoá đoạn giữ nguyên ở web UI, nơi trang tự tải lại sau mỗi thao tác.

## 7. Xác thực và bảo mật

### Lưu token

Thêm cột `api_json` vào bảng `settings`, theo đúng lối cột `reader_json` đã được thêm ở schema v2 (khai báo trong `_SCHEMA_STATEMENTS` cho DB mới, và trong `_ADDED_COLUMNS` để `_ensure_columns` vá DB cũ bằng `ALTER TABLE`). `SCHEMA_VERSION` 7 → 8.

```python
@dataclass
class ApiConfig:
    token: str = ""
    cors_origins: list[str] = field(default_factory=list)
```

Token là cấu hình **toàn cục**, không per-ebook.

### Cơ chế

Chấp nhận hai dạng cùng lúc:

- **Basic** — readest gửi username/password cho OPDS. Username bỏ qua, password so với token.
- **Bearer** — cho API sửa của fork GĐ2, và cho việc thử bằng `curl`.

So khớp bằng `hmac.compare_digest` để không rò độ dài token qua thời gian phản hồi.

### Miễn trừ localhost

Request từ `127.0.0.1` / `::1` được miễn token, để web UI hiện tại và readest desktop chạy cùng máy không phải cấu hình gì.

Địa chỉ lấy từ **`request.client.host`** (địa chỉ socket thật). **Tuyệt đối không đọc `X-Forwarded-For` hay `X-Real-IP`** — client tự đặt được hai header đó, tin chúng sẽ biến miễn trừ localhost thành cửa mở toang cho cả LAN. Đây phải là một test riêng, không chỉ là một dòng bình luận.

### CORS

Danh sách origin lấy từ `api.cors_origins`, mặc định rỗng. Chỉ bản readest **web** cần — Tauri desktop và mobile gọi HTTP native, không đi qua CORS. Không bao giờ dùng `*`.

### Đặt token ở đâu

Thêm một khối vào trang Cài đặt. Vì `api.*` là cấu hình toàn cục (không per-ebook), nó thuộc nhóm ghi bằng `config_writer.update_defaults` — cùng cơ chế với khối kết nối Reader (`READER_GLOBAL_FIELDS`), chứ không phải `update_ebook`.

Khối gồm: ô token (có nút sinh token ngẫu nhiên bằng `secrets.token_urlsafe(32)`, có nút hiện/ẩn), ô danh sách CORS origin, và **URL catalog OPDS hiển thị sẵn để chép vào readest**. URL đó phải dùng địa chỉ LAN của máy chứ không phải `localhost` — vì `localhost` trên điện thoại trỏ về chính cái điện thoại đó, dán vào là readest báo lỗi kết nối mà người dùng không hiểu vì sao.

Token **không** được nhúng vào URL hiển thị. Nó đi qua ô username/password của readest. Đặt bí mật vào URL là đưa nó vào lịch sử duyệt, log server và mọi chỗ URL bị chép qua lại.

### Token không vào log

Cùng nguyên tắc `reader_client.py` đang giữ với `service_key`: token không bao giờ xuất hiện trong log job, thông báo lỗi, hay trang `/queue` và `/logs`.

## 8. Xử lý lỗi

| Tình huống | Mã | Nội dung |
|---|---|---|
| `expected` không khớp bản hiện tại | **409** | kèm đoạn hiện tại, để client hiện "ai đó đã sửa đoạn này" |
| Chưa cấu hình token, request đến từ ngoài localhost | **503** | kèm hướng dẫn bật — phân biệt rõ với "sai token" |
| Sai token | **401** | |
| Ebook / chương không tồn tại | **404** | |
| Chương chưa có bản dịch (PATCH) | **404** | "chương chưa dịch" |
| `text` rỗng | **400** | "không xoá đoạn qua API" |
| File EPUB chưa build | **404** | "chưa build EPUB" |

## 9. Test

Theo lối `tests/test_reader_sync.py`: logic thuần tách khỏi HTTP.

| File | Nội dung |
|---|---|
| `tests/test_opds.py` | Cấu trúc feed, XML hợp lệ, escape tiêu đề chứa `《》`/`&`/dấu ngoặc, entry thiếu bìa, ebook archive bị loại |
| `tests/test_epub_anchors.py` | `data-n2e-p` khớp **chính xác** `notes.split_paras`; case block nhiều dòng (đúng tình huống 161≠160); heading nhận đúng chỉ số; chương không bật cờ thì **không** có neo nào |
| `tests/test_api_auth.py` | Basic, Bearer, sai token, chưa cấu hình, miễn localhost, và **không** miễn khi `X-Forwarded-For` giả mạo |
| `tests/test_opds_routes.py` | TestClient: 401 / 503 / 404, EPUB chưa build |
| `tests/test_paragraph_patch.py` | PATCH thành công, 409 stale, 400 rỗng, 404 chương chưa dịch |

### Test khứ hồi — quan trọng nhất

Build EPUB thật từ dữ liệu dựng sẵn → giải nén, parse XHTML → lấy `data-n2e-p` của một đoạn → PATCH đoạn đó qua API → đọc lại `translated_text` từ DB → khẳng định **đúng đoạn đó đổi và không đoạn nào khác động**.

Đây là test duy nhất thực sự chứng minh cơ chế neo hoạt động. Các test còn lại chỉ chứng minh từng mảnh rời. Nó phải bao cả chương có block nhiều dòng và chương có footnote, vì đó là hai chỗ hai định nghĩa đoạn có thể lệch nhau.

## 10. Rủi ro và việc cần xác minh

| # | Rủi ro | Xử lý |
|---|---|---|
| 1 | readest có thể dùng OPDS 2.0 (JSON) thay vì 1.2 (Atom) | Đọc code readest **trước khi** viết feed. `opds.py` thuần nên chỉ đổi hàm sinh output. |
| 2 | readest có thể yêu cầu trường Atom/OPDS mà thiết kế chưa liệt kê | Thử feed bằng readest thật ngay sau khi có bản chạy được, trước khi làm tiếp API sửa. |
| 3 | Neo theo vị trí lệch khi thêm/xoá đoạn trên PC | `para_text_expected` bắt được và trả 409. Đã chấp nhận. |
| 4 | Một số tính năng readest bị khoá theo gói trả phí | Ảnh hưởng các nhà cung cấp sync bên thứ ba, không ảnh hưởng OPDS tự host. Cần xác nhận lại khi thử thật. |
| 5 | Mở novel2epub ra LAN làm lộ toàn bộ web UI, không chỉ OPDS | Nằm ngoài phạm vi GĐ1. Nếu cần, đặt sau reverse proxy hoặc Tailscale. Cần nói rõ với người dùng khi hướng dẫn bind `0.0.0.0`. |

## 11. Giai đoạn 2 — phác thảo, chưa cam kết

Fork readest, thêm đúng một tính năng: bôi đen trong lúc đọc → đọc `data-n2e-p` từ DOM foliate-js → gọi `GET` lấy `expected` → `PATCH` sửa đoạn. Giữ fork càng mỏng càng tốt để còn merge được upstream.

Spec riêng, viết sau khi GĐ1 chạy thật và cơ chế neo đã được kiểm chứng trên dữ liệu thật.
