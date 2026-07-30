# Thiết kế tính năng xóa ebook

## Mục tiêu

Cho phép người dùng xóa vĩnh viễn một ebook khỏi cả trang Thư viện và trang Cài đặt. Thao tác xóa toàn bộ cấu hình và dữ liệu theo ebook trong SQLite, các automation liên quan, và file EPUB đầu ra. Đây là thao tác không thể hoàn tác nên người dùng phải nhập chính xác slug của ebook.

## Ngoài phạm vi

- Không hỗ trợ khôi phục ebook sau khi xóa.
- Không tự hủy job đang chạy hoặc đang chờ.
- Không xóa lịch sử các job đã kết thúc; lịch sử vẫn là nhật ký vận hành.
- Không xóa từ điển idiom dùng chung hoặc source preset dùng chung.
- Không hỗ trợ xóa hàng loạt bằng một lần xác nhận, vì yêu cầu nhập slug không phù hợp với thao tác nhiều ebook và dễ gây xóa nhầm.

## Kiến trúc

Logic xóa tập trung trong một service ở tầng ứng dụng thay vì đặt trực tiếp trong route. Service nhận đường dẫn DB, slug, đường dẫn EPUB và thông tin queue; nó chịu trách nhiệm xác thực điều kiện, xóa tài nguyên ngoài DB, rồi cập nhật DB. Route chỉ chuyển dữ liệu HTTP sang service và ánh xạ lỗi nghiệp vụ thành mã trạng thái.

Hai vị trí UI dùng cùng endpoint và cùng hành vi xác nhận:

- Trang Thư viện có nút `Xóa` trong nhóm thao tác của từng ebook.
- Cuối trang Cài đặt có vùng nguy hiểm với nút `Xóa ebook`.

Modal hiển thị tên và slug, cảnh báo dữ liệu sẽ bị xóa vĩnh viễn, yêu cầu nhập slug, và chỉ bật nút xác nhận khi nội dung khớp chính xác.

## Hợp đồng HTTP

`POST /library/ebooks/{slug}/delete` nhận form field `confirm_slug`.

Kết quả:

- `303` chuyển về `/` khi xóa thành công.
- `400` khi `confirm_slug` không trùng chính xác với slug trên URL.
- `404` khi ebook không tồn tại.
- `409` khi ebook có ít nhất một job pending hoặc running.
- `500` với thông báo rõ ràng khi file EPUB tồn tại nhưng không thể xóa.

Route không tin dữ liệu từ UI: mọi điều kiện đều được kiểm tra lại phía server.

## Luồng xóa

1. Kiểm tra `confirm_slug == slug`; sai thì dừng mà không thay đổi filesystem hoặc DB.
2. Đọc ebook trực tiếp từ DB; không tồn tại thì trả `404`.
3. Lấy snapshot queue dưới API thread-safe hiện có và tìm mọi job pending/running có `ebook == slug`; nếu có thì trả `409`.
4. Resolve cấu hình hiệu lực để lấy đúng `epub_path` trước khi xóa row ebook.
5. Nếu EPUB tồn tại, xóa file. Nếu thao tác filesystem lỗi, dừng và giữ nguyên toàn bộ dữ liệu DB.
6. Trong một transaction SQLite, xóa mọi row `automations` có `ebook == slug`, rồi xóa row `ebooks`.
7. Các bảng `chapters`, `glossary_entries`, `characters`, `character_relations`, `notes`, `ebook_covers`, và `ebook_extra_json` được xóa bằng foreign key `ON DELETE CASCADE`.
8. Xóa trạng thái archived đi cùng row `ebooks`; không cần thao tác riêng vì trạng thái hiện nằm trong cột `ebooks.archived`.

Thứ tự này ưu tiên không làm mất dữ liệu DB nếu việc xóa EPUB thất bại. Filesystem và SQLite không thể nằm trong cùng transaction; trường hợp hiếm SQLite thất bại sau khi EPUB đã xóa sẽ được trả lỗi và ghi log, nhưng không tạo thêm cơ chế rollback file hoặc thùng rác vì vượt quá phạm vi hiện tại.

## Kiểm tra queue

`JobQueue` bổ sung một truy vấn thread-safe theo ebook, ví dụ `has_active_ebook(ebook)`, kiểm tra cả `_running` và mọi deque trong `_pending`. Service chỉ cần giao tiếp qua API công khai này, không truy cập trạng thái nội bộ của queue.

Job đã hoàn tất, thất bại hoặc bị hủy trong history không chặn xóa. Automation không được coi là job đang hoạt động; chúng được xóa trong transaction để không thể chạy ebook mồ côi về sau.

## UI và lỗi

Modal xác nhận dùng lại một implementation chung trong template/base JavaScript nếu cấu trúc hiện tại cho phép; nếu không, markup nhỏ được include ở hai trang nhưng vẫn gọi chung endpoint. Nút xác nhận giữ trạng thái disabled cho đến khi slug khớp.

Khi server trả lỗi, modal vẫn mở và hiển thị nội dung lỗi. Khi thành công, trình duyệt chuyển về trang Thư viện. Nút bulk hiện mang nhãn `Gỡ khỏi thư viện` nhưng gọi endpoint chưa tồn tại; nút này sẽ bị loại bỏ để tránh một luồng xóa không đáp ứng xác nhận theo slug.

## Kiểm thử

Kiểm thử service/route bao phủ tối thiểu:

1. Thành công: EPUB bị xóa; ebook, dữ liệu cascade và automation biến mất; response chuyển về `/`; lịch sử job không bị xóa.
2. Sai slug xác nhận: trả `400`; EPUB, ebook, dữ liệu con và automation đều còn nguyên.
3. Lỗi EPUB: mô phỏng lỗi unlink, trả `500`; DB và automation không thay đổi.
4. Job đang hoạt động: kiểm tra riêng pending hoặc running đại diện, trả `409`; EPUB và DB không thay đổi.

Kiểm thử bổ sung:

- Ebook không tồn tại trả `404`.
- API queue phát hiện job theo đúng ebook và không chặn bởi job của ebook khác hoặc history.
- Trang Thư viện và trang Cài đặt đều render điểm kích hoạt xóa cùng slug.
- Foreign-key cascade xóa các bảng dữ liệu per-ebook quan trọng.

## Tiêu chí hoàn thành

- Người dùng có thể bắt đầu xóa từ cả Thư viện và Cài đặt.
- Không thể gửi xóa thành công nếu không xác nhận đúng slug.
- Không thể xóa ebook có job pending/running.
- Xóa thành công loại bỏ EPUB, automation và toàn bộ dữ liệu SQLite riêng của ebook.
- Lỗi xóa EPUB không làm thay đổi DB.
- Các kiểm thử mới và toàn bộ test suite liên quan đều vượt qua.
