## ADDED Requirements

### Requirement: Xuất gom bản dịch nhiều chương đã chọn

Hệ thống SHALL cho phép người dùng chọn nhiều chương trên trang ebook và xuất bản dịch hiện hành (`translated/`) của các chương đó thành một khối văn bản duy nhất, sẵn sàng để copy dán lên web chat AI biên tập.

#### Scenario: Xuất các chương đã tick

- **WHEN** người dùng tick ít nhất một chương rồi bấm "Xuất chương đã chọn"
- **THEN** hệ thống trả về một khối văn bản chứa bản dịch của tất cả chương đã chọn, sắp xếp theo `index` tăng dần

#### Scenario: Chưa chọn chương nào

- **WHEN** người dùng bấm "Xuất chương đã chọn" mà chưa tick chương nào
- **THEN** hệ thống báo lỗi yêu cầu chọn ít nhất một chương và KHÔNG xuất gì

### Requirement: Marker phân tách chương ổn định cho round-trip

Mỗi chương trong khối xuất SHALL được bao bằng marker chứa `index` chương để khi nhập lại có thể tách đúng từng chương. Marker MUST không trùng với nội dung văn bản thông thường và MUST giữ nguyên kể cả khi AI biên tập nội dung bên trong.

#### Scenario: Mỗi chương có marker mở đầu chứa index

- **WHEN** hệ thống xuất chương có `index = N`
- **THEN** phần nội dung chương đó được đặt sau một marker chứa giá trị `N` để import nhận diện

#### Scenario: Chương thiếu bản dịch

- **WHEN** một chương được chọn nhưng chưa có file trong `translated/`
- **THEN** hệ thống bỏ qua chương đó khỏi khối xuất và ghi rõ trong thông báo những chương bị bỏ qua

### Requirement: Kèm prompt hướng dẫn AI biên tập theo nguyên tắc edit

Khối xuất SHALL kèm phần prompt hướng dẫn AI biên tập bản dịch theo các nguyên tắc "edit đúng/hay" chắt lọc từ `docs/rule.md`, và yêu cầu AI GIỮ NGUYÊN marker chương khi trả kết quả, để bảo đảm nhập lại được.

#### Scenario: Prompt nêu nguyên tắc biên tập

- **WHEN** hệ thống tạo khối xuất
- **THEN** đầu khối có prompt yêu cầu AI: đối chiếu bản gốc để giữ đúng nghĩa, chọn ngôi xưng theo quan hệ nhân vật (hạn chế "ta–ngươi" máy móc), chỉnh ngữ pháp/trật tự từ tiếng Việt, cân bằng Hán–Việt với thuần Việt, và giữ tên riêng ở dạng Hán Việt viết hoa

#### Scenario: Prompt yêu cầu giữ marker

- **WHEN** hệ thống tạo khối xuất
- **THEN** prompt yêu cầu AI giữ nguyên các marker phân tách chương trong kết quả trả về

### Requirement: Đính kèm glossary hiện có để giữ tên nhất quán

Khối xuất SHALL đính kèm glossary hiện có của ebook (`names.txt` + `vietphrase.txt`) vào prompt, kèm chỉ thị yêu cầu AI dùng đúng các tên/thuật ngữ này, để bản biên tập nhất quán với chương đã dịch trước và giữa các lần export.

#### Scenario: Có glossary thì đính kèm

- **WHEN** ebook đã có mục trong `names.txt` hoặc `vietphrase.txt`
- **THEN** khối xuất chứa danh sách các cặp `source = target` đó kèm chỉ thị AI phải dùng đúng

#### Scenario: Chưa có glossary

- **WHEN** ebook chưa có mục glossary nào
- **THEN** hệ thống vẫn xuất bình thường, bỏ qua phần đính kèm glossary mà không báo lỗi

### Requirement: Yêu cầu AI tự sinh glossary xuyên suốt

Prompt SHALL yêu cầu AI, ngoài bản biên tập, xuất thêm một khối `GLOSSARY` ở cuối kết quả gồm các tên riêng/thuật ngữ MỚI gặp trong loạt chương, chia hai nhóm `[NAMES]` và `[VIETPHRASE]`, mỗi dòng theo format `source = target`, để import nạp ngược về hệ thống.

#### Scenario: Prompt mô tả định dạng glossary đầu ra

- **WHEN** hệ thống tạo khối xuất
- **THEN** prompt nêu rõ AI phải thêm khối `GLOSSARY` với hai nhóm `[NAMES]`/`[VIETPHRASE]` và mỗi mục viết dạng `source = target`

### Requirement: Xuất bản gốc (raw) để dịch bằng web chat AI

Hệ thống SHALL cho phép xuất bản gốc tiếng Trung (`raw/`) của các chương đã chọn, dùng cho chương chưa dịch hoặc muốn dịch lại, kèm prompt hướng dẫn AI DỊCH (không phải biên tập) sang tiếng Việt theo nguyên tắc dịch nhất quán với prompt dịch chính thức của hệ thống.

#### Scenario: Chọn chế độ xuất raw

- **WHEN** người dùng tick chương rồi bấm "Xuất RAW để dịch"
- **THEN** hệ thống trả về khối văn bản chứa bản gốc tiếng Trung của các chương đã chọn (sắp theo `index`), kèm prompt yêu cầu AI dịch sang tiếng Việt

#### Scenario: Chương chưa có raw

- **WHEN** một chương được chọn ở chế độ xuất raw nhưng chưa có file trong `raw/`
- **THEN** hệ thống bỏ qua chương đó khỏi khối xuất và ghi rõ trong thông báo những chương bị bỏ qua

#### Scenario: Prompt dịch nhất quán với prompt dịch chính thức

- **WHEN** hệ thống tạo khối xuất ở chế độ raw
- **THEN** prompt dịch áp dụng các nguyên tắc dịch giống prompt dịch mặc định của backend AI trong hệ thống (ngôi xưng theo quan hệ, ngữ pháp Việt, tên riêng Hán Việt nhất quán, không dịch kiểu Vietphrase ghép nghĩa từng chữ)
