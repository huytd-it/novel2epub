# Spec: moxhimt-translator

## Purpose

Cung cấp một backend dịch máy chạy cục bộ (offline, không gọi API ngoài)
dựa trên model MoxhiMT (CTranslate2 + SentencePiece), tích hợp vào hệ thống
translator hiện có (`cli`/`google`/`none`) như một lựa chọn `type: "moxhimt"`,
với việc chia chunk theo đoạn văn (mặc định) hoặc câu, áp dụng glossary sau
dịch, và hỗ trợ đổi model tương thích qua config mà không cần sửa code.

## Requirements

### Requirement: MoxhiMT backend selection
`make_translator()` SHALL trả về một `MoxhiMTTranslator` khi `cfg.type == "moxhimt"`, tuân thủ đúng `Translator` Protocol (`translate()`, `translate_title()`) đang dùng cho `cli`/`google`/`none`.

#### Scenario: Chọn backend moxhimt qua config
- **WHEN** `translate.type` trong config được đặt là `"moxhimt"`
- **THEN** `make_translator(cfg)` trả về instance `MoxhiMTTranslator`, không raise lỗi `ValueError` như với type không hợp lệ

#### Scenario: Type không hợp lệ vẫn báo lỗi như cũ
- **WHEN** `translate.type` là một chuỗi không thuộc `cli|google|none|moxhimt`
- **THEN** `make_translator(cfg)` raise `ValueError` nêu rõ các type hợp lệ bao gồm `moxhimt`

### Requirement: Local model loading and caching
`MoxhiMTTranslator` SHALL tải model `DanVP/MoxhiMT-60` (CTranslate2 + SentencePiece) cục bộ, tự động tải xuống từ Hugging Face Hub lần đầu sử dụng, và tái sử dụng cache cho các lần dịch sau trong cùng tiến trình và giữa các lần chạy.

#### Scenario: Lần đầu dùng backend, chưa có model trong cache
- **WHEN** khởi tạo `MoxhiMTTranslator` và model chưa tồn tại trong thư mục cache cấu hình (hoặc cache mặc định)
- **THEN** model được tải từ Hugging Face Hub về cache trước khi dịch câu đầu tiên

#### Scenario: Đã có model trong cache
- **WHEN** khởi tạo `MoxhiMTTranslator` và model đã tồn tại trong cache từ lần chạy trước
- **THEN** không tải lại qua mạng, model được load trực tiếp từ cache cục bộ

#### Scenario: Tải model thất bại (mạng lỗi hoặc không truy cập được Hugging Face Hub)
- **WHEN** quá trình tải model gặp lỗi mạng/HTTP
- **THEN** `MoxhiMTTranslator` raise `RuntimeError` với thông báo tiếng Việt giải thích rõ nguyên nhân và cách khắc phục (kiểm tra mạng, biến môi trường HF_HOME/cache)

### Requirement: Paragraph-first chunking with sentence fallback
`MoxhiMTTranslator.translate()` SHALL mặc định chia văn bản đầu vào theo **đoạn văn** (mỗi dòng/đoạn của bản gốc là một đơn vị dịch) để giữ trọn ngữ cảnh đoạn cho model — đây là chế độ mặc định, cẩn thận nhất. Khi một đoạn vượt quá ngân sách token an toàn cho `max_length=512`, đoạn đó SHALL được chia tiếp thành câu (theo dấu kết câu Hán/Việt); nếu một câu vẫn vượt ngưỡng, SHALL cắt cứng theo ký tự. Xuống dòng và cấu trúc đoạn của văn bản gốc SHALL được giữ nguyên trong kết quả ghép lại.

#### Scenario: Đoạn văn vừa với giới hạn token (mặc định)
- **WHEN** một đoạn văn (một dòng gốc) nằm trong ngân sách token an toàn
- **THEN** cả đoạn được dịch trong một lượt gọi model (không bẻ thành câu), giữ ngữ cảnh liên câu trong đoạn

#### Scenario: Đoạn vượt giới hạn token → fallback chia câu
- **WHEN** một đoạn văn ước lượng vượt ngân sách token an toàn cho `max_length=512`
- **THEN** đoạn đó được chia thành các câu (ngăn bởi `。！？…` hoặc tương đương) và dịch từng câu, rồi nối lại đúng thứ tự trong cùng đoạn

#### Scenario: Câu vẫn vượt quá độ dài an toàn cho model
- **WHEN** một câu sau khi chia vẫn vượt ngưỡng ký tự/token an toàn ước tính
- **THEN** câu đó được cắt nhỏ thêm theo ký tự trước khi đưa vào model, tránh bị cắt cụt (truncate) âm thầm làm sai nghĩa

