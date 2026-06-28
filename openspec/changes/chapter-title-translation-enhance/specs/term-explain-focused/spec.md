## ADDED Requirements

### Requirement: Giải thích từ riêng và thành ngữ
Hệ thống SHALL điều chỉnh prompt giải thích từ ngữ để tập trung vào tên riêng (nhân vật, địa danh, môn phái) và thành ngữ/diện tích, thay vì giải thích toàn bộ nội dung đoạn văn.

#### Scenario: Prompt mới tập trung vào từ riêng
- **WHEN** người dùng bấm nút 💡 "Giải thích từ ngữ" trên 1 paragraph
- **THEN** hệ thống SHALL sử dụng prompt mới chỉ yêu cầu giải thích: tên riêng Hán-Việt, thành ngữ, điển tích, thuật ngữ đặc thù

#### Scenario: Bỏ qua giải thích nội dung chung
- **WHEN** AI trả lời yêu cầu giải thích
- **THEN** câu trả lời SHALL chỉ chứa danh sách từ ngữ cần giải thích, KHÔNG chứa tóm tắt hay giải thích nội dung đoạn văn

#### Scenario: Format kết quả giải thích
- **WHEN** hiển thị kết quả giải thích
- **THEN** hệ thống SHALL hiển thị dạng danh sách: `**Từ gốc** (Hán): giải thích ngắn gọn`

### Requirement: Gợi ý từ ngữ quan trọng
Hệ thống SHALL thêm gợi ý cho người dùng khi review bản dịch, giúp họ nhận diện các từ ngữ cần chú ý.

#### Scenario: Hiển thị gợi ý trên paragraph
- **WHEN** paragraph chứa từ riêng hoặc thành ngữ chưa có trong glossary
- **THEN** hệ thống SHALL hiển thị icon gợi ý (⚠️ hoặc similar) bên cạnh nút 💡

#### Scenario: Click gợi ý để thêm glossary
- **WHEN** người dùng bấm vào gợi ý
- **THEN** hệ thống SHALL mở dialog hoặc panel để thêm từ vào glossary ngay lập tức

#### Scenario: Gợi ý dựa trên context chương
- **WHEN** tạo gợi ý
- **THEN** hệ thống SHALL phân tích cả raw text (ZH) và translated text để nhận diện từ quan trọng

### Requirement: Điều chỉnh giao diện giải thích
Hệ thống SHALL cập nhật giao diện phần giải thích từ ngữ để phù hợp hơn với mục đích.

#### Scenario: Đổi tên nút giải thích
- **WHEN** hiển thị nút 💡
- **THEN** tooltip SHALL hiển thị "Giải thích từ riêng/thành ngữ" thay vì "Giải thích từ ngữ"

#### Scenario: Thêm filter loại từ
- **WHEN** hiển thị kết quả giải thích
- **THEN** hệ thống SHALL có thể lọc theo loại: tên riêng, thành ngữ, thuật ngữ
