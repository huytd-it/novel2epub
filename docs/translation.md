# Dịch Và Biên Tập

## Luồng Nội Dung

Mỗi chương có ba lớp nội dung:

- Raw: văn bản nguồn sau crawl.
- MT snapshot: kết quả dịch ban đầu, dùng để đối chiếu và phục hồi.
- Translated: bản đang biên tập và là nguồn để build EPUB.

Biên tập không ghi đè snapshot MT. Có thể so sánh nguồn, bản máy và bản sửa trong trình đọc ba cột.

## Dịch tiêu đề nhanh

Chọn các chương cần dịch tại trang truyện → **Khác → Dịch tiêu đề nhanh**.
Local MT xử lý từng tiêu đề và lưu ngay vào SQLite, không chờ hoàn tất cả danh sách.
Danh sách chương tự làm mới mỗi 2 giây trong lúc job chạy. Dừng job hoặc gặp lỗi
giữa chừng vẫn giữ các tiêu đề đã lưu; kết quả dịch rỗng không ghi đè tiêu đề cũ.
Tiêu đề nguồn và nội dung chương được giữ nguyên.

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

## Chuẩn hóa xưng hô không tốn token

Lệnh `normalize-pronouns` dùng quy tắc cục bộ, không gọi AI, phù hợp phong cách
võ hiệp/tiên hiệp muốn thống nhất `ta/ngươi`. Đây là **lựa chọn phong cách**,
không phải sửa ngữ nghĩa hay nhận diện người nói; `ngươi` có thể thiếu lịch sự
trong ngữ cảnh hiện đại hoặc quan hệ tôn ti.

```sh
# Xem đầy đủ diff, không ghi DB; bắt buộc chọn nhánh
python -m novel2epub -e <slug> normalize-pronouns --branch local_mt --from 1 --to 10
# Sau khi duyệt diff và sao lưu DB, thêm --apply để ghi kèm lịch sử phiên bản
python -m novel2epub -e <slug> normalize-pronouns --branch local_mt --from 1 --to 10 --apply
```

- Chỉ sửa trong ngoặc kép cân bằng cùng dòng (`"…"`, `“…”`, `«…»`, `「…」`,
  `『…』`): `tôi/tao/tớ → ta`, `mày → ngươi`. Giữ viết hoa.
- Giữ số nhiều: `chúng/bọn/tụi + tôi/tao/tớ → bọn ta`,
  `chúng/bọn/tụi mày → các ngươi`; không đổi thành `chúng ta` (khác nghĩa).
- Giữ lời kể, đại từ mơ hồ (`anh/em/bạn/mình/mi`), ngôi thứ ba và danh xưng
  quan hệ. Bỏ qua ngoặc thiếu/lồng, thoại nhiều dòng và thoại gạch đầu dòng.
- Có ngoại lệ từ đồng âm thường gặp (`cái tôi`, `đầy tớ`, `thanh tao`,
  `tôi luyện`, `lông mày`...). Không bảo đảm bao phủ mọi từ đồng âm; phải duyệt
  diff, nhất là trích dẫn không phải lời thoại. Entity `protect` giữ cả literal
  source lẫn target, không thay tên theo từ điển trong bước này.
- Bỏ `--from/--to` để quét toàn nhánh; bỏ qua chương skipped/chưa dịch hoàn chỉnh.
  Index là index lưu trong DB. Không thay raw, snapshot MT, tiêu đề, nhánh còn lại
  hoặc lựa chọn nhánh xuất bản. Không tự build EPUB/publish Reader.
- Mỗi chương ghi qua revision/hash CAS và lịch sử bất biến; gặp xung đột thì dừng,
  không ghi đè. Những chương đã lưu trước lỗi vẫn giữ nguyên; xem lại preview để
  chạy tiếp. Skill `.opencode/skills/normalize-pronouns/SKILL.md` hướng dẫn agent
  thực hiện quy trình duyệt trước khi ghi.

### Dùng trên giao diện web

