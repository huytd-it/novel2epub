# novel2epub

Crawl truyện chữ tiếng Trung → **dịch sang tiếng Việt** → đóng gói thành **EPUB**,
kèm Web UI quản lý quy mô lớn: **hàng đợi job song song**, **thư viện ebook**,
**quản lý nguồn**, **crawl console**, **lưu trữ**, và **tự động hóa theo lịch**.

Pipeline 3 bước, mỗi bước **cache trên đĩa** nên có thể dừng và chạy lại bất cứ lúc
nào mà không crawl/dịch lại những chương đã xong (quan trọng để tiết kiệm chi phí dịch).

```
mục lục  ──crawl──▶  raw/*.md (tiếng Trung)  ──dịch──▶  translated/*.md (tiếng Việt)  ──build──▶  .epub
```

EPUB xuất ra tạo **mỗi chương = 1 spine document**, khớp với cách
[`epub-audiobook-app`](../epub-audiobook-app) tách chương để làm audiobook → video.

## Mục lục

- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
- [Sử dụng (CLI)](#sử-dụng-cli)
- [Web UI](#web-ui)
  - [Thư viện ebook](#thư-viện-ebook)
  - [Hàng đợi job (song song)](#hàng-đợi-job-song-song)
  - [Crawl console](#crawl-console)
  - [Dịch song song trên CPU (moxhimt)](#dịch-song-song-trên-cpu-moxhimt)
  - [Quản lý nguồn (site preset)](#quản-lý-nguồn-site-preset)
  - [Lưu trữ](#lưu-trữ)
  - [Tự động hóa & lịch chạy](#tự-động-hóa--lịch-chạy)
  - [Metadata EPUB đầy đủ](#metadata-epub-đầy-đủ)
- [Quy trình khuyên dùng cho truyện mới](#quy-trình-khuyên-dùng-cho-truyện-mới)
- [Hạn chế](#hạn-chế)

## Cài đặt

Yêu cầu Python ≥ 3.10.

```bash
cd novel2epub
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`crawl4ai` là dependency tùy chọn, không cài mặc định để
tránh lỗi build `lxml` trên Windows. Chỉ cài khi cần:
```bash
pip install crawl4ai && crawl4ai-setup   # cài Playwright + Chromium
```
Engine mặc định `http` chỉ cần `requests` + `beautifulsoup4`.

Engine `scrapling` (stealth/anti-bot, xem [Quản lý nguồn](#quản-lý-nguồn-site-preset)):
```bash
pip install "scrapling[fetchers]" && scrapling install
```

Backend dịch cục bộ `moxhimt` (offline, miễn phí, chạy trên CPU):
```bash
pip install ctranslate2 sentencepiece huggingface_hub
```

`fastapi`/`uvicorn`/`jinja2`/`python-multipart` chỉ cần nếu dùng Web UI (xem dưới):
```bash
python -m pip install fastapi uvicorn jinja2 python-multipart
```

> **Migration từ `firecrawl`**: engine `firecrawl` và dependency `firecrawl-py`
> đã bị loại bỏ. Nếu config cũ của bạn dùng `engine: firecrawl`, hãy đổi thành
> `engine: crawl4ai` (nếu site cần trình duyệt) hoặc `engine: http` (nếu site tĩnh),
> đồng thời xoá các dòng `api_key` / `api_url` trong nhánh `crawl`.

## Cấu hình

Toàn bộ cấu hình nằm trong **một file gộp duy nhất** `novel2epub.yaml`:

```bash
cp novel2epub.example.yaml novel2epub.yaml   # rồi chỉnh sửa
```

File có 3 khối top-level:

- `defaults` — phần DÙNG CHUNG cho mọi ebook (prompt dịch, style, output...).
- `sources` — preset theo website (selector/pattern) để tái dùng.
- `ebooks` — mỗi ebook CHỈ khai phần KHÁC với `defaults`.

Config hiệu lực của một ebook = `deep_merge(defaults, ebooks[<slug>])`.

Cạnh file `novel2epub.yaml` còn có thư mục sidecar `workspace/.n2e/` (tự tạo,
**không commit**) chứa trạng thái runtime của Web UI: lịch sử hàng đợi job
(`queue_history.json`), automation do bạn tạo (`automations.yaml`), và cờ
ebook đã lưu trữ (`library_state.json`). Xoá thư mục này an toàn — chỉ mất
lịch sử/automation, không mất dữ liệu truyện.

### Quản lý nhiều ebook

Mỗi ebook là một mục trong khối `ebooks:` (không còn file config riêng):

```yaml
ebooks:
  xich-tam-tuan-thien:
    name: "Xích Tâm Tuần Thiên"
    novel: { slug: xich-tam-tuan-thien, title: "Xích Tâm Tuần Thiên" }
    crawl: { toc_url: "https://www.shuhaige.net/17619/" }
```

CLI và Web UI chọn ebook theo slug (`-e <slug>`). Nếu chỉ có một ebook, bỏ `-e`
sẽ tự lấy ebook đầu tiên. Đã có sẵn layout cũ nhiều file? Chạy
`python scripts/migrate_to_single_yaml.py` để gộp tự động.

### `crawl` — lấy truyện

| Khóa | Ý nghĩa |
|------|---------|
| `engine` | `http` (mặc định, free) / `crawl4ai` (browser + JS) / `scrapling` (stealth/anti-bot) |
| `toc_url` | URL trang mục lục chứa danh sách link chương |
| `chapter_link_pattern` | Regex lọc link chương trên URL đầy đủ |
| `max_chapters` | Giới hạn số chương (0 = tất cả) — đặt nhỏ để test trước |
| `content_selector` | CSS selector vùng nội dung chương, vd `#content` |
| `toc_selector` | (http) CSS selector vùng danh sách chương, loại link rác |
| `encoding` | (http) bảng mã — nhiều site Trung dùng `gbk`/`gb2312` |
| `headless` / `magic` / `js_code` | (crawl4ai) trình duyệt ẩn / vượt bot detection / JS tùy chọn |
| `strip_patterns` | Regex các dòng rác cần bỏ (quảng cáo, "đọc tiếp tại...") |
| `max_workers` | Số chương tải **song song** (1 = tuần tự). Có thể đặt 5–100; bị chặn bởi `concurrency_cap` của nguồn (xem dưới) |
| `concurrency_cap` | Trần song song **cứng** cho nguồn này, độc lập với `max_workers` job yêu cầu. `0` = mặc định theo engine (20 cho `http`/scrapling `fetcher`, 5 cho `crawl4ai`/scrapling `stealthy`/`dynamic`) |

**Mẹo tìm selector:** mở chương trong trình duyệt → F12 → chuột phải phần nội
dung → Inspect → xem `id`/`class` của thẻ bao quanh.

**Khi nào dùng `crawl4ai`?** Khi engine `http` bị site redirect sang trang xác
minh "tôi không phải bot" hoặc trả nội dung rỗng do load bằng JavaScript —
`crawl4ai` chạy trình duyệt Chromium thật (qua Playwright) nên vượt được các
chặn đó. Đổi `crawl.engine: crawl4ai` là dùng được ngay, các khóa `toc_url`,
`content_selector`, `chapter_link_pattern`... giữ nguyên ý nghĩa.

**Khi nào dùng `scrapling`?** Khi `crawl4ai` vẫn bị chặn (site có Cloudflare
Turnstile, fingerprint TLS chặt) hoặc bạn muốn crawl **nhanh + song song nhiều
chương cùng lúc** mà không cần browser nặng. Xem chi tiết 3 mode ở
[Quản lý nguồn](#quản-lý-nguồn-site-preset).

### `translate` — phần quan trọng nhất

`type` chọn engine dịch:

- **`cli`** *(mặc định)* — gọi một **AI CLI bất kỳ**, rẻ/miễn phí:

  ```yaml
  translate:
    type: cli
    cli:
      command: "opencode run"     # hoặc: llm -m gpt-4o-mini  /  ollama run qwen2.5
      model: "cliproxyapi/gpt-5.5" # tùy chọn; opencode nhận dạng provider/model
      mode: stdin                 # prompt đưa vào qua stdin (hợp văn bản dài)
      prompt_template: |          # đã có sẵn prompt "edit" chuẩn convert truyện
        ...
  ```

  `prompt_template` mặc định đã mã hóa các **nguyên tắc edit truyền thống**
  (tên riêng để Hán Việt, chọn ngôi xưng tiếng Việt, đảo trật tự câu cho tự
  nhiên...). `{text}` = nội dung cần dịch, `{glossary}` = bảng thuật ngữ.
  Với `opencode`, dùng `command: "opencode run"`; nếu đặt `model`, chương trình
  sẽ tự thêm `--model <provider/model>` vào lệnh.

  Bạn cũng có thể cấu hình thêm `style`, `glossary_files`, `retry`, `chunk` để
  phù hợp từng truyện và từng model. `max_workers > 1` sẽ dịch nhiều chương
  song song (mỗi luồng gọi CLI riêng).

- **`google`** — Google Translate miễn phí (`deep-translator`), nhanh nhưng văn
  phong kém tự nhiên, hay sai tên riêng. Cũng tôn trọng `max_workers`.

- **`moxhimt`** — model NMT cục bộ (CTranslate2 + SentencePiece), **chạy offline
  hoàn toàn trên CPU**, không cần API/key, không cần GPU. Xem
  [Dịch song song trên CPU](#dịch-song-song-trên-cpu-moxhimt).

- **`none`** — không dịch, giữ tiếng Trung (để test bước crawl/build).

**Bảng thuật ngữ (`glossary`)** — đóng vai trò như `Name.txt` của Quick Translator:
giữ nhất quán tên nhân vật / công pháp / địa danh. Áp dụng cả trong prompt cho LLM
lẫn thay thế literal sau khi dịch.

```yaml
  glossary:
    "陆压": "Lục Áp"
    "金丹": "Kim Đan"
```

## Sử dụng (CLI)

```bash
# Chọn ebook bằng -e <slug> (bỏ -e sẽ lấy ebook đầu tiên trong khối ebooks:).
# Liệt kê các ebook đang có:
python -m novel2epub list

# Chạy từng bước (khuyên dùng — kiểm tra kết quả mỗi bước):
python -m novel2epub -e xich-tam-tuan-thien crawl       # lấy mục lục + nội dung chương
python -m novel2epub -e xich-tam-tuan-thien translate   # dịch các chương đã crawl
python -m novel2epub -e xich-tam-tuan-thien build        # đóng gói EPUB

# Chỉ lấy metadata + toàn bộ mục lục/chapter list, không tải nội dung chương:
python -m novel2epub -e xich-tam-tuan-thien toc
python -m novel2epub -e xich-tam-tuan-thien meta         # dịch title/author/description theo rule Hán Việt

# Xem/lọc/sort danh sách chương (Web UI dùng cùng table này):
python -m novel2epub -e xich-tam-tuan-thien chapters --sort title --search "章" --filter raw:no

# Chọn range theo danh sách đang sort/filter; --force = override old cache:
python -m novel2epub -e xich-tam-tuan-thien crawl --sort title --search "章" --range 1:3
python -m novel2epub -e xich-tam-tuan-thien translate --sort source --range 1:1 --force

# AI đánh giá glossary + bản dịch (chỉ xem, không sửa file):
python -m novel2epub -e xich-tam-tuan-thien evaluate --from 1 --to 2

# Hoặc chạy tất cả:
python -m novel2epub -e xich-tam-tuan-thien run
python -m novel2epub -e xich-tam-tuan-thien translate --missing
python -m novel2epub -e xich-tam-tuan-thien translate --chapter 12
```

Dữ liệu lưu tại `data/<slug>/`:

```
data/ten-truyen/
  manifest.json         # danh sách chương + tiêu đề đã dịch
  raw/0001.md           # bản tiếng Trung đã crawl
  translated_mt/0001.md # snapshot máy dịch gốc, KHÔNG bị ghi đè khi biên tập tay
  translated/0001.md    # bản tiếng Việt đã biên tập — build/EPUB đọc từ đây
```

Có thể **mở trực tiếp** các file `translated/*.md` để soát/sửa tay trước khi
`build` — chính là khâu "edit" cuối cùng.

## Web UI

```bash
python -m pip install fastapi uvicorn jinja2 python-multipart
uvicorn app.main:app --reload --port 8010
```

Mở `http://127.0.0.1:8010`. Giao diện dùng layout **rộng, linh hoạt** (tận dụng
màn hình lớn cho bảng/thẻ dữ liệu) và hỗ trợ **theme sáng/tối** (nút 🌓 ở góc
trên, tự nhận `prefers-color-scheme`, nhớ lựa chọn qua lần sau).

Thanh điều hướng trên cùng có 4 mục: **Thư viện** (trang chủ), **Nguồn**,
**Lưu trữ**, **Tự động hóa** — cộng với chỉ báo hàng đợi job (⏳, link sang
`/queue`).

Biến môi trường liên quan: `NOVEL2EPUB_FILE` — đường dẫn file cấu hình gộp
(mặc định `novel2epub.yaml`).

### Thư viện ebook

Trang chủ hiển thị mỗi ebook dưới dạng **thẻ tiến độ** (số chương, đã crawl,
đã dịch, có EPUB chưa) với hành động nhanh: mở, cài đặt, export config, tải
EPUB, lưu trữ/bỏ lưu trữ, gỡ.

- **Bulk action**: tick nhiều ebook → chọn crawl/dịch/build/chạy tất cả → áp
  dụng cho tất cả ebook đã tick trong 1 lần bấm (mỗi ebook enqueue 1 job riêng).
- **Lưu trữ ebook** (archive): ẩn ebook không còn cập nhật khỏi trang chủ mà
  không xoá dữ liệu — bấm "Hiện N đã lưu trữ" để xem lại.
- **Export/Import config**: tải file YAML cấu hình hiệu lực của 1 ebook, hoặc
  nhập 1 file YAML để tạo ebook mới nhanh (vd nhân bản cấu hình giữa 2 máy).

### Hàng đợi job (song song)

Crawl và dịch chạy trên **2 nhóm worker độc lập** (mỗi nhóm N luồng, cấu hình
qua `app.state.job`), nên có thể vừa crawl ebook A vừa dịch ebook B cùng lúc.
Job mới luôn được **đưa vào hàng đợi** (không còn báo lỗi "đang bận") — trang
`/queue` cho thấy job đang chạy, đang đợi (kèm vị trí), và lịch sử, với nút
**Hủy / Retry**. Riêng `build`/`run` chiếm **độc quyền** crawl + dịch (đợi cả
2 nhóm rảnh rồi mới chạy, chặn job crawl/dịch mới trong lúc nó chạy) vì
`run` tự gọi crawl → dịch → build nối tiếp.

### Crawl console

Trong trang ebook, mục **Crawl console** tính sẵn số chương "thiếu/lỗi" (chưa
crawl được, hoặc file rỗng/quá ngắn) và cho **Retry đúng những chương đó**
bằng 1 nút — không cần tự dò range. Mục "Tùy chọn crawl nâng cao" cho đổi
`engine`/`delay`/`retry`/`force` **chỉ cho lượt chạy này**, không ghi đè cấu
hình đã lưu của ebook.

Crawl song song được **giới hạn theo nguồn** (`crawl.concurrency_cap`, xem
bảng ở trên) và có **bộ điều tiết thích ứng**: tự giảm số luồng khi gặp dồn
dập lỗi 429/anti-bot, rồi tăng dần lại khi ổn định — cộng với jitter giữa các
request cùng domain để giảm khả năng bị site phát hiện.

### Dịch song song trên CPU (moxhimt)

Máy **không có GPU rời (CUDA)** vẫn dịch nhanh hàng loạt nhờ CTranslate2 chạy
trên CPU. Thay vì mở 1 luồng Python/chương (dễ tranh CPU), `moxhimt` gom toàn
bộ đoạn của 1 chương thành **1 lượt `translate_batch`** và để CTranslate2 tự
song song hóa nội bộ qua 2 tham số:

```yaml
translate:
  type: moxhimt
  moxhimt:
    inter_threads: 0   # 0 = tự suy theo số nhân CPU (mặc định an toàn)
    intra_threads: 0   # inter × intra <= số nhân vật lý máy
```

Để trống (`0`) là dùng được ngay — tự tính theo `os.cpu_count()`. Máy nhiều
nhân (vd 16–20 nhân) có thể tăng cả 2 lên (vd `intra_threads: 4`, `inter_threads`
tự co theo) để tận dụng hết CPU khi dịch hàng trăm chương. `translate.max_workers`
**không áp dụng** cho `moxhimt` (cố định 1 — song song đến từ CT2, không phải
luồng-mỗi-chương); `cli`/`google` vẫn dùng `max_workers` như bình thường.

### Quản lý nguồn (site preset)

Trang `/sources` quản lý preset theo website (selector/pattern dùng lại khi
thêm ebook mới):

- **Nhân bản** 1 preset để chỉnh riêng cho site tương tự, không phải gõ lại từ đầu.
- **Test (dry-run)**: nhập 1 URL mục lục mẫu, hệ thống thử `fetch_toc` + tải 1
  chương đầu — **không ghi gì xuống đĩa** — báo tiêu đề/số chương/mẫu nội dung
  hoặc lý do lỗi. Kết quả lần test gần nhất hiển thị ngay trong bảng preset.
- **Export/Import**: tải toàn bộ preset ra 1 file YAML để chia sẻ/sao lưu;
  nhập lại preset từ file, trùng tên thì chọn ghi đè hoặc đổi tên tự động.
- Xoá preset đang được ebook nào dùng sẽ bị **chặn** kèm danh sách ebook đó.

**3 engine, khi nào dùng cái nào:**

| Engine | Tốc độ/Tải | Vượt bot | Hợp dùng khi |
|---|---|---|---|
| `http` | Rất nhẹ, concurrency cao | Không | Site tĩnh, không chặn |
| `crawl4ai` | Nặng (Chromium qua Playwright) | Trung bình | Site cần render JS |
| `scrapling` mode `fetcher` | Nhẹ, concurrency cao | Giả TLS fingerprint | Site chỉ chặn theo fingerprint, không cần JS |
| `scrapling` mode `stealthy` | Nặng (browser Camoufox) | Cao, qua được Cloudflare Turnstile | Site có Cloudflare/anti-bot mạnh |
| `scrapling` mode `dynamic` | Nặng nhất (Playwright đầy đủ) | Cao | Site cần JS phức tạp + vượt bot |

`novel2epub.example.yaml` có sẵn các preset mẫu dùng `scrapling`:
`scrapling-fetcher`/`scrapling-stealth` (khung trống để bạn điền `url`/`domains`),
và preset cụ thể `qidian-scrapling`, `jjwxc-scrapling`, `69shuba-scrapling` (bản
thay thế nhẹ hơn cho preset `crawl4ai` cùng site khi vẫn bị chặn hoặc cần crawl
nhanh nhiều chương song song). Mỗi preset `scrapling`/`crawl4ai` đều có
`concurrency_cap` riêng — đặt thấp (4–6) cho mode dùng browser thật để tránh
ngốn RAM (~300–600MB/instance), đặt cao (15–20+) cho `http`/`fetcher`.

### Lưu trữ

Trang `/storage` cho thấy dung lượng đĩa từng ebook theo từng loại (raw / MT
snapshot / bản đã biên tập / glossary / EPUB) cùng tổng dung lượng toàn bộ thư
viện. Hành động dọn dẹp đều có xác nhận và **không bao giờ đụng vào bản đã
biên tập tay** (`translated/`):

- **Xóa raw** — xoá bản tiếng Trung gốc (giữ được vì có thể crawl lại).
- **Xóa MT snapshot** — xoá `translated_mt/` (bản máy dịch gốc dùng để so sánh).
- **Xóa EPUB** — xoá file `.epub` đã build (build lại bất cứ lúc nào).
- **Đóng gói .zip** — tải toàn bộ dữ liệu 1 ebook (manifest + raw + bản dịch +
  glossary + config + EPUB nếu có) thành 1 file để sao lưu/chuyển máy.

### Tự động hóa & lịch chạy

Trang `/automation` định nghĩa **chuỗi bước** chạy theo lịch hoặc bấm tay cho
từng ebook: chọn các bước theo thứ tự trong `fetch-toc` → `crawl-new` →
`translate-pending` → `build`, đặt lịch `manual` (chỉ bấm tay) hoặc
`daily@HH:MM` (chạy 1 lần/ngày vào giờ đó). Một daemon thread poll mỗi ~30s,
tự enqueue automation tới hạn **qua đúng hàng đợi job** ở trên (không có
luồng "ngầm" riêng, không tranh tài nguyên với job tay).

Mỗi lần chạy ghi lại **thời điểm** và **kết quả** (thành công / lỗi / một
phần — nếu 1 bước giữa chuỗi lỗi, các bước trước đó vẫn được tính đã xong).

### Metadata EPUB đầy đủ

Trang cài đặt ebook (`/ebooks/<slug>/settings`) có đủ field để đóng gói EPUB
đúng chuẩn, hiển thị tốt trên Calibre/máy đọc sách:

| Field | Ánh xạ vào EPUB |
|---|---|
| Nhà xuất bản | `dc:publisher` |
| Ngày xuất bản | `dc:date` |
| Chủ đề (nhiều dòng/phẩy) | 1 `dc:subject` / chủ đề |
| Bộ sách + Số thứ tự | `calibre:series` + `calibre:series_index` |
| Đã thêm (tự ghi khi tạo ebook) | `calibre:timestamp` |
| Định danh (urn:uuid) | `dc:identifier` — tự sinh 1 lần, **ổn định qua các lần build lại**, có thể tự ghi đè |
| Miêu tả | `dc:description` |

Field để trống sẽ **không** xuất hiện trong EPUB (không ghi giá trị rỗng).
Kích thước file EPUB hiển thị tự động (tính từ file trên đĩa), không phải field
nhập tay.

## Quy trình khuyên dùng cho truyện mới

1. Đặt `max_chapters: 2` và `translate.type: none`, chạy `crawl` → kiểm tra
   `raw/*.md` lấy đúng nội dung (chỉnh `content_selector`/`encoding` nếu cần).
   Nếu dùng Web UI: thử **Test (dry-run)** trên preset nguồn trước khi gắn vào
   ebook, tránh tốn thời gian crawl cả truyện chỉ để phát hiện sai selector.
2. Đổi `translate.type: cli` (hoặc `moxhimt` nếu muốn offline/miễn phí), chạy
   `translate` 2 chương → xem chất lượng dịch, bổ sung `glossary` cho tên
   riêng hay bị sai.
3. Đặt `max_chapters: 0` (toàn bộ); nếu nguồn ổn định, tăng `crawl.max_workers`
   (vd 10–30 cho `http`/scrapling `fetcher`) để crawl nhanh nhiều chương song
   song — `concurrency_cap` của nguồn sẽ tự giới hạn an toàn. Chạy `run`.

Khi ebook đã ổn, có thể dùng UI để chỉnh glossary, soát chương lỗi (Crawl
console → Retry), build lại ngay sau khi sửa tay, hoặc đặt **automation**
`daily@HH:MM` để tự crawl chương mới + dịch + build hàng ngày.

## Hạn chế

- Engine `http` chỉ đọc HTML tĩnh; site dùng JavaScript/chống bot nên thử
  `engine: crawl4ai` hoặc `scrapling`; chương VIP/cần đăng nhập cần nguồn khác.
- Chất lượng dịch phụ thuộc model của AI CLI bạn cắm vào (với `type: cli`),
  hoặc giới hạn của model NMT cục bộ (với `type: moxhimt`).
- `moxhimt` chỉ tối ưu cho CPU — không có đường chạy GPU/CUDA theo thiết kế;
  máy có GPU mạnh nên dùng `type: cli` qua 1 AI CLI để tận dụng GPU đó.
- Tôn trọng bản quyền & điều khoản của trang nguồn; chỉ dùng cho mục đích cá nhân.
