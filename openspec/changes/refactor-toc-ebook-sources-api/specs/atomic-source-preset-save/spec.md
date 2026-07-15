## ADDED Requirements

### Requirement: Lưu một preset độc lập không ảnh hưởng preset khác
Hàm `save_preset(path, preset)` SHALL lưu đúng một `SourcePreset` vào DB bằng `INSERT OR REPLACE` mà không xóa hay thay đổi bất kỳ row nào khác trong bảng `sources`.

#### Scenario: Lưu preset mới
- **WHEN** `save_preset()` được gọi với preset có `name` chưa tồn tại trong DB
- **THEN** một row mới được thêm vào bảng `sources`, số lượng row tăng thêm 1

#### Scenario: Cập nhật preset đã có
- **WHEN** `save_preset()` được gọi với preset có `name` đã tồn tại
- **THEN** row cũ bị ghi đè, tổng số row không thay đổi, các row khác không bị ảnh hưởng

#### Scenario: Crash giữa chừng khi lưu nhiều preset
- **WHEN** `save_presets()` đang ghi N preset và process bị kill sau khi ghi xong preset thứ K (K < N)
- **THEN** K preset đầu đã ghi đúng vẫn còn trong DB; DB không ở trạng thái trống

### Requirement: Xóa một preset độc lập
Hàm `delete_preset(path, name)` SHALL xóa đúng row có `name` khớp; nếu `name` không tồn tại thì không làm gì (không raise exception).

#### Scenario: Xóa preset tồn tại
- **WHEN** `delete_preset()` được gọi với `name` đang có trong DB
- **THEN** row đó bị xóa, các row khác không thay đổi

#### Scenario: Xóa preset không tồn tại
- **WHEN** `delete_preset()` được gọi với `name` không có trong DB
- **THEN** hàm trả về bình thường, không raise exception, DB không thay đổi

### Requirement: `save_presets()` vẫn hoạt động như cũ (back-compat)
`save_presets(path, presets)` SHALL ghi đúng tập preset được truyền vào. Preset nào có trong DB nhưng không có trong dict truyền vào SHALL bị xóa (để đảm bảo DB đồng bộ với state in-memory).

#### Scenario: Ghi toàn bộ preset thay thế preset cũ
- **WHEN** `save_presets()` được gọi với dict gồm 3 preset
- **THEN** bảng `sources` chứa đúng 3 row đó sau khi gọi; preset cũ không có trong dict bị xóa
