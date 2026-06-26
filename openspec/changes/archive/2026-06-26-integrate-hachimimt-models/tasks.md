## 1. Tokenizer Detection & Loading

- [x] 1.1 Sửa `_locate_model_files()` trong `MoxhiMTTranslator` để detect cả `source.spm` + `target.spm` pair — trả `(ct2_dir, source_spm, target_spm | None)`
- [x] 1.2 Sửa `_ensure_loaded()` để load 1 hoặc 2 `SentencePieceProcessor` tùy theo kết quả `_locate_model_files()` — encode dùng `source_spm`, decode dùng `target_spm` hoặc shared
- [x] 1.3 Cập nhật `_translate_texts()` để decode bằng `target_spm` (hoặc shared spm) thay vì `self._sp` hardcode
- [x] 1.4 Thêm unit test cho tokenizer detection: mock model directory với source.spm + target.spm, verify load đúng

- [x] 2.1 Thêm logic detect `model_id` chứa "HachimiMT" trong `load_config()` để auto-set beam_size=2, max_input_tokens=160 khi chưa override
- [x] 2.2 Đảm bảo user override (beam_size, max_length...) trong config vẫn có hiệu lực ưu tiên hơn auto-preset
- [x] 2.3 Thêm test case: config chỉ set model_id HachimiMT-60, không set beam → verify beam_size=2

- [x] 3.1 Đổi `TranslateConfig.type` default từ `"openai"` thành `"moxhimt"` trong `config.py`
- [x] 3.2 Cập nhật `novel2epub.example.yaml` với `translate.type: moxhimt` và hướng dẫn HachimiMT model_id
- [x] 3.3 Verify `load_config()` hoạt động đúng khi không khai báo `translate.type` → type = "moxhimt"

- [x] 4.1 Thêm `translate_titles(self, titles: list[str]) -> list[str]` vào `MoxhiMTTranslator` — filter rỗng, encode tất cả, gọi `_translate_texts()` 1 lần, apply glossary, trả list kết quả đúng thứ tự
- [x] 4.2 Refactor `pipeline.py`: tạo hàm `_batch_translate_titles(translator, chapters, log)` gom toàn bộ `ch.title_zh` chưa có `title_vi`, gọi `translate_titles()` 1 lần, map kết quả về chapter trước khi vào loop dịch nội dung
- [x] 4.3 Gọi `_batch_translate_titles()` trước loop `_translate_one()` trong `step_translate_selected()`, truyền dict title đã dịch vào `_translate_one()` để skip phần dịch title trong loop
- [x] 4.4 Thêm test: `translate_titles(["A", "", "B"])` → verify entry rỗng giữ nguyên, batch gọi translate_batch 1 lần

- [x] 5.1 Cập nhật `novel2epub.example.yaml`: thêm comment cả hai model NMT (MoxhiMT-60 chậm/chắc, HachimiMT-60 có tokenizer riêng), hướng dẫn switch model_id
- [x] 5.2 Thêm comment trong config: "Cả hai model đều chậm mà chắc — offline, miễn phí, không cần API key"
- [x] 5.3 Chạy `pytest tests/ -v` để verify không có regression

- [x] 6.1 Tự động detect GPU (CUDA) nếu có, fallback CPU — device: "auto" làm default
