# novel2epub

Ứng dụng crawl tiểu thuyết web, dịch sang tiếng Việt, biên tập và xuất EPUB. Hệ thống cung cấp cả CLI lẫn Web UI, lưu cấu hình và dữ liệu vận hành trong một SQLite database.

```text
fetch TOC -> crawl raw -> translate -> edit/cleanup -> build EPUB
```

Mỗi bước ghi kết quả vào DB nên có thể dừng, chạy tiếp hoặc chạy lại một phạm vi chương mà không bắt đầu từ đầu.

## Tính năng

- Crawl bằng Scrapling với ba mode: `fetcher`, `stealthy`, `dynamic`.
- Hỗ trợ mục lục và chương phân trang, retry/backoff, giới hạn song song theo nguồn.
- Dịch bằng OpenAI-compatible API hoặc Local MT cục bộ (CTranslate2), hoặc passthrough nguồn tiếng Việt.
- Quản lý glossary theo ebook, từ điển thành ngữ dùng chung và bảng nhân vật/xưng hô.
- Biên tập từng đoạn, AI review/rewrite, cleanup chữ Hán còn sót và xử lý hàng loạt.
- Job queue theo nhóm crawl/translate, automation bằng cron và lịch sử thực thi.
- Xuất EPUB có bìa, metadata, series và chú thích glossary.
- Đồng bộ tăng dần sang novel-reader qua Supabase mà không thay ID chương.
- Backup/restore toàn bộ hệ thống bằng một file SQLite.
- Catalog OPDS để đọc trực tiếp bằng readest, tự build EPUB (chỉ chương đã dịch) khi catalog được gọi — xem [Đọc bằng readest qua OPDS](docs/operations.md#đọc-bằng-readest-qua-opds).
- Quản lý profile WireGuard và cung cấp profile qua wgcf — profile nằm ngoài DB, SQLite chỉ lưu metadata, không bao giờ chứa private key (xem [WireGuard trong vận hành](docs/operations.md#vị-trí-wireguard-và-pipeline)).

## Cài đặt

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
scrapling install
python scripts/init_db.py
```

Linux/macOS dùng `source .venv/bin/activate` thay cho lệnh kích hoạt PowerShell.

Local MT (`translate.type=localmt`) là backend cục bộ tùy chọn:

```sh
pip install ctranslate2 sentencepiece huggingface_hub
```

## Khởi động

### Web UI (Jinja2)

```sh
uvicorn app.main:app --reload --port 8010
```

Mở `http://127.0.0.1:8010`, tạo ebook ở trang Thư viện, chọn source preset hoặc điền URL mục lục, sau đó chạy lần lượt TOC, crawl, translate và build.

### SPA React (`frontend/`)

Giao diện mới là SPA React, phục vụ tại `/app` khi bundle đã build; bản dev chạy qua Vite.

Yêu cầu Node.js và npm.

```sh
cd frontend
npm install            # lần đầu
npm run dev            # http://localhost:5183
```

Backend phải chạy ở cổng `8011` để Vite proxy `/api/*` sang đúng địa chỉ:

```sh
uvicorn app.main:app --reload --port 8011
```

Build production (xuất ra `app/webui/`, FastAPI phục vụ tại `/app`):

```sh
npm run build          # bản web
npm run build:tauri    # bundle cho Tauri desktop
```

Desktop Tauri: `npm run tauri:dev`. Khi mở bản web, SPA dùng chung origin với backend nên không cần cấu hình; chỉ nhập base/token ở trang Kết nối khi SPA chạy ngoài origin backend (Tauri hoặc deploy tách host).

Luồng CLI tương đương:

```sh
python -m novel2epub list
python -m novel2epub -e <slug> toc
python -m novel2epub -e <slug> crawl
python -m novel2epub -e <slug> translate
python -m novel2epub -e <slug> build
```

Chạy trọn pipeline bằng `python -m novel2epub -e <slug> run`.

## Dữ liệu Và Cấu Hình

`novel2epub.db` là nguồn dữ liệu chính, gồm:

- Cấu hình mặc định, source preset và override từng ebook.
- Manifest, raw, bản dịch máy, bản biên tập và metadata chương.
- Glossary, thành ngữ, nhân vật, quan hệ và ghi chú.
- Job queue, lịch sử, automation, trạng thái lưu trữ và thông tin đồng bộ Reader.

`novel2epub.example.yaml` chỉ là mẫu seed cho `scripts/init_db.py`, không phải file cấu hình runtime. Cấu hình được chỉnh qua Web UI và có thể export/import YAML theo từng ebook.

Đổi vị trí DB bằng biến `NOVEL2EPUB_DB`:

```powershell
$env:NOVEL2EPUB_DB = "D:\data\novel2epub.db"
uvicorn app.main:app --port 8010
```

Đổi sang cổng khác (ví dụ `8011`) cho SPA dev cũng chạy tương tự: `uvicorn app.main:app --port 8011`.

`NOVEL2EPUB_FILE` và `NOVEL2EPUB_CONFIG` chỉ còn là fallback tương thích, nhưng giá trị vẫn phải trỏ đến file `.db`.

## Backup

```sh
python -m novel2epub backup
python -m novel2epub restore --from backups/novel2epub-YYYYMMDD-HHMMSS.db
```

Không copy trực tiếp DB đang chạy nếu muốn bảo đảm snapshot nhất quán. Lệnh `backup` dùng SQLite backup API và an toàn khi Web UI đang hoạt động.

## Tài Liệu

- [Kiến trúc hệ thống](docs/architecture.md)
- [Cấu hình](docs/configuration.md)
- [Hướng dẫn vận hành](docs/operations.md)
- [Dịch và biên tập](docs/translation.md)
- [Phát triển và kiểm thử](docs/development.md)
- [Release, Vercel và Tailscale](docs/release.md)
- [Giao diện SPA](docs/architecture.md#giao-diện-spa-frontend)

## Giới Hạn

- Nội dung VIP hoặc cần đăng nhập chỉ crawl được khi nguồn và phiên truy cập cho phép.
- Cấu trúc website có thể thay đổi; selector và source preset cần được bảo trì.
- Chất lượng bản dịch phụ thuộc backend, model, prompt, glossary và bước biên tập.
- Chỉ sử dụng nội dung khi bạn có quyền truy cập và tuân thủ điều khoản của nguồn.
