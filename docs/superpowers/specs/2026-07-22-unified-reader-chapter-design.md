# Gộp Chapter vào Reader

Date: 2026-07-22

## Mục tiêu

Gộp giao diện Chapter/editor vào Reader để `/ebooks/{slug}/read/{index}` trở thành trang mặc định cho cả đọc và biên tập chương. Reader vẫn ưu tiên trải nghiệm đọc sạch, nhưng có thể bật chế độ biên tập để thao tác crawl/dịch/glossary và so sánh với raw.

## Quyết định UX

### Reader là mặc định

- Người dùng mở chương qua `/ebooks/{slug}/read/{index}`.
- Nếu chương đã có bản dịch, trang hiển thị nội dung VI như reader hiện tại.
- Các tính năng đọc hiện có vẫn giữ: chọn chương, prev/next, bookmark, copy, tuỳ chỉnh font/theme/width, ghi chú lỗi dịch, sửa đoạn inline.

### Empty state theo dữ liệu

- Nếu chưa có raw: giữa trang hiển thị CTA lớn **Crawl**.
- Nếu có raw nhưng chưa có bản dịch: giữa trang hiển thị CTA lớn **Dịch**.
- CTA dùng lại endpoint action hiện có thay vì thêm backend mới.

### Chế độ biên tập

- Thêm nút **Chế độ biên tập** trên thanh nav reader.
- Mặc định tắt để reader không bị rối.
- Khi bật, hiển thị toolbar kỹ thuật:
  - Crawl / crawl lại
  - Dịch / dịch lại
  - Làm sạch Hán
  - Xóa raw
  - Xóa bản dịch
  - Mở Glossary
- Mode có thể được kích hoạt từ query `?edit=1` để route Chapter cũ chuyển vào đúng trạng thái.

### So sánh với raw

- Thêm nút **So sánh raw**.
- Khi bật, nội dung reader được thay bằng bảng 2 cột: `ZH raw | VI biên tập`.
- Desktop: 2 cột song song theo paragraph.
- Mobile: từng paragraph xếp dọc, raw nhỏ/mờ phía trên, VI phía dưới.
- Tắt so sánh thì quay lại reader VI bình thường.

## Kiến trúc

### Route

- `app/routes/reader.py` sẽ truyền thêm dữ liệu raw và edit context vào `reader.html`:
  - `has_raw`
  - `raw`
  - `raw_paras`
  - `edit_paras`
  - `raw_char_count`
  - metadata cần hiển thị nếu có
- `app/routes/chapters.py` route GET `/ebooks/{slug}/chapters/{index}` sẽ redirect sang `/ebooks/{slug}/read/{index}?edit=1`.
- Các POST/API hiện có trong `chapters.py` được giữ lại để toolbar reader gọi lại, giảm rủi ro rewrite.

### Template

- `app/templates/reader.html` nhận thêm:
  - empty state CTA Crawl/Dịch
  - edit toolbar ẩn/hiện
  - compare raw view ẩn/hiện
- `chapter.html` không còn là giao diện chính cho GET theo slug, nhưng có thể giữ lại tạm thời cho back-compat route không slug hoặc để tránh xóa scope lớn.

### Dữ liệu paragraph

- Raw và bản dịch được tách paragraph bằng cùng logic đơn giản như Chapter hiện tại: split theo dòng trống, gộp line trong cùng block.
- Hai danh sách paragraph được pad về cùng độ dài để render bảng so sánh.
- Nếu raw rỗng, không render bảng so sánh; hiển thị CTA Crawl.

## User flows

### 1. Đọc chương đã dịch

1. Người dùng mở ebook/chương.
2. App vào `/ebooks/{slug}/read/{index}`.
3. Nếu có translated, hiển thị reader VI.
4. Người dùng có thể bookmark, đổi font, copy, ghi chú, sửa đoạn inline.

### 2. Chương chưa crawl

1. Người dùng mở chương.
2. App phát hiện `has_raw = false`.
3. Nội dung giữa trang hiển thị nút lớn **Crawl**.
4. Bấm Crawl gọi action hiện có.
5. Sau khi crawl xong, người dùng có thể bấm Dịch nếu chưa có bản dịch.

### 3. Chương đã crawl nhưng chưa dịch

1. Người dùng mở chương.
2. App phát hiện có raw nhưng chưa có translated.
3. Nội dung giữa trang hiển thị nút lớn **Dịch**.
4. Bấm Dịch gọi action hiện có.
5. Sau khi dịch xong, reader hiển thị bản VI.

### 4. Biên tập và so sánh raw

1. Người dùng bật **Chế độ biên tập**.
2. Toolbar kỹ thuật xuất hiện.
3. Người dùng bấm **So sánh raw**.
4. Reader chuyển sang bảng `ZH raw | VI biên tập`.
5. Người dùng tắt so sánh để quay lại đọc VI.

### 5. Link Chapter cũ

1. Người dùng mở `/ebooks/{slug}/chapters/{index}`.
2. App redirect sang `/ebooks/{slug}/read/{index}?edit=1`.
3. Reader mở sẵn chế độ biên tập.

## Error handling

- Nếu chưa có manifest: giữ lỗi 404 hiện có.
- Nếu không tìm thấy chương: giữ lỗi 404 hiện có.
- Nếu action crawl/dịch thất bại: dùng hành vi form/redirect/toast hiện có.
- Nếu người dùng bật so sánh raw nhưng raw rỗng: hiển thị thông báo cần crawl trước và nút Crawl.

## Testing

- Unit/route tests nên kiểm tra:
  - Reader trả 200 khi chương có translated.
  - Reader hiển thị CTA Crawl khi chưa có raw.
  - Reader hiển thị CTA Dịch khi có raw nhưng chưa có translated.
  - GET `/ebooks/{slug}/chapters/{index}` redirect sang `/ebooks/{slug}/read/{index}?edit=1`.
- Manual UI check:
  - reader mặc định sạch, edit toolbar ẩn.
  - bật edit mode thấy toolbar.
  - bật/tắt so sánh raw hoạt động trên desktop và mobile.
  - prev/next/chapter select vẫn tới `/read`.

## Ngoài phạm vi

- Không rewrite toàn bộ Chapter backend.
- Không thêm SPA/state manager mới.
- Không xóa ngay `chapter.html` nếu chưa cần; ưu tiên redirect và giữ back-compat.
