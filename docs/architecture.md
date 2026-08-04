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

## Trang Đọc

`/ebooks/{slug}/read/{index}` là trang đọc. Bôi đen văn bản mở thanh công cụ nổi: copy, dịch nhanh, thay thế, đọc từ đoạn này, ghi chú lỗi dịch.

- `POST /api/ebooks/{slug}/quick-translate`: dịch đoạn bôi đen bằng NMT cục bộ (HachimiMT/MoxhiMT), bất kể `translate.type` của ebook. Instance model được cache theo `model_key` trong tiến trình web.
- Thay thế có ba phạm vi: vùng đã chọn ghi thẳng qua `chapters/{index}/para/save`; toàn bộ chương và toàn bộ sách uỷ quyền cho `glossary/propagate` (có backup + job queue). Tuỳ chọn "toàn bộ từ" bọc chuỗi tìm bằng `\b` và gửi như regex.
- `POST /api/tts`: tổng hợp giọng đọc bằng Edge TTS (`edge-tts`), trả mp3 cho từng đoạn. Trang đọc phát tuần tự, prefetch đoạn kế và tự chuyển chương khi hết bài. Dịch vụ Edge thỉnh thoảng trả stream rỗng nên endpoint thử lại tối đa 3 lần.

## Reader Sync

Tích hợp Reader dùng Supabase PostgREST. Đồng bộ dựa trên hash nội dung và upsert theo `(book_id, index)`:

- Thêm chương chưa tồn tại.
- Cập nhật tiêu đề/nội dung đã đổi và giữ nguyên `chapters.id`.
- Bỏ qua chương không đổi hoặc chưa dịch.
- Không tự xóa chương trên Reader.
