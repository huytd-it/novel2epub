## 1. Chuẩn bị & hạ tầng Tailwind

- [x] 1.1 Cập nhật `app/templates/base.html`: xóa thẻ `<link>` Pico CSS và `<link href="/static/style.css">`.
- [x] 1.2 Thêm `<script src="https://cdn.tailwindcss.com"></script>` trong `<head>` của `base.html`.
- [x] 1.3 Khai báo `tailwind.config` inline: bật `darkMode: 'class'`, mở rộng `theme.extend.colors` (`app`, `surface`, `surface-alt`, `border`, `fg`, `muted`, `link`, `ok`, `no`, `run`), `theme.extend.borderRadius.card` (`10px`), `theme.extend.boxShadow.card`.
- [x] 1.4 Cập nhật pre-paint script: set cả `data-theme` và `class="dark"` lên `<html>` dựa trên `localStorage["n2e-theme"]` hoặc `prefers-color-scheme`.
- [x] 1.5 Cập nhật `app/static/app.js`: `initTheme()` toggle cả `data-theme` và `class` `dark`.

## 2. Shell chung (base + header + nav + queue + theme)

- [x] 2.1 Viết lại `<header>` trong `base.html` bằng utility Tailwind: flex, gap, padding, border-bottom. Logo dùng `text-lg font-semibold`.
- [x] 2.2 Render 5 nav link với logic active: link active dùng `text-link font-semibold`, ngược lại `text-muted hover:text-fg`.
- [x] 2.3 Queue indicator: anchor pill `rounded-full border border-border bg-surface-alt px-2 py-0.5 text-sm`. Khi active thêm `border-amber-500 bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200`.
- [x] 2.4 Theme toggle button: `rounded-md border border-border p-1.5 hover:bg-surface-alt`.
- [x] 2.5 Toast region: `<div id="toast-region" class="fixed bottom-4 right-4 flex flex-col gap-2 z-50" aria-live="polite">`.
- [x] 2.6 Main wrapper: `<main class="mx-auto max-w-[1320px] px-6 py-5">` với surface `bg-surface border border-border rounded-xl shadow-card p-5`.

## 3. Cập nhật JS helper

- [x] 3.1 `toast()`: render `<div class="rounded-lg border bg-surface px-3 py-2 text-sm shadow-card transition ...">`; kind `error` thêm `border-red-500`, kind `success` thêm `border-green-500`. Animation fade in/out giữ nguyên bằng class `opacity-0 translate-y-2` → `opacity-100 translate-y-0`.
- [x] 3.2 `openModal/closeModal`: backdrop dùng `fixed inset-0 z-40 flex items-center justify-center bg-black/45`. Modal box dùng `bg-surface text-fg border border-border rounded-card p-5 max-w-lg shadow-card`.
- [x] 3.3 `openCanvas/closeCanvas`: backdrop `fixed inset-0 z-40 flex justify-end bg-black/35`. Panel `bg-surface border-l border-border w-[min(45vw,600px)] h-screen overflow-y-auto`. Transition dùng `translate-x-full` ↔ `translate-x-0` + class `open` để trigger.
- [x] 3.4 `switchTab()`: tab buttons `px-3 py-1.5 text-sm border-b-2 border-transparent text-muted`; active `text-link border-link`. Tab content ẩn/hiện bằng class `hidden`.
- [x] 3.5 `initQueueIndicator()`: thay `classList.toggle("active", total > 0)` bằng toggle class Tailwind tương ứng.
- [x] 3.6 Cập nhật click handler trên backdrop modal/canvas để khớp selector class Tailwind mới.

## 4. Viết lại các template đơn giản

- [x] 4.1 `app/templates/storage.html`: danh sách path/manifest dùng `<table class="w-full text-sm">` với `thead` uppercase tracking-wide `text-muted`, `tbody` row `border-b border-border hover:bg-surface-alt`.
- [x] 4.2 `app/templates/logs.html`: panel log dùng `bg-zinc-950 text-zinc-100 font-mono text-xs rounded-card p-3 overflow-auto`.
- [x] 4.3 `app/templates/automation.html`: card grid `grid grid-cols-1 md:grid-cols-2 gap-4`, mỗi card `bg-surface border border-border rounded-card p-4 shadow-card`.
- [x] 4.4 `app/templates/queue.html`: danh sách job dùng utility table; pill trạng thái dùng `bg-ok`/`bg-no`/`bg-run` tuỳ trạng thái.

