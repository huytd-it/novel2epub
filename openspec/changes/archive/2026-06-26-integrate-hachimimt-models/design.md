## Context

Project novel2epub đã có backend `moxhimt` trong `translator.py` dùng `MoxhiMTTranslator` với CTranslate2 + SentencePiece. Hiện tại chỉ hỗ trợ layout tokenizer một file `.model` chung (MoxhiMT-60). Model HachimiMT-60 (`ngocdang83/HachimiMT-60-zh-vi`) dùng layout `source.spm` + `target.spm` riêng biệt, cần mở rộng tokenizer detection. Config hiện tại default `translate.type: openai` — cần đổi sang NMT cho chapter translation.

## Goals / Non-Goals

**Goals:**
- Hỗ trợ cả hai layout tokenizer: shared `.model` (MoxhiMT) và separate `source.spm`/`target.spm` (HachimiMT)
- Đặt cả hai model NMT (MoxhiMT-60 + HachimiMT-60) làm default — chậm mà chắc, offline, miễn phí
- Both models dùng chung `MoxhiMTTranslator` — chỉ khác tokenizer loading + auto-preset params
- Không phá vỡ config hiện tại — `model_id` override vẫn hoạt động

**Non-Goals:**
- Tích hợp post-processing nâng cao của HachimiMT-demo (honorific normalization, pronoun harmonization) — có thể là change riêng sau
- Thay đổi Google/Noop backends
- Thêm package dependency mới
- OpenAI cho translation — giữ lại chỉ cho edge cases khi user explicit set `type: openai`

## Decisions

### Decision 1: Mở rộng `_locate_model_files()` thay vì tạo class riêng

**Lựa chọn**: Sửa `_locate_model_files()` trong `MoxhiMTTranslator` để detect và trả về cả hai layout tokenizer.

**Alternatives considered**:
- Tạo `HachimiMTTranslator` class riêng: Code duplication cao, cả hai backend dùng chung logic CTranslate2 giống nhau. Chỉ khác tokenizer loading.
- Abstract base class + hai subclass: Over-engineered cho khác biệt nhỏ (2 files vs 1 file).

**Rationale**: `_locate_model_files()` hiện đã rank `source.spm` cao nhất (score 0). Chỉ cần detect khi có cả `source.spm` + `target.spm` → trả tuple `(ct2_dir, source_spm, target_spm)` hoặc `(ct2_dir, shared_spm, None)`. `_ensure_loaded()` check `target_spm is not None` để quyết định load 1 hay 2 SentencePieceProcessor.

### Decision 2: Trả về `tuple[Path, Path, Path | None]` từ `_locate_model_files()`

**Lựa chọn**: Thay đổi signature thành `tuple[Path, Path, Path | None]` — `(ct2_dir, source_spm, target_spm_or_none)`.

**Rationale**: backward-compatible — caller hiện tại unpack thành `ct2_dir, spm_path` sẽ lỗi, nhưng chỉ có `_ensure_loaded()` gọi hàm này. Fix一处。

### Decision 3: Thêm config preset cho HachimiMT

**Lựa chọn**: Thêm dataclass `HachimiMTConfig` hoặc dùng chung `MoxhiMTConfig` với preset dictionary.

**Rationale**: Dùng chung `MoxhiMTConfig` với preset dict trong code (không thêm dataclass mới) — giữ config schema đơn giản. Khi `model_id` chứa `HachimiMT`, tự apply preset values (beam=2, max_input_tokens=160...) nếu user không override.

### Decision 4: Cả hai NMT model là default, OpenAI chỉ khi explicit

**Lựa chọn**: `type: moxhimt` mặc định. Cả MoxhiMT-60 và HachimiMT-60 đều là NMT chạy offline — chậm mà chắc. User chỉ cần đổi `model_id` để chọn model, không cần đổi `type`.

**Rationale**: NMT chuyên biệt hóa zh→vi cho tiểu thuyết mạng, chất lượng ổn định, không phụ thuộc API. OpenAI giữ lại làm fallback khi user set `type: openai`.

## Risks / Trade-offs

- **[Risk]** Existing configs with `translate.type: openai` sẽ không bị ảnh hưởng vì default chỉ áp dụng khi không khai báo → **Mitigation**: Đây là intent đúng — existing configs explicit nên không đổi.
- **[Risk]** HachimiMT-60首次 tải về (~57MB) có thể chậm trên mạng chậm → **Mitigation**: Đã có cơ chế lazy download + cache, giống MoxhiMT-60 hiện tại.
- **[Risk]** SentencePiece loading 2 files có thể hơi chậm hơn 1 file → **Mitigation**: Chỉ load 1 lần, negligible so với inference time.
