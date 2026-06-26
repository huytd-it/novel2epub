## ADDED Requirements

### Requirement: Three-column chapter editor layout
Trang chương (`app/templates/chapter.html`) SHALL trình bày nội dung theo 3 cột song song: cột `ZH` (gốc tiếng Trung, chỉ đọc), cột `VI` (bản dịch máy, chỉ đọc, để đối chiếu), và cột `Biên tập` (sửa tay, là bản lưu cuối cùng đi vào EPUB). Layout 3 cột SHALL thay thế layout 2 cột hiện tại.

#### Scenario: Mở chương đã dịch
- **WHEN** người dùng mở trang một chương đã có bản dịch
- **THEN** trang hiển thị 3 cột: ZH (gốc), VI (bản dịch máy, chỉ đọc), Biên tập (nội dung sửa được)

#### Scenario: Cột ZH giữ tính năng tô sáng & jump-to glossary
- **WHEN** bật tô sáng thuật ngữ và bấm soi vị trí (jump-to) một mục glossary
- **THEN** cột ZH tô sáng thuật ngữ và cuộn tới đúng vị trí như hành vi hiện tại, không bị mất khi chuyển sang layout 3 cột

#### Scenario: Màn hình hẹp
- **WHEN** bề rộng cửa sổ nhỏ hơn ngưỡng responsive
- **THEN** 3 cột xếp dọc (stack) thay vì dàn ngang, vẫn đọc/sửa được

### Requirement: Machine-translation snapshot separate from edited copy
Hệ thống SHALL lưu bản dịch máy (kết quả translator) như một snapshot độc lập với bản biên tập cuối (`translated`). Cột `VI` SHALL hiển thị snapshot này; cột `Biên tập` SHALL hiển thị và ghi `translated`. Bước build EPUB SHALL tiếp tục dùng `translated` (bản biên tập), không dùng snapshot.

#### Scenario: Dịch một chương sinh ra snapshot máy
- **WHEN** một chương được dịch qua pipeline
- **THEN** bản dịch máy được ghi vào snapshot (cột VI) và đồng thời khởi tạo bản biên tập (`translated`, cột Biên tập) bằng chính nội dung đó

#### Scenario: Sửa cột Biên tập không làm đổi cột VI
- **WHEN** người dùng sửa và lưu nội dung ở cột Biên tập
- **THEN** `translated` được cập nhật, còn snapshot bản dịch máy (cột VI) giữ nguyên để vẫn đối chiếu được với bản máy gốc

#### Scenario: Chương cũ chưa có snapshot máy (degrade an toàn)
- **WHEN** mở một chương đã dịch từ trước thay đổi này, chưa có snapshot bản dịch máy
- **THEN** cột VI hiển thị (chỉ đọc) chính nội dung `translated` hiện có thay vì trống, trang không lỗi

### Requirement: Edit column supports direct editing and AI editing
Cột `Biên tập` SHALL cho phép (a) sửa trực tiếp trong `textarea` và lưu, và (b) chạy "Biên tập bằng AI" tái dùng pipeline `ai/rewrite` hiện có trên nội dung cột này. Chỉ cột Biên tập SHALL có nút Lưu; cột ZH và VI là chỉ đọc.

#### Scenario: Sửa tay rồi lưu
- **WHEN** người dùng chỉnh sửa nội dung trong cột Biên tập và bấm Lưu
- **THEN** `translated` được ghi lại, nội dung được giữ sau khi tải lại trang

#### Scenario: Biên tập bằng AI
- **WHEN** người dùng bấm nút "Biên tập bằng AI" trên cột Biên tập
- **THEN** hệ thống chạy pipeline `ai/rewrite` (job nền) và hiển thị bản nháp AI qua panel diff hiện có để xem trước trước khi áp dụng

#### Scenario: Áp dụng bản nháp AI ghi vào cột Biên tập
- **WHEN** người dùng áp dụng bản nháp AI
- **THEN** `translated` (cột Biên tập) được cập nhật bằng bản nháp, snapshot bản dịch máy (cột VI) không đổi
