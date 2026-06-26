## MODIFIED Requirements

### Requirement: Configurable inference parameters with best-quality defaults
Config `translate.moxhimt` SHALL cho phép cấu hình `model_id` (mặc định `"DanVP/MoxhiMT-60"`), `beam_size` (mặc định 4), `max_length` (mặc định 512), `chunk_mode` (mặc định `"paragraph"`), `cache_dir` (mặc định rỗng = cache mặc định), `device` (mặc định `"cpu"`), và các tham số song song hóa CPU `inter_threads` và `intra_threads`. Bộ giá trị mặc định SHALL là cấu hình chất lượng cao nhất (cẩn thận nhất) — người dùng không cần chỉnh gì để đạt chất lượng tốt nhất. Khi `inter_threads`/`intra_threads` không được khai báo, mặc định SHALL được suy ra từ số nhân vật lý của máy sao cho tổng tải (`inter_threads × intra_threads`) không vượt số nhân vật lý.

#### Scenario: Dùng giá trị mặc định khi không khai báo `translate.moxhimt`
- **WHEN** file config có `translate.type: moxhimt` nhưng không khai báo khối `moxhimt:`
- **THEN** `MoxhiMTTranslator` dùng đúng các giá trị mặc định nêu trên (model 60, beam 4, chia theo đoạn văn, device cpu) và chọn `inter_threads`/`intra_threads` mặc định theo số nhân CPU

#### Scenario: Override beam_size/cache_dir qua config
- **WHEN** file config khai báo `translate.moxhimt.beam_size: 6` và `translate.moxhimt.cache_dir: "./models/moxhimt"`
- **THEN** model được load/dịch dùng đúng các giá trị đã override

#### Scenario: Override số luồng CPU qua config
- **WHEN** file config khai báo `translate.moxhimt.inter_threads: 4` và `translate.moxhimt.intra_threads: 4`
- **THEN** CTranslate2 được khởi tạo với đúng `inter_threads`/`intra_threads` đó

## ADDED Requirements

### Requirement: Batched translation on CPU
`MoxhiMTTranslator` SHALL dịch nhiều đơn vị (đoạn/câu) trong một lượt bằng `translate_batch` của CTranslate2 thay vì gọi tuần tự từng đơn vị, để khai thác song song hóa nội bộ của CT2 trên CPU. Kết quả ghép lại SHALL giữ nguyên thứ tự và cấu trúc đoạn như khi dịch tuần tự, và logic chunk (đoạn → câu → ký tự) cùng glossary post-processing SHALL không đổi về mặt hành vi kết quả.

#### Scenario: Nhiều đơn vị được gom thành batch
- **WHEN** một văn bản được chia thành nhiều chunk vừa với giới hạn token
- **THEN** các chunk được đưa vào model theo batch (`translate_batch`) và kết quả nối lại đúng thứ tự gốc

#### Scenario: Kết quả batch trùng với kết quả tuần tự
- **WHEN** cùng một văn bản đầu vào được dịch ở chế độ batch
- **THEN** văn bản kết quả (sau ghép + glossary) tương đương với khi dịch từng chunk tuần tự

### Requirement: CPU thread pool over thread-per-chapter
Khi `translate.type == "moxhimt"`, hệ thống SHALL khai thác song song qua `inter_threads`/`intra_threads` của CTranslate2 và batching, thay vì tạo một luồng Python cho mỗi chương (tránh oversubscription nhân CPU). Với backend `cli`/`google` (I/O-bound), cơ chế `translate.max_workers` hiện có SHALL vẫn áp dụng như cũ.

#### Scenario: moxhimt không fan-out luồng-mỗi-chương
- **WHEN** dịch nhiều chương với `translate.type: moxhimt`
- **THEN** song song hóa đến từ CT2 (inter/intra threads + batch), không phải từ việc tạo một luồng Python riêng cho mỗi chương

#### Scenario: cli/google giữ nguyên hành vi max_workers
- **WHEN** dịch nhiều chương với `translate.type: cli` hoặc `google` và `translate.max_workers > 1`
- **THEN** các chương vẫn được dịch song song bằng nhiều luồng như hành vi hiện tại
