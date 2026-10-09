# Dịch Và Biên Tập

## Luồng Nội Dung

Mỗi chương có ba lớp nội dung:

- Raw: văn bản nguồn sau crawl.
- MT snapshot: kết quả dịch ban đầu, dùng để đối chiếu và phục hồi.
- Translated: bản đang biên tập và là nguồn để build EPUB.

Biên tập không ghi đè snapshot MT. Có thể so sánh nguồn, bản máy và bản sửa trong trình đọc ba cột.

## Soát Lỗi Có Duyệt

Luồng **Lỗi → Soát lỗi** khác **AI biên tập** ghi trực tiếp Local MT:

| Nhóm | Xử lý |
| --- | --- |
| Control/BOM/ZWSP, spaces, markdown heading/fence, HTML/entity, punctuation lặp/dots lạ | Thuật toán sau xác nhận; chỉ bỏ markup, giữ text bên trong và đoạn/dòng |
| Hán sót, `�`, mojibake, từ lặp, URL theo ngữ cảnh, spelling nghi vấn | AI đề xuất vùng lỗi đã chọn, FULL diff và duyệt toàn chương |
| Viết tắt | Informational, không tự coi là rác |
| Rỗng/chỉ ký hiệu, trùng chính xác, số chương thiếu/trùng/giảm, lỗi title | Manual mặc định; có hướng dẫn chi tiết mới cho AI đề xuất title/text toàn chương |

Spelling là heuristic nhẹ toàn token (`[a-zA-ZÀ-ỹ]+(?:\.[a-zA-ZÀ-ỹ]+)*`, bỏ token
dưới 3 ký tự): ASCII vowel lặp ≥3, q/x trước nhóm phụ âm, ≥4 phụ âm liên tiếp
không phân biệt hoa thường. Có false positive (tên riêng/từ ngoại ngữ), không phải
chẩn đoán chắc hay từ điển. Roman phù hợp không bị coi là acronym.

