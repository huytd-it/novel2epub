## 1. Data model — Manifest & Chapter

- [x] 1.1 Sửa `Chapter` dataclass trong `novel2epub/storage.py`: xóa `title_zh`, đổi tên `title_vi` → `title`
- [x] 1.2 Sửa `Manifest` dataclass trong `novel2epub/storage.py`: xóa `title`, `author`, `description` (zh cũ), đổi tên `title_vi` → `title`, `author_vi` → `author`, `description_vi` → `description`
- [x] 1.3 Cập nhật `Manifest.to_json()`: serialize field mới (`title`/`author`/`description` thay vì 6 field zh+vi cũ)
- [x] 1.4 Sửa `Chapter.stem` property nếu có tham chiếu `title_zh`

## 2. Storage migration — backward compat

- [x] 2.1 Sửa `Storage.load_manifest()`: khi đọc manifest.json cũ (có field `title` zh và `title_vi` riêng), tự động merge: lấy `title_vi` trước, fallback `title` (zh) → gán vào `title` mới. Tương tự cho author/description
- [x] 2.2 Sửa `Storage.load_manifest()`: khi đọc chapter cũ (có `title_zh` + `title_vi`), merge `title_vi` trước, fallback `title_zh` → gán vào `title` mới
- [x] 2.3 Sửa `Storage.save_manifest()`: luôn ghi theo schema mới (chỉ `title`, `author`, `description`, không còn `_vi` suffix)

## 3. Slugify tiếng Việt

- [x] 3.1 Tạo hàm `vn_slugify()` trong `app/routes/library.py`: chuyển ký tự có dấu tiếng Việt sang không dấu, sau đó strip non-ASCII, thay non-alphanumeric bằng `-`, lowercase, fallback `"novel"`
- [x] 3.2 Thay thế tất cả lời gọi `slugify()` cũ bằng `vn_slugify()` trong `library.py`
- [x] 3.3 Sửa form "Thêm Ebook" trong `create_ebook()`: dùng `vn_slugify(name)` thay vì `slugify(slug or name)`, không cần nhận field `slug` từ form (giữ optional để tương thích)

## 4. Pipeline — loại bỏ metadata zh flow

- [x] 4.1 Sửa `_refresh_manifest()`: không gán `toc.title`/`toc.author`/`toc.description` (zh) vào manifest nữa, chỉ gán `cfg.novel.title`/`cfg.novel.author` vào `manifest.title`/`manifest.author`
- [x] 4.2 Sửa merge chapter trong `_refresh_manifest()`: không merge `title_zh` từ TOC, dùng `title_vi` cũ → `title` mới
- [x] 4.3 Sửa `step_translate_meta()`: không gọi translator để dịch metadata zh→vi; thay vào đó gán trực tiếp `cfg.novel.title`/`cfg.novel.author` vào manifest, save manifest
- [x] 4.4 Sửa `_translate_titles()` và các hàm liên quan: tham chiếu `ch.title` thay vì `ch.title_zh`
- [x] 4.5 Sửa tất cả reference `ch.title_zh` trong pipeline.py → `ch.title` (khoảng 30+ vị trí)

## 5. Config — source_language default

- [x] 5.1 Sửa `TranslateConfig.source_language` default từ `"zh-CN"` → `""` trong `novel2epub/config.py`
- [x] 5.2 Sửa `LibreTranslateConfig.source_language` default từ `"zh"` → `""` trong `novel2epub/config.py`
- [x] 5.3 Cập nhật `app/deps.py` `_CONFIG_DEFAULTS`: `translate.source_language` default `""`
- [x] 5.4 Kiểm tra các translator backend xử lý `source_language` rỗng không lỗi (fallback auto-detect)

## 6. EPUB builder

- [x] 6.1 Sửa `build_epub()` trong `novel2epub/epub_builder.py`: dùng `manifest.title` thay vì `manifest.title_vi or manifest.title`
- [x] 6.2 Sửa `build_epub()`: dùng `manifest.author` thay vì `manifest.author_vi or manifest.author`
- [x] 6.3 Sửa `build_epub()`: dùng `manifest.description` thay vì `manifest.description_vi or manifest.description`

## 7. Web UI — form & templates

- [x] 7.1 Sửa `app/templates/index.html`: form "Thêm Ebook" — bỏ field slug, tự động hiển thị slug preview khi nhập title
- [x] 7.2 Sửa `app/templates/ebook.html`: tham chiếu `manifest.title`/`manifest.author` thay vì `title_vi`/`author_vi` trong bảng metadata
- [x] 7.3 Sửa `app/templates/reader.html`: tham chiếu `ch.title` thay vì `ch.title_vi or ch.title_zh`
- [x] 7.4 Sửa `app/templates/chapter.html`: tham chiếu `ch.title` thay vì `ch.title_vi or ch.title_zh`
- [x] 7.5 Sửa `app/routes/chapters.py`: tham chiếu `ch.title` thay vì `ch.title_zh`/`ch.title_vi`
- [x] 7.6 Sửa `app/routes/reader.py`: tham chiếu `ch.title` thay vì `ch.title_vi or ch.title_zh`
- [x] 7.7 Sửa `app/routes/ebooks.py`: tham chiếu field mới

## 8. TOC, crawler & misc

- [x] 8.1 Sửa `novel2epub/toc.py`: `ChapterRow` xóa `title_zh`, `visible_title` dùng `ch.title` thay vì `ch.title_vi or ch.title_zh`
- [x] 8.2 Sửa `novel2epub/crawler.py`: `TocResult` giữ nguyên (vẫn crawl zh metadata, nhưng pipeline không dùng để gán manifest)
- [x] 8.3 Sửa `novel2epub/cli.py`: cập nhật tham chiếu `title_zh` → `title` nếu có
- [x] 8.4 Sửa `novel2epub/search.py`: kiểm tra không có tham chiếu field cũ

## 9. Example config & test

- [x] 9.1 Cập nhật `novel2epub.example.yaml`: minh họa cấu trúc mới không có field zh, không cần slug riêng
- [x] 9.2 Chạy `pytest tests/ -v` để kiểm tra không có test nào fail do thay đổi field
- [x] 9.3 Sửa các test bị ảnh hưởng bởi thay đổi field (nếu có)
