## Context

Trang ebook (`app/templates/ebook.html`) đã có sẵn cơ chế chọn nhiều chương bằng checkbox (`chapter-check`, `check-all`) và một thanh `selected-actions` với các thao tác batch (crawl/dịch/build/dịch tiêu đề/glossary suggest). Các endpoint batch hiện có (`/api/ebooks/{slug}/batch/...` trong `app/routes/chapters.py`) gom `indexes` dạng comma-separated rồi chạy job nền.

Bản dịch hiện hành nằm ở `translated/` (file build/EPUB đọc), snapshot bản máy nằm ở `translated_mt/`. `Storage` cung cấp `read_translated` / `write_translated` / `has_translated` theo `Chapter`.

Hiện chưa có cách lấy nhiều chương ra một khối để biên tập ngoài hệ thống (bằng web chat AI) rồi nạp ngược trở lại. Thao tác thủ công từng chương dễ lẫn thứ tự, mất đồng bộ với manifest.

## Goals / Non-Goals

**Goals:**
- Xuất bản dịch (`translated/`) của các chương đã chọn thành một khối text có marker + prompt biên tập (chuẩn theo `docs/rule.md`) + glossary hiện có, copy-paste được lên web chat AI.
- Xuất CẢ bản gốc (`raw/`) của các chương chưa dịch (hoặc muốn dịch lại) để dịch bằng web chat AI, dùng prompt dịch nhất quán với `config.DEFAULT_PROMPT` (prompt dịch chính thức của AI backend trong app).
- Bản biên tập/dịch hay và chính xác: prompt hướng dẫn AI theo nguyên tắc edit/dịch, giữ tên riêng nhất quán nhờ đính kèm glossary đang dùng.
- Web chat tự sinh glossary xuyên suốt; import parse khối glossary và merge vào `names.txt`/`vietphrase.txt`.
- Nhập lại khối text đã biên tập/dịch, parse theo marker, preview diff theo chương, ghi đè an toàn vào `translated/` (và backfill `translated_mt/` nếu chương chưa có snapshot — tức lần dịch đầu).
- Round-trip ổn định: import tách đúng chương kể cả khi AI thay đổi nội dung bên trong (miễn là giữ marker).
- Tách logic format/parse marker + glossary thành module thuần Python để unit-test độc lập với web.

**Non-Goals:**
- KHÔNG gọi API AI từ server (toàn bộ việc biên tập/dịch do người dùng làm trên web chat bên ngoài).
- KHÔNG ghi đè raw (`raw/`) — luồng raw chỉ ĐỌC để xuất, không sửa.
- KHÔNG tự động merge/diff thông minh ở mức từng dòng; preview chỉ ở mức chương (đổi/không đổi).
- KHÔNG hỗ trợ xuất nhiều ebook cùng lúc.

## Decisions

### 1. Định dạng marker round-trip: tiêu đề Markdown

Dùng tiêu đề Markdown (`##`) chứa `index`, thay vì marker `=====` thô:

```
## Chương 12
<nội dung bản dịch chương 12>

## Chương 13
<nội dung bản dịch chương 13>
```

- Parse bằng regex chấp nhận cả heading Markdown lẫn marker `=====` cũ: `^(?:#{1,6}\s*|={3,}\s*)CHƯƠNG\s+(\d+)\b` (case-insensitive), nội dung chương = phần text giữa hai tiêu đề.
- **Vì sao Markdown**: AI/LLM được huấn luyện nặng trên văn bản Markdown nên nhận diện và *giữ nguyên* cấu trúc heading rất đáng tin cậy — tốt hơn ký hiệu tự chế `=====`; đồng thời cho phép xuất thẳng dạng file `.md` để **tải xuống** hoặc **upload** lên web chat AI (nhiều chat UI nhận file `.md`/`.txt` đính kèm, ổn định hơn copy-paste khối text khổng lồ vào ô chat).
- Tiêu đề chứa `index` (không dựa vào tên chương) nên không phụ thuộc thứ tự và không vỡ khi AI dịch lại tiêu đề.
- **Tương thích ngược**: marker `=====` của các bản xuất trước đó vẫn được `parse_import`/`parse_glossary` nhận diện (cùng regex, alternation `#{1,6}|={3,}`), không cần migrate dữ liệu cũ.
- **Thay thế đã cân nhắc**: (a) JSON — chính xác hơn nhưng AI hay làm hỏng escape/format, người dùng khó sửa tay; (b) marker dùng tiêu đề chương thay vì index — không ổn định vì tiêu đề có thể trùng/bị AI dịch lại; (c) giữ nguyên `=====` — đổi sang Markdown vì AI xử lý heading tốt hơn và hỗ trợ xuất file `.md` tự nhiên hơn. → Chọn heading Markdown mang `index`.

