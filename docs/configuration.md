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

`translate.type` nhận `openai`, `hachimimt`, `google`, `libretranslate` hoặc `none`.

Thiết lập chung gồm:

- `source_language`, `target_language`, `genre` và `style`.
- `chunk.max_chars`, `prompt_max_chars`, `batch_size`, `max_workers`.
- `auto_glossary`, `ai_glossary_analysis`, `use_idioms`.
- `auto_cleanup_han` và `cleanup_han`.

OpenAI-compatible cần `base_url`, `api_key`, `model`, `timeout_seconds`, `temperature`. URL phải trỏ đến API root hỗ trợ `/chat/completions`; ví dụ local gateway thường dùng `http://localhost:20128/v1`.

HachimiMT chọn model qua `translate.model` hoặc `hachimimt.model_key`. Model được tải ở lần chạy đầu nếu chưa có cache.

`ai.openai` là backend riêng cho review, rewrite, glossary, nhân vật và cleanup. Nếu không cấu hình, hệ thống fallback về `translate.openai`.

## Queue

- `queue.crawl_workers`: số job crawl chạy đồng thời.
- `queue.translate_workers`: số job dịch/AI chạy đồng thời.

Đây là số job, khác với `crawl.max_workers` và `translate.max_workers` là mức song song bên trong một job.

## Reader

Field global: `url`, `service_key`, `timeout_seconds`, `batch_size`.

Field theo ebook: `slug`, `free_chapters`, `published`.

`service_key` là Supabase service-role key và bypass RLS. Không chia sẻ DB hoặc backup có chứa key.

## Mẫu YAML

`novel2epub.example.yaml` được `scripts/init_db.py` đọc một lần để seed defaults và source presets. Chỉnh file này chỉ ảnh hưởng DB được tạo sau đó, không thay cấu hình của DB hiện tại. Với hệ thống đang chạy, dùng Web UI; YAML export/import chỉ dùng để trao đổi cấu hình từng ebook.