Ở trang truyện, bấm **Chuẩn hóa xưng hô** trong thanh tiêu đề bảng Chương:

1. Chọn rõ nhánh **AI** hoặc **Local MT**. Không tự lấy nhánh đang xuất bản.
2. Dùng các chương đang chọn trong bảng, hoặc nhập khoảng **index trong kết quả
   đang lọc**. Mỗi lượt tối đa 50 chương và 2 MB nội dung; không âm thầm cắt phạm vi.
   Trong **Chỉ sửa bên trong dấu**, chọn:
   - **Ngoặc kép thông dụng (hiện tại)**: `"…"`, `“…”`, `«…»`, `「…」`, `『…』`.
     Đây vẫn là mặc định, tương thích hành vi cũ.
   - **Chỉ nháy đơn / dấu thoại Trung**: `'…'`, `‘…’`, `“…”`, `「…」`, `『…』`.
     Không sửa trong ngoặc kép ASCII `"…"` hoặc `«…»`; bỏ qua mọi vùng lồng nhau,
     kể cả khi cặp ngoài không thuộc kiểu dấu được chọn. Dấu nháy trong từ như
     `don't`/`O’Connor` không được xem là ranh giới lời thoại.
   - **Chỉ ngoặc đơn**: `(…)` và `（…）`. Đây có thể là chú thích/suy nghĩ chứ không
     phải lời nói; chỉ dùng khi biết định dạng truyện và vẫn phải duyệt diff.
   Tất cả đều lọc **dấu trong bản dịch**, không căn chỉnh với bản gốc tiếng Trung;
   không tự suy luận lời nói hoặc sửa ngoài vùng đã chọn. Cặp thiếu, lồng, hoặc
   kéo dài nhiều dòng bị bỏ qua. Đổi kiểu dấu sẽ hủy bản xem trước và xác nhận cũ.
3. Bấm **Xem trước thay đổi**, mở từng chương để xem đầy đủ diff trước/sau.
   Việc mở hộp thoại và xem trước không ghi nội dung hoặc backfill lịch sử.
4. Tích xác nhận đã duyệt rồi bấm **Áp dụng … chương đã duyệt**. Đổi nhánh/phạm vi
   sẽ bỏ bản xem trước và xác nhận cũ. Không tự build EPUB hoặc đẩy Reader.

API nội bộ `POST /api/ui/ebooks/{slug}/pronouns/preview` và `/apply` chạy quy tắc
cục bộ, không gọi model. Approval ràng buộc với ebook, nhánh, danh sách index,
revision/hash nguồn, trạng thái bỏ qua/hoàn chỉnh, kiểu dấu bao quanh, entity protect và kết quả đề
xuất. Bản xem trước cũ bị từ chối; ghi từng chương bằng revision/hash CAS. Nếu có
xung đột giữa lúc ghi, giao diện báo rõ index thành công/thất bại. Sau lỗi mạng,
phải xem trước lại trạng thái hiện tại, không tự gửi lại lệnh ghi.

CLI có cùng bộ lọc: thêm `--dialogue-marks single_chinese` hoặc
`--dialogue-marks parentheses`; không truyền tương đương `standard`. API dùng
field `dialogue_marks` với ba giá trị đó (mặc định `standard`). Kiểu dấu được lưu
trong metadata của lần ghi; approval không thể dùng lại với kiểu dấu khác.

## Hai Con Đường Dịch

Chỉ còn **hai** backend dịch (`translate.type`):

| Backend | Phù hợp |
| --- | --- |
| `localmt` | Local MT cục bộ (CTranslate2). Nhanh, miễn phí, offline; ~90% đúng với tiên hiệp/huyền huyễn. |
| `openai` | AI qua API OpenAI-Compatible. Chất lượng văn phong cao, prompt/ngữ cảnh phong phú, tự trích glossary. |
| `none` | Nguồn tiếng Việt hoặc kiểm thử pipeline (passthrough). |

