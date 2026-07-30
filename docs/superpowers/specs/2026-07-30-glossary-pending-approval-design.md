# Glossary Pending Approval Design

Ngày: 2026-07-30
Trạng thái: đã được người dùng duyệt

## Mục tiêu

Đưa đề xuất glossary chờ duyệt và các xung đột do AI tạo ra vào cùng bảng
`Glossary Entries`. Người dùng có thể xem, hiệu chỉnh, duyệt hoặc bỏ từng dòng
và hàng loạt. Chỉ dữ liệu đã duyệt mới trở thành nguồn glossary chính dùng cho
prompt dịch.

## Phạm vi

- Hiển thị đề xuất mới và xung đột trước các glossary entry đã duyệt.
- Cho phép sửa đề xuất AI trước khi duyệt hoặc chấp nhận ghi đè.
- Hỗ trợ thao tác từng dòng và hàng loạt theo từng loại dữ liệu.
- Giữ nguyên phân trang, tìm kiếm và sắp xếp server-side cho glossary chính.
- Tận dụng các API pending hiện có và thêm API conflict bulk để thao tác ghi đè
  và resolve được thực hiện an toàn trên server.

Không thay đổi cách translator tạo `glossary_pending` hoặc
`glossary_conflicts`, và không đưa dữ liệu chưa duyệt vào prompt.

## Mô hình hiển thị

Bảng có ba loại dòng theo thứ tự cố định:

1. `conflict`: source đã tồn tại nhưng AI đề xuất target khác.
2. `pending`: source mới chưa tồn tại trong glossary chính.
3. `entry`: glossary chính đã duyệt.

Bảng có các cột:

| Cột | Conflict | Pending | Entry |
| --- | --- | --- | --- |
| Chọn | Checkbox conflict | Checkbox pending | Checkbox entry |
| Trạng thái | `Xung đột` | `Chờ duyệt` | Không cần badge |
| Hán | Source hiện tại, chỉ đọc | Source đề xuất, cho sửa | Source chính, cho sửa |
| Việt hiện tại | Target đang dùng, chỉ đọc | Trống | Target chính, cho sửa |
| AI đề xuất mới | Cho sửa | Cho sửa | Trống |
| Ghi chú | Cho sửa trước khi ghi đè | Cho sửa trước khi duyệt | Cho sửa |
| Thao tác | Chấp nhận ghi đè / Giữ hiện tại | Duyệt / Bỏ đề xuất | Xóa |

Conflict và pending dùng màu nền hoặc badge trạng thái rõ ràng nhưng vẫn tuân
theo hệ thống màu sáng/tối hiện có. Pending và conflict luôn xuất hiện ở đầu
bảng, không bị ẩn bởi trang hiện tại của glossary chính.

## Tải dữ liệu

Client tải song song ba nguồn:

- `/api/ebooks/{slug}/glossary/list` cho trang glossary chính hiện tại.
- `/api/ebooks/{slug}/glossary/pending` cho toàn bộ đề xuất mới.
- `/api/ebooks/{slug}/glossary/suspects` cho conflicts và dữ liệu nghi vấn hiện
  có; client chỉ lấy phần `conflicts` để ghép vào bảng chính.

Pending và conflict được quản lý trong state riêng, không trộn vào `ROWS` dùng
cho phân trang glossary. Tìm kiếm, sắp xếp và phân trang chỉ áp dụng cho entry
chính. Bộ đếm hiển thị riêng số entry chính, pending và conflict để tránh hiểu
nhầm tổng phân trang.

## Thao tác từng dòng

### Pending

- `Duyệt` gửi source, target đề xuất đã sửa, note và source gốc tới API approve.
- Thành công sẽ upsert entry vào glossary chính và gỡ source gốc khỏi pending.
- `Bỏ đề xuất` chỉ gỡ source gốc khỏi pending.

### Conflict

- `Chấp nhận ghi đè` dùng target AI đã sửa để upsert source hiện tại, sau đó
  resolve đúng conflict.
- `Giữ hiện tại` chỉ resolve conflict, không sửa glossary chính.
- Nếu upsert thất bại thì conflict không được resolve.
- Sau khi chấp nhận target mới, UI có thể dùng luồng propagate hiện có để đề nghị
  thay target cũ trong các chương đã dịch.

### Entry chính

Giữ nguyên autosave khi rời ô, xóa từng dòng và luồng propagate hiện có.

## Thao tác hàng loạt

Toolbar chỉ hiện nút khi có dữ liệu phù hợp:

- `Duyệt đã chọn`: duyệt các pending được chọn.
- `Duyệt tất cả`: duyệt snapshot toàn bộ pending đang có trên client, gồm các
  giá trị người dùng đã hiệu chỉnh.
