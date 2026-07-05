## 1. Config model — thêm field `source`

- [x] 1.1 Thêm field `source: str = ""` vào ebook config trong `config.py` (nơi nào ebook config được load — có thể là NovelConfig hoặc AppConfig level)
- [x] 1.2 Cập nhật `load_config()` trong `config.py`: nếu ebook có `source` → lookup preset từ `sources:` block → deep_merge crawl fields từ preset vào TRƯỚC khi ebook override ghi đè
- [x] 1.3 Thêm fallback: nếu preset name trong `source` không tồn tại → log warning, dùng ebook crawl fields như hiện tại
- [x] 1.4 Thêm helper `resolve_source_overrides(ebook_data, sources_data) -> dict` để tách logic resolve ra khỏi load_config chính

## 2. Config writer — ghi `source` thay vì copy field

- [x] 2.1 Sửa `config_writer.add_ebook()`: thay vì copy preset fields vào crawl block, chỉ ghi `source: preset_name` + `toc_url` + field đặc thù
- [x] 2.2 Sửa `config_writer.update_ebook()`: khi ghi crawl block, chỉ ghi field user thực sự thay đổi (không ghi field resolve từ preset)
- [x] 2.3 Danh sách field deprecated YAML-only: thêm list `_DEPRECATED_CRAWL_FIELDS` và `_DEPRECATED_TRANSLATE_FIELDS` trong config_writer.py
- [x] 2.4 `_deep_merge()` trong config_writer: filter bỏ deprecated field trước khi ghi

## 3. Source preset — propagate update

- [x] 3.1 Thêm hàm `sources.propagate_preset_update(path, preset_name, presets) -> list[str]`: nhận preset mới, cập nhật ebook có `source == preset_name`, trả về danh sách ebook bị ảnh hưởng
- [x] 3.2 Logic propagate: chỉ update field ebook CHƯA override (key không tồn tại trong ebook.crawl block trong YAML)
- [x] 3.3 Sửa `app/routes/sources.py` — `save_source_preset()`: sau khi save preset, gọi `propagate_preset_update()` và log kết quả
- [x] 3.4 Sửa `_preset_usage()`: thay brute-force so sánh field bằng đọc `source` field trực tiếp từ ebook config

## 4. Web UI — ebook settings

- [x] 4.1 Sửa `app/routes/settings.py` — `save_source()`: khi user lưu crawl settings, detect field nào khác preset → chỉ ghi field đó vào ebook YAML (không ghi toàn bộ crawl block)
- [x] 4.2 Thêm endpoint `POST /ebooks/{slug}/settings/sync-to-source`: lấy crawl config hiện tại, update preset, propagate sang ebook khác
- [x] 4.3 Thêm confirm dialog trong ebook settings UI: khi nhấn "Lưu vào nguồn", hiển thị field sẽ thay đổi trong preset

## 5. Web UI — source indicator

- [x] 5.1 Truyền thêm context vào ebook settings template: `source_preset` (resolved preset object), `overridden_fields` (set key ebook đã override)
- [x] 5.2 Trong template `settings.html`: hiển thị indicator cho mỗi crawl field — "từ nguồn: X" hoặc "ghi đè"
- [x] 5.3 Hiển thị nút "Lưu vào nguồn" chỉ khi ebook có `source`

## 6. Web UI — source preset page

- [x] 6.1 Sửa `sources.html`: hiển thị danh sách ebook đang dùng preset (dùng `_preset_usage()` mới)
- [x] 6.2 Khi edit preset, hiển thị warning: "N thay đổi sẽ propagate sang M ebook"

## 7. Migration & backward compat

- [ ] 7.1 Test: ebook cũ không có `source` field → load_config hoạt động bình thường
- [ ] 7.2 Test: ebook có `source` nhưng preset bị xóa → fallback dùng crawl fields
- [ ] 7.3 Test: tạo ebook mới → tự detect preset từ URL
- [x] 7.4 Sửa `app/routes/library.py` — `create_ebook()`: detect preset từ URL, ghi `source` field

## 8. YAML cleanup

- [x] 8.1 Audit `novel2epub.example.yaml`: xóa tất cả field deprecated khỏi example file
- [x] 8.2 Đảm bảo `config_writer` không ghi field deprecated khi tạo ebook mới
- [x] 8.3 Đảm bảo `config_writer` không ghi field deprecated khi update ebook

## 9. Tests

- [ ] 9.1 Viết test cho `resolve_source_overrides()`: merge preset → ebook override
- [ ] 9.2 Viết test cho `propagate_preset_update()`: update preset → ebook không override bị ảnh hưởng
- [ ] 9.3 Viết test cho `_preset_usage()` mới: dùng `source` field thay vì brute-force
- [ ] 9.4 Viết test cho YAML cleanup: tạo ebook mới không chứa field deprecated
- [ ] 9.5 Viết test integration: tạo ebook → update preset → verify ebook nhận field mới