### 2. Module logic riêng `novel2epub/bulk_transfer.py`

Hai hàm thuần: `build_export(chapters_with_text, prompt=...) -> str` và `parse_import(text) -> list[(index, content)]` (kèm hàm validate đối chiếu tập index mong đợi). Routes chỉ lo I/O + job/permission.
- **Vì sao**: dễ unit-test các ca biên (thiếu marker, dư/thiếu chương, marker lạ) mà không cần dựng web.

### 3. Luồng import 2 bước: preview → confirm

- `POST /api/ebooks/{slug}/batch/export`: nhận `indexes`, trả `{text, skipped}`.
- `POST /api/ebooks/{slug}/batch/import` với `mode=preview`: parse + validate, trả danh sách chương sẽ cập nhật / không đổi / lỗi, KHÔNG ghi.
- `POST .../import` với `mode=confirm`: ghi đè `translated/` cho các chương khớp.
- **Vì sao**: ghi đè bản dịch là thao tác khó hoàn tác; preview trước khi ghi tránh mất công sức biên tập do dán nhầm.
- **Thay thế đã cân nhắc**: ghi thẳng — bỏ vì rủi ro mất dữ liệu khi marker lỗi/dán nhầm ebook.

### 4. Prompt biên tập + glossary round-trip

Khối xuất có cấu trúc 3 phần: **(a) prompt** → **(b) glossary hiện có** → **(c) các chương có marker**.

- **Prompt** chắt lọc `docs/rule.md` thành chỉ thị ngắn (đối chiếu bản gốc; ngôi xưng theo quan hệ, hạn chế "ta–ngươi"; chỉnh ngữ pháp/trật tự từ Việt; cân bằng Hán–Việt; tên riêng Hán Việt viết hoa; giữ tiêu đề chương), viết dạng Markdown (`#`/`##` heading, numbered list), và yêu cầu AI xuất thêm mục `## GLOSSARY` ở cuối. Lưu prompt thành hằng/template trong `bulk_transfer.py` (không hardcode rải rác).
- **Glossary hiện có** đọc từ `Storage.read_glossary_file("names.txt"/"vietphrase.txt")`, render dạng Markdown `### Tên riêng`/`### Thuật ngữ` với bullet `- source = target`, có chỉ thị "dùng đúng các tên này" → bảo đảm nhất quán giữa các lần export.
- **Khối glossary AI sinh** dùng heading Markdown riêng để import tách:

```
## GLOSSARY

### NAMES
- 萧炎 = Tiêu Viêm

### VIETPHRASE
- 斗气 = Đấu khí
```

- Import: `parse_glossary(text) -> {names: {...}, vietphrase: {...}}` (chấp nhận cả `### NAMES` lẫn `[NAMES]` cũ, có/không bullet `-`), rồi merge qua hàm append sẵn có (tương đương `_append_glossary_entry` trong `app/routes/glossary.py`: dedup theo `source`, format `source = target | note`).
- **Vì sao tách module + tái dùng append**: giữ một nguồn sự thật cho format glossary; consistency "xuyên suốt" đạt được bằng cách *luôn* bơm glossary hiện có vào prompt mỗi lần export (web chat vô trạng thái giữa các phiên).
- **Thay thế đã cân nhắc**: nhúng nguyên văn `docs/rule.md` vào prompt — bỏ vì quá dài, tốn ngữ cảnh web chat; chỉ chắt lọc các chỉ thị actionable.

### 5. UI: tái dùng thanh `selected-actions` + cửa sổ riêng (không phải `<dialog>`)

Thêm 2 nút "Xuất chương đã chọn" và "Nhập bản biên tập" vào thanh selected-actions; mở **cửa sổ trình duyệt mới** (`window.open` + dựng DOM trực tiếp, không document.write) thay vì `<dialog>` modal. Xuất: textarea read-only + nút "Copy toàn bộ" + nút "Tải file .md" (Blob + `<a download>`). Nhập: textarea dán + nút "Chọn file .md..." (đọc qua `FileReader`) + nút preview/confirm. Tái dùng JS gom index từ `.chapter-check` đã tick (giống `batch-form`).
- **Vì sao không dùng `<dialog>`**: dự án dùng Pico CSS v2, framework này style mọi `<dialog[open]>` thành `display:flex` phủ toàn viewport và kỳ vọng nội dung bọc trong `<article>` mới render thành "card" — nếu không, modal hiện ra trống trơn/full màn hình (bug đã gặp thực tế). Mở cửa sổ riêng né hoàn toàn việc này, đồng thời cho không gian rộng hơn để review export lớn (có thể hàng trăm KB) và hỗ trợ tải file/upload file tự nhiên hơn so với một modal nhỏ.
- **window.open() chạy script trong realm của trang gốc**: các hàm tạo DOM/gắn event listener cho cửa sổ mới được gọi trực tiếp từ script của trang ebook (không qua `document.write` + thẻ `<script>` riêng), nên `fetch`, `FormData` dùng thẳng global của trang gốc (không cần lo base URL của `about:blank`); chỉ `clipboard`/`FileReader`/`Blob`/`URL` dùng tiền tố `win.` vì các API này cần chạy trong realm/focus của cửa sổ đang hiển thị.

