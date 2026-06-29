## 1. Backend — Route & Template

- [x] 1.1 Tạo file `app/routes/reader.py` với router mới
- [x] 1.2 Thêm route `GET /ebooks/{slug}/read/{index}` — render template `reader.html` với context (ch, translated, meta, slug, chapter list cho navigation)
- [x] 1.3 Thêm route `GET /ebooks/{slug}/read` — redirect tới chương bookmark gần nhất hoặc chương đầu tiên
- [x] 1.4 Đăng ký router trong `app/main.py`
- [x] 1.5 Xử lý edge case: chương không tồn tại (404), chương chưa có bản dịch (hiển thị thông báo + link editor)

## 2. Template — reader.html

- [x] 2.1 Tạo `app/templates/reader.html` kế thừa `base.html` — layout 1 cột, book-like
- [x] 2.2 Render nội dung bản dịch dạng paragraphs (split theo `\n`, wrap trong `<p>`)
- [x] 2.3 Thêm thanh điều hướng trên/dưới: prev/next buttons + dropdown chọn chương
- [x] 2.4 Thêm nút "Sửa bản dịch" link tới editor
- [x] 2.5 Thêm nút "Copy tất cả" (copy toàn bộ nội dung chương)
- [x] 2.6 Thêm nút copy từng đoạn (icon nhỏ bên phải mỗi paragraph)

## 3. CSS — Theme & Typography

- [x] 3.1 Thêm CSS variables cho light/dark theme trong reader context
- [x] 3.2 Style reader layout: max-width, line-height, paragraph spacing, typography
- [x] 3.3 Thêm theme toggle button (sun/moon icon)
- [x] 3.4 Style nút điều hướng, dropdown, bookmark indicator
- [x] 3.5 Responsive: đảm bảo đọc tốt trên mobile

## 4. JavaScript — Client-side Features

- [x] 4.1 Theme toggle: lưu/đọc `data-theme` từ localStorage
- [x] 4.2 Font/cỡ chữ/chiều rộng dòng: controls + lưu localStorage
- [x] 4.3 Copy text: dùng Clipboard API, fallback `execCommand`, hiển thị toast "Đã copy"
- [x] 4.4 Lưu vị trí cuộn: debounce `scroll` event, lưu `scrollY` vào localStorage (key: `n2e-read-{slug}-{index}`)
- [x] 4.5 Khôi phục vị trí cuộn khi page load
- [x] 4.6 Bookmark: lưu/xóa vị trí bookmark vào localStorage, hiển thị indicator
- [x] 4.7 Phím tắt: mũi tên trái/phải (prev/next), `B` (bookmark), `C` (copy all)
- [x] 4.8 Khôi phục font/theme/size preferences khi page load

## 5. Navigation — Keyboard & Chapter Switch

- [x] 5.1 Thêm keyboard event listener cho phím tắt (chỉ khi không focus input/textarea)
- [x] 5.2 Prev/next: chuyển hướng URL tương đối
- [x] 5.3 Dropdown: `onchange` redirect tới chapter được chọn
