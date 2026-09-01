# Cấu Hình

## Nguồn Cấu Hình

Runtime chỉ đọc SQLite DB, mặc định là `novel2epub.db`. Khởi tạo DB mới:

```sh
python scripts/init_db.py
```

Chọn đường dẫn khác:

```sh
python scripts/init_db.py --db path/to/library.db
python -m novel2epub -c path/to/library.db list
```

Web UI dùng `NOVEL2EPUB_DB`. Hai biến cũ `NOVEL2EPUB_FILE` và `NOVEL2EPUB_CONFIG` là fallback và cũng phải trỏ đến DB.

## Ba Tầng

| Tầng | Vai trò |
| --- | --- |
| Defaults | Giá trị chung và fallback |
| Source preset | Thiết lập crawl dùng lại theo website |
| Ebook | Metadata và override riêng của truyện |

Cấu hình hiệu lực là deep merge theo thứ tự trên. Source preset không ghi đè phần dịch hoặc output.

## Crawl

Các field quan trọng:

| Field | Ý nghĩa |
| --- | --- |
| `toc_url` | URL mục lục |
| `chapter_link_pattern` | Regex chọn link chương |
| `cover_url_pattern` | Regex suy URL ảnh bìa từ HTML mục lục khi thiếu `og:image` (rỗng = không dùng) |
| `content_selector` | CSS selector vùng nội dung |
| `max_chapters` | Giới hạn thử nghiệm, `0` là tất cả |
| `max_workers` | Số tác vụ crawl yêu cầu |
| `concurrency_cap` | Trần song song, `0` dùng mặc định theo mode |
| `delay_seconds` | Khoảng nghỉ giữa request cùng domain |
| `strip_patterns` | Regex loại nội dung rác |

Scrapling nằm trong `crawl.scrapling`: `mode`, `solve_cloudflare`, `network_idle`, `impersonate`, `proxy`, `dns_over_https`.

Phân trang chương dùng `next_page_selector` hoặc `next_page_url_pattern` có đúng một capture group. Phân trang TOC dùng `toc_next_page_selector` và `toc_max_pages`.

Retry dùng `attempts`, `delay_seconds`, `backoff`, `max_delay_seconds` và `respect_retry_after`.

## Dịch

`translate.type` nhận `openai`, `localmt` hoặc `none`. (`google`/`libretranslate` đã gỡ; `hachimimt`/`moxhimt` cũ được migrate → `localmt`.)

Thiết lập chung gồm:

- `source_language`, `target_language`, `genre` và `style`.
- `chunk.max_chars`, `prompt_max_chars`, `batch_size`, `max_workers`.
- `auto_glossary`, `ai_glossary_analysis`, `use_idioms`.
- `auto_cleanup_han` và `cleanup_han` (`cleanup_han.engine`: `local_mt` mặc định | `openai`).

OpenAI-compatible cần `base_url`, `api_key`, `model`, `timeout_seconds`, `temperature`. URL phải trỏ đến API root hỗ trợ `/chat/completions`; ví dụ local gateway thường dùng `http://localhost:20128/v1`.

Local MT chọn model qua `translate.model` hoặc `translate.hachimimt.model_key` (khoá config engine cục bộ giữ tên `hachimimt`). Model được tải ở lần chạy đầu nếu chưa có cache.

`ai.openai` là backend riêng cho review, rewrite, glossary, nhân vật và cleanup. Nếu không cấu hình, hệ thống fallback về `translate.openai`.

## Output

- `output.epub_path`: đường dẫn file EPUB do người dùng đặt. Để trống thì mặc định là `<data_dir>/data/<slug>/<tựa đề> - <tác giả>.epub` (thiếu tác giả thì chỉ còn `<tựa đề>.epub`).
- `output.data_dir` luôn được ép về thư mục chứa file DB — không nên đổi qua cấu hình.

## Queue

- `queue.crawl_workers`: số job crawl chạy đồng thời.
- `queue.translate_workers`: số job dịch/AI chạy đồng thời.

Đây là số job, khác với `crawl.max_workers` và `translate.max_workers` là mức song song bên trong một job.

## Reader

Field global: `url`, `service_key`, `timeout_seconds`, `batch_size`, `push_anchors`.

Field theo ebook: `slug`, `free_chapters`, `published`.

`service_key` là Supabase service-role key và bypass RLS. Không chia sẻ DB hoặc backup có chứa key.

`push_anchors` mặc định **tắt** — xem [Neo đoạn khi đẩy sang Reader](architecture.md#neo-đoạn-khi-đẩy-sang-reader) trước khi bật.

## WireGuard (chỉ toàn cục)

Cấu hình WireGuard nằm trong khối `wireguard:` ở `defaults:`. **AN TOÀN:** DB không bao giờ lưu nội dung cấu hình WireGuard hay private key — profile là file ngoài trong `profiles_dir`; SQLite chỉ lưu metadata (id opaque, filename tương đối, source, enabled, order, status, timestamps, error).

| Field | Ý nghĩa |
| --- | --- |
| `enabled` | Bật dùng WireGuard làm "chặng mạng" cố định khi crawl/toc |
| `profiles_dir` | Thư mục bảo mật chứa file `.conf`. Rỗng = mặc định `<db_dir>/wireguard` |
| `wg_exe` | Đường dẫn `wireguard.exe` cho service tunnel Windows |
| `manage_service` | Tự cài/gỡ tunnel service (cần quyền admin) khi kích hoạt |
| `service_timeout_seconds` | Timeout lệnh service (mặc định 60) |
| `lock_timeout_seconds` | Timeout chờ khóa liên tiến trình (mặc định 30) |

### wgcf (cung cấp profile)

| Field | Ý nghĩa |
| --- | --- |
| `wgcf.enabled` | Bật cung cấp profile qua wgcf |
| `wgcf.executable` | Đường dẫn `wgcf` thực thi (bắt buộc) |
| `wgcf.argv` | Danh sách tham số **tường minh** — hệ thống không tự bịa cờ mặc định cho wgcf |
| `wgcf.output` | Tên file **tương đối** wgcf sinh ra trong cwd tạm cô lập |
| `wgcf.timeout_seconds` | Timeout chạy wgcf (mặc định 120) |

wgcf chạy trong một thư mục làm việc tạm; profile sinh ra được nhập vào `profiles_dir`, sau đó toàn bộ artifact trong cwd tạm bị dọn sạch. `output` bị chặn path traversal (phải là tên file đơn giản).

## Mẫu YAML

`novel2epub.example.yaml` được `scripts/init_db.py` đọc một lần để seed defaults và source presets. Chỉnh file này chỉ ảnh hưởng DB được tạo sau đó, không thay cấu hình của DB hiện tại. Với hệ thống đang chạy, dùng Web UI; YAML export/import chỉ dùng để trao đổi cấu hình từng ebook.
