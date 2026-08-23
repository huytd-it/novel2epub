# Dịch Và Biên Tập

## Luồng Nội Dung

Mỗi chương có ba lớp nội dung:

- Raw: văn bản nguồn sau crawl.
- MT snapshot: kết quả dịch ban đầu, dùng để đối chiếu và phục hồi.
- Translated: bản đang biên tập và là nguồn để build EPUB.

Biên tập không ghi đè snapshot MT. Có thể so sánh nguồn, bản máy và bản sửa trong trình đọc ba cột.

## Hai Con Đường Dịch

Chỉ còn **hai** backend dịch (`translate.type`):

| Backend | Phù hợp |
| --- | --- |
| `localmt` | Local MT cục bộ (CTranslate2). Nhanh, miễn phí, offline; ~90% đúng với tiên hiệp/huyền huyễn. |
| `openai` | AI qua API OpenAI-Compatible. Chất lượng văn phong cao, prompt/ngữ cảnh phong phú, tự trích glossary. |
| `none` | Nguồn tiếng Việt hoặc kiểm thử pipeline (passthrough). |

Với nguồn tiếng Việt, đặt `source_language=vi`; hệ thống tự passthrough và không gọi model. `google` và `libretranslate` đã bị gỡ — ebook cũ dùng chúng được tự chuyển sang `openai` khi load (kèm cảnh báo).

### Workflow A — Local MT rồi OpenAI biên tập

Điểm mạnh của Local MT là nhanh và miễn phí; điểm yếu là ~10% dịch sai/không hợp ngữ cảnh đô thị hiện đại và không tự trích glossary. Quy trình an toàn:

Trong SPA, hai hành động dịch là tường minh và không phụ thuộc `translate.type`: **Local MT** luôn dùng engine Local MT và ghi nhánh `local_mt`; **Dịch AI** luôn dùng OpenAI-compatible và ghi nhánh `ai`. Vì vậy Local MT không gọi `ai.openai` hoặc endpoint `/chat/completions`. `translate.type` chỉ còn là backend mặc định cho CLI/automation cũ.

1. Dịch bằng `localmt` (ghi vào nhánh `local_mt`).
2. Dùng **AI biên tập** (hành động `ai-edit`, engine rewrite chỉ đọc nhánh `local_mt`, không bao giờ thấy raw) để nắn văn phong/xưng hô và **trích glossary** từ chính bản dịch.
3. Trước khi gửi, SPA hiện hộp thoại xác nhận vì kết quả **ghi đè trực tiếp** vào nhánh `local_mt`; bản Local MT gốc được giữ lại trong snapshot (đọc bản gốc khi cần xem lại) và nhánh `ai` không bị đụng tới.

Vì AI chỉ *biên tập* (không dịch trực tiếp từ bản gốc), workflow này **không có rủi ro bản quyền**.

Vì AI chỉ *biên tập* (không dịch trực tiếp từ bản gốc), workflow này **không có rủi ro bản quyền**.

### Workflow B — OpenAI dịch rồi Local MT clear Hán

