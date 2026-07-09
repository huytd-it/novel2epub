## ADDED Requirements

### Requirement: Nút action không bị disabled khi có job đang chạy

Hệ thống SHALL giữ tất cả nút action (crawl, dịch, cleanup Hán, xóa bản dịch, AI review...) luôn ở trạng thái enabled, không phụ thuộc vào việc có job nào cùng category đang chạy hay không. Mọi request SHALL được enqueue vào hàng đợi.

#### Scenario: Bấm "Dịch" khi đang có job dịch khác đang chạy
- **WHEN** job dịch đang chạy cho chapter 1
- **THEN** nút "Dịch" trên chapter 5 vẫn enabled
- **THEN** khi bấm "Dịch" trên chapter 5, hệ thống enqueue job mới vào queue, không trả 409

#### Scenario: Bấm "Crawl" khi đang có job crawl đang chạy
- **WHEN** job crawl đang chạy
- **THEN** nút "Crawl selected" vẫn enabled
- **THEN** khi bấm, job mới được enqueue bình thường

### Requirement: Endpoint action đơn lẻ không trả 409

Hệ thống SHALL không trả HTTP 409 khi người dùng gửi action đơn lẻ (POST `/ebooks/{slug}/chapters/{index}/action`) trong lúc có job khác đang chạy. Mọi request hợp lệ SHALL được enqueue và trả về redirect 303.

#### Scenario: Action đơn lẻ luôn thành công
- **WHEN** người dùng gửi POST `/ebooks/{slug}/chapters/5/action` với `action=translate` trong lúc job dịch khác đang chạy
- **THEN** server enqueue job mới và trả 303 redirect
- **THEN** không có HTTP 409 trong bất kỳ trường hợp nào

### Requirement: Queue status indicator thay thế disabled state

Hệ thống SHALL hiển thị badge nhỏ bên cạnh mỗi nhóm nút action (crawl/dịch) cho biết số job pending và running hiện tại, thay vì disable nút.

#### Scenario: Hiển thị queue status khi có job đang chạy
- **WHEN** có 3 job dịch pending và 1 job dịch running
- **THEN** badge cạnh nhóm nút dịch hiển thị "3 pending · 1 running"
- **THEN** tất cả nút dịch vẫn clickable

#### Scenario: Không hiển thị badge khi queue trống
- **WHEN** không có job nào trong category dịch
- **THEN** không hiển thị badge hoặc hiển thị badge "0" (tùy thiết kế UI)
