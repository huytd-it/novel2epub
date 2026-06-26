## Why

Trang `/ebooks/{slug}/settings` hiện tại có UX/UI nghèo nàn: ô nhập liệu dạng text tràn lan, không phân loại rõ ràng, thiếu giá trị mặc định gợi ý, và không có tiện ích kiểm tra nhanh (test crawl, test kết nối AI). Người dùng khó định hướng, dễ nhập sai kiểu dữ liệu, mất thời gian tra cứu cấu hình. Cần tái thiết kế để đạt trải nghiệm cấu hình ebook hiện đại, trực quan.

## What Changes

- **Phân loại settings thành các nhóm trực quan**: Novel (metadata), Crawl (nguồn), Translate (dịch), Output (đầu ra). Mỗi nhóm có sub-tabs hoặc accordion sections.
- **Thay input text bằng `<select>`** ở các trường có giá trị hữu hạn: `engine`, `language` (dropdown ngôn ngữ), `encoding`, `tone`, `pronoun_policy`, `title_mode`, `han_viet_level`, `crawl4ai` sub-options.
- **Hiển thị default value** bên cạnh mỗi field (từ `novel2epub/config.py`), làm mờ nếu giá trị chưa override.
- **Thêm utility buttons**:
  - "Test crawl" – gọi crawl thử URL mục lục, preview kết quả
  - "Test kết nối AI" – ping `{base_url}/models`, hiển thị model list
  - "Xem config gốc" – popup/section hiện raw YAML override
- **Tái cấu trúc form layout**: grid 2 cột cho fields, fieldset grouping rõ ràng, validation inline.
- **Gom nhóm crawl engine-specific fields**: chỉ hiển thị fieldset tương ứng với engine đang chọn (JS toggle).
- **Responsive hơn**: mobile-friendly layout.
- **Giữ nguyên API backend**: không thay đổi route handler hay config writer. Chỉ đổi template + thêm JS/CSS.

## Capabilities

### New Capabilities
- `settings-layout`: Bố cục settings được phân loại thành các nhóm (Novel, Crawl, Translate, Output) với sub-navigation.
- `settings-defaults`: Hiển thị giá trị mặc định cho từng field, phân biệt giữa default chưa ghi đè và giá trị đã override.
- `settings-utilities`: Các utility actions: test crawl, test kết nối AI, xem raw config.
- `settings-field-types`: Chuyển đổi các trường phù hợp sang `<select>`, radio, checkbox, number input thay vì text.

### Modified Capabilities
- Không có — đây là thay đổi UI thuần túy, không ảnh hưởng spec hành vi hiện có.

## Impact

- **Template**: Toàn bộ `app/templates/settings.html` được viết lại.
- **CSS/Static**: Cần thêm CSS class mới cho grid layout, utility buttons, default value badges.
- **Routes**: `settings.py` giữ nguyên — không thay đổi API.
- **Config models**: `config.py` giữ nguyên — không thay đổi.
- **No breaking changes**: Dữ liệu cấu hình cũ vẫn đọc/ghi bình thường.
