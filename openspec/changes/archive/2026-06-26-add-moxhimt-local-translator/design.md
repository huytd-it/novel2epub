## Context

`novel2epub/translator.py` định nghĩa `Translator` Protocol (`translate()`, `translate_title()`) với 3 implementation hiện có: `CLITranslator` (gọi AI CLI ngoài bằng prompt LLM, chia đoạn theo `max_chars`), `GoogleTranslator` (deep-translator, chia theo 4500 ký tự), `NoopTranslator` (passthrough test). `make_translator(cfg)` chọn implementation theo `cfg.type`.

`DanVP/MoxhiMT-60` là model NMT (Marian seq2seq, encoder-decoder cố định) chứ không phải LLM theo prompt — input là 1 câu/đoạn ngắn (≤512 token), output là bản dịch tương ứng, không có khái niệm "system prompt" hay "glossary trong prompt". Space `ngocdang83/HachimiMT-demo` chỉ là Gradio UI demo bọc model này (CTranslate2 backend, hậu xử lý chuẩn hóa xưng hô) — không có HTTP API ổn định nào được công bố để gọi từ xa, nên tích hợp đúng đắn là chạy model cục bộ, không phải gọi Space.

## Goals / Non-Goals

**Goals:**
- Thêm backend `translate.type: moxhimt` tuân thủ đúng interface `Translator` hiện có, hoạt động được trong toàn bộ pipeline (`crawl → translate → build`) không cần sửa `pipeline.py`/`cli.py`/web UI.
- Tự tải model HF về cache cục bộ khi cần (giống cách `deep_translator` được lazy-import trong `GoogleTranslator`).
- Áp dụng glossary (names/vietphrase) bằng string-replace sau dịch, nhất quán với 2 backend khác (`_apply_glossary`).
- Mặc định chia theo đoạn văn để giữ ngữ cảnh tốt nhất, fallback chia câu khi đoạn vượt giới hạn 512 token.
- Dựng lại giao diện biên tập chương thành 3 cột (ZH · VI máy · Biên tập) theo phong cách bản demo, tách bản dịch máy khỏi bản biên tập cuối.

**Non-Goals:**
- Không gọi qua HF Space demo (`HachimiMT-demo`) — không có API ổn định, lại phụ thuộc uptime Space của người khác.
- Không tích hợp GPU/batch training, không fine-tune model.
- Không thêm chế độ "dịch tiêu đề có giải thích" (`GIẢI THÍCH:`) như `CLITranslator` — model không sinh được giải thích, `translate_title()` chỉ trả `(bản dịch, "")` giống `GoogleTranslator`.
- Không tự động chọn giữa backend `transformers` (PyTorch) và `ctranslate2` — chỉ dùng CTranslate2 (nhẹ hơn, không cần torch, đúng như khuyến nghị của chính model card và Space demo).
- Không xây mới một engine AI biên tập riêng cho cột Biên tập — tái dùng pipeline `ai/rewrite` (CLI translator) đã có; backend `moxhimt` chỉ là engine dịch máy, không phải engine biên tập.
- Không port nguyên hậu xử lý chuẩn hóa xưng hô (pronoun harmonizer) của Space demo trong change này — để dành change sau (`moxhimt-pronoun-clf`).

## Decisions

1. **Dùng CTranslate2 + SentencePiece, không dùng `transformers`/PyTorch.**
   Model card khuyến nghị CTranslate2 INT8 cho CPU inference nhanh hơn; Space demo gốc cũng mặc định CTranslate2 và chỉ dùng torch như fallback tùy chọn. Tránh kéo theo dependency `torch` nặng (>1GB) cho một model 57M tham số chỉ cần CPU.
   *Alternative đã xét*: dùng `transformers.AutoModelForSeq2SeqLM` — đơn giản hơn về code nhưng nặng hơn nhiều về dependency và chậm hơn trên CPU; bỏ.

2. **Tự tải model qua `huggingface_hub.snapshot_download`, cache tại `~/.cache/novel2epub/moxhimt/<model_id>` (hoặc thư mục cấu hình được).**
   Nhất quán với cách Space demo "lazily download trên lần dùng đầu". Cho phép override qua config `translate.moxhimt.cache_dir` để người dùng tự quản lý dung lượng disk.
   *Alternative*: yêu cầu người dùng tự `git clone`/tải tay — bị loại vì làm onboarding phức tạp, ngược với trải nghiệm "pip install rồi dùng được ngay" của các backend khác.