### 6. Xuất raw để dịch (`source=translated|raw`)

Ngoài xuất bản dịch để biên tập, thêm chế độ xuất **bản gốc** (`raw/`) cho chương chưa dịch (hoặc cần dịch lại) để dịch hẳn bằng web chat AI thay vì backend AI cấu hình trong app.

- `POST /api/ebooks/{slug}/batch/export` nhận thêm `source` (`"translated"` mặc định | `"raw"`). `source=raw` đọc `storage.read_raw(ch)` (yêu cầu `has_raw`), dùng `ch.title_zh` làm tiêu đề chương trong heading, và chọn `TRANSLATE_PROMPT` thay vì `EDIT_PROMPT`.
- **`TRANSLATE_PROMPT` bám sát `config.DEFAULT_PROMPT`**: nguyên tắc 1-7 lấy gần như nguyên văn từ `DEFAULT_PROMPT` (prompt dịch chính thức của backend AI `openai` trong app) — chỉ đổi phần đầu/cuối cho phù hợp batch nhiều chương theo Markdown (heading `## Chương N`, khối `## GLOSSARY` ở cuối). **Vì sao**: người dùng có thể dịch một phần truyện qua backend AI cấu hình sẵn, một phần qua web chat thủ công (vd khi muốn dùng model khác/tiết kiệm chi phí) — hai đường phải cho ra văn phong/nguyên tắc nhất quán, không lệch tông.
- **Backfill `translated_mt/` khi confirm import**: nếu chương CHƯA có `translated_mt/` (vd vừa dịch lần đầu qua raw-export), ghi luôn cả `translated_mt/` lẫn `translated/` — mô phỏng đúng hành vi của pipeline dịch bình thường (luôn ghi cả 2 file ở lần dịch đầu, xem `CLAUDE.md` mục Machine-translation snapshot). Nếu đã có `translated_mt/` (đang biên tập/dịch lại), giữ nguyên — không phá snapshot dùng để so sánh trong editor 3 cột.
- **Thay thế đã cân nhắc**: viết `TRANSLATE_PROMPT` từ đầu độc lập với `DEFAULT_PROMPT` — bỏ vì dễ lệch nguyên tắc dịch giữa 2 đường (AI backend vs web chat thủ công) theo thời gian khi một bên được chỉnh mà bên kia quên cập nhật.

## Risks / Trade-offs

- [AI sửa/xóa marker khi trả kết quả] → Prompt nêu rõ "giữ nguyên marker"; parse khoan dung khoảng trắng và biến thể (`=+`); bước preview phát hiện chương thiếu để người dùng dán lại.
- [Người dùng dán nhầm khối của ebook khác] → Validate `index` phải thuộc manifest hiện tại; báo lỗi rõ và chỉ ghi chương khớp sau xác nhận.
- [Khối xuất quá lớn vượt giới hạn ngữ cảnh của web chat] → Không chặn ở server, nhưng hiển thị tổng số chương + độ dài ký tự để người dùng tự chia nhỏ lần chọn; marker chứa `index` nên import nhiều lần (từng phần) vẫn ghép đúng.
- [Nội dung chương vô tình chứa dòng giống marker] → Chọn marker hiếm gặp (dấu `=` lặp + chữ "CHƯƠNG" hoa + số); rủi ro thấp với truyện dịch; có thể escape nếu phát hiện trong tương lai.
- [AI bịa tên/đổi tên đã chốt làm sai glossary] → Đính kèm glossary hiện có + chỉ thị "dùng đúng"; bước preview hiển thị mục glossary sẽ thêm để người dùng kiểm trước khi merge; chỉ thêm, không tự ghi đè mục cũ.
- [AI quên xuất khối GLOSSARY] → Không chặn được phía server; coi glossary là phần tùy chọn — không có khối thì import vẫn chạy, chỉ bỏ qua merge.
