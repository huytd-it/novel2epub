## Why

Dịch vụ OpenAI tốn chi phí và chậm cho volume lớn (truyện dài hàng ngàn chương). Project đã có backend `moxhimt` chạy offline bằng MoxhiMT-60, nhưng chưa hỗ trợ đầy đủ các model mới hơn trong họ HachimiMT (source.spm + target.spm riêng biệt) và chưa có default NMT cho chapter translation. Cần tích hợp HachimiMT-60 (`ngocdang83/HachimiMT-60-zh-vi`) làm tùy chọn song song với MoxhiMT-60, đặt NMT làm mặc định cho dịch chapter, và giữ OpenAI chỉ cho biên tập title/tên chương.

## What Changes

- **Mở rộng tokenizer detection** trong `MoxhiMTTranslator._locate_model_files()` để hỗ trợ cả layout `source.spm` + `target.spm`riêng (HachimiMT) lẫn layout `.model` chung (MoxhiMT hiện tại)
- **Thêm model preset `hachimimt`**: cấu hình sẵn `model_id: "ngocdang83/HachimiMT-60-zh-vi"` với các tham số tối ưu (beam=2, max_input_tokens=160, ct2_subdir="ct2-int8_float32")
- **Đổi default `translate.type`** từ `"openai"` thành `"moxhimt"` trong config, để NMT là backend mặc định cho dịch chapter
- **Tách logic dịch title**: `translate_title()` dùng OpenAI (hoặc configurable), `translate()` dùng NMT — hiện tại `MoxhiMTTranslator.translate_title()` cũng dùng NMT, cần thêm tùy chọn dùng OpenAI cho title
- **Cập nhật `novel2epub.example.yaml`** với block translate mặc định mới và hướng dẫn cấu hình

## Capabilities

### New Capabilities
- `hachimimt-tokenizer`: Hỗ trợ tokenizer HachimiMT (source.spm + target.spm riêng) trong MoxhiMTTranslator
- `nmt-default-config`: Đặt NMT (moxhimt) làm backend mặc định cho chapter translation, OpenAI chỉ cho title

### Modified Capabilities
- `moxhimt-translator`: Mở rộng để detect và load cả HachimiMT tokenizer layout, cập nhật model preset defaults

## Impact

- `novel2epub/translator.py`: Sửa `_locate_model_files()` để detect source.spm/target.spm, thêm HachimiMT preset
- `novel2epub/config.py`: Đổi default `type` trong `TranslateConfig`, thêm HachimiMTConfig preset
- `novel2epub.example.yaml`: Cập nhật translate block mặc định
- Không phá vỡ API hiện tại — `translate.type: moxhimt` vẫn hoạt động, chỉ mở rộng khả năng
- Dependencies: không thêm package mới (ctranslate2 + sentencepiece + huggingface_hub đã là dependency hiện tại)
