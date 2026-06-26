## ADDED Requirements

### Requirement: NMT as default translate type
`TranslateConfig.type` SHALL mặc định là `"moxhimt"` thay vì `"openai"`. Cả hai model NMT (MoxhiMT-60 và HachimiMT-60) đều chạy offline — chậm mà chắc, miễn phí, không phụ thuộc API. Khi user không khai báo `translate.type`, hệ thống SHALL dùng NMT backend. NMT models là seq2seq chuyên biệt hóa — dịch trực tiếp text → text, KHÔNG dùng prompt template.

#### Scenario: Config không khai báo translate.type
- **WHEN** file config không có `translate.type` (hoặc khối `translate:` rỗng)
- **THEN** `load_config()` trả về `TranslateConfig.type == "moxhimt"`

#### Scenario: Config explicit set translate.type: openai
- **WHEN** file config có `translate.type: openai`
- **THEN** `load_config()` trả về `TranslateConfig.type == "openai"` (giữ nguyên hành vi cũ)

#### Scenario: Chọn model NMT qua model_id
- **WHEN** `translate.type: moxhimt` và `translate.moxhimt.model_id: "ngocdang83/HachimiMT-60-zh-vi"`
- **THEN** dùng HachimiMT-60, không cần đổi `type`

### Requirement: Both NMT models pre-configured as defaults
Config example SHALL liệt kê cả hai model NMT (MoxhiMT-60 và HachimiMT-60) như tùy chọn mặc định, với comment hướng dẫn rõ model nào chậm/chắc hơn. `MoxhiMTConfig.model_id` default SHALL là `"DanVP/MoxhiMT-60"` (chất lượng cao nhất), và HachimiMT-60 là alternative khi cần tokenizer riêng.

#### Scenario: Default config dùng MoxhiMT-60
- **WHEN** user copy `novel2epub.example.yaml` thành `novel2epub.yaml` mà không sửa `moxhimt.model_id`
- **THEN** hệ thống dùng MoxhiMT-60 với beam=4, chunk_mode=paragraph

#### Scenario: Switch sang HachimiMT-60
- **WHEN** user đổi `moxhimt.model_id: "ngocdang83/HachimiMT-60-zh-vi"`
- **THEN** hệ thống tự detect tokenizer layout riêng (source.spm + target.spm), auto-preset beam=2, max_input_tokens=160

### Requirement: NMT batch title translation
`MoxhiMTTranslator` SHALL hỗ trợ dịch hàng loạt tên chương — nhận danh sách tất cả tiêu đề chương từ TOC, đưa vào CTranslate2 `translate_batch` 1 lần duy nhất, trả về danh sách kết quả. Nhanh hơn đáng kể so với gọi `translate_title()` tuần tự từng chương vì tránh overhead khởi tạo inference mỗi lần.

#### Scenario: Dịch batch toàn bộ TOC
- **WHEN** gọi `translate_titles(["第一章 龙王出世", "第二章 凤舞九天", "第三章 ..."])` với danh sách N tiêu đề
- **THEN** tất cả N tiêu đề được encode + đưa vào `translate_batch` 1 lần, trả về list[str] N bản dịch

#### Scenario: Batch rỗng
- **WHEN** gọi `translate_titles([])`
- **THEN** trả về list rỗng `[]`, không raise lỗi

#### Scenario: Batch có entry rỗng/whitespace
- **WHEN** danh sách input có chứa `""` hoặc `"   "`
- **THEN** giữ nguyên entry đó (không dịch), trả về đúng vị trí trong output list
