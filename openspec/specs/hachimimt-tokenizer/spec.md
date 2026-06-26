# Spec: hachimimt-tokenizer

## Purpose

Hỗ trợ model HachimiMT-60/30 có layout tokenizer riêng (source.spm + target.spm) bên cạnh layout shared .model của MoxhiMT. Auto-detect layout và load đúng SentencePieceProcessor cho encode/decode.

## Requirements

### Requirement: Separate source/target SentencePiece tokenizer support
`MoxhiMTTranslator` SHALL detect và load được cả hai layout tokenizer: (a) shared `.model` file (MoxhiMT-60) và (b) separate `source.spm` + `target.spm` files (HachimiMT-60). Khi cả hai file `source.spm` và `target.spm` tồn tại trong model directory, SHALL dùng riêng cho encode (source) và decode (target). Khi chỉ có một file `.model` hoặc `.spm`, SHALL dùng chung cho cả encode và decode như hiện tại.

#### Scenario: Model có source.spm + target.spm riêng (HachimiMT layout)
- **WHEN** model directory chứa cả `source.spm` và `target.spm`
- **THEN** `_locate_model_files()` trả về `(ct2_dir, source_spm_path, target_spm_path)` và `_ensure_loaded()` tạo 2 `SentencePieceProcessor` riêng: encode bằng `source.spm`, decode bằng `target.spm`

#### Scenario: Model có shared .model file (MoxhiMT layout)
- **WHEN** model directory chỉ chứa một file `.model` hoặc `.spm` (không có `source.spm` + `target.spm` pair)
- **THEN** `_locate_model_files()` trả về `(ct2_dir, shared_spm_path, None)` và `_ensure_loaded()` dùng chung 1 `SentencePieceProcessor` cho cả encode và decode

#### Scenario: Ưu tiên INT8 ct2 subdirectory
- **WHEN** model directory chứa nhiều ct2 subdirectories (vd `ct2-int8/`, `ct2-int8_float32/`)
- **THEN** `_locate_model_files()` ưu tiên thư mục có "int8" trong tên, giống logic hiện tại

### Requirement: HachimiMT model_id auto-preset
Khi `model_id` chứa `HachimiMT`, hệ thống SHALL tự động áp dụng các tham số tối ưu (beam_size=2, max_input_tokens=160) nếu user chưa override rõ ràng trong config.

#### Scenario: Dùng HachimiMT-60 với default config
- **WHEN** `translate.moxhimt.model_id: "ngocdang83/HachimiMT-60-zh-vi"` và không khai báo beam_size/max_input_tokens
- **THEN** model load với beam_size=2, max_input_tokens=160

#### Scenario: User override beam_size khi dùng HachimiMT
- **WHEN** `translate.moxhimt.model_id: "ngocdang83/HachimiMT-60-zh-vi"` và `translate.moxhimt.beam_size: 4`
- **THEN** dùng beam_size=4 (user override), các tham số khác auto-preset
