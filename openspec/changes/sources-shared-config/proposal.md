## Why

Hiện tại source preset và ebook config **không có liên kết rõ ràng**. Khi tạo ebook, các field crawl từ preset được **copy phẳng** vào ebook config — sau đó ebook không biết mình dùng preset nào. Kết quả:

- Cập nhật preset (vd: đổi selector) **không propagate** sang ebook đang dùng preset đó.
- Không có cơ chế sync ngược: sửa crawl settings trong ebook UI → không biết nên cập nhật preset nào.
- YAML chứa nhiều field không hiển thị trong web UI (`strip_patterns`, `ai_fallback`, `auto_glossary`, `batch_size`...) tạo rác config khó maintain.
- `_preset_usage()` phải brute-force so sánh từng field để đoán ebook nào dùng preset nào — chậm và dễ sai.

## What Changes

- **Thêm field `source` vào ebook config**: mỗi ebook lưu tên preset thay vì copy toàn bộ field. Khi load config, field từ source preset được áp dụng trước, ebook override ghi đè sau.
- **Sync nguồn → ebook**: khi lưu source preset, tự động cập nhật crawl config cho mọi ebook tham chiếu preset đó (trừ field ebook đã override thủ công).
- **Sync ebook → nguồn**: trong ebook settings UI, thêm nút "Lưu vào nguồn" để cập nhật preset từ crawl settings hiện tại của ebook.
- **Dọn rác YAML**: audit toàn bộ field trong YAML không có counterpart trong web UI → xóa khỏi output của config_writer. Các field deprecated sẽ bị strip khi ghi.
- **Web UI nhất quán**: mọi field trong YAML đều có UI control; mọi field trong UI đều ghi đúng 1 nơi trong YAML.

## Capabilities

### New Capabilities
- `source-ebook-link`: Liên kết rõ ràng giữa ebook và source preset qua field `source` trong ebook config. Bao gồm: load config resolve preset → merge ebook override, validation source name hợp lệ, fallback khi preset bị xóa.
- `source-sync`: Cơ chế sync hai chiều: source → ebooks (propagate khi lưu preset) và ebook → source (nút "Lưu vào nguồn" trong ebook settings). Tracking field nào ebook đã override thủ công để không ghi đè.

### Modified Capabilities
_(không có spec hiện có cần thay đổi requirements)_

## Impact

- **config.py**: thêm field `source: str` vào dataclass ebook config (hoặc NovelConfig). Thay đổi `load_config()` để resolve preset trước khi merge ebook override.
- **config_writer.py**: `add_ebook()` ghi `source` thay vì copy preset fields. `update_ebook()` cần biết field nào từ source, field nào override.
- **sources.py**: thêm hàm `apply_preset_to_ebook()` và `sync_ebook_to_preset()`.
- **app/routes/settings.py**: thêm endpoint + UI nút "Lưu vào nguồn" cho ebook crawl settings.
- **app/routes/sources.py**: `save_source_preset()` gọi propagate sang ebook sau khi lưu.
- **app/routes/library.py**: `create_ebook()` ghi `source` field.
- **Templates**: cập ebook settings.html, sources.html.
- **YAML schema**: breaking change — ebook config chuyển từ copy fields sang reference `source`.