#### Scenario: chunk_mode="sentence" để dịch nhanh hơn
- **WHEN** config đặt `translate.moxhimt.chunk_mode: "sentence"`
- **THEN** văn bản được chia theo câu ngay từ đầu (không gom đoạn), đánh đổi ngữ cảnh lấy tốc độ

#### Scenario: on_chunk callback vẫn được gọi đúng tổng số chunk
- **WHEN** `translate()` được gọi với kwarg `on_chunk`
- **THEN** callback được gọi báo tiến độ theo từng chunk xử lý, với cờ `is_final=True` ở chunk cuối cùng — tương thích với cách `CLITranslator`/`GoogleTranslator` đang dùng `on_chunk`

### Requirement: Glossary post-processing
`MoxhiMTTranslator` SHALL áp dụng glossary (gộp từ `cfg.glossary` và file `names`/`vietphrase`) bằng cách thay thế literal trên kết quả dịch của model, nhất quán với cách `CLITranslator`/`GoogleTranslator` đang xử lý glossary.

#### Scenario: Glossary có entry khớp trong câu đã dịch
- **WHEN** kết quả dịch từ model chứa một cụm từ trùng khóa Hán trong glossary
- **THEN** cụm đó được thay bằng giá trị tiếng Việt tương ứng trong glossary trước khi trả về

### Requirement: Title translation without explanation
`MoxhiMTTranslator.translate_title()` SHALL dịch tiêu đề bằng cùng pipeline dịch câu của model và trả về tuple `(bản dịch, "")` — không có phần giải thích (`GIẢI THÍCH:`) như `CLITranslator`, vì model NMT không sinh được giải thích.

#### Scenario: Dịch tiêu đề chương
- **WHEN** gọi `translate_title(text, kind="tên chương")`
- **THEN** trả về `(tiêu_đề_đã_dịch, "")`, áp dụng glossary lên `tiêu_đề_đã_dịch` giống `translate()`

### Requirement: Configurable inference parameters with best-quality defaults
Config `translate.moxhimt` SHALL cho phép cấu hình `model_id` (mặc định `"DanVP/MoxhiMT-60"`), `beam_size` (mặc định 4), `max_length` (mặc định 512), `chunk_mode` (mặc định `"paragraph"`), `cache_dir` (mặc định rỗng = cache mặc định), và `device` (mặc định `"cpu"`). Bộ giá trị mặc định SHALL là cấu hình chất lượng cao nhất (cẩn thận nhất) — người dùng không cần chỉnh gì để đạt chất lượng tốt nhất.

#### Scenario: Dùng giá trị mặc định khi không khai báo `translate.moxhimt`
- **WHEN** file config có `translate.type: moxhimt` nhưng không khai báo khối `moxhimt:`
- **THEN** `MoxhiMTTranslator` dùng đúng các giá trị mặc định nêu trên (model 60, beam 4, chia theo đoạn văn)

#### Scenario: Override beam_size/cache_dir qua config
- **WHEN** file config khai báo `translate.moxhimt.beam_size: 6` và `translate.moxhimt.cache_dir: "./models/moxhimt"`
- **THEN** model được load/dịch dùng đúng các giá trị đã override

### Requirement: Swappable compatible model_id
`MoxhiMTTranslator` SHALL không hardcode một model_id cụ thể trong logic load/dịch — mọi model HF cùng kiến trúc (SentencePiece tokenizer + CTranslate2 Marian model) SHALL chạy được chỉ bằng cách đổi `translate.moxhimt.model_id`, không cần sửa code. Hỗ trợ cả hai layout tokenizer: shared `.model` file (MoxhiMT) và separate `source.spm`/`target.spm` files (HachimiMT). Danh sách model đã kiểm chứng tương thích (`DanVP/MoxhiMT-60`, `DanVP/MoxhiMT-30`, `ngocdang83/HachimiMT-60-zh-vi`, `ngocdang83/HachimiMT-30-zh-vi`) SHALL được ghi trong docs/example config.

#### Scenario: Đổi sang model HachimiMT cùng kiến trúc
- **WHEN** file config đặt `translate.moxhimt.model_id: "ngocdang83/HachimiMT-60-zh-vi"`
- **THEN** `MoxhiMTTranslator` tải và dùng đúng model đó để dịch, tự detect và load separate `source.spm`/`target.spm` tokenizer, không raise lỗi

#### Scenario: Model_id không tương thích kiến trúc
- **WHEN** `model_id` trỏ tới một repo không có cấu trúc SentencePiece + CTranslate2 mong đợi (ví dụ LoRA adapter như `hy-mt-xianxia-lora-vi`)
- **THEN** `MoxhiMTTranslator` raise lỗi rõ ràng khi load model (không crash mơ hồ), nêu rõ định dạng model được hỗ trợ
