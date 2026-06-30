## ADDED Requirements

### Requirement: Hệ thống dùng Tailwind CSS làm framework styling

Giao diện web SHALL dùng Tailwind CSS (utility-first) thay cho Pico CSS và file `style.css` tự viết. Toàn bộ markup trong `app/templates/*.html` SHALL sử dụng utility class Tailwind; KHÔNG được tham chiếu đến class Pico (ví dụ `container`, `grid`, `contrast`, `secondary`, `outline`, `pico-*`) hoặc class tự định nghĩa cũ (`shell-header`, `queue-indicator`, `toast`, `modal`, `canvas`, `n2e-*`).

#### Scenario: Không còn class Pico trong templates
- **WHEN** quét tất cả file trong `app/templates/*.html` để tìm class thuộc Pico
- **THEN** hệ thống SHALL không tìm thấy class Pico nào (trừ trường hợp utility Tailwind trùng tên vô tình nhưng vẫn thuộc Tailwind)

#### Scenario: Không còn class tự định nghĩa cũ
- **WHEN** quét tất cả file trong `app/templates/*.html` tìm các class `shell-header`, `queue-indicator`, `toast`, `modal`, `canvas`, `tab-bar`, `tab-content`, `panel`, `n2e-*`
- **THEN** hệ thống SHALL không tìm thấy các class này

### Requirement: File style.css cũ được loại bỏ hoàn toàn

File `app/static/style.css` MUST được xóa khỏi repository và KHÔNG được tham chiếu trong bất kỳ template nào. Mọi quy tắc trình bày SHALL được biểu diễn bằng utility class Tailwind trong template hoặc cấu hình `tailwind.config` inline.

#### Scenario: style.css không còn trong repo
- **WHEN** kiểm tra thư mục `app/static/`
- **THEN** file `style.css` SHALL không tồn tại

#### Scenario: Template không tham chiếu style.css
- **WHEN** tìm chuỗi `style.css` trong `app/templates/*.html`
- **THEN** hệ thống SHALL không tìm thấy tham chiếu nào

### Requirement: Cấu hình Tailwind inline trong base.html

`app/templates/base.html` MUST bao gồm script CDN Tailwind (`https://cdn.tailwindcss.com`) và cấu hình `tailwind.config` inline. Cấu hình SHALL bật `darkMode: 'class'`, mở rộng `theme.colors` với token tương ứng `--n2e-*` cũ, và preflight tắt một số style mặc định nếu gây xung đột.

#### Scenario: Base template load Tailwind
- **WHEN** mở bất kỳ trang nào render từ `base.html`
- **THEN** phần tử `<head>` SHALL chứa `<script src="https://cdn.tailwindcss.com"></script>` và `<script>tailwind.config = { ... }</script>`

#### Scenario: Dark mode hoạt động qua class
- **WHEN** nhấn nút theme toggle và `html` có class `dark`
- **THEN** toàn bộ trang SHALL render với utility class dark mode (ví dụ `bg-white dark:bg-zinc-900`)

### Requirement: Design token ánh xạ từ hệ thống cũ

Hệ thống SHALL giữ nguyên tinh thần design token cũ thông qua `tailwind.config.theme.extend`:

- Màu nền chính: `bg-app` (light: `#fafafa`, dark: `#14161a`).
- Màu surface: `bg-surface` (light: `#ffffff`, dark: `#1c1f24`).
- Màu surface alt: `bg-surface-alt` (light: `#f7f7f7`, dark: `#20242a`).
- Màu viền: `border-border` (light: `#e5e5e5`, dark: `#2e3338`).
- Màu chữ: `text-fg` (light: `#202020`, dark: `#e7e9ec`).
- Màu chữ muted: `text-muted` (light: `#777`, dark: `#9aa2ad`).
- Màu link: `text-link` (light: `#2563eb`, dark: `#6ea8fe`).
- Màu badge ok/no/run: `bg-ok`, `bg-no`, `bg-run`.
- Bán kính: `rounded-card` (`10px`).
- Bóng: `shadow-card`.

#### Scenario: Token có sẵn trong tất cả template
- **WHEN** một template sử dụng `bg-app`, `bg-surface`, `text-fg`, `border-border`...
- **THEN** Tailwind SHALL render đúng màu theo `data-theme` của `<html>`

### Requirement: Thành phần shell (header + nav + queue indicator)

`base.html` MUST render header gồm: logo (link về `/`), nav 5 mục (Thư viện, Nguồn, Lưu trữ, Tự động hóa, Nhật ký), queue indicator với `<span id="queue-count">`, và nút theme toggle `<button id="theme-toggle">`. Mục nav đang active SHALL được đánh dấu bằng utility class màu link + font-semibold.