Với nguồn tiếng Việt, đặt `source_language=vi`; hệ thống tự passthrough và không gọi model. `google` và `libretranslate` đã bị gỡ — ebook cũ dùng chúng được tự chuyển sang `openai` khi load (kèm cảnh báo).

### Guard bắt buộc khi dịch chương

Mọi bản dịch chương (AI lẫn Local MT, trừ passthrough `none`/`source_language=vi`) phải qua guard trong `novel2epub/translation_guard.py` trước khi được coi là dịch xong. Không có cấu hình tắt.

- **Dài bất thường:** số từ bản dịch vượt `3 × số từ nguồn + 50` (mọi ngôn ngữ nguồn). Mỗi chữ Hán tính là một từ, mỗi cụm chữ/số ngoài Hán là một từ; chữ Hán còn sót trong bản dịch không được tính là từ tiếng Việt.
- **Dính prompt dịch:** nếu phản hồi của AI lặp lại prompt, phần prompt (và nội dung gốc bị lặp kèm) được tách bỏ theo từng chunk, log `⚠ phản hồi lặp lại prompt dịch`. Bỏ prompt xong mà không còn bản dịch thì chunk đó lỗi.

Bản bị guard từ chối là dịch thất bại: các chunk đã stream bị bỏ, nhánh trở về đúng nội dung trước khi dịch (bản hoàn chỉnh cũ vẫn giữ nguyên khi dịch lại với `force`), lý do nằm ở `meta.last_error` và nhật kí job (`Guard từ chối bản dịch chương ...`). Chương được đánh dấu `failed`; batch vẫn dịch tiếp các chương khác.

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
Prompt AI duyệt & dọn glossary cũng viết bằng tiếng Anh, chia mục INPUT / TRANSLATION
RULES / DECISIONS / READER NOTES / OUTPUT; hai chế độ (rà toàn bộ và dọn mục đã
chọn) dùng chung quy tắc, chỉ khác mục DECISIONS. Quy tắc dựa trên nguyên tắc ngôn ngữ
của `DEFAULT_PROMPT`: đúng nghĩa theo ngữ cảnh, Hán Việt phù hợp cho tên riêng,
thuần Việt tự nhiên cho từ đời thường, không cố định xưng hô máy móc. Tên người
nước ngoài phiên âm bằng chữ Hán **luôn nghiêng về dạng Latin kiểu châu Âu**
(艾伦 → Allen, không "Ngải Luân") ở cả prompt dịch lẫn prompt glossary: nhận ra
tên gốc thì dùng chính tả gốc, chưa chắc thì chọn cách viết Latin phổ biến nhất
khớp âm đọc; chỉ dùng Hán Việt khi rõ ràng là tên Trung Quốc. Prompt dịch mặc
định đã lưu trong DB (global và từng ebook) được tự nâng luật này khi khởi động;
prompt tự viết giữ nguyên. Đầu ra của tác vụ dọn vẫn là mảng JSON thao tác,
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

### Xuất / nhập glossary (SPA Glossary)

Nút **Xuất / Nhập** mở 3 tab, cùng một backend `novel2epub/glossary_sheet.py`:

- **Xuất Excel**: `GET /api/ebooks/{slug}/glossary/export.xlsx` trả file `.xlsx`
  (mọi mục `names.txt` + `vietphrase.txt` đã gộp) với cột `Hán · Việt · Ghi chú ·
  Version · Cập nhật`. Ba cột đầu là dữ liệu thật, hai cột sau chỉ để đối chiếu với
  bảng trên web và **bị bỏ qua khi nhập**. Cần `openpyxl` (đã có trong
  `requirements.txt`).
- **Xuất cho AI**: khối text `GLOSSARY:` + prompt dọn lại (giữ nguyên từ trước).
- **Nhập**: nạp file `.xlsx` hoặc dán khối AI — cùng một luật merge (Hán trùng thì
  giá trị mới thắng, mọi mục gộp về `names.txt`).

Riêng đường `.xlsx`:

