## Why

Người dùng muốn nhập thủ công metadata tiếng Việt (tên truyện, tác giả, mô tả) thay vì phụ thuộc vào metadata tiếng Trung tự động crawl từ trang nguồn. Đồng thời tự động sinh slug từ tiêu đề tiếng Việt nhập vào thay vì yêu cầu nhập slug riêng. Việc này đơn giản hóa quy trình tạo ebook và loại bỏ các field trung gian liên quan đến zh.

## What Changes

- **BREAKING**: Xóa các field metadata zh khỏi `Manifest` (`title`, `author`, `description`) — thay bằng `title_vi`, `author_vi`, `description_vi` làm field chính
- **BREAKING**: Xóa `Chapter.title_zh` — giữ `title_vi` và `title_note` làm field chính cho tiêu đề chương
- **BREAKING**: Đổi default `TranslateConfig.source_language` từ `"zh-CN"` thành rỗng (không mặc định ngôn ngữ nguồn)
- Sửa `slugify()` để hỗ trợ tiếng Việt có dấu (chuyển đ thành d, ơ thành o, v.v.) thay vì strip toàn bộ non-ASCII
- Form "Thêm Ebook" trong Web UI: tự động sinh slug từ `title_vi` khi người dùng nhập, không cần field slug riêng
- Bước `step_translate_meta` trong pipeline: không còn dịch metadata zh→vi nữa, thay vào đó gán trực tiếp metadata vi do người dùng nhập
- Cập nhật `novel2epub.example.yaml` để phản ánh cấu trúc mới không có field zh

## Capabilities

### New Capabilities

- `vi-slug-auto-generate`: Tự động sinh slug từ tiêu đề tiếng Việt, hỗ trợ chuyển đổi ký tự có dấu sang không dấu (đ → d, ơ → o, ư → u, v.v.) thay vì xóa toàn bộ non-ASCII

### Modified Capabilities

<!-- Không có spec hiện có nào bị thay đổi yêu cầu -->

## Impact

- `novel2epub/storage.py`: `Manifest` dataclass — đổi tên/loại bỏ field zh, `Chapter` — xóa `title_zh`
- `novel2epub/config.py`: `TranslateConfig.source_language` default rỗng
- `novel2epub/pipeline.py`: `_refresh_manifest()` không merge metadata zh từ TOC, `step_translate_meta()` không cần dịch zh→vi nữa
- `novel2epub/crawler.py`: `TocResult` dataclass — giữ nguyên để crawl TOC, nhưng không map vào manifest
- `novel2epub/epub_builder.py`: metadata assembly dùng trực tiếp `title_vi`/`author_vi` thay vì fallback sang zh
- `app/routes/library.py`: `slugify()` hỗ trợ tiếng Việt, form "Add Ebook" tự động sinh slug
- `app/routes/settings.py`: form chỉnh sửa metadata không còn field zh
- `app/templates/`: cập nhật form và hiển thị metadata
- `novel2epub.example.yaml`: cập nhật cấu trúc mẫu
- `novel2epub/toc.py`: `ChapterRow` bỏ `title_zh`, điều chỉnh `visible_title`