Dịch thẳng bằng `openai` cho chất lượng tốt với đa số ngữ cảnh (tùy model), nhưng đôi khi sót ký tự Hán. Bước clear Hán mặc định dùng **Local MT** (miễn phí, offline) thay vì tốn token OpenAI — xem [Clear Hán](#clear-hán-chữ-hán-còn-sót). Khi API gặp giới hạn, tận dụng **export/import** (`bulk_transfer`) để dịch/biên tập qua web chat AI miễn phí rồi nạp ngược.

### Tự host endpoint OpenAI-compatible

Backend `openai` không bắt buộc phải là dịch vụ trả tiền: bất kỳ server nào lộ `POST {base_url}/chat/completions` và `GET {base_url}/models` đều dùng được. `notebooks/novel2epub_zhvi_server.ipynb` dựng sẵn một server như vậy trên GPU miễn phí của Colab/Kaggle với model mạnh Trung → Việt (Qwen3/Qwen3.5 hoặc Sailor2 — bản train riêng cho Đông Nam Á). Chi tiết vận hành xem [operations.md](operations.md#tự-host-model-dịch-trên-colabkaggle).

Khi tự host, chỉnh kèm mấy tham số sau cho khớp server:

- `temperature` 0.3 — mặc định 0.7 quá cao cho dịch, dễ chế thêm chi tiết.
- `translate.max_workers` bằng số slot song song mà engine báo (notebook in sẵn); đặt cao hơn chỉ làm request xếp hàng.
- `translate.prompt_max_chars` không quá một nửa context của model (mặc định notebook là 8192 token → khoảng 4000 ký tự).
- `timeout_seconds` 600, vì GPU miễn phí sinh chậm hơn API thương mại.

Model có thinking mode (Qwen3/Qwen3.5) phải **tắt thinking ở phía server**: client chỉ gửi đúng một message `user` nên không có chỗ truyền cờ. Notebook lo việc này, và còn lọc `<think>` trên luồng SSE để phòng hờ — nếu bản dịch xuất hiện thẻ `<think>`, đó là dấu hiệu endpoint chưa tắt đúng.

### Model Local MT

Local MT dùng model NMT/seq2seq lượng tử hóa qua CTranslate2, chọn qua `translate.model` (preset) hoặc `translate.hachimimt.model_key`:

Các cấu hình được tách trong SPA: **Cài đặt > Local MT** chứa model offline, beam/chunk và clear Hán; **Cài đặt > Dịch API** chứa OpenAI-compatible dùng để dịch; **Cài đặt > AI biên tập** là backend riêng cho rewrite, sửa ghi chú, glossary và nhân vật.

- **HachimiMT/MoxhiMT CT2**: tích hợp sẵn, phù hợp truyện Trung → Việt và glossary hậu xử lý.
- **HirashibaMT (Medium/Tiny)**: nhẹ hơn, benchmark trước khi dùng hàng loạt.

Không dùng model nhỏ để tự suy luận glossary phức tạp; hãy dịch thẳng, sau đó duyệt tên riêng và biên tập theo thể loại.

## Ngữ Cảnh Dịch

Glossary theo ebook dùng để cố định tên riêng và thuật ngữ đặc thù. Không đưa từ đời thường vào glossary. Matching ưu tiên source dài để tên dài không bị mục ngắn thay trước.

Idioms là từ điển dùng chung cho mọi ebook. Với LLM, idiom được đưa vào prompt như tham chiếu; với MT cục bộ, hệ thống có thể chuẩn hóa bản literal hoặc bảo vệ source qua placeholder.

Bảng nhân vật lưu tên, alias, giới tính, cách tự xưng và cách người kể gọi. Quan hệ có hướng lưu cách xưng hô theo mốc chương, giúp thay đổi quan hệ không áp ngược cho toàn truyện.

Genre và style cung cấp luật xưng hô, mức Hán Việt, tông giọng và cách xử lý tiêu đề. Ngữ cảnh cụ thể và bảng nhân vật có ưu tiên cao hơn preset thể loại.

## AI Hỗ Trợ

Backend `ai.openai` phục vụ:

- Review và rewrite bản dịch.
- Đề xuất glossary và xử lý thay đổi cần duyệt.
- Trích nhân vật/quan hệ theo nhóm chương.
- Clear Hán còn sót (khi `cleanup_han.engine=openai`; mặc định dùng Local MT).
- Sửa đoạn, giải thích và ghi chú chất lượng.

Đề xuất thay đổi glossary hoặc quan hệ nên được duyệt trước khi lan truyền. Các thao tác hàng loạt chạy qua job queue để có log và khả năng hủy/retry.

## Clear Hán (chữ Hán còn sót)

Sau khi dịch, bản Việt đôi khi còn sót ký tự Hán. Bước clear Hán quét và sửa các vùng đó, có hai engine (`translate.cleanup_han.engine`):

- **`local_mt` (mặc định)**: dịch riêng từng vùng Hán bằng Local MT cục bộ, giữ nguyên phần Việt. Miễn phí, offline, không tốn token — chạy được cả với ebook dịch bằng `openai`.
- **`openai`**: nhờ AI biên tập (`ai.openai`) sửa vùng Hán trong ngữ cảnh câu; chất lượng cao hơn nhưng tốn token và cần cấu hình AI biên tập.

Bật tự động sau mỗi chương bằng `translate.auto_cleanup_han`, hoặc chạy tay:

- **CLI**: `cleanup-han [--engine local_mt|openai]`.
- **Trang chương / trình đọc**: nút Clear Hán.
- **Hàng loạt ở trang truyện**: chọn chương trong bảng rồi bấm **Dọn chữ Hán** ở thanh hành động. Hộp thoại cho chọn engine (bỏ trống = theo cấu hình truyện) và tuỳ chọn quét lại chương đã dọn. Gọi `POST /api/ebooks/{slug}/batch/cleanup-han` với `indexes`, `engine`, `force`; cả lô chạy trong MỘT job nên Local MT chỉ nạp model một lần.

Bản dịch trước khi dọn được giữ trong snapshot để so sánh và khôi phục.

## Dọn tiêu đề TOC

Tiêu đề chương đôi khi dính từ rác kêu gọi độc giả ("(Cầu nguyệt phiếu)", "cầu vé tháng", `求月票`...). Hàm `toc.strip_toc_junk` loại chúng mà giữ nguyên số chương:

- **Tự động**: chạy trong `_clean_title` mỗi khi dịch/dịch lại tiêu đề.
- **Thủ công**: nút **Chuẩn hóa TOC** trong SPA (`batch/clean-toc`) mặc định dọn tiêu đề đã dịch và tiêu đề theo nhánh Local MT/AI. Tiêu đề nguồn `title_zh` chỉ được dọn khi bật **Gốc (zh)** vì nó tham gia khóa nhận diện chương mới `(url, title_zh hoặc title)`; đổi trường này có thể khiến lần cập nhật TOC sau coi tiêu đề nguồn chưa dọn là một chương mới. CLI `clean-toc [--apply]` mặc định chỉ preview.

### Trích xuất tên riêng từ raw

`POST /api/ebooks/{slug}/glossary/proper-names/extract` quét raw bằng heuristic họ người Trung Quốc, tần suất và ngữ cảnh hội thoại. Vì tiếng Trung không viết hoa và không tách từ như tiếng Việt, kết quả chỉ là **ứng viên**, không phải nhận diện chắc chắn.

Endpoint có thể dịch từng ứng viên bằng Local MT rồi đưa vào `glossary_pending`. Nó không ghi trực tiếp vào `names.txt`: source đã tồn tại trong glossary hoặc hàng chờ được bỏ qua, và thao tác merge hàng chờ dùng transaction `BEGIN IMMEDIATE` để không ghi đè snapshot mới hơn. Hãy mở trang Glossary, kiểm tra context/confidence, sửa bản dịch rồi mới duyệt.

## Checklist Chất Lượng

- Không thêm, bỏ hoặc giải thích nội dung ngoài nguyên tác.
- Câu tiếng Việt tự nhiên, không giữ máy móc trật tự từ nguồn.
- Ngôi kể và xưng hô đúng quan hệ, thân phận, thời điểm.
- Tên riêng và thuật ngữ nhất quán với glossary.
- Thành ngữ được dịch theo nghĩa và sắc thái, không ghép từng chữ.
- Hán Việt đủ giữ không khí nhưng không làm câu khó hiểu.
- Không còn lời mở đầu của model, Markdown fence hoặc chữ Hán chưa xử lý.
- Giữ cấu trúc đoạn hợp lý và tiêu đề chương rõ nghĩa.

## Quy Trình Khuyến Nghị

1. Dịch thử vài chương đại diện trước khi chạy toàn bộ.
2. Xây glossary và bảng nhân vật từ đầu truyện.
3. Kiểm tra xưng hô ở các mốc quan hệ thay đổi.
4. Dùng cleanup Hán sau dịch, không thay cho việc review nội dung.
5. Biên tập các chương quan trọng và dùng batch export/import khi làm ngoài hệ thống.
6. Build EPUB thử, đọc trên thiết bị thật rồi mới phát hành bản cuối.
