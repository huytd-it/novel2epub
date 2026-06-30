## Context

Trước đây giao diện web (`app/main.py` + Jinja2 templates trong `app/templates/`) dựa trên Pico CSS 2.x làm base kết hợp file `app/static/style.css` tự viết (~44KB) với hàng trăm class tùy biến (tiền tố `--n2e-*` và class `.shell-header`, `.queue-indicator`, `.toast`, `.modal`, `.canvas`, `.tab-*`, `.panel`, `.status-pill`...). File này dần phình to, khó tái sử dụng, và mỗi lần thêm view mới phải sửa CSS để vừa khít.

Có hai hướng tiếp cận Tailwind phổ biến:

1. **CDN play** (`https://cdn.tailwindcss.com`): dán script, cấu hình `tailwind.config` inline trong `<head>`. Không cần build step, tiện cho dự án server-rendered đơn giản.
2. **Build pipeline** (PostCSS/CLI) sinh ra file `tailwind.css` rồi serve static. Tối ưu production, purge class không dùng, nhưng cần thêm bước build và watcher.

Dự án hiện chỉ có Flask app + Jinja2 render thuần, không có bundler JS, không có `package.json`. Việc thêm Tailwind build pipeline sẽ kéo theo nhiều thay đổi hạ tầng (Node, npm scripts, watcher dev, CI) nằm ngoài phạm vi yêu cầu "điều chỉnh giao diện theo style tailwindcss (loại bỏ style cũ)".

## Goals / Non-Goals

**Goals:**

- Loại bỏ hoàn toàn `app/static/style.css` và Pico CSS.
- Toàn bộ trình bày chuyển sang utility class Tailwind ngay trong template.
- Giữ nguyên 100% hành vi nghiệp vụ và JS helper (toast, modal, canvas, theme, queue).
- Giữ dark mode hoạt động xuyên suốt (pre-paint, persist `localStorage`).
- Cấu hình Tailwind inline đủ để giữ design token cũ (`--n2e-*`) ánh xạ thành utility Tailwind (`bg-app`, `text-fg`, `border-border`...).
- Không thêm bước build mới.

**Non-Goals:**

- Không thêm Node.js, npm, PostCSS, hay build pipeline Tailwind.
- Không chuyển sang SPA/React/Vue.
- Không refactor backend (`app/main.py`, `app/deps.py`, `app/job.py`).
- Không thay đổi API, command pipeline, schema YAML, hay format EPUB.
- Không viết unit test cho CSS (kiểm thử bằng mắt + thao tác thủ công trên browser).
- Không tối ưu production (purge, minify) — chấp nhận bundle Tailwind CDN lớn hơn để đổi lấy tốc độ áp dụng.

## Decisions

### Quyết định 1: Dùng Tailwind CSS CDN play, không build pipeline

- **Chọn**: Tải `https://cdn.tailwindcss.com` trong `<head>`, khai báo `tailwind.config = {...}` inline.
- **Bỏ qua**: PostCSS/CLI Tailwind, `package.json`, `npm run build:css`.
- **Lý do**: Dự án không có JS bundler; thêm Node vào stack để đổi CSS là phạm vi lớn hơn yêu cầu. CDN play chạy JIT trong browser, đủ dùng cho template server-rendered cỡ 15 file.
- **Phương án thay thế đã cân nhắc**:
  - *Tailwind CLI sinh `tailwind.css` rồi serve static*: tối ưu hơn, nhưng đòi hỏi build step + watcher + CI. Đẩy sang change tương lai nếu cần tối ưu.
  - *UnoCSS*: tương đương Tailwind, nhưng ecosystem nhỏ hơn, không có lợi thế rõ ràng.

### Quyết định 2: Mở rộng `tailwind.config.theme.extend` để giữ design token cũ