- Cột nhận diện theo **tên** (Hán/Việt/Ghi chú, cả `source`/`target`/`note` và
  `Hán tự`/`bản dịch`), nên kéo đổi thứ tự cột hay tự tạo file mới vẫn nạp được;
  không khớp tiêu đề nào thì mặc định cột A/B/C.
- Dòng thiếu Hán, thiếu Việt, hoặc Hán không có chữ Hán **bị bỏ kèm số hàng**
  (`errors`) thay vì làm hỏng cả file — sửa trong Excel rồi nạp lại.
- Ô **Ghi chú** trống giữ ghi chú cũ (khớp luật nhập từ AI); tick *Ô Ghi chú trống
  sẽ xoá ghi chú đang có* (`clear_empty_notes`) thì mới xoá.
- Import KHÔNG lan truyền vào bản dịch chương đã dịch — sửa cột Việt ở đây chỉ đổi
  glossary; muốn thay bản dịch cũ thì áp dụng từng mục ở bảng glossary.

### AI tự động duyệt & dọn (SPA Glossary)

- Bắt đầu từ **các mục đã chọn** trong glossary và hàng chờ (khóa trùng được gộp).
  AI chuẩn hóa Hán/Việt, dịch lại theo bối cảnh, sửa Việt còn Hán, giữ mục đúng
  hoặc xóa mục lỗi/rác. Khi một thay đổi cần lan truyền bản dịch dùng chung,
  hệ thống **tự xét thêm các khóa Hán cùng dùng bản dịch đó**, kể cả ngoài lựa chọn.
  AI nhận bản dịch cũ và các đề xuất chưa ghi để đánh giá đồng thuận; không tự
  tạo thuật ngữ mới. Log liệt kê các alias được xét thêm.
- Chọn **1–100 mục/lô, mặc định 30**; chạy tuần tự và cập nhật tham chiếu sau mỗi lô.
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
  Các lượt xét thêm tuân thủ giới hạn mục/lô, ngân sách context và retry;
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
  Mục cũ có **khóa không chứa chữ Hán** (ví dụ `Patty`, `Ropeny Grilan`) mà AI
  giữ nguyên cũng chỉ được giữ lại như vậy: AI không thể tự đặt khóa Hán, nên
  mục đó không đổi, ghi vào `held` và phần còn lại của lô vẫn được ghi. Sửa khóa
  hoặc xóa mục đó bằng tay; AI vẫn có thể `delete` nếu xác định là rác.
  Lỗi được xử lý **theo từng mục**, không làm hỏng cả job: mục AI bỏ sót, trả
  nhiều quyết định, hoặc trả giá trị không hợp lệ (cột Việt còn chữ Hán, khóa
  mới lẫn Latin…) được **giữ nguyên** cùng nhóm alias của nó — mục đang chờ
  duyệt vẫn nằm trong hàng chờ để duyệt tay — và ghi vào `held`; các mục còn
  lại của lô vẫn được ghi. Khóa cũ có sẵn chữ Latin (ví dụ `圣洁战锤-ii`) mà AI
  giữ nguyên thì vẫn sửa được cột Việt. Lô mà AI trả JSON hỏng, hoặc dữ liệu đã
  đổi sau khi gửi AI, bị bỏ qua nguyên lô (chưa ghi gì, tính vào "lô lỗi" ở dòng
  tổng kết) rồi job chạy tiếp lô sau; chọn lại các mục đó để chạy lại.
- Provider có thể có giới hạn thời gian riêng (ví dụ `recipe_timeout` sau 120s).
  Lỗi tạm thời được nhận diện (timeout, rate limit, 5xx, lỗi kết nối khi gửi request)
  được thử lại 1 lần sau 5 giây; nếu vẫn lỗi thì **hủy cả job** (không chia nhỏ
  lô, không chạy tiếp lô sau) — các lô trước đã hoàn tất vẫn được giữ, chạy lại
  khi provider ổn định. Lỗi cấu hình (401, sai định dạng) không thử lại. `timeout_seconds` phía client không ảnh
  hưởng giới hạn của proxy; muốn nới phải chỉnh ở chính provider.
