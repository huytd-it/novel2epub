## ADDED Requirements

### Requirement: JobQueue cho phép nhiều translate job trên các ebook khác nhau chạy song song

Khi có >1 worker cho category "translate", JobQueue SHALL cho phép các job translate trên các ebook khác nhau chạy đồng thời.

#### Scenario: Hai ebook khác nhau — translate song song
- **WHEN** ebook A đang chạy translate
- **AND** người dùng enqueue translate cho ebook B
- **THEN** job translate ebook B SHALL bắt đầu chạy ngay (không cần đợi A xong)
- **AND** cả hai job SHALL chạy đồng thời

#### Scenario: Cùng ebook — xếp hàng chờ
- **WHEN** ebook A đang chạy translate
- **AND** người dùng enqueue translate cho ebook A lần nữa
- **THEN** job thứ hai SHALL ở trạng thái pending cho đến khi job đầu hoàn tất

#### Scenario: Worker tối đa bị chiếm
- **WHEN** `workers["translate"] = 2`
- **AND** 2 job translate trên 2 ebook khác nhau đang chạy
- **AND** người dùng enqueue translate cho ebook C
- **THEN** job cho ebook C SHALL ở trạng thái pending

### Requirement: Per-ebook lock ngăn xung đột I/O trên cùng ebook

JobQueue SHALL ngăn 2 job cùng category + cùng ebook chạy đồng thời để tránh xung đột ghi file `translated/{stem}.md`.

#### Scenario: Ebook lock hoạt động
- **WHEN** job translate cho ebook "tien-hiep" đang chạy
- **THEN** `_can_start("translate")` SHALL trả None cho mọi job translate có `ebook = "tien-hiep"`
- **AND** job đó SHALL được dequeue và chạy ngay sau khi job hiện tại hoàn tất

#### Scenario: Ebook lock khác category
- **WHEN** job translate cho ebook "tien-hiep" đang chạy
- **THEN** job crawl cho cùng ebook "tien-hiep" SHALL vẫn chạy được (lock per-category)

### Requirement: Web UI hiển thị trạng thái translate per-ebook

Web UI SHALL hiển thị trạng thái translate riêng cho từng ebook. Nút translate chỉ bị disable nếu đang có translate job chạy trên **chính ebook đó**.

#### Scenario: Translate khác ebook — nút active
- **WHEN** ebook "tien-hiep" đang chạy translate
- **AND** người dùng xem trang ebook "kiem-hiep"
- **THEN** nút translate cho "kiem-hiep" SHALL ở trạng thái active (có thể bấm)

#### Scenario: Translate cùng ebook — nút disabled
- **WHEN** ebook "tien-hiep" đang chạy translate
- **AND** người dùng xem trang ebook "tien-hiep"
- **THEN** nút translate SHALL disabled với message "Đang dịch…"

### Requirement: Mặc định worker translate = 2

JobRunner SHALL dùng mặc định `workers={"translate": 2}` nếu không có config workers nào được truyền vào.

#### Scenario: Default workers
- **WHEN** khởi tạo `JobRunner()` không truyền workers
- **THEN** `self.queue._workers["translate"]` SHALL bằng 2
- **AND** `self.queue._workers["crawl"]` SHALL bằng 1

#### Scenario: Override workers
- **WHEN** khởi tạo `JobRunner(workers={"translate": 4, "crawl": 2})`
- **THEN** `self.queue._workers["translate"]` SHALL bằng 4
- **AND** `self.queue._workers["crawl"]` SHALL bằng 2