- **Chọn**: Khai báo `theme.extend.colors` với key `app`, `surface`, `surface-alt`, `border`, `fg`, `muted`, `link`, `ok`, `no`, `run`. Tương ứng `theme.extend.borderRadius.card = '10px'`, `theme.extend.boxShadow.card = '0 6px 24px rgba(0,0,0,0.04)'`. Cấu hình `darkMode: 'class'`.
- **Lý do**: Token cũ (`--n2e-*`) phản ánh ý đồ thiết kế đã chốt (màu nền `#fafafa`/`#14161a`, link xanh dương, badge xanh lá/đỏ/vàng). Đặt tên ngắn giúp template gọn hơn là lặp lại hex khắp nơi, đồng thời cho phép Tailwind sinh cả biến thể `dark:` tự động.
- **Phương án thay thế**: Dùng thẳng utility Tailwind mặc định (`bg-zinc-50`, `text-zinc-900`...). Loại bỏ hoàn toàn token cũ. Tuy nhiên sẽ khó ánh xạ 1-1 badge màu `ok`/`no`/`run` và dễ lệch tông nếu có người dùng Tailwind utility mặc định.

### Quyết định 3: Theme sáng/tối điều khiển qua `class="dark"` trên `<html>`, giữ data-theme làm mirror

- **Chọn**: Khi toggle, JS vừa set `class="dark"` lên `<html>` (để Tailwind `dark:` hoạt động), vừa set `data-theme="dark"` để tương thích với selector cũ (nếu có chỗ nào còn sót). Pre-paint inline script đọc `localStorage["n2e-theme"]` để set cả hai.
- **Lý do**: Tailwind dark mode yêu cầu `class` (hoặc `media`). Trước đó hệ thống dùng `data-theme` để switch biến CSS; giữ cả hai giúp quá trình migrate an toàn và dễ debug (nếu selector cũ còn dùng ở đâu đó).
- **Phương án thay thế**: Chỉ dùng `class="dark"`, bỏ `data-theme`. Đơn giản hơn nhưng phá vỡ selector cũ còn sót trong giai đoạn chuyển tiếp.

### Quyết định 4: Giữ nguyên chữ ký JS helper, chỉ sửa selector/class nội bộ

- **Chọn**: `app/static/app.js` giữ nguyên các hàm `toast()`, `openModal()`, `closeModal()`, `openCanvas()`, `closeCanvas()`, `switchTab()`, `initTheme()`, `initQueueIndicator()`. Khi cần tham chiếu class mới, cập nhật bên trong (ví dụ thay `el.classList.toggle('active', total > 0)` cho queue indicator bằng class Tailwind, hoặc toggle class `dark` trên `<html>`).
- **Lý do**: Tách biệt rõ ràng giữa lớp JS (hành vi) và CSS (trình bày). Không phải test lại logic.
- **Phương án thay thế**: Viết lại toàn bộ JS theo hướng component. Quá phạm vi.

### Quyết định 5: Xóa `app/static/style.css`, không tạo file Tailwind CSS mới

- **Chọn**: Xóa file style.css, không sinh file Tailwind build. Mọi style nằm trong template + cấu hình inline.
- **Lý do**: Theo yêu cầu "loại bỏ style cũ" và vì CDN play không tạo file.
- **Phương án thay thế**: Tạo `app/static/tailwind.css` rỗng làm placeholder. Không có mục đích — bỏ.

### Quyết định 6: Áp dụng utility trực tiếp trong template, không tạo component template partial

- **Chọn**: Mỗi template tự viết utility class. KHÔNG tạo `app/templates/_components/button.html`, `card.html`...
- **Lý do**: Tailwind utility-first khuyến khích style tại chỗ. Tạo component riêng sẽ đi ngược tinh thần framework và phải truyền prop.
- **Phương án thay thế**: Tạo `app/templates/_components/` với macro Jinja2. Có thể áp dụng sau nếu nhiều nơi lặp lại.

## Risks / Trade-offs

