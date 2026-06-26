# novel2epub

Crawl truyện chữ tiếng Trung → **dịch sang tiếng Việt** → đóng gói thành **EPUB**,
kèm Web UI quản lý quy mô lớn: **hàng đợi job song song**, **thư viện ebook**,
**crawl console**, **lưu trữ**, và **tự động hóa theo lịch**.

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
- [Hạn chế](#hạn-chế)

## Cài đặt

Yêu cầu Python ≥ 3.10.

```bash
cd novel2epub
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
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

## Cấu hình

Toàn bộ cấu hình nằm trong **một file gộp duy nhất** `novel2epub.yaml`:

```bash
cp novel2epub.example.yaml novel2epub.yaml   # rồi chỉnh sửa
```

File có 2 khối top-level:

- `defaults` — phần DÙNG CHUNG cho mọi ebook (prompt dịch, style, output...).
- `ebooks` — mỗi ebook CHỈ khai phần KHÁC với `defaults`.

Config hiệu lực của một ebook = `deep_merge(defaults, ebooks[<slug>])`.

Cạnh file `novel2epub.yaml` còn có thư mục sidecar `.n2e/` (tự tạo,
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
sẽ tự lấy ebook đầu tiên.

### `crawl` — lấy truyện

Engine duy nhất: **`scrapling`** với 3 mode:

| Mode | Backend | Concurrency | Khi nào dùng |
|------|---------|-------------|--------------|
| `fetcher` (mặc định) | HTTP requests + TLS fingerprint giả | Cao (20+) | Site tĩnh, chỉ chặn theo fingerprint |
| `stealthy` | Camoufox browser (ẩn) | Thấp (4-6) | Site có Cloudflare Turnstile / anti-bot mạnh |
| `dynamic` | Playwright (trình duyệt đầy đủ) | Thấp (4-6) | Site cần JS phức tạp + vượt bot |

| Khóa | Ý nghĩa |
|------|---------|
| `toc_url` | URL trang mục lục chứa danh sách link chương |
| `chapter_link_pattern` | Regex lọc link chương trên URL đầy đủ |
| `max_chapters` | Giới hạn số chương (0 = tất cả) — đặt nhỏ để test trước |
| `content_selector` | CSS selector vùng nội dung chương, vd `#content` |
| `scrapling.mode` | `fetcher` / `stealthy` / `dynamic` |
| `scrapling.solve_cloudflare` | Chỉ dùng cho `stealthy` mode |
| `scrapling.impersonate` | TLS fingerprint cho `fetcher` (vd `"chrome"`) |
| `strip_patterns` | Regex các dòng rác cần bỏ (quảng cáo, "đọc tiếp tại...") |
| `max_workers` | Số chương tải **song song** (1 = tuần tự). Có thể đặt 5–100; bị chặn bởi `concurrency_cap` |
| `concurrency_cap` | Trần song song **cứng** cho nguồn này. `0` = mặc định theo mode (20 cho `fetcher`, 5 cho `stealthy`/`dynamic`) |

**Mẹo tìm selector:** mở chương trong trình duyệt → F12 → chuột phải phần nội
dung → Inspect → xem `id`/`class` của thẻ bao quanh.

### `translate` — phần quan trọng nhất

`type` chọn engine dịch:

- **`moxhimt`** *(mặc định)* — model NMT cục bộ (CTranslate2 + SentencePiece), **chạy offline
  hoàn toàn trên CPU**, không cần API/key, không cần GPU. Miễn phí, tối ưu cho
  tiểu thuyết mạng/tiên hiệp.

- **`openai`** — gọi AI qua HTTP theo chuẩn OpenAI-Compatible (OpenAI, OpenRouter, Ollama, LM Studio, vLLM, llama.cpp server...):

  ```yaml
  translate:
    type: openai
    openai:
      base_url: "http://localhost:11434/v1"  # Ollama local
      api_key: ""
      model: "gpt-4o-mini"
      prompt_template: |
        ...
  ```

- **`google`** — Google Translate miễn phí (`deep-translator`), nhanh nhưng văn
  phong kém tự nhiên, hay sai tên riêng.

- **`none`** — không dịch, giữ tiếng Trung (để test bước crawl/build).

**Bảng thuật ngữ (`glossary`)** — giữ nhất quán tên nhân vật / công pháp / địa danh:

```yaml
  glossary:
    "陆压": "Lục Áp"
    "金丹": "Kim Đan"
```

## Sử dụng (CLI)

```bash
python -m novel2epub list

python -m novel2epub -e xich-tam-tuan-thien crawl
python -m novel2epub -e xich-tam-tuan-thien translate
python -m novel2epub -e xich-tam-tuan-thien build

python -m novel2epub -e xich-tam-tuan-thien toc
python -m novel2epub -e xich-tam-tuan-thien meta

python -m novel2epub -e xich-tam-tuan-thien chapters --sort title --filter raw:no

python -m novel2epub -e xich-tam-tuan-thien evaluate --from 1 --to 2

python -m novel2epub -e xich-tam-tuan-thien run
python -m novel2epub -e xich-tam-tuan-thien translate --missing
python -m novel2epub -e xich-tam-tuan-thien translate --chapter 12
```

Dữ liệu lưu tại `data/<slug>/`:

```
data/ten-truyen/
  manifest.json
  raw/0001.md
  translated_mt/0001.md
  translated/0001.md
```

Có thể **mở trực tiếp** các file `translated/*.md` để soát/sửa tay trước khi
`build` — chính là khâu "edit" cuối cùng.

## Web UI

```bash
uvicorn app.main:app --reload --port 8010
```

Mở `http://127.0.0.1:8010`.

### Thư viện ebook

Trang chủ hiển thị mỗi ebook dưới dạng **thẻ tiến độ** với hành động nhanh: mở,
cài đặt, export config, tải EPUB, lưu trữ/bỏ lưu trữ, gỡ.

- **Bulk action**: tick nhiều ebook → chọn crawl/dịch/build/chạy tất cả.
- **Lưu trữ ebook** (archive): ẩn ebook không còn cập nhật.
- **Export/Import config**: tải file YAML cấu hình, hoặc nhập file YAML.

### Hàng đợi job (song song)

Crawl và dịch chạy trên **2 nhóm worker độc lập**. Job mới được **đưa vào hàng đợi**
— trang `/queue` cho thấy job đang chạy, đang đợi, và lịch sử, với nút Hủy / Retry.

### Crawl console

Trong trang ebook, Crawl console tính số chương thiếu/lỗi và cho Retry đúng những
chương đó bằng 1 nút. Crawl song song có bộ điều tiết thích ứng: tự giảm số luồng
khi gặp lỗi 429/anti-bot, rồi tăng dần lại khi ổn định.

### Dịch song song trên CPU (moxhimt)

Máy không có GPU vẫn dịch nhanh nhờ CTranslate2 chạy trên CPU. `moxhimt` gom toàn
bộ đoạn của 1 chương thành 1 lượt `translate_batch` và để CTranslate2 tự song
song hóa nội bộ.

### Lưu trữ

Trang `/storage` cho thấy dung lượng đĩa từng ebook, với hành động dọn dẹp: xóa
raw, xóa MT snapshot, xóa EPUB, đóng gói .zip.

### Tự động hóa & lịch chạy

Trang `/automation` định nghĩa chuỗi bước chạy theo lịch hoặc bấm tay cho từng
ebook: chọn các bước theo thứ tự trong `fetch-toc` → `crawl-new` →
`translate-pending` → `build`, đặt lịch `manual` hoặc `daily@HH:MM`.

### Metadata EPUB đầy đủ

Trang cài đặt ebook có đủ field để đóng gói EPUB đúng chuẩn: nhà xuất bản, ngày
xuất bản, chủ đề, bộ sách, định danh, miêu tả.

## Quy trình khuyên dùng cho truyện mới

1. Đặt `max_chapters: 2` và `translate.type: none`, chạy `crawl` → kiểm tra
   `raw/*.md` lấy đúng nội dung (chỉnh `content_selector` nếu cần).
2. Đổi `translate.type: openai` (hoặc `moxhimt`), chạy `translate` 2 chương →
   xem chất lượng dịch, bổ sung `glossary`.
3. Đặt `max_chapters: 0` (toàn bộ), tăng `crawl.max_workers` (vd 10–30 cho
   `fetcher` mode). Chạy `run`.

Khi ebook đã ổn, có thể dùng UI để chỉnh glossary, soát chương lỗi, build lại,
hoặc đặt automation `daily@HH:MM` để tự crawl chương mới + dịch + build hàng ngày.

## Hạn chế

- Chương VIP/cần đăng nhập cần nguồn khác.
- Chất lượng dịch phụ thuộc model AI bạn dùng (với `type: openai`),
  hoặc giới hạn của model NMT cục bộ (với `type: moxhimt`).
- `moxhimt` chỉ tối ưu cho CPU — không có đường chạy GPU/CUDA theo thiết kế;
  máy có GPU mạnh nên dùng `type: openai` với provider có GPU để tận dụng.
- Tôn trọng bản quyền & điều khoản của trang nguồn; chỉ dùng cho mục đích cá nhân.
