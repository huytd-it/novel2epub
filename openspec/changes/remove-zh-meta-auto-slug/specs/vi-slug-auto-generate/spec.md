## ADDED Requirements

### Requirement: Tự động sinh slug từ tiêu đề tiếng Việt có dấu

Hệ thống SHALL tự động sinh slug từ tiêu đề tiếng Việt bằng cách chuyển các ký tự có dấu sang ký tự không dấu tương ứng (đ → d, ơ → o, ư → u, v.v.), strip toàn bộ ký tự non-ASCII còn lại, thay thế khoảng trắng và ký tự đặc biệt bằng dấu gạch ngang, và lowercase toàn bộ. Slug sinh ra SHALL dùng được làm URL path segment và tên thư mục.

#### Scenario: Tiêu đề tiếng Việt có dấu cơ bản
- **WHEN** người dùng nhập tiêu đề `"Tên Truyện Hay"`
- **THEN** slug sinh ra là `"ten-truyen-hay"`

#### Scenario: Tiêu đề có ký tự đặc biệt và nhiều khoảng trắng
- **WHEN** người dùng nhập tiêu đề `"Tên Truyện:  Hay   Quá!"`
- **THEN** slug sinh ra là `"ten-truyen-hay-qua"` (dấu hai chấm và `!` thành gạch ngang, khoảng trắng thừa gộp lại)

#### Scenario: Tiêu đề có chữ `đ` và `Đ`
- **WHEN** người dùng nhập tiêu đề `"Đường Đến Đỉnh Cao"`
- **THEN** slug sinh ra là `"duong-den-dinh-cao"`

#### Scenario: Tiêu đề trống hoặc chỉ có ký tự đặc biệt
- **WHEN** người dùng nhập tiêu đề `""` hoặc `"!@#$%"`
- **THEN** slug sinh ra là `"novel"` (fallback)

#### Scenario: Tiêu đề toàn ký tự ASCII
- **WHEN** người dùng nhập tiêu đề `"Hello World 123"`
- **THEN** slug sinh ra là `"hello-world-123"`