3. **Mặc định chia theo ĐOẠN VĂN (mỗi dòng/đoạn gốc = 1 đơn vị dịch), chỉ fallback chia câu khi đoạn vượt ngân sách token an toàn — đây là cấu hình mặc định "cẩn thận nhất".**
   Yêu cầu của người dùng: cấu hình mặc định phải là chất lượng cao nhất. Dịch trọn cả đoạn cho model giữ được ngữ cảnh liên câu trong đoạn (xưng hô, mạch văn) tốt hơn so với bẻ vụn từng câu. Vì model giới hạn cứng 512 token/lần gọi, khi một đoạn ước lượng vượt ngưỡng token an toàn thì mới chia tiếp đoạn đó thành câu (regex `。！？…` và `.!?`); nếu một câu vẫn quá dài thì cắt cứng theo ký tự (xem decision dưới). Xuống dòng/cấu trúc đoạn gốc luôn được giữ nguyên khi ghép kết quả (tương thích `keep_paragraphs` và epub builder).
   *Alternative đã xét*: chia câu vô điều kiện cho mọi đầu vào — đơn giản hơn nhưng làm mất ngữ cảnh đoạn, đi ngược yêu cầu "cẩn thận nhất"; chỉ dùng như bước fallback, không phải mặc định.

4. **Glossary áp dụng bằng post-processing string-replace (`_apply_glossary`), không đưa vào input model.**
   NMT model không nhận "instruction" kiểu LLM; đưa thẳng tên riêng gốc vào câu cho model dịch (model có thể dịch sai/phiên âm khác), sau đó thay thế bằng glossary đã định nghĩa — giống cách `GoogleTranslator` đang làm.

5. **Cấu hình mới `TranslateConfig.moxhimt: MoxhiMTConfig`** với các field: `model_id` (mặc định `"DanVP/MoxhiMT-60"` — model 60 lớn/chất lượng nhất trong họ), `backend` (mặc định `"ctranslate2"`), `beam_size` (mặc định 4, theo khuyến nghị model card cho chất lượng tốt nhất), `max_length` (mặc định 512), `chunk_mode` (mặc định `"paragraph"` — chế độ cẩn thận nhất; tùy chọn `"sentence"` cho người muốn nhanh hơn), `cache_dir` (mặc định rỗng = dùng cache mặc định của `huggingface_hub`), `device` (mặc định `"cpu"`). **Toàn bộ mặc định được chọn là bộ tham số chất lượng cao nhất** — người dùng không cần chỉnh gì.

6. **Không hardcode 1 model — `model_id` là điểm mở rộng chính.** Cùng tác giả công bố nhiều model cùng kiến trúc Marian/CTranslate2 (entry-decoder tương tự MoxhiMT-60): `DanVP/MoxhiMT-30` (nhẹ hơn, 36.5M tham số), `DanVP/MoxhiMT-30-web`, `ngocdang83/HachimiMT-60-zh-vi`, `ngocdang83/HachimiMT-30-zh-vi`. Vì `MoxhiMTTranslator` chỉ giả định "repo HF chứa SentencePiece tokenizer + CTranslate2 model thư mục `ct2-int8/` (hoặc gốc)", đổi sang các model này chỉ cần đổi `translate.moxhimt.model_id`, không cần sửa code. Docs/example config sẽ liệt kê rõ các `model_id` đã kiểm chứng tương thích.
   *Việc không tương thích trực tiếp*: `DanVP/hy-mt-xianxia-lora-vi` (LoRA adapter trên base model khác, cần loader PEFT riêng) và `DanVP/moxhimt-pronoun-clf` (classifier hậu xử lý, không phải translator NMT) — nằm ngoài scope của decision này, không được hỗ trợ bởi `MoxhiMTTranslator`.

7. **Giao diện chương 3 cột (ZH · VI máy · Biên tập), thay layout 2 cột hiện tại.**
   Bản demo trình bày song song nguồn–đích để dễ đối chiếu. Áp cho novel2epub:
   - **Cột ZH (gốc Trung)**: chỉ đọc, giữ nguyên tính năng tô sáng thuật ngữ glossary + jump-to hiện có.
   - **Cột VI (bản dịch máy)**: chỉ đọc, là *snapshot bất biến* của output translator lần dịch gần nhất — để người biên tập luôn đối chiếu được "máy dịch ra gì" kể cả sau khi đã sửa nhiều ở cột Biên tập.
   - **Cột Biên tập**: `textarea` sửa tay = bản lưu cuối cùng đi vào EPUB (chính là field `translated` hiện tại). Có nút **"Biên tập bằng AI"** chạy pipeline `ai/rewrite` sẵn có trên nội dung cột này, và nút **Lưu**.
   *Alternative đã xét*: chỉ thêm 1 cột mà gộp VI máy và Biên tập làm một (giữ 2 cột) — đơn giản hơn nhưng mất khả năng đối chiếu với bản máy gốc sau khi sửa, đúng thứ bản demo nhấn mạnh; bỏ.