Raw chỉ là bằng chứng đối chiếu, không giả lập alignment giữa dòng raw/dịch.
Không tạo/xóa/sắp lại chương, đổi index/skipped hoặc suy đoán khôi phục nội dung mất.
AI không chắc/không có bằng chứng phải để unresolved. HTML lạ giữ inner text để
không xóa nhầm ý nghĩa; nội dung từ thẻ script/style còn lại cần người đọc đánh giá.
Hướng dẫn vận hành và các giới hạn an toàn ở [operations.md](operations.md#soát-lỗi-chương--hàng-loạt).

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

Prompt Auto Glossary kèm bản dịch và AI phân tích chương viết bằng tiếng Anh.
Prompt AI duyệt & dọn glossary viết bằng tiếng Việt, dựa trên nguyên tắc ngôn ngữ
của `DEFAULT_PROMPT`: đúng nghĩa theo ngữ cảnh, Hán Việt phù hợp cho tên riêng,
thuần Việt tự nhiên cho từ đời thường, không cố định xưng hô máy móc và không
đoán tên Latin khi thiếu căn cứ. Đầu ra của tác vụ dọn vẫn là mảng JSON thao tác,
không phải bản dịch chương. Tên dịch, ghi chú và lý do bằng tiếng Việt (tên ngoại
giữ dạng Latin gốc khi xác định chắc chắn). Chỉ tạo ghi chú cho **nhân vật** khi
ngữ cảnh cung cấp rõ vai trò, thuộc phe/phái, quan hệ hoặc bí danh/tên gọi: tối đa một câu ngắn,
30 từ. Thiếu bằng chứng thì không tạo ghi chú; không suy đoán từ tên, dùng kiến
thức ngoài hay tiết lộ tình tiết tương lai. Địa danh/tổ chức/chức danh/công pháp/
vật phẩm/thuật ngữ khác không được tạo ghi chú. Lý do quyết định tách khỏi ghi
chú độc giả. AI dọn giữ ghi chú cũ khi không có thông tin mới, không tự xóa
ghi chú thủ công chỉ vì mục không phải nhân vật.

Bí danh, biệt danh và tên nhân vật dùng trong mạng lưới/thế giới ảo cũng được
ghi chú: tên đó chỉ ai, ai sử dụng cách gọi ấy và dùng trong hoàn cảnh nào.
Không bắt buộc mục glossary là tên thật của nhân vật. Ví dụ hợp lệ khi ngữ cảnh
đã xác nhận: `塞尔西 = Tạ Nhĩ Tây | Được Patty gọi, là tên Cao Văn dùng trong mạng lưới`.
AI dọn giữ các ghi chú nhận diện bí danh này, không coi chúng là lý do sửa bản dịch.

Step automation `glossary-ai` là hậu kiểm Glossary: đọc các xung đột đang có, nhờ LLM chọn bản dịch thống nhất theo prompt dịch nghiêm ngặt (kèm tên truyện + tác giả), tự duyệt mục hợp lệ và lan truyền thay đổi vào bản dịch cũ. Mục LLM không trả lời được vẫn giữ trong hàng chờ. Cột Ghi chú giữ nguyên — lý do của LLM chỉ ghi log.

### AI tự động duyệt & dọn (SPA Glossary)

- Bắt đầu từ **các mục đã chọn** trong glossary và hàng chờ (khóa trùng được gộp).
  AI chuẩn hóa Hán/Việt, dịch lại theo bối cảnh, sửa Việt còn Hán, giữ mục đúng
  hoặc xóa mục lỗi/rác. Khi một thay đổi cần lan truyền bản dịch dùng chung,
  hệ thống **tự xét thêm các khóa Hán cùng dùng bản dịch đó**, kể cả ngoài lựa chọn.
  AI nhận bản dịch cũ và các đề xuất chưa ghi để đánh giá đồng thuận; không tự
  tạo thuật ngữ mới. Log liệt kê các alias được xét thêm.
- Chọn **1–100 mục/lô, mặc định 10**; chạy tuần tự và cập nhật tham chiếu sau mỗi lô.
  Ngân sách context **200.000 token**, dành 16.000 cho output. Bộ đếm dùng số
  byte UTF-8 làm cận trên bảo thủ cho tokenizer kiểu byte, không nhầm ký tự với
  token. `REFERENCE` chỉ gửi tối đa **5 mục liên quan** (khóa Hán chứa nhau),
  tổng tối đa **2.000 ký tự JSON**; bỏ mục trùng lô, trùng khóa hoặc quá dài.
  Không có mục liên quan thì gửi danh sách rỗng. Mục trong lô quá dài được chia
  lô nhỏ hơn. Model/API phải hỗ trợ context 200k; ứng dụng không
  tự nâng giới hạn provider. HTTP/JSON lỗi thì không ghi lô và job báo lỗi.
- Kiểm định khóa thuộc lô, dữ liệu thay đổi sau khi gửi, trùng khóa đích,
  source Hán/target Việt hợp lệ. AI phải trả đúng một quyết định cho mỗi mục.
  Thay đổi **chỉ hoa/thường** (ví dụ `Quân Đoàn` → `Quân đoàn`) được duyệt
  vào glossary và gỡ khỏi hàng chờ, nhưng không tìm–thay toàn văn để giữ cách
  viết theo ngữ cảnh trong chương; không cần đồng thuận của các mục dùng chung.
  Quy tắc này áp dụng cả `keep` đề xuất đang chờ và `update`.
  Với thay đổi từ ngữ thực sự, một bản dịch cũ có nhiều chủ sở hữu chỉ được lan truyền khi **tất cả chủ sở
  hữu trong nhóm kiểm định** có quyết định hợp lệ và đồng thuận cùng bản dịch mới.
  Mục chưa được kiểm định, bị loại kiểm định hoặc bị xóa không được coi là đồng
  thuận; xóa glossary không cho phép đổi văn bản chương của mục đó. `keep` một
  đề xuất đang chờ vẫn có thể đổi bản dịch chuẩn nên cũng cần kiểm định này.
  Chủ sở hữu được tính theo **khóa có chữ Hán, không lẫn Latin/tiếng Việt** trong glossary và hàng chờ.
  Dòng cũ đặt nhầm tiếng Việt vào khóa Hán (ví dụ `Lệ Liệp Nguyệt`, `Cự Quy Nham Đài号`)
  không tạo xung đột giả chặn mục Hán hợp lệ. Nếu một khóa như vậy được sửa thành
  khóa Hán hợp lệ trong lô, nó vẫn phải đồng thuận về bản dịch trước khi lan truyền.
  Khóa chèn khoảng trắng (ví dụ `猎 魔 人`) và tên rút gọn (ví dụ `巨龟岩台`)
  vẫn cần quyết định AI, không tự coi là đồng thuận hay xóa để vượt kiểm định.
  Nếu AI bỏ khoảng trắng làm khóa trùng một mục đã có, hệ thống giữ nguyên
  khóa alias và kiểm định target/note riêng, không ghi đè mục đích hay mất ghi chú.
  Các lượt xét thêm tuân thủ giới hạn mục/lô, ngân sách context và retry/chia lô;
  nếu phát hiện thêm chủ sở hữu qua đề xuất chờ, tiếp tục xét đến khi đủ nhóm.
  Chỉ ghi glossary, hàng chờ, audit và lan truyền **cả nhóm trong một transaction**
  sau khi tất cả lượt AI hoàn tất. Mục đã xử lý sớm cùng nhóm được bỏ qua ở lô sau.
  Nếu AI vẫn đưa quyết định mâu thuẫn hoặc đổi sang khóa đã tồn tại, **giữ nguyên
  cả nhóm liên quan** trong glossary/hàng chờ và không lan truyền bản dịch của
  nhóm đó; ghi lý do vào `held` trong outcome, log và audit. Các mục độc lập trong
  lô và các lô sau tiếp tục được xử lý, không làm dừng job. Nhóm liên quan tính
  cả các bản dịch cũ/đề xuất chờ nối tiếp và khóa đích của thao tác đổi khóa.
  Xem các mục giữ lại trong log để điều chỉnh bản dịch; hệ thống không ép các
  thuật ngữ khác nghĩa dùng chung bản dịch.
  Thiếu/trùng quyết định, đầu ra không hợp lệ hoặc dữ liệu đã đổi sau khi gửi AI:
  cả lô chưa ghi, job báo lỗi để chạy lại; các lô trước đã hoàn tất vẫn được giữ.
- Provider có thể có giới hạn thời gian riêng (ví dụ `recipe_timeout` sau 120s).
  Lỗi tạm thời được nhận diện (timeout, rate limit, 5xx, lỗi kết nối khi gửi request)
  được thử lại 1 lần sau 5 giây; nếu vẫn lỗi và lô còn hơn 1 mục thì hệ thống
  **tự chia đôi lô**. Khi còn 1 mục mà vẫn lỗi, job báo lỗi. Lỗi cấu hình
  (401, sai định dạng) không thử lại. `timeout_seconds` phía client không ảnh
  hưởng giới hạn của proxy; muốn nới phải chỉnh ở chính provider.
- Kết quả ghi trực tiếp và gỡ các mục đã xử lý khỏi hàng chờ trong cùng transaction,
  **không cần duyệt lại**. Bản dịch glossary hợp lệ sau sửa (trừ thay đổi chỉ hoa/thường) được lan truyền vào chương
  trong cùng transaction, sau khi kiểm tra thay thế không nhập nhằng.
  Mục lỗi bị loại chỉ xóa khỏi glossary/hàng chờ, không thay hay hoàn tác nội dung chương.
- **Ghi chú là chú thích cho độc giả**, không phải lý do sửa. AI bỏ trường
  `note` để giữ cũ, hoặc sửa/bỏ chú thích sai một cách tường minh.
  `reason` chỉ vào log và audit SQLite `glossary_curator_audit` (kèm dữ liệu cũ).
  Hiện chưa có nút hoàn tác; nên backup DB và lưu các nháp trước khi chạy.
- API `/api/ebooks/{slug}/glossary/ai/reprocess-pending` yêu cầu `sources` không rỗng,
  nhận `batch_size` (mặc định 10) và `instruction`. Job lưu `selected_only=true`
  cùng phạm vi/lô để phục hồi đúng; job spec cũ vẫn dùng luồng cũ.

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

- Trong **Cài đặt truyện → Dịch API**, bật **Tự động dọn chữ Hán còn sót** và chọn `LLM / AI biên tập` để chạy cleanup ngay sau mỗi chương. `cleanup_han_max_chars` giới hạn kích thước mỗi lượt gọi và `cleanup_han_retries` là số lần thử lại.

- **CLI**: `cleanup-han [--engine local_mt|openai]`.
- **Trang chương / trình đọc**: nút Clear Hán.
- **Hàng loạt ở trang truyện**: chọn chương trong bảng rồi bấm **Dọn chữ Hán** ở thanh hành động. Hộp thoại cho chọn engine (bỏ trống = theo cấu hình truyện) và tuỳ chọn quét lại chương đã dọn. Gọi `POST /api/ebooks/{slug}/batch/cleanup-han` với `indexes`, `engine`, `force`; cả lô chạy trong MỘT job nên Local MT chỉ nạp model một lần. Nút **Dọn Hán (MT)** cạnh bên xếp job thẳng với `engine=local_mt`, bỏ qua hộp thoại.

Bản dịch trước khi dọn được giữ trong snapshot để so sánh và khôi phục.

## Dọn nhanh Markdown / dấu câu kiểu Hán

Bản dịch cũ (dịch trước khi có validate `_clean_output`) có thể dính format Markdown rò rỉ (`**in đậm**`, `## …`) hoặc dấu câu kiểu Hán (`，。「」…`). Hai nút **Sửa Markdown** / **Sửa dấu câu** ở nhóm **Dọn nhanh** (thanh hành động trang truyện) áp lại đúng quy tắc đó lên dữ liệu đã lưu: gọi `POST /api/ebooks/{slug}/batch/normalize-text` với `indexes` và `mode` (`markdown`|`punct`|`all`).

Endpoint chạy đồng bộ (thuần string-op, không qua job queue), quét cả hai nhánh có nội dung + tiêu đề nhánh (không đụng `title_zh`/raw), chỉ ghi chương thực sự đổi (revision +1, token preview cũ hết hiệu lực) và trả `{scanned, updated, mode}`.

## Dọn tiêu đề TOC

Tiêu đề chương đôi khi dính từ rác kêu gọi độc giả ("(Cầu nguyệt phiếu)", "cầu vé tháng", `求月票`...). Hàm `toc.strip_toc_junk` loại chúng mà giữ nguyên số chương:

- **Tự động**: chạy trong `_clean_title` mỗi khi dịch/dịch lại tiêu đề.
- **Thủ công**: nút **Chuẩn hóa TOC** trong SPA (`batch/clean-toc`) mặc định dọn tiêu đề đã dịch và tiêu đề theo nhánh Local MT/AI. Tiêu đề nguồn `title_zh` chỉ được dọn khi bật **Gốc (zh)** vì nó tham gia khóa nhận diện chương mới `(url, title_zh hoặc title)`; đổi trường này có thể khiến lần cập nhật TOC sau coi tiêu đề nguồn chưa dọn là một chương mới. CLI `clean-toc [--apply]` mặc định chỉ preview.

### Trích xuất tên riêng từ raw

`POST /api/ebooks/{slug}/glossary/proper-names/extract` quét raw bằng heuristic họ người Trung Quốc, tần suất và ngữ cảnh hội thoại. Vì tiếng Trung không viết hoa và không tách từ như tiếng Việt, kết quả chỉ là **ứng viên**, không phải nhận diện chắc chắn.

Endpoint có thể dịch từng ứng viên bằng Local MT rồi đưa vào `glossary_pending`. Nó không ghi trực tiếp vào `names.txt`: source đã tồn tại trong glossary hoặc hàng chờ được bỏ qua, và thao tác merge hàng chờ dùng transaction `BEGIN IMMEDIATE` để không ghi đè snapshot mới hơn. Hãy mở trang Glossary, kiểm tra context/confidence, sửa bản dịch rồi mới duyệt.

### AI Harness — rà soát toàn truyện, dịch tại chỗ và tìm-thay thông minh

Tab **Trợ lý và tool** của trang AI Harness làm việc trong phạm vi ebook đang mở (raw, bản dịch nhánh active, tiêu đề, glossary,
nhân vật, idiom; tối đa 300 đoạn một lượt). Header cho đổi provider/model theo thread (lưu vào
`assistant_threads`, không chạm config ebook/global).

Tab **Rà soát** chạy workflow v1 qua hàng đợi trên toàn bộ chương đã dịch. Kết quả, lỗi quét và tiến độ
được lưu trong SQLite; lỗi gọi model/JSON hiện là chương thất bại, không được coi là sạch. Agent chỉ tạo
đề xuất neo vào đúng một đoạn hoặc một mục Glossary. Người dùng lọc, chọn nhiều lỗi, xem diff rồi mới
áp dụng; preview cũ hoặc bản dịch đổi bị từ chối. Glossary dùng lại luồng sửa mục và lan truyền cũ.
Báo cáo `.md` là bản xuất tùy chọn, không phải nguồn dữ liệu để agent ghi ngược.

- **Dịch tại chỗ**: chip "Dịch đoạn đang chọn" gửi đoạn bôi đen + ngữ cảnh chương cho agent; muốn sửa bản dịch thì
  agent trả thẻ preview diff theo đoạn — tick xác nhận rồi bấm **Áp dụng** mới ghi (stale protection kiểu
  para/save, tăng revision nhánh).
- **Fill ngữ cảnh**: nút **Fill ngữ cảnh** (hoặc nhờ trực tiếp trong chat) dò tên riêng từ raw vào hàng chờ duyệt
  (task nhanh, chạy ngay), còn AI dịch lại hàng loạt + trích nhân vật/quan hệ chạy job nền category=translate —
  theo dõi ở `/queue`, kết quả vào hàng chờ duyệt, không tự ghi glossary/nhân vật.
- **Tìm-thay thông minh**: nhờ "thay X bằng Y", agent tìm chính xác trước, sinh regex + giải thích, gợi ý thêm
  biến thể nghĩa, gộp MỘT preview để tick chọn từng đoạn rồi áp dụng (backup meta `before_find_replace[_branch]` /
  `before_find_replace_raw`). Tìm kiếm luôn không phân biệt hoa/thường.

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