- **[Bundle Tailwind CDN lớn ~300KB JS]** → Chấp nhận đổi lấy tốc độ áp dụng; tối ưu sau bằng build pipeline nếu cần.
- **[CDN phụ thuộc mạng]** → Có thể tải về serve local từ `app/static/tailwind.js` nếu môi trường offline. Không làm trong change này.
- **[Không có purge]** → Một số class không dùng vẫn nằm trong JIT engine. Không ảnh hưởng UX, chỉ tốn bộ nhớ browser.
- **[Có thể sót class cũ]** → Rà soát bằng `grep -rE "shell-header|queue-indicator|toast|modal|canvas|tab-bar|panel|status-pill|n2e-" app/templates/` sau khi viết lại, đảm bảo rỗng.
- **[Một số class Pico trùng tên Tailwind]** → Ví dụ `flex`, `grid` vừa là Pico vừa là Tailwind. Khi rà soát, dùng danh sách class Pico đặc thù (`container-fluid`, `contrast`, `striped`, `secondary`, `outline`, `pico-*`) thay vì regex chung.
- **[JS selector có thể vỡ]** → Sau khi đổi class, kiểm thử thủ công: mở từng route, click nút toast/modal/canvas/theme để xác nhận.
- **[Dark mode flicker (FOUC)]** → Inline pre-paint script trong `<head>` vẫn chạy đồng bộ, set `class="dark"` lên `<html>` trước khi Tailwind CDN load xong. Đã chạy thử nghiệm với script CDN vẫn ổn vì pre-paint chỉ set attribute.
- **[Mất chức năng Pico mặc định]** → Ví dụ focus ring, button hover. Tái tạo thủ công bằng `focus:ring-2 focus:ring-link/40` tương ứng.

## Migration Plan

1. Tạo branch mới (khuyến nghị) hoặc làm việc trực tiếp trên nhánh hiện tại nếu không có quy trình PR.
2. Cập nhật `app/templates/base.html`:
   - Xóa thẻ `<link rel="stylesheet" ... pico>` và `<link rel="stylesheet" href="/static/style.css">`.
   - Thêm `<script src="https://cdn.tailwindcss.com"></script>` + `<script>tailwind.config = { ... }</script>` trong `<head>`.
   - Cập nhật pre-paint script để set `class="dark"` lên `<html>`.
   - Viết lại header, main, toast region bằng utility Tailwind.
3. Cập nhật `app/static/app.js`:
   - `initTheme()` toggle cả `data-theme` và `class` `dark`.
   - `initQueueIndicator()` thêm/xóa class Tailwind thay cho class `active` cũ.
   - Selector `.tab-bar button` / `.tab-content` nếu đổi tên class thì cập nhật.
4. Lần lượt viết lại từng template còn lại theo thứ tự độ phức tạp tăng dần:
   1. `storage.html`, `logs.html`, `automation.html` (đơn giản).
   2. `queue.html`, `glossary.html`, `settings.html` và các tab con.
   3. `sources.html`, `index.html`, `chapter.html`, `ebook.html` (phức tạp nhất).
   4. `reader.html` (giao diện đọc, có CSS riêng — chuyển sang utility Tailwind).
5. Xóa file `app/static/style.css` bằng lệnh `Remove-Item app/static/style.css`.
6. Rà soát: `grep -rE "pico|shell-header|queue-indicator|toast|modal|canvas|tab-bar|panel|status-pill|n2e-" app/templates/` → đảm bảo không còn sót (trừ comment).
7. Khởi động lại server dev: `uvicorn app.main:app --reload --port 8010`.
8. Mở thủ công từng route, kiểm tra light/dark mode, click nút theme, mở modal, mở canvas, gọi toast.
9. Commit theo convention hiện có của repo.

**Rollback**: `git revert` commit. Vì thay đổi tập trung ở template + xóa 1 file CSS, revert sẽ khôi phục trạng thái cũ hoàn toàn.

## Open Questions

- Có muốn tải Tailwind về serve local (`app/static/tailwind.js`) thay vì CDN để chạy offline? Hiện chưa làm, để mặc định CDN.
- Có muốn thêm `safelist` cho một số class sinh động (ví dụ badge status pill có thể dùng class động theo biến)? Hiện dùng utility cố định, không cần safelist.
- Có muốn tích hợp Tailwind build pipeline sau này? Không thuộc scope change này; mở issue riêng nếu cần.