8. **Lưu snapshot bản dịch máy tách khỏi bản biên tập cuối, trong `storage.py`.**
   Thêm một file/field "bản dịch máy" (vd `translated_mt`) ghi tại bước dịch (cột VI), độc lập với `translated` (cột Biên tập, được sửa tay/AI rewrite). Bước build EPUB vẫn đọc `translated` như cũ — không đổi hành vi build.
   *Degrade an toàn*: chương cũ đã dịch trước thay đổi này chưa có snapshot máy → cột VI fallback hiển thị chính `translated` hiện có (read-only), không vỡ trang.
   *Alternative*: tái dùng `meta["before_rewrite"]` làm snapshot máy — sai ngữ nghĩa (đó là "bản trước lần rewrite gần nhất", không phải "bản máy gốc"), nên dùng field riêng.

9. **Nút "Biên tập bằng AI" tái dùng đúng endpoint/pipeline `ai/rewrite` đang có**, không thêm engine AI mới. Khác biệt UX duy nhất: đặt nút ngay trên cột Biên tập để thao tác liền mạch; kết quả vẫn hiện qua panel diff "bản nháp AI" sẵn có để người dùng xem trước rồi áp dụng.

## Risks / Trade-offs

- [Model phải tải lần đầu (~vài chục MB), có thể chậm/lỗi nếu mạng kém hoặc HF Hub bị chặn] → Bắt lỗi rõ ràng, thông báo tiếng Việt hướng dẫn kiểm tra mạng/HF_HOME, giống cách `CLITranslator` báo lỗi khi không thấy CLI.
- [Chất lượng dịch NMT 57M tham số thấp hơn LLM lớn cho văn cảnh phức tạp/đa nghĩa, đặc biệt ngoài thể loại tiên hiệp] → Ghi rõ trong docs đây là backend "nhanh, miễn phí, tối ưu tiên hiệp/web-novel", khuyến nghị dùng `cli` cho chất lượng cao nhất; không thay đổi mặc định `translate.type` hiện tại (`cli`).
- [`ctranslate2`/`sentencepiece` là dependency mới, tăng kích thước cài đặt cho người không dùng backend này] → Lazy-import trong `MoxhiMTTranslator.__init__` (giống `deep_translator` trong `GoogleTranslator`), không thêm vào `requirements.txt` bắt buộc mà ghi chú "cài thêm nếu dùng translate.type=moxhimt" hoặc thêm vào extras nếu dự án có cơ chế optional-deps.
- [Model không xử lý tốt câu quá dài/không có dấu câu rõ ràng (chunk theo câu thất bại)] → Fallback nhiều tầng: đoạn quá dài → chia câu; câu vẫn quá dài → cắt cứng theo ký tự trước khi đưa vào model (tránh lỗi truncation âm thầm làm mất nghĩa).
- [Snapshot bản dịch máy làm tăng dung lượng đĩa (~gấp đôi text mỗi chương)] → Chấp nhận được (text thuần, nhẹ); chỉ ghi khi dịch bằng pipeline, không nhân bản cho chương cũ.
- [Layout 3 cột chật trên màn hình hẹp] → CSS responsive: dưới ngưỡng rộng nhất định, các cột xếp dọc (stack) thay vì 3 cột ngang; giữ usability trên laptop nhỏ.
- [Người dùng nhầm cột VI máy (read-only) là chỗ sửa] → Nhãn rõ ràng "Bản dịch máy (chỉ đọc, để đối chiếu)" vs "Biên tập — sửa & lưu tại đây", và chỉ cột Biên tập có nút Lưu.

## Migration Plan

- Thay đổi thuần cộng thêm (additive): không sửa hành vi `type: cli|google|none` hiện tại, không cần migrate config cũ.
- Người dùng muốn dùng backend mới chỉ cần đặt `translate.type: moxhimt` trong `novel2epub.yaml` và cài thêm `pip install ctranslate2 sentencepiece huggingface_hub` (nếu tách thành optional deps).
- Rollback: đổi `translate.type` về `cli`/`google`/`none`, không cần dọn dẹp gì (model cache có thể giữ lại hoặc xóa thủ công).

## Open Questions

- Tên model chính xác cần fetch trên CTranslate2 (`ct2-int8/` subfolder của `DanVP/MoxhiMT-60`) hay model "HachimiMT-60" trên repo khác — cần xác nhận `model_id` mặc định đúng khi implement (ưu tiên dùng đúng `DanVP/MoxhiMT-60` theo yêu cầu người dùng).