- Kết quả ghi trực tiếp và gỡ các mục đã xử lý khỏi hàng chờ trong cùng transaction,
  **không cần duyệt lại**. Bản dịch glossary hợp lệ sau sửa (trừ thay đổi chỉ hoa/thường) được lan truyền vào chương
  trong cùng transaction, sau khi kiểm tra thay thế không nhập nhằng.
  Mục lỗi bị loại chỉ xóa khỏi glossary/hàng chờ, không thay hay hoàn tác nội dung chương.
  Bỏ tick "Lan truyền bản dịch đã sửa vào nội dung chương" (`propagate=false`) để AI chỉ
  ghi glossary/gỡ hàng chờ mà không thay gì trong chương — khi đó cũng không cần đồng thuận alias.
- Ở hàng chờ duyệt, **Bỏ** gỡ đề xuất và hoàn tác từ mới về bản dịch cũ ở chương đã sinh
  gợi ý; **Chỉ bỏ** (`pending/clear` với `revert=false`) chỉ gỡ đề xuất, giữ nguyên nội dung
  chương — dùng khi chính đề xuất bị sai để tránh thay thế nhầm.
- **Ghi chú là chú thích cho độc giả**, không phải lý do sửa. AI bỏ trường
  `note` để giữ cũ, hoặc sửa/bỏ chú thích sai một cách tường minh.
  `reason` chỉ vào log và audit SQLite `glossary_curator_audit` (kèm dữ liệu cũ).
  Hiện chưa có nút hoàn tác; nên backup DB và lưu các nháp trước khi chạy.
- Trước khi chia lô, các source được **gom nhóm liên quan** (chung một cụm 2 chữ Hán liền
  kề: họ, tên, tiền tố/hậu tố, tên đầy đủ/rút gọn) và xếp liền nhau để AI quyết định cả
  nhóm trong cùng lô — thống nhất một hệ đặt tên (Hán Việt, Latin gốc, romaji Nhật,
  La-tinh hóa Hàn) cho các tên liên quan. Cụm xuất hiện ở hơn 20 mục bị bỏ qua khi gom.
- API `/api/ebooks/{slug}/glossary/ai/reprocess-pending` yêu cầu `sources` không rỗng,
  nhận `batch_size` (mặc định 30), `instruction` và `propagate` (mặc định `true`). Job lưu `selected_only=true`
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

`POST /api/ebooks/{slug}/glossary/proper-names/extract` quét raw bằng heuristic họ người Trung Quốc, tần suất và ngữ cảnh hội thoại. Vì tiếng Trung không viết hoa và không tách từ như tiếng Việt, kết quả chỉ là **ứng viên**, không phải nhận diện chắc chắn. Recognizer còn bắt **tên nước ngoài phiên âm** (chuỗi nằm trọn trong bảng chữ phiên âm, có ít nhất một chữ đặc trưng như 斯/尔/克/伦, hoặc có dấu `·`); mỗi ứng viên có `kind` (`translit`/`cn_name`/`term`) và `status` (`new`/`pending`/`glossary`). Body nhận `include_terms=true` để bắt thuật ngữ lặp, `dry_run=true` để chỉ trả ứng viên (không dịch hoặc ghi hàng chờ) và `sources=[...]` để chỉ xếp hàng ứng viên đã chọn.

Nút **Trích tên riêng** và **Trích glossary** ở bảng Chương mở trang riêng, giữ phạm vi chương đang chọn hoặc toàn bộ truyện. Trang này cho chọn **Dịch thô Local MT** (mặc định, không dùng API AI), engine mặc định của ebook hoặc giữ Hán. Dịch diễn ra khi đưa các mục đã chọn vào tab Chờ duyệt của Glossary; cần duyệt lại bản dịch thô trước khi áp dụng. API dùng `translate_engine=localmt` để buộc Local MT, hoặc `translate=false` để giữ Hán; mặc định API vẫn dùng engine ebook. Engine lỗi thì giữ Hán, không tự chuyển sang gọi AI.

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
