## 1. Backend: Route & Jinja2 filter

- [x] 1.1 Thêm route `GET /ebooks/{slug}/settings/output` handler (render tab Output giống các tab khác) — đã serve qua main GET handler
- [x] 1.2 Thêm route `POST /ebooks/{slug}/settings/output` để lưu output config (`data_dir`, `epub_path`, crawl/translate `max_workers`)
- [x] 1.3 Đăng ký Jinja2 filter `default_value(section, field)` trả về giá trị mặc định từ dataclass config
- [x] 1.4 Đăng ký Jinja2 filter `is_default(current, section, field)` kiểm tra field có đang dùng default không
- [x] 1.5 Hàm tiện ích `get_defaults_dict()` trả về dict các default value để dùng trong template context

## 2. Template: Layout & tabs (settings.html chính)

- [ ] 2.1 Viết lại `settings.html` với sidebar 4 tab (Novel, Crawl, Translate, Output) + content area
- [ ] 2.2 JS function `switchSettingsTab(tabName)` để chuyển tab + cập nhật active state
- [ ] 2.3 CSS cho sidebar layout, active tab highlight, responsive grid 2 cột
- [ ] 2.4 Tạo partial `settings_novel.html` (nội dung tab Novel)
- [ ] 2.5 Tạo partial `settings_crawl.html` (nội dung tab Crawl)
- [ ] 2.6 Tạo partial `settings_translate.html` (nội dung tab Translate)
- [ ] 2.7 Tạo partial `settings_output.html` (nội dung tab Output)

## 3. Template: Tab Novel (metadata)

- [ ] 3.1 Giữ nguyên các field: title, author, publisher, pubdate, subjects, series, series_index, identifier
- [ ] 3.2 Chuyển `language` từ `<input type="text">` sang `<select>` với các ngôn ngữ phổ biến (vi, zh-CN, en, ja, ko...)
- [ ] 3.3 Thêm default badges bên cạnh mỗi field (dùng filter `default_value`)
- [ ] 3.4 Thêm nút "Xem raw YAML" cuối tab

## 4. Template: Tab Crawl (source)

- [ ] 4.1 Preset quick-apply section (giữ nguyên logic, cải thiện UI)
- [ ] 4.2 Chuyển `encoding` từ text sang `<select>` (auto, utf-8, gbk, gb2312, big5, euc-kr, shift-jis)
- [ ] 4.3 Engine-specific fieldset toggle: class `engine-specific` + JS ẩn/hiện theo engine
- [ ] 4.4 Fieldset `engine-specific-http`: content_selector, toc_selector, chapter_title_selector, title/author/desc/cover_selector
- [ ] 4.5 Fieldset `engine-specific-crawl4ai`: headless, magic, js_code
- [ ] 4.6 Fieldset `engine-specific-scrapling`: scrapling_mode (select: stealthy/fetcher/dynamic), solve_cloudflare, network_idle, impersonate
- [ ] 4.7 Pagination fieldset (giữ nguyên)
- [ ] 4.8 Retry fieldset (giữ nguyên)
- [ ] 4.9 Thêm default badges + nút "Thử crawl TOC" (placeholder)
- [ ] 4.10 Thêm nút "Xem raw YAML" cuối tab

## 5. Template: Tab Translate (AI/Dịch)

- [ ] 5.1 Chuyển `tone` sang `<select>` với 6 tone mẫu + option "Tùy chỉnh..." (kèm text input)
- [ ] 5.2 Chuyển `pronoun_policy` sang `<select>` (contextual, formal, modern_casual, Tùy chỉnh...)
- [ ] 5.3 Chuyển `title_mode` sang `<select>` (creative, literal)
- [ ] 5.4 Chuyển `han_viet_level` sang `<select>` (balanced, heavy, light)
- [ ] 5.5 OpenAI-Compatible fieldset: base_url, api_key, model, timeout, temperature (giữ nguyên)
- [ ] 5.6 Nút "Kiểm tra kết nối AI" kế thừa JS từ code cũ (gọi `GET /settings/ai/models`)
- [ ] 5.7 Prompt template textarea (giữ nguyên)
- [ ] 5.8 Style fieldset field grouping
- [ ] 5.9 Retry/Chunk/Rate fieldset (giữ nguyên)
- [ ] 5.10 Thêm default badges + nút "Xem raw YAML"

## 6. Template: Tab Output

- [ ] 6.1 Field: data_dir (text input)
- [ ] 6.2 Field: epub_path (text input)
- [ ] 6.3 Field: crawl.max_workers (number input)
- [ ] 6.4 Field: translate.max_workers (number input)
- [ ] 6.5 Form POST đến `/ebooks/{slug}/settings/output`
- [ ] 6.6 Thêm default badges + nút "Xem raw YAML"

## 7. CSS & Responsive

- [ ] 7.1 Sidebar layout: flex/grid 2 cột (sidebar ~200px, content flex)
- [ ] 7.2 Grid 2 cột cho field pairs (label+input) — 1 cột trên mobile
- [ ] 7.3 Default badge styling (mờ, small, muted)
- [ ] 7.4 Override indicator (màu sắc khác / icon)
- [ ] 7.5 Utility button styling (secondary, nhỏ gọn)
- [ ] 7.6 Responsive breakpoints (max-width: 768px → 1 cột)

## 8. Validation & Hoàn thiện

- [ ] 8.1 Kiểm tra tất cả form giữ nguyên action URL cũ (không breaking change)
- [ ] 8.2 Kiểm tra `update_ebook` xử lý đúng block `output`
- [ ] 8.3 Chạy pytest verify không regression
- [ ] 8.4 Mở UI, kiểm tra tất cả tab load đúng dữ liệu
- [ ] 8.5 Test lưu từng tab và verify YAML file
