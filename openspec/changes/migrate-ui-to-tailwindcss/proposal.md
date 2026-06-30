## Why

Giao diện web hiện tại dùng Pico CSS kết hợp với file `app/static/style.css` (44KB) chứa hàng trăm class tự định nghĩa. Cách tiếp cận này khiến mã CSS khó bảo trì, khó scale khi thêm trang mới, và phụ thuộc nặng vào biến CSS riêng. Cần chuyển sang Tailwind CSS để chuẩn hóa utility-first, loại bỏ hoàn toàn `style.css` cũ, đồng thời giữ nguyên UX cốt lõi (theme sáng/tối, header, toast, modal, canvas, tab) và các tương tác JS phía client.

## What Changes

- **Loại bỏ** `@picocss/pico` CDN và toàn bộ file `app/static/style.css` (~44KB) cùng các biến CSS tùy biến (`--n2e-*`).
- **Thêm Tailwind CSS** dạng CDN play (`https://cdn.tailwindcss.com`) trong `base.html` cấu hình `tailwind.config` inline (dark mode `class`, theme mở rộng theo design token cũ) để giữ tương thích mà không cần build step.
- **Viết lại toàn bộ template** trong `app/templates/*.html` (15 file) dùng utility class Tailwind thay cho class Pico và class tự định nghĩa. Bao gồm: header, navigation, button, table, form, modal, canvas, toast, tab, badge, status pill.
- **Giữ nguyên** logic JS trong `app/static/app.js` và `log-panel.js` (theme toggle, toast, modal/canvas helpers, queue indicator) — chỉ cập nhật selector/classes nếu cần.
- **BREAKING** Drop toàn bộ custom class `n2e-*`, `shell-header`, `queue-indicator`, `toast`, `modal`, `canvas` cũ. Nếu có CSS/JS bên ngoài nào reference các class này sẽ cần cập nhật theo.
- **Giữ nguyên** hành vi nghiệp vụ: crawl, translate, build, queue, log, settings — chỉ thay đổi lớp trình bày.

## Capabilities

### New Capabilities

- `design-system`: Đặc tả design system dùng Tailwind CSS — bao gồm design token (màu sắc, spacing, radius, shadow), quy tắc utility class cho từng thành phần (header, nav, button, card, form, table, modal, canvas, toast, tab, badge), và cơ chế dark mode. Đây là spec mô tả hợp đồng trực quan cho toàn bộ UI.

### Modified Capabilities

<!-- Không có spec hiện hữu nào thuộc loại design-system/UI shell bị thay đổi ở mức yêu cầu. Các spec như chapter-pagination, chapter-three-column-editor mô tả hành vi nghiệp vụ, không bị ảnh hưởng bởi đổi CSS framework. -->

## Impact

- **Templates**: 15 file trong `app/templates/*.html` cần viết lại markup + class.
- **Static assets**: Xóa `app/static/style.css`. Thêm CDN script Tailwind + cấu hình inline.
- **JS**: `app/static/app.js` và `app/static/log-panel.js` — rà soát và cập nhật selector/class name nếu thay đổi.
- **Backend**: Không ảnh hưởng. `app/main.py`, `app/deps.py`, `app/job.py` giữ nguyên.
- **Crawl/translate/build pipeline**: Không ảnh hưởng.
- **Phụ thuộc mới**: Tailwind CSS CDN (`https://cdn.tailwindcss.com`). Có thể chuyển sang build pipeline (PostCSS) trong tương lai nhưng không thuộc scope change này.
- **Testing**: Kiểm thử thủ công bằng cách mở từng route trong trình duyệt (light + dark mode), xác nhận không có class cũ nào sót lại.