## 5. Viết lại settings & glossary

- [x] 5.1 `app/templates/settings.html`: tab bar dùng utility Tailwind; container dùng `max-w-3xl mx-auto`.
- [x] 5.2 `app/templates/settings_crawl.html`, `settings_novel.html`, `settings_output.html`, `settings_translate.html`: form fields với `space-y-4`, input `w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-link/40`. Label `text-sm font-medium text-fg`. Button chính `bg-link text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-link/90`. Button phụ `bg-surface-alt text-fg border border-border rounded-md px-4 py-2 text-sm hover:bg-surface`.
- [x] 5.3 `app/templates/glossary.html`: bảng thuật ngữ 2 cột (gốc ↔ dịch) với action button dùng utility Tailwind.

## 6. Viết lại sources & index & ebook

- [x] 6.1 `app/templates/sources.html`: layout grid 2 cột (danh sách preset + form chi tiết). Bảng nguồn dùng utility Tailwind.
- [x] 6.2 `app/templates/index.html`: thư viện ebook dạng card grid `grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4`. Card ebook `bg-surface border border-border rounded-card p-4 shadow-card hover:shadow-md transition`. Mỗi card hiển thị tên, slug, badge trạng thái (`bg-ok`/`bg-no`/`bg-run`).
- [x] 6.3 `app/templates/ebook.html` (lớn nhất, ~46KB): rewrite toàn bộ. Bố cục gồm header ebook, panel job queue, danh sách chapter dạng table, modal preview chapter, canvas chỉnh sửa. Mỗi phần dùng utility Tailwind tương ứng.
- [x] 6.4 Đảm bảo các hàm JS inline trong template (nếu có) vẫn hoạt động: cập nhật selector class.

## 7. Viết lại chapter & reader

- [x] 7.1 `app/templates/chapter.html` (~39KB): 3 cột editor. Mỗi cột `bg-surface border border-border rounded-card p-4 h-full overflow-y-auto`. Toolbar nút `inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-alt`.
- [x] 7.2 `app/templates/reader.html` (giao diện đọc sách): typography `prose dark:prose-invert max-w-2xl mx-auto`. Pagination controls `fixed bottom-4 left-1/2 -translate-x-1/2 flex gap-2 bg-surface border border-border rounded-full px-3 py-1.5 shadow-card`.

## 8. Dọn dẹp & kiểm thử

- [x] 8.1 Xóa file `app/static/style.css` bằng `Remove-Item app/static/style.css`.
- [x] 8.2 Chạy `grep -rE "pico|shell-header|queue-indicator|toast|modal|canvas|tab-bar|tab-content|status-pill|panel|n2e-" app/templates/` để rà soát class cũ còn sót. Sửa đến khi rỗng (trừ comment giải thích).
- [x] 8.3 Chạy `grep -rE "@picocss|cdn.jsdelivr.net.*pico" app/` để xác nhận không còn tham chiếu Pico.
- [x] 8.4 Khởi động `uvicorn app.main:app --reload --port 8010`. Mở từng route: `/`, `/sources`, `/storage`, `/automation`, `/logs`, `/queue`, `/settings`, `/settings/crawl`, `/settings/novel`, `/settings/output`, `/settings/translate`, `/glossary`, `/ebook/<slug>`, `/ebook/<slug>/chapter/<n>`, `/reader/<slug>/<n>`.
- [x] 8.5 Kiểm tra dark mode: click theme toggle ở mỗi trang, refresh để xác nhận persist không bị FOUC.
- [x] 8.6 Kiểm tra modal: mở một modal bất kỳ (ví dụ trong `/ebook/<slug>`), đóng bằng click backdrop và phím `Escape`.
- [x] 8.7 Kiểm tra canvas: mở canvas chỉnh sửa, đóng bằng nút `X` và phím `Escape`.
- [x] 8.8 Kiểm tra toast: trigger một action thành công/thất bại, xác nhận toast xuất hiện ở góc dưới phải và tự ẩn sau 4 giây.
- [x] 8.9 Kiểm tra queue indicator: chạy một job, xác nhận số đếm tăng và pill chuyển sang màu amber.
- [x] 8.10 Kiểm tra responsive: thu nhỏ trình duyệt xuống 375px width, xác nhận nav và table không vỡ.
- [x] 8.11 Commit theo convention repo, ghi message rõ ràng (ví dụ `feat(ui): migrate to tailwindcss, drop legacy style.css`).
