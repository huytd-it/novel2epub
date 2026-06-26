## MODIFIED Requirements

### Requirement: Swappable compatible model_id
`MoxhiMTTranslator` SHALL không hardcode một model_id cụ thể trong logic load/dịch — mọi model HF cùng kiến trúc (SentencePiece tokenizer + CTranslate2 Marian model) SHALL chạy được chỉ bằng cách đổi `translate.moxhimt.model_id`, không cần sửa code. Danh sách model đã kiểm chứng tương thích (`DanVP/MoxhiMT-60`, `DanVP/MoxhiMT-30`, `ngocdang83/HachimiMT-60-zh-vi`, `ngocdang83/HachimiMT-30-zh-vi`) SHALL được ghi trong docs/example config. Hỗ trợ cả hai layout tokenizer: shared `.model` và separate `source.spm`/`target.spm`.

#### Scenario: Đổi sang model HachimiMT cùng kiến trúc
- **WHEN** file config đặt `translate.moxhimt.model_id: "ngocdang83/HachimiMT-60-zh-vi"`
- **THEN** `MoxhiMTTranslator` tải và dùng đúng model đó để dịch, tự detect và load separate `source.spm`/`target.spm` tokenizer, không raise lỗi

#### Scenario: Đổi sang model MoxhiMT cùng kiến trúc
- **WHEN** file config đặt `translate.moxhimt.model_id: "DanVP/MoxhiMT-60"`
- **THEN** `MoxhiMTTranslator` tải và dùng đúng model đó, load shared `.model` tokenizer như hiện tại

#### Scenario: Model_id không tương thích kiến trúc
- **WHEN** `model_id` trỏ tới một repo không có cấu trúc SentencePiece + CTranslate2 mong đợi (ví dụ LoRA adapter)
- **THEN** `MoxhiMTTranslator` raise lỗi rõ ràng khi load model, nêu rõ định dạng model được hỗ trợ