- `Bỏ đề xuất đã chọn`: gỡ các pending được chọn mà không thêm vào glossary.
- `Chấp nhận ghi đè đã chọn`: ghi đè các conflict được chọn bằng target AI đang
  hiển thị.
- `Giữ hiện tại đã chọn`: resolve các conflict được chọn mà không sửa glossary.
- `Xóa đã chọn`: chỉ xóa các entry chính được chọn.

Checkbox đầu bảng chọn mọi dòng đang hiển thị. Mỗi nút bulk tự lọc đúng loại
dòng, hiển thị số lượng của loại đó, và không áp dụng hành động lên loại khác.
Hộp xác nhận ghi rõ số mục và hậu quả, đặc biệt với ghi đè và xóa.

## Tính nhất quán và cạnh tranh

Bulk action gửi một snapshot cụ thể thay vì lệnh mơ hồ "duyệt mọi thứ trên
server". Nếu job dịch thêm pending hoặc conflict trong lúc request đang chạy,
các mục mới không nằm trong snapshot phải được giữ lại.

Với conflict, resolve phải nhận đủ khóa nhận dạng hiện có (`source` và target AI
gốc nếu endpoint đang dùng cặp này). Việc người dùng sửa target AI chỉ thay đổi
giá trị ghi vào glossary, không thay đổi khóa dùng để gỡ conflict gốc.

Mỗi thao tác khóa tạm nút liên quan để tránh gửi lặp. Sau thành công, client tải
lại cả ba nguồn. Sau lỗi, state vẫn giữ nguyên và hiển thị thông báo từ API nếu
có.

## Backend

Các API pending hiện có tiếp tục là giao diện chính:

- `GET /glossary/pending`
- `POST /glossary/pending/approve`
- `POST /glossary/pending/clear`

API conflict hiện có tiếp tục hỗ trợ resolve từng mục trong tab `Nghi vấn`. Bảng
hợp nhất dùng endpoint mới:

- `POST /api/ebooks/{slug}/glossary/conflicts/bulk-resolve`

Payload gồm `action` là `take` hoặc `keep`, và `entries` chứa `source`, target AI
gốc dùng làm khóa conflict, target đã hiệu chỉnh dùng để ghi glossary, cùng note.
Endpoint xác nhận từng conflict vẫn tồn tại. Với `take`, server upsert target đã
hiệu chỉnh trước rồi mới gỡ conflict; với `keep`, server chỉ gỡ conflict. Response
trả số mục đã xử lý và số conflict còn lại. Mục không còn tồn tại được bỏ qua và
không thay đổi glossary.

Không có endpoint nào được đưa pending trực tiếp vào nguồn prompt ngoài việc
upsert thành glossary chính.

## Xử lý lỗi

- Payload không có dòng hợp lệ trả `400` với thông báo rõ ràng.
- Pending đã biến mất được bỏ qua an toàn; response phản ánh số thực tế đã xử lý.
- Conflict không còn tồn tại không làm thay đổi glossary nếu server không thể
  xác nhận khóa conflict.
- Upsert thất bại không được gỡ pending hoặc conflict tương ứng.
- Lỗi mạng giữ nguyên dữ liệu đang sửa trên client để người dùng có thể thử lại.

## Kiểm thử

### Route tests

- Duyệt nhiều pending sẽ upsert đúng target/note đã sửa và chỉ gỡ source gốc đã
  gửi.
- Pending được thêm đồng thời nhưng không có trong snapshot vẫn còn nguyên.
- Bỏ nhiều pending không tạo glossary entry.
- Chấp nhận conflict ghi target đã sửa rồi mới resolve conflict.
- Upsert conflict thất bại không resolve conflict.
- Giữ conflict không thay đổi target hiện tại.
- Bulk conflict xử lý đúng các mục được chọn và báo số lượng chính xác.

### Template/JavaScript tests

- Có controls cho duyệt pending, bỏ pending, nhận conflict và giữ conflict.
- Render đúng ba loại dòng và cột `AI đề xuất mới`.
- Bulk selection phân loại pending, conflict và entry chính.
- `Duyệt tất cả` gửi snapshot pending đang hiển thị thay vì cờ `all`.
- Reload dữ liệu sau thành công và giữ state khi request lỗi.

### Regression

- CRUD, pagination, search và sort của glossary chính vẫn hoạt động.
- Tab `Nghi vấn` và luồng resolve conflict hiện có không bị hỏng.
- Translator tiếp tục bỏ qua pending và conflict khi tạo prompt.
