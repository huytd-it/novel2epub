## ADDED Requirements

### Requirement: Parse văn bản đã biên tập theo marker

Hệ thống SHALL nhận khối văn bản người dùng dán lại (đã được AI biên tập) và parse theo marker chương để tách thành các cặp `(index, nội-dung-mới)`.

#### Scenario: Parse thành công nhiều chương

- **WHEN** người dùng dán khối văn bản chứa đầy đủ marker của các chương đã xuất
- **THEN** hệ thống tách ra đúng số chương với `index` và nội dung biên tập tương ứng

#### Scenario: Thiếu marker hoàn toàn

- **WHEN** văn bản dán vào không chứa marker chương nào hợp lệ
- **THEN** hệ thống báo lỗi không nhận diện được chương và KHÔNG ghi đè bất kỳ file nào

#### Scenario: Marker không khớp chương đã chọn

- **WHEN** văn bản chứa `index` không nằm trong tập chương của ebook, hoặc thiếu một số chương đã xuất
- **THEN** hệ thống báo cụ thể chương nào dư/thiếu và chỉ cho ghi đè các chương khớp sau khi người dùng xác nhận

### Requirement: Preview thay đổi trước khi ghi đè

Trước khi ghi vào `translated/`, hệ thống SHALL hiển thị preview cho biết mỗi chương sẽ thay đổi như thế nào (số chương được cập nhật, chương không đổi) và CHỈ ghi đè sau khi người dùng xác nhận.

#### Scenario: Xem preview rồi xác nhận

- **WHEN** parse thành công và người dùng yêu cầu nhập
- **THEN** hệ thống hiển thị danh sách chương sẽ được cập nhật trước, chờ người dùng xác nhận rồi mới ghi đè

#### Scenario: Hủy trước khi xác nhận

- **WHEN** người dùng xem preview nhưng không xác nhận
- **THEN** không có file `translated/` nào bị thay đổi

### Requirement: Ghi đè bản dịch an toàn

Khi xác nhận, hệ thống SHALL ghi nội dung biên tập vào `translated/` của đúng từng chương theo `index`, không đụng tới `translated_mt/` (snapshot bản máy) và không ảnh hưởng các chương không nằm trong tập nhập.

#### Scenario: Ghi đè đúng chương

- **WHEN** người dùng xác nhận nhập với tập chương đã parse
- **THEN** mỗi chương trong tập được ghi nội dung mới vào `translated/`, các chương khác giữ nguyên

#### Scenario: Giữ nguyên snapshot bản máy

- **WHEN** hệ thống ghi đè bản dịch khi nhập
- **THEN** file `translated_mt/` của các chương đó KHÔNG bị thay đổi

### Requirement: Parse và merge glossary do AI sinh

Khi văn bản nhập chứa khối `GLOSSARY`, hệ thống SHALL parse các mục trong nhóm `[NAMES]` và `[VIETPHRASE]` (format `source = target`) và merge vào `names.txt` / `vietphrase.txt` tương ứng, bỏ qua mục trùng và mục thiếu `source`/`target`.

#### Scenario: Merge glossary mới vào đúng file

- **WHEN** khối nhập chứa `GLOSSARY` với mục mới trong `[NAMES]` và `[VIETPHRASE]`
- **THEN** mục `[NAMES]` được thêm vào `names.txt` và mục `[VIETPHRASE]` được thêm vào `vietphrase.txt`

#### Scenario: Bỏ qua mục trùng

- **WHEN** một mục glossary đã tồn tại với đúng `source = target`
- **THEN** hệ thống không thêm trùng và không báo lỗi

#### Scenario: Không có khối glossary

- **WHEN** văn bản nhập không chứa khối `GLOSSARY`
- **THEN** hệ thống chỉ ghi đè bản dịch như bình thường và không thay đổi file glossary

#### Scenario: Glossary nằm trong preview

- **WHEN** người dùng chạy import ở chế độ preview và văn bản có khối `GLOSSARY`
- **THEN** hệ thống hiển thị các mục glossary sẽ được thêm nhưng CHƯA ghi vào file cho tới khi xác nhận
