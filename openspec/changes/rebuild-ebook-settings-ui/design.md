## Context

Trang `/ebooks/{slug}/settings` hiện dùng template `settings.html` với 3 tab ngang (Truyện, Nguồn, AI/Dịch), form dạng dọc với input text tràn lan, fieldset grouping cơ bản. Không có hiển thị default value, không có tiện ích kiểm tra, không có validation inline. CSS dùng class cơ bản từ `base.html` (`muted`, `check`, `tab-panel`, `tab-bar`, `tab-content`, `form-row`, `section-head`).

Backend route (3 POST handlers) và config model không đổi — chỉ can thiệp template + static.

Template engine: Jinja2. Không có JS framework client — JS thuần (vanilla). CSS inline trong template + kế thừa từ base.

## Goals / Non-Goals

**Goals:**
- Tái tổ chức layout thành 4 nhóm: **Novel**, **Crawl**, **Translate**, **Output** với sub-navigation (tab ngang hoặc sidebar nhỏ).
- Mỗi nhóm là accordion section hoặc tab riêng.
- Chuyển các trường hữu hạn sang `<select>`: engine, encoding, language, tone, pronoun_policy, title_mode, han_viet_level, scrapling_mode, translate type.
- Hiển thị default value gốc (từ dataclass config) dạng badge/chip mờ bên cạnh input — tự động biến mất khi người dùng override.
- Gom field crawl-engine-specific vào fieldset có class `engine-specific` với data attribute `data-engine` — JS ẩn/hiện theo engine đang chọn.
- Utility buttons gọi API test:
  - "Kiểm tra kết nối" ở tab Translate → gọi `GET /settings/ai/models` hiện tại, preview model list.
  - "Thử crawl TOC" ở tab Crawl → gọi API crawl thử trang mục lục (cần route mới `POST /ebooks/{slug}/settings/test-crawl`). **Non-goal**: triển khai route test-crawl trong change này, chỉ dựng placeholder UI.
- Responsive: grid 2 cột cho field pairs (label+input) trên desktop, 1 cột trên mobile.
- Validation: `type="number"`, `min`/`max`, `pattern`, `required` inline HTML5 — không JS validation phức tạp.

**Non-Goals:**
- Không thay đổi route handler hay config writer.
- Không thêm dependency JS/CSS mới (giữ vanilla JS + base CSS).
- Không triển khai API test-crawl thật — chỉ dựng UI placeholder.
- Không ảnh hưởng pipeline, crawler, translator.
- Không thay đổi dataclass config.

## Decisions

### 1. Layout: Sidebar navigation thay vì tab ngang
- **Quyết định**: Dùng sidebar dọc trái (2 cột) cho 4 nhóm settings, content phải.
- **Lý do**: 4 nhóm cần hiển thị đồng thời tiêu đề để người dùng định hướng. Tab ngang chỉ hiện 1 hàng, khó phân biệt khi đông.
- **Alternative**: Accordion sections — bị loại vì khó nhìn tổng thể, phải scroll nhiều.
- **Alternative**: Wizard (multi-step) — bị loại vì settings không phải workflow tuần tự.

### 2. Hiển thị default value: Dùng Jinja2 filter so sánh runtime
- **Quyết định**: Thêm Jinja2 filter `is_default(value, default)` trả về boolean. Dùng conditional class `default` / `overridden` trên input. Default badge hiện text mờ bên phải.
- **Lý do**: Cache-friendly (không cần JS). Tận dụng Jinja2 server-side.
- **Implementation**: Filter nhận `(current_value, field_name, section)` → so với hard-coded default dict trong template context.
- **Alternative**: JS fetch defaults từ API — overengineer, latency không đáng.

### 3. Engine-specific fields toggle: CSS-only
- **Quyết định**: Dùng class `engine-http`, `engine-crawl4ai`, `engine-scrapling` trên fieldset, kết hợp JS toggle khi `<select name="engine">` thay đổi.
- **Lý do**: Đơn giản, dễ maintain. CSS ẩn toàn bộ fieldset engine-specific, JS show cái phù hợp.
- **Alternative**: Server-side render riêng cho từng engine — phức tạp, phải reload page.

### 4. Output tab mới
- **Quyết định**: Thêm tab Output với các field: `data_dir`, `epub_path`, `max_workers` (crawl), `max_workers` (translate).
- **Lý do**: Các field này hiện không có UI — người dùng phải edit YAML thủ công.
- **Route**: Dùng form POST đến route hiện có hoặc route mới `POST /ebooks/{slug}/settings/output`. **Quyết định**: Thêm route handler mới trong `settings.py` để tránh lộn với form cũ.
- **Lưu ý**: `update_ebook` cần đảm bảo xử lý được output block.

### 5. `<select>` mapping

| Field hiện tại (text) | Chuyển thành | Options |
|---|---|---|
| `engine` (đã select, thêm scrapling) | `<select>` | http, crawl4ai, scrapling |
| `encoding` | `<select>` | auto, utf-8, gbk, gb2312, big5, euc-kr, shift-jis |
| `language` | `<select>` | vi, zh-CN, en, ja, ko, ... (~20 ngôn ngữ phổ biến) |
| `tone` | `<select>` | 5-6 tone mẫu + custom text input |
| `pronoun_policy` | `<select>` | contextual, formal, modern_casual, custom |
| `title_mode` | `<select>` | creative, literal |
| `han_viet_level` | `<select>` | balanced, heavy, light |
| `scrapling_mode` | `<select>` | stealthy, fetcher, dynamic |
| `translate.type` (đã select, thêm moxhimt) | `<select>` | moxhimt, openai, google, none |

## Risks / Trade-offs

- **[Risk] Output tab route mới**: `update_ebook` cần xử lý block `output`. Hiện tại nó đã hỗ trợ deep-merge toàn bộ dict nên không cần sửa, nhưng cần test. → **Mitigation**: Dùng `update_ebook` với dict con `{"output": {...}}` giống các tab khác.
- **[Risk] Template quá lớn**: 4 tabs × nhiều field → settings.html có thể 400+ dòng. → **Mitigation**: Dùng Jinja2 `include` để tách file partial: `settings_novel.html`, `settings_crawl.html`, `settings_translate.html`, `settings_output.html`.
- **[Trade-off] Vanilla JS**: Không dùng framework → nhiều DOM manipulation thủ công. Phù hợp vì scope nhỏ, không cần state phức tạp.
- **[Trade-off] Default value hiển thị có thể lỗi thời**: Nếu default trong code thay đổi, template context cần cập nhật đồng bộ. → **Accept**: Config dataclass hiếm khi đổi default.
