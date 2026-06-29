## ADDED Requirements

### Requirement: Trang đọc chương
Hệ thống SHALL cung cấp trang đọc chương tại `/ebooks/{slug}/read/{index}` với giao diện sách sạch, chỉ hiển thị bản dịch (không có editor).

#### Scenario: Truy cập trang đọc
- **WHEN** người dùng truy cập `/ebooks/{slug}/read/{index}`
- **THEN** hệ thống hiển thị trang đọc với tiêu đề chương và nội dung bản dịch

#### Scenario: Chương không tồn tại
- **WHEN** người dùng truy cập `/ebooks/{slug}/read/{index}` với index không hợp lệ
- **THEN** hệ thống trả lỗi 404

#### Scenario: Chương chưa có bản dịch
- **WHEN** người dùng truy cập trang đọc chương chưa được dịch
- **THEN** hệ thống hiển thị thông báo "Chưa có bản dịch" và link tới editor

### Requirement: Điều hướng chương
Hệ thống SHALL cung cấp điều hướng prev/next chapter và dropdown chọn chương nhanh.

#### Scenario: Chuyển chương tiếp theo
- **WHEN** người dùng nhấn nút "Chương tiếp" hoặc phím mũi tên phải
- **THEN** hệ thống chuyển sang trang đọc chương tiếp theo

#### Scenario: Chuyển chương trước
- **WHEN** người dùng nhấn nút "Chương trước" hoặc phím mũi tên trái
- **THEN** hệ thống chuyển sang trang đọc chương trước đó

#### Scenario: Chọn chương từ dropdown
- **WHEN** người dùng chọn một chương từ dropdown
- **THEN** hệ thống chuyển sang trang đọc chương đó

#### Scenario: Chương đầu tiên
- **WHEN** người dùng đang ở chương đầu tiên
- **THEN** nút "Chương trước" bị disabled hoặc ẩn

#### Scenario: Chương cuối cùng
- **WHEN** người dùng đang ở chương cuối cùng
- **THEN** nút "Chương tiếp" bị disabled hoặc ẩn

### Requirement: Copy text
Hệ thống SHALL cho phép copy toàn bộ nội dung chương hoặc copy từng đoạn.

#### Scenario: Copy toàn bộ chương
- **WHEN** người dùng nhấn nút "Copy tất cả"
- **THEN** toàn bộ nội dung bản dịch được copy vào clipboard

#### Scenario: Copy từng đoạn
- **WHEN** người dùng chọn một đoạn văn và nhấn nút copy
- **THEN** đoạn văn đó được copy vào clipboard

#### Scenario: Thông báo copy thành công
- **WHEN** text được copy thành công
- **THEN** hệ thống hiển thị thông báo "Đã copy" trong 2 giây

### Requirement: Tuỳ chỉnh hiển thị
Hệ thống SHALL cho phép tuỳ chỉnh font, cỡ chữ, chiều rộng dòng, dark/light theme. Tất cả lưu trong localStorage.

#### Scenario: Thay đổi theme
- **WHEN** người dùng toggle dark/light mode
- **THEN** giao diện chuyển theme ngay lập tức và lưu preference vào localStorage

#### Scenario: Thay đổi font
- **WHEN** người dùng chọn font mới từ dropdown
- **THEN** nội dung hiển thị với font mới và lưu preference vào localStorage

#### Scenario: Thay đổi cỡ chữ
- **WHEN** người dùng chọn cỡ chữ mới
- **THEN** nội dung hiển thị với cỡ chữ mới và lưu preference vào localStorage

#### Scenario: Thay đổi chiều rộng dòng
- **WHEN** người dùng điều chỉnh chiều rộng dòng đọc
- **THEN** nội dung hiển thị với chiều rộng mới và lưu preference vào localStorage

#### Scenario: Khôi phục preference
- **WHEN** người dùng truy cập trang đọc lần sau
- **THEN** hệ thống tự động áp dụng font, cỡ chữ, theme, chiều rộng đã lưu

### Requirement: Lưu vị trí đọc
Hệ thống SHALL tự động lưu vị trí cuộn và khôi phục khi quay lại.

#### Scenario: Tự động lưu vị trí
- **WHEN** người dùng cuộn trang đọc
- **THEN** hệ thống debounce lưu vị trí cuộn vào localStorage (key theo slug + index)

#### Scenario: Khôi phục vị trí
- **WHEN** người dùng quay lại trang đọc cùng chương
- **THEN** hệ thống tự động cuộn đến vị trí đã lưu

#### Scenario: Vị trí lưu riêng theo chương
- **WHEN** người dùng đọc nhiều chương
- **THEN** mỗi chương có vị trí cuộn riêng, không ghi đè lẫn nhau

### Requirement: Bookmark
Hệ thống SHALL cho phép đánh dấu vị trí đọc dở.

#### Scenario: Đặt bookmark
- **WHEN** người dùng nhấn nút bookmark
- **THEN** hệ thống lưu vị trí hiện tại vào localStorage với timestamp

#### Scenario: Nhảy tới bookmark
- **WHEN** người dùng nhấn nút "Đi tới bookmark"
- **THEN** hệ thống cuộn đến vị trí bookmark đã lưu

#### Scenario: Xóa bookmark
- **WHEN** người dùng nhấn nút xóa bookmark
- **THEN** bookmark bị xóa khỏi localStorage

#### Scenario: Bookmark indicator
- **WHEN** trang đọc có bookmark
- **THEN** hiển thị indicator trên thanh điều hướng

### Requirement: Link tới editor
Hệ thống SHALL cung cấp link nhanh từ reader sang editor.

#### Scenario: Chuyển sang editor
- **WHEN** người dùng nhấn nút "Sửa bản dịch"
- **THEN** hệ thống chuyển sang trang editor (`/ebooks/{slug}/chapters/{index}`)

### Requirement: Phím tắt
Hệ thống SHALL hỗ trợ phím tắt cho các thao tác đọc cơ bản.

#### Scenario: Phím tắt điều hướng
- **WHEN** người dùng nhấn phím mũi tên trái/phải
- **THEN** hệ thống chuyển chương trước/tiếp

#### Scenario: Phím tắt bookmark
- **WHEN** người dùng nhấn phím `B`
- **THEN** hệ thống toggle bookmark tại vị trí hiện tại

#### Scenario: Phím tắt copy
- **WHEN** người dùng nhấn phím `C` (không có text selection)
- **THEN** hệ thống copy toàn bộ nội dung chương
