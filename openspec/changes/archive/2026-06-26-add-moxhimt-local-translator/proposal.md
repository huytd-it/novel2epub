## Why

novel2epub hiện chỉ có 3 backend dịch: `cli` (gọi AI CLI ngoài, tốn phí/quota), `google` (Google Translate miễn phí nhưng chất lượng chung, không tối ưu cho tiểu thuyết mạng), và `none` (test). Có một model dịch Trung→Việt chuyên cho tiểu thuyết mạng/tiên hiệp (`DanVP/MoxhiMT-60` trên Hugging Face — Marian seq2seq ~57M tham số, có sẵn bản CTranslate2 INT8 chạy nhanh trên CPU) và một Space demo (`ngocdang83/HachimiMT-demo`, Gradio UI bọc cùng dòng model "HachimiMT-60"/"MoxhiMT-60"). Tích hợp model này như một backend dịch cục bộ giúp dịch offline, không phụ thuộc quota/API key, miễn phí, và bám sát văn phong tiên hiệp/web-novel hơn Google Translate.

## What Changes

- Thêm backend dịch mới `translate.type: moxhimt` chạy cục bộ qua CTranslate2 (ưu tiên bản `ct2-int8/` cho tốc độ CPU) + SentencePiece tokenizer, không gọi qua HF Space demo (Space chỉ là Gradio UI bọc model, không có API ổn định để tích hợp).
- Backend tổng quát theo `model_id` cấu hình được (không hardcode 1 model): mặc định `DanVP/MoxhiMT-60`, đồng thời tương thích sẵn với các model cùng kiến trúc Marian/CTranslate2 của cùng tác giả — `DanVP/MoxhiMT-30`, `DanVP/MoxhiMT-30-web`, `ngocdang83/HachimiMT-60-zh-vi`, `ngocdang83/HachimiMT-30-zh-vi` — chỉ cần đổi `translate.moxhimt.model_id` trong config, không sửa code.
- Model được tải tự động từ Hugging Face Hub vào cache cục bộ ở lần dùng đầu tiên (lazy download), tái sử dụng cho các lần sau.
- **Cấu hình mặc định = cấu hình tốt nhất, dịch cẩn thận nhất**: backend chia theo **đoạn văn** (giữ trọn ngữ cảnh đoạn cho model dịch), chỉ rơi xuống chia theo câu khi một đoạn vượt quá ngân sách token an toàn của `max_length=512`. Người dùng không cần chỉnh gì để có chất lượng cao nhất.
- `translate_title()` dùng chung pipeline dịch của model (không có prompt riêng theo kiểu CLI vì model không phải LLM theo prompt).
- Thêm cấu hình `translate.moxhimt` (tên model HF, beam size, batch size, thư mục cache) trong `config.py`, với giá trị mặc định là bộ tham số chất lượng cao nhất theo khuyến nghị model card.
- Thêm dependency `ctranslate2` + `sentencepiece` (tùy chọn, chỉ cần khi dùng backend này) vào `requirements.txt`.
- Cập nhật `novel2epub.example.yaml` và docs với ví dụ cấu hình `translate.type: moxhimt`.
- **Dựng lại giao diện chương (`app/templates/chapter.html`) theo hướng bản demo: 3 cột** — `ZH` (gốc Trung, chỉ đọc) · `VI` (bản dịch máy, snapshot bất biến để đối chiếu) · `Biên tập` (bản sửa tay = bản lưu cuối vào EPUB, có nút "Biên tập bằng AI" tái dùng pipeline AI rewrite sẵn có, và sửa trực tiếp).

## Capabilities

### New Capabilities
- `moxhimt-translator`: Backend dịch Trung→Việt cục bộ dùng model NMT cùng kiến trúc Marian/CTranslate2 (mặc định MoxhiMT-60, đổi được sang MoxhiMT-30/MoxhiMT-30-web/HachimiMT-60-zh-vi/HachimiMT-30-zh-vi qua config), tuân thủ interface `Translator` hiện có (`translate()`, `translate_title()`), tự tải model từ Hugging Face Hub, chia theo đoạn văn (fallback câu khi đoạn quá dài).
- `chapter-three-column-editor`: Giao diện biên tập chương 3 cột (ZH gốc · VI bản dịch máy · Biên tập) theo phong cách bản demo, tách bản dịch máy (đối chiếu) khỏi bản biên tập cuối (lưu vào EPUB), với nút biên tập bằng AI và sửa tay trực tiếp.

### Modified Capabilities
(không có — không thay đổi requirement của backend `cli`/`google`/`none` hiện tại)

## Impact

- Code: `novel2epub/translator.py` (thêm class `MoxhiMTTranslator`, nhánh trong `make_translator()`), `novel2epub/config.py` (thêm `MoxhiMTConfig`, mở rộng `TranslateConfig.type` và parser `load_config`).
- Dependencies mới (tùy chọn/lazy-import như `deep_translator`): `ctranslate2`, `sentencepiece`, `huggingface_hub` (tải model).
- Config: `novel2epub.example.yaml` thêm ví dụ `translate.type: moxhimt`.
- Web UI: `app/templates/chapter.html` (layout 3 cột + nút biên tập AI), `app/routes/chapters.py` (đọc/lưu cột Biên tập, snapshot bản dịch máy), `novel2epub/storage.py` (lưu snapshot bản dịch máy tách khỏi bản biên tập cuối), CSS `app/static/style.css`.
- Không ảnh hưởng `crawler.py`, `epub_builder.py` — EPUB vẫn build từ bản dịch cuối như cũ (cột Biên tập).
- Không có thay đổi breaking với cấu hình hiện tại (`type: cli|google|none` vẫn hoạt động như cũ); chương đã dịch trước đây chưa có snapshot bản dịch máy thì cột VI hiển thị từ chính bản hiện có (degrade an toàn).
