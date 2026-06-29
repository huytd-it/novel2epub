## Why

Trang chapter hiện tại (`chapter.html`) là editor 3 cột (ZH raw | MT | biên tập) — phục vụ mục đích review/sửa bản dịch. Khi muốn **đọc** bản dịch như đọc sách, giao diện editor cồng kềnh, thiếu điều hướng chương, không có tính năng đọc cơ bản (copy, bookmark, đọc liên tục). Cần một dedicated reader page tách biệt.

## What Changes

- Thêm route `/ebooks/{slug}/read/{index}` — trang đọc chương với giao diện sách sạch
- Thêm route `/ebooks/{slug}/read` — landing page chọn chương để đọc (hoặc redirect chương đầu)
- **Điều hướng chương**: prev/next chapter, dropdown chọn chương nhanh
- **Copy text**: nút copy toàn bộ chương hoặc copy từng đoạn
- **Font & hiển thị**: tuỳ chỉnh font, cỡ chữ, chiều rộng dòng, dark/light theme (localStorage)
- **Đọc liên tục**: cuộn mượt, vị trí đọc được lưu (resume khi quay lại)
- **Bookmark**: đánh dấu vị trí đọc dở
- **Link tới editor**: nút chuyển nhanh sang trang editor để sửa bản dịch

## Capabilities

### New Capabilities
- `page-reader`: Trang đọc chương với giao diện sách, điều hướng, copy, bookmark, tuỳ chỉnh hiển thị

### Modified Capabilities
<!-- Không có capability nào thay đổi yêu cầu — reader là trang mới tách biệt -->

## Impact

- **Routes mới**: thêm `reader.py` trong `app/routes/`
- **Template mới**: `reader.html` trong `app/templates/`
- **JS/CSS**: thêm styles cho reader mode (theme, typography, layout)
- **Storage**: thêm field `bookmark` vào manifest hoặc meta chương (nếu bookmark lưu server-side)
- **Không ảnh hưởng** đến editor hiện tại — hai trang độc lập
