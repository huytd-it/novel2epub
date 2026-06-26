## 1. Config

- [x] 1.1 Thêm `MoxhiMTConfig` dataclass trong `novel2epub/config.py` (`model_id="DanVP/MoxhiMT-60"`, `backend="ctranslate2"`, `beam_size=4`, `max_length=512`, `chunk_mode="paragraph"`, `cache_dir=""`, `device="cpu"`) — mặc định là bộ tham số chất lượng cao nhất
- [x] 1.2 Thêm field `moxhimt: MoxhiMTConfig` vào `TranslateConfig`
- [x] 1.3 Parse khối `translate.moxhimt` trong `load_config()` (giống cách `cli`/`chunk`/`retry` đang được pop + build), giữ nguyên hành vi mặc định khi không khai báo
- [x] 1.4 Cập nhật comment `type: str = "cli"  # cli | google | none` thành `# cli | google | none | moxhimt`

## 2. Translator implementation

- [x] 2.1 Thêm hàm chia chunk trong `translator.py`: mặc định `chunk_mode="paragraph"` gom theo đoạn/dòng gốc, đoạn vượt ngân sách token an toàn thì fallback `_split_into_sentences` (tách `。！？….!?`); câu vẫn quá dài thì cắt cứng theo ký tự; giữ nguyên cấu trúc dòng/đoạn gốc để ghép lại
- [x] 2.2 Implement class `MoxhiMTTranslator` với `__init__(cfg, log=None)`: lazy-import `ctranslate2`, `sentencepiece`, `huggingface_hub`; raise `ImportError` rõ ràng (kiểu tiếng Việt, giống `GoogleTranslator`) nếu thiếu package
- [x] 2.3 Implement tải/cache model: dùng `huggingface_hub.snapshot_download(cfg.moxhimt.model_id, cache_dir=...)`, ưu tiên subfolder CTranslate2 INT8 nếu có trong repo; bắt lỗi mạng và raise `RuntimeError` thông báo tiếng Việt
- [x] 2.4 Implement `translate()`: chia chunk theo `chunk_mode`, dịch qua `ctranslate2.Translator.translate_batch` (beam_size, max_length từ config), nối lại theo cấu trúc dòng gốc, gọi `on_chunk` đúng thứ tự/tổng số, áp dụng `_apply_glossary` cuối cùng
- [x] 2.5 Implement `translate_title()`: dùng lại pipeline của `translate()`, trả về `(kết_quả, "")`
- [x] 2.6 Thêm nhánh `moxhimt` trong `make_translator()`, cập nhật message lỗi `ValueError` liệt kê đủ 4 type

## 3. Storage — snapshot bản dịch máy

- [x] 3.1 Thêm vào `novel2epub/storage.py` đường dẫn + read/write cho snapshot bản dịch máy (vd `translated_mt`), tách khỏi `translated` (bản biên tập cuối)
- [x] 3.2 Ghi snapshot máy tại bước dịch trong `pipeline.py` (`step_translate_*`): khi translator trả kết quả, ghi cả snapshot máy (cột VI) và khởi tạo `translated` (cột Biên tập) nếu chưa có
- [x] 3.3 Đảm bảo `epub_builder.py`/build vẫn đọc đúng `translated` (bản biên tập), không đổi hành vi build

## 4. Web UI — editor 3 cột

- [x] 4.1 Dựng lại layout 3 cột trong `app/templates/chapter.html`: ZH (gốc, chỉ đọc, giữ tô sáng + jump-to) · VI (bản dịch máy, chỉ đọc) · Biên tập (textarea sửa tay + nút Lưu)
- [x] 4.2 Cột VI lấy từ snapshot máy; fallback hiển thị `translated` hiện có khi chương cũ chưa có snapshot (degrade an toàn)
- [x] 4.3 Đặt nút "Biên tập bằng AI" trên cột Biên tập, trỏ tới endpoint `ai/rewrite` sẵn có; giữ panel diff "bản nháp AI" để xem trước/áp dụng
- [x] 4.4 Cập nhật `_chapter_context`/route trong `app/routes/chapters.py` để truyền nội dung cột VI (snapshot) cho template
- [x] 4.5 Thêm CSS 3 cột + responsive (stack dọc khi màn hình hẹp) trong `app/static/style.css`

## 5. Dependencies & docs

- [x] 5.1 Thêm `ctranslate2`, `sentencepiece`, `huggingface_hub` vào `requirements.txt` (ghi chú nếu dự án có cơ chế optional-deps, tách riêng nhóm; nếu không có, thêm thẳng kèm comment "chỉ cần khi translate.type=moxhimt")
- [x] 5.2 Thêm ví dụ `translate.type: moxhimt` + khối `translate.moxhimt` vào `novel2epub.example.yaml`
- [x] 5.3 Cập nhật `CLAUDE.md`/README liên quan phần `translator.py` mô tả 3 backend → 4 backend, nêu rõ backend `moxhimt` chạy model cục bộ, không qua HF Space; cập nhật mô tả trang chương sang editor 3 cột
- [x] 5.4 Ghi danh sách `model_id` đã kiểm chứng tương thích (cùng kiến trúc SentencePiece + CTranslate2 Marian) trong docs/example config: `DanVP/MoxhiMT-60` (mặc định), `DanVP/MoxhiMT-30`, `DanVP/MoxhiMT-30-web`, `ngocdang83/HachimiMT-60-zh-vi`, `ngocdang83/HachimiMT-30-zh-vi`; ghi rõ `hy-mt-xianxia-lora-vi` (LoRA) và `moxhimt-pronoun-clf` (classifier) KHÔNG tương thích trực tiếp với backend này

## 6. Tests

- [x] 6.1 Unit test chia chunk: `chunk_mode="paragraph"` gom trọn đoạn vừa giới hạn; đoạn dài fallback chia câu; câu quá dài cắt cứng; `chunk_mode="sentence"` chia câu ngay; giữ nguyên xuống dòng
- [x] 6.2 Unit test `make_translator()` trả đúng `MoxhiMTTranslator` khi `type="moxhimt"`, vẫn raise `ValueError` cho type sai
- [x] 6.3 Test `MoxhiMTTranslator.translate()`/`translate_title()` với model/ctranslate2 đã mock (không tải model thật trong CI) — kiểm tra glossary áp dụng đúng, `on_chunk` được gọi đúng số lần và `is_final` đúng ở chunk cuối
- [x] 6.4 Test đường lỗi: thiếu package `ctranslate2` → `ImportError` thông báo rõ; mock lỗi tải model → `RuntimeError` thông báo rõ
- [x] 6.5 Test storage snapshot: dịch ghi cả snapshot máy + `translated`; sửa `translated` không đổi snapshot; chương cũ thiếu snapshot → đọc fallback `translated`
- [x] 6.6 Test route chương trả context có nội dung cột VI (snapshot/fallback) và lưu cột Biên tập ghi đúng `translated`
