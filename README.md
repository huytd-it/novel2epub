# novel2epub

Crawl truyện chữ tiếng Trung → dịch sang tiếng Việt → đóng gói EPUB,
kèm Web UI quản lý: hàng đợi job song song, thư viện ebook, crawl console,
và tự động hóa theo lịch.

Pipeline 3 bước, mỗi bước cache nên có thể dừng/chạy lại bất cứ lúc nào:

```
TOC fetch → crawl raw → translate → translated → build → .epub
```

## Cài đặt

Yêu cầu Python >= 3.10.

```bash
git clone <repo-url> && cd novel2epub
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install "scrapling[fetchers]"
scrapling install
```

Dịch cục bộ `hachimimt` (offline, miễn phí, CPU/GPU):

```bash
pip install ctranslate2 sentencepiece huggingface_hub
```

Web UI:

```bash
pip install fastapi uvicorn jinja2 python-multipart
```

## Cấu hình

Toàn bộ cấu hình nằm trong 1 file `novel2epub.yaml` và 1 file `novel2epub.db`:

```bash
cp novel2epub.example.yaml novel2epub.yaml   # chỉnh sửa
```

**`novel2epub.yaml`** — 3 khối top-level:

| Khối | Nội dung |
|------|----------|
| `defaults` | Cấu hình dùng chung: crawl, translate, AI, output, queue |
| `sources` | Preset crawl cho từng website (selector, engine, delay...) |
| `ebooks` | Mỗi ebook chỉ khai phần KHÁC với `defaults` |

Config hiệu lực của ebook = `deep_merge(defaults, ebooks[<slug>])`.

**`novel2epub.db`** — SQLite chứa toàn bộ dữ liệu runtime: chapters, glossary,
job queue, automations, covers, notes. File này được tạo tự động, không cần
tạo thủ công. Web UI dùng `NOVEL2EPUB_DB` env để trỏ đường dẫn (mặc định:
`novel2epub.db` cùng thư mục với file YAML).

### Cấu trúc dữ liệu trong DB

Tất cả state trước đây nằm rải rác trong `data/<slug>/` và `.n2e/` nay đã
gộp vào `novel2epub.db`:

| Dữ liệu cũ | Bảng DB |
|------------|---------|
| `manifest.json` | `ebooks` + `chapters` |
| `raw/*.md` | `chapters.raw_text` |
| `translated/*.md` | `chapters.translated_text` |
| `glossary/*.txt` | `glossary_entries` |
| `cover.*` | `ebook_covers` |
| `queue_history.json` | `job_queue_history` |
| `automations.yaml` | `automations` |
| `library_state.json` | `ebooks.archived` |

Có thể backup/toàn bộ state chỉ bằng 1 file `.db`.

### Crawl engines

| Engine | Backend | Khi nào dùng |
|--------|---------|--------------|
| `http` | requests + BeautifulSoup | Site HTML tĩnh |
| `crawl4ai` | Playwright browser | Site cần JS render, SPA |
| `scrapling` | Scrapling stealth browser | Anti-bot, Cloudflare bypass |

`scrapling` có 3 mode: `fetcher` (nhanh, cao concurrency), `stealthy` (Camoufox
ẩn), `dynamic` (Playwright đầy đủ).

### Dịch (translate)

| Engine | Loại | Ghi chú |
|--------|------|---------|
| `hachimimt` | NMT cục bộ (CTranslate2) | Mặc định, offline, miễn phí |
| `openai` | OpenAI-compatible HTTP | OpenAI, Ollama, LM Studio... |
| `google` | Google Translate (deep-translator) | Nhanh, văn phong kém |
| `none` | Không dịch | Test crawl/build |

Model `hachimimt` mặc định: **HachimiMT-60** (`ngocdang83/HachimiMT-60-zh-vi`).
Tự tải từ Hugging Face Hub về cache ở lần dùng đầu.

## Sử dụng CLI

```bash
# Liệt kê ebook
python -m novel2epub list

# Pipeline từng bước (có -e <slug>)
python -m novel2epub -e <slug> crawl
python -m novel2epub -e <slug> translate
python -m novel2epub -e <slug> build

# Chạy toàn bộ pipeline
python -m novel2epub -e <slug> run

# Dịch chương còn thiếu / 1 chương cụ thể
python -m novel2epub -e <slug> translate --missing
python -m novel2epub -e <slug> translate --chapter 12

# Lấy mục lục / metadata
python -m novel2epub -e <slug> toc
python -m novel2epub -e <slug> meta

# Liệt kê chương với filter
python -m novel2epub -e <slug> chapters --sort title --filter raw:no

# Đánh giá chất lượng dịch
python -m novel2epub -e <slug> evaluate --from 1 --to 2
```

## Web UI

```bash
uvicorn app.main:app --reload --port 8010
```

Mở `http://127.0.0.1:8010`.

### Tính năng chính

- **Thư viện ebook** — thẻ tiến độ với hành động nhanh: crawl, dịch, build,
  tải EPUB, lưu trữ.
- **Hàng đợi job song song** — 2 nhóm worker độc lập cho crawl và dịch,
  có Hủy / Retry, tự điều tiết khi gặp rate-limit.
- **Crawl console** — hiển thị chương thiếu/lỗi, retry đúng chương đó
  bằng 1 nút.
- **Automation** — chuỗi bước (fetch-toc → crawl-new → translate-pending →
  build) chạy theo lịch `daily@HH:MM` hoặc bấm tay.
- **Storage** — xem dung lượng từng ebook, dọn raw, xóa MT snapshot, đóng
  gói .zip.
- **Metadata EPUB đầy đủ** — nhà xuất bản, ngày xuất bản, chủ đề, bộ sách,
  định danh, miêu tả.

## Quy trình cho truyện mới

1. Đặt `max_chapters: 2`, `translate.type: none`, chạy `crawl` → kiểm tra
   `raw` lấy đúng nội dung, chỉnh `content_selector` nếu cần.
2. Đổi `translate.type: openai` (hoặc `hachimimt`), dịch 2 chương → xem
   chất lượng, bổ sung `glossary`.
3. Đặt `max_chapters: 0`, tăng `max_workers` (10-30 cho `fetcher`).
   Chạy `run`.

## Môi trường

| Biến | Ý nghĩa |
|------|---------|
| `NOVEL2EPUB_DB` | Đường dẫn file SQLite (mặc định: `novel2epub.db`) |
| `NOVEL2EPUB_FILE` | Fallback nếu `NOVEL2EPUB_DB` không set |

## Hạn chế

- Chương VIP/cần đăng nhập cần nguồn khác.
- Chất lượng dịch phụ thuộc model AI (với `openai`) hoặc giới hạn NMT cục bộ
  (với `hachimimt`).
- Tôn trọng bản quyền & điều khoản trang nguồn; chỉ dùng cho mục đích cá nhân.