#### Scenario: Header hiển thị đầy đủ thành phần
- **WHEN** mở bất kỳ trang nào
- **THEN** header SHALL chứa logo, 5 nav link, queue indicator, theme toggle

#### Scenario: Nav active phản ánh URL hiện tại
- **WHEN** URL hiện tại bắt đầu bằng `/sources`
- **THEN** link "Nguồn" SHALL có class `text-link font-semibold`; các link khác dùng `text-muted`

### Requirement: Hệ thống toast giữ hành vi cũ

`<div id="toast-region" aria-live="polite">` SHALL tồn tại trong `base.html`. Hàm `toast(message, kind)` trong `app/static/app.js` MUST hoạt động không đổi; toast mới SHALL dùng utility class Tailwind (`fixed bottom-4 right-4 ...`) thay cho class `toast` cũ. Kind `error`/`success` SHALL đổi màu viền tương ứng.

#### Scenario: Toast xuất hiện khi gọi toast()
- **WHEN** JS gọi `toast("Lỗi", "error")`
- **THEN** một phần tử SHALL xuất hiện ở góc dưới phải với viền đỏ và tự ẩn sau 4 giây

### Requirement: Modal backdrop và canvas slide-in

Template SHALL dùng Tailwind để render modal (`fixed inset-0 ... flex items-center justify-center`) và canvas (`fixed inset-y-0 right-0 ...`). Hàm `openModal/closeModal/openCanvas/closeCanvas` trong `app/static/app.js` MUST giữ nguyên chữ ký; chỉ cập nhật class nếu tên class thay đổi. Modal MUST đóng khi click backdrop hoặc nhấn `Escape`.

#### Scenario: Click backdrop đóng modal
- **WHEN** người dùng click trực tiếp lên phần tử backdrop (không phải nội dung modal)
- **THEN** modal SHALL ẩn đi

#### Scenario: Phím Escape đóng modal/canvas
- **WHEN** người dùng nhấn `Escape` khi modal hoặc canvas đang mở
- **THEN** phần tử đó SHALL đóng lại

### Requirement: Bảng biểu (table) dùng utility Tailwind

Mọi `<table>` SHALL dùng utility class Tailwind (`w-full text-sm text-left`, `border-b border-border` cho hàng). KHÔNG dùng class Pico (`striped`, `contrast`).

#### Scenario: Bảng hiển thị trong trang chính
- **WHEN** mở route `/` (danh sách ebook) hoặc `/sources`
- **THEN** bảng SHALL render với utility class Tailwind, có header phân biệt rõ và hàng cách nhau bằng border mảnh

### Requirement: Form input/select/button dùng utility Tailwind

Mọi `<input>`, `<select>`, `<textarea>`, `<button>` SHALL dùng utility class Tailwind (`border border-border rounded-md px-3 py-2 text-sm`, focus ring, v.v.) thay cho style Pico mặc định. Button chính SHALL dùng `bg-link text-white`; button phụ dùng `bg-surface-alt text-fg border border-border`.

#### Scenario: Input có style đồng nhất
- **WHEN** mở trang settings có form
- **THEN** mọi input/select SHALL có border, padding, và bo góc đồng nhất theo utility Tailwind

### Requirement: Dark mode hoạt động xuyên suốt

Khi `<html data-theme="dark">` (hoặc class `dark`), mọi utility class Tailwind SHALL render với biến thể dark tương ứng. Theme SHALL được persist trong `localStorage` qua khóa `n2e-theme` và preload trước khi paint (chống FOUC).

#### Scenario: Toggle theme đổi giao diện
- **WHEN** người dùng click nút theme toggle
- **THEN** `<html>` SHALL chuyển `data-theme` giữa `light` và `dark`, giao diện SHALL đổi ngay lập tức và lưu vào `localStorage`

#### Scenario: Refresh trang giữ theme đã chọn
- **WHEN** người dùng refresh trang sau khi chọn dark mode
- **THEN** `<html>` SHALL được set `data-theme="dark"` trước khi nội dung paint (inline script pre-paint)

### Requirement: Không thay đổi hành vi nghiệp vụ

API endpoints, command pipeline (crawl/translate/build), job queue, log streaming, và cấu hình YAML MUST giữ nguyên hành vi. Change này chỉ thay đổi lớp trình bày (HTML/CSS), không được sửa logic backend trừ khi cần cập nhật selector/class trong JS.

#### Scenario: Các route API vẫn hoạt động
- **WHEN** gọi `POST /api/...` hoặc `GET /api/...`
- **THEN** phản hồi SHALL giống hệt như trước khi đổi UI

#### Scenario: Pipeline CLI không đổi
- **WHEN** chạy `python -m novel2epub crawl/translate/build`
- **THEN** kết quả SHALL giống hệt như trước khi đổi UI
