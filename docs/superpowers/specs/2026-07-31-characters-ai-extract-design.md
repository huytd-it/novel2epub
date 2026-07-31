# AI trích nhân vật & quan hệ → hàng chờ duyệt (sub-project B)

Ngày: 2026-07-31

Tiếp nối `2026-07-30-characters-pronoun-design.md` (sub-project A, đã merge vào
`master` tại `54974cf`). A dựng bảng nhân vật và đường dẫn nó vào prompt; B lấp
chỗ trống lớn nhất còn lại — phải gõ tay toàn bộ bảng đó.

## 1. Vấn đề

Bảng nhân vật của A chỉ có giá trị khi được điền. Với truyện 500 chương và 40
nhân vật, nhập tay là rào cản đủ lớn để tính năng không bao giờ được dùng. Phần
tốn công nhất lại chính là phần giá trị nhất: các mốc `from_chapter` ghi lại
thời điểm quan hệ chuyển giai đoạn.

## 2. Quyết định nền: gom nhóm chương, KHÔNG chạy từng chương

`POST /api/ebooks/{slug}/batch/suggest-glossary` xử lý độc lập từng chương. Với
glossary điều đó đúng — mỗi tên riêng là một sự kiện cục bộ.

Với nhân vật thì cách đó hỏng ở đúng chỗ quan trọng nhất. Alias rải rác nhiều
chương, và **mốc đổi xưng hô chỉ tồn tại khi so sánh được hai thời điểm**. Chạy
riêng lẻ, chương 2 và chương 120 là hai lời gọi không biết gì về nhau; AI không
có cơ sở nào để nhận ra quan hệ đã chuyển từ xa lạ sang thân mật.

Vì vậy B gom chương thành nhóm vừa `prompt_max_chars`, mỗi nhóm một lời gọi,
đánh dấu `## Chương N` trước mỗi chương để AI trích được số chương làm mốc, rồi
gộp kết quả các nhóm.

## 3. Phân biệt bắt buộc: chữ Hán gốc ≠ bản Việt hoá

Đây là ràng buộc trung tâm của spec này.

Trong văn bản Trung có sẵn **dạng xưng hô gốc**: `师父`, `弟子`, `徒儿`, `姑娘`,
`公子`, `在下`, `晚辈`, `前辈`, `本座`, `朕`, `臣`, `妾身`, `奴家`, `为师`,
`老朽`, `小生`... Nhưng chuỗi tiếng Việt *"đồ nhi"*, *"cô nương"*, *"tại hạ"*
**không hề có trong bản gốc** — chúng là lựa chọn dịch, phụ thuộc thể loại và
giọng truyện.

Hệ quả: mỗi giá trị xưng hô phải lưu **hai phần**.

- `*_raw` — chuỗi Hán thực sự có trong văn bản (`师父`, `弟子`, `清雪`).
- `*_vi` — bản Việt hoá do AI đề xuất (`sư phụ`, `đồ nhi`, `Thanh Tuyết`).

Ba lý do bắt buộc tách:

1. Người duyệt nhìn `raw` là biết ngay AI có bịa hay không.
2. Đổi phong cách dịch về sau (`姑娘` từ "cô nương" sang "cô") vẫn còn `raw` để
   map lại hàng loạt, không phải đọc lại truyện.
3. Với truyện đô thị chỉ có `你/我/他/她`, `raw` sẽ rỗng — và chính sự rỗng đó
   là tín hiệu cho biết đây là suy luận, không phải trích dẫn.

`raw` KHÔNG bao giờ được chèn vào prompt dịch. Prompt chỉ dùng `*_vi`. `raw`
tồn tại cho người duyệt và cho việc map lại sau này.

## 4. Bằng chứng và độ tin cậy

Mỗi quan hệ mang thêm ba trường:

- `evidence` — câu Hán ngắn làm căn cứ, tối đa 200 ký tự (cắt bớt nếu dài hơn).
  Giữ ngắn để hàng chờ không phình.
- `inferred` — `true` khi kết luận đến từ ngữ cảnh chứ không từ trích dẫn trực
  tiếp.
- `confidence` — `high` | `medium` | `low`.

Hai mức khác nhau về bản chất, spec phải bắt AI phân biệt:

**Chứng cứ trực tiếp.** `师父，弟子回来了。` → Lâm Phàm gọi `师父`, tự xưng `弟子`.
`a_calls_b_raw="师父"`, `a_self_raw="弟子"`, `inferred=false`, `confidence=high`.

**Suy luận ngữ cảnh.** `苏清雪冷冷地看着他："林公子，请自重。"` — chương này
KHÔNG có lời thoại nào của Lâm Phàm, nên không có căn cứ trực tiếp cho việc hắn
gọi nàng là gì. Suy ra từ thái độ lạnh nhạt và cách nàng gọi `林公子`:
`a_calls_b_raw=null`, `a_calls_b_vi="Tô cô nương"`, `inferred=true`,
`confidence=medium`.

`confidence`/`inferred` chỉ là tín hiệu cho người duyệt. Mục đã duyệt thì vào
bảng như mọi mục khác — prompt không phân biệt.

## 5. Luật ràng buộc AI

**Luật 1 — không bịa khi thiếu căn cứ.** Đoạn chỉ có `他说："你好。"` không đủ
cơ sở kết luận bất kỳ xưng hô nào. Khi đó trả `a_calls_b_vi: null`,
`a_self_vi: null`, `confidence: "low"` — KHÔNG được đoán bừa theo thể loại.

**Luật 2 — bỏ mục rỗng.** Quan hệ có cả `a_calls_b_vi` lẫn `a_self_vi` là null
thì không đưa vào hàng chờ; nó không dùng được cho prompt và chỉ làm nhiễu bảng
duyệt. Lọc ở bước parse.

**Luật 3 — ưu tiên xưng hô đặc thù hơn đại từ chung.** `朕` → "trẫm", không phải
"ta". `为师` → "vi sư". `本座` → "bổn tọa". `妾身` → "thiếp". Chỉ lùi về đại từ
chung khi bản gốc thật sự chỉ có `我/你/他/她`.

**Luật 4 — một cặp nhân vật có NHIỀU mốc.** Không được gộp cứng thành một dòng
cho cả truyện. Đây là giá trị chính của tính năng.

**Luật 5 — không đề xuất lại nhân vật đã có.** Danh sách nhân vật hiện tại được
nhét vào prompt kèm chỉ thị bỏ qua, giống `suggest_glossary`. Bản sửa tay của
người dùng không bao giờ bị động tới.

**Ngoại lệ của luật 5 — `update_only`.** Nếu nhân vật đã có nhưng AI phát hiện
alias MỚI, được phép đề xuất dạng:

```json
{"source": "林凡", "update_only": true,
 "new_aliases_raw": ["凡儿", "林公子"],
 "new_aliases_vi": ["Phàm nhi", "Lâm công tử"]}
```

Duyệt mục `update_only` chỉ **nối thêm** alias, không đụng tới trường nào khác.
Đây là tinh chỉnh của quyết định "bỏ qua hoàn toàn nhân vật đã có": bỏ qua việc
đề xuất lại, nhưng không bỏ qua alias mới.

## 6. Thay đổi schema (v5 → v6)

A đã merge với schema v5. Các trường mới là cột thật, cần migration.

**`characters`** — thêm một cột:

```sql
aliases_vi TEXT NOT NULL DEFAULT ''    -- '|'-sep, bản Việt của aliases
```

Cột `aliases` sẵn có GIỮ NGUYÊN ý nghĩa: alias dạng chữ Hán gốc. Đây chính là
thứ `characters.filter_for_text` đang khớp với text nguồn, nên không được đổi.
`aliases_vi` là bản hiển thị, và mở đường xử lý một tồn đọng đã ghi nhận ở
review tổng của A: trên đường export bản `translated`, lọc nhân vật khớp chữ Hán
với nội dung tiếng Việt nên gần như không nhân vật nào match. Có `aliases_vi` +
`target` thì khớp được. **Việc dùng nó cho đường export KHÔNG thuộc B** — B chỉ
tạo và điền cột; đổi logic lọc là spec riêng.

**`character_relations`** — thêm năm cột:

```sql
to_chapter    INTEGER,                      -- NULL = chưa chấm dứt
a_calls_b_raw TEXT NOT NULL DEFAULT '',
a_self_raw    TEXT NOT NULL DEFAULT '',
evidence      TEXT NOT NULL DEFAULT '',
inferred      INTEGER NOT NULL DEFAULT 0,
confidence    TEXT NOT NULL DEFAULT ''
```

Cột `a_calls_b` và `a_self` sẵn có GIỮ NGUYÊN TÊN và mang giá trị **tiếng Việt**
— chúng vốn đã là bản Việt hoá. JSON của AI dùng hậu tố `_vi`; ánh xạ sang tên
cột thực hiện ở bước nạp. Đổi tên cột sẽ phải sửa `storage.py`,
`characters.py`, `app/routes/characters.py`, `characters.html` và bộ test của A
mà không được gì về ngữ nghĩa.

`SCHEMA_VERSION` 5 → 6. Cột mới khai ở HAI nơi, đúng cơ chế sẵn có của dự án:
trong `CREATE TABLE` (cho DB tạo mới) và trong danh sách `_ADDED_COLUMNS`
(`db.py:230`), nơi `_ensure_columns` vá bằng `ALTER TABLE` cho DB cũ —
`CREATE TABLE IF NOT EXISTS` không thêm cột vào bảng đã tồn tại. Bỏ sót nửa sau
thì DB v5 hiện có của người dùng sẽ thiếu cột và vỡ khi đọc.

## 7. `to_chapter`: ngữ nghĩa và lý do để trống

Một mốc có hiệu lực khi `from_chapter <= N` VÀ (`to_chapter` rỗng HOẶC
`N <= to_chapter`). Trong các mốc hợp lệ, chọn mốc có `from_chapter` lớn nhất.

`to_chapter` **để trống là mặc định** và có nghĩa "còn hiệu lực tới mốc kế tiếp,
hoặc mãi mãi nếu không có mốc nào sau".

**Không bao giờ điền `to_chapter` chỉ để lặp lại ranh giới của mốc kế tiếp.**
Giá trị đó suy ra được từ mốc sau, nên lưu cả hai là dữ liệu thừa có thể mâu
thuẫn: sửa `from_chapter` của mốc sau mà quên sửa `to_chapter` của mốc trước là
lập tức tạo khoảng hở hoặc chồng lấn, và không có gì báo lỗi.

Chỉ điền khi quan hệ **chấm dứt mà không có mốc kế tiếp** — nhân vật chết, sư đồ
đoạn tuyệt, nhân vật rời truyện. Đây là ca mà `from_chapter` một mình không diễn
đạt được: mốc cuối cùng sẽ kéo dài vô tận.

AI chỉ được điền `to_chapter` khi có căn cứ rõ ràng về việc chấm dứt. Mặc định
là `null`.

`characters.resolve_relations` phải sửa để tôn trọng `to_chapter`. Đây là thay
đổi hành vi trên code đã merge — cần test cho cả ca cũ (không có `to_chapter`,
hành vi phải y hệt trước) lẫn ca mới.

## 8. Luật xung đột — thuộc bước GỘP, không thuộc DB

Hai nhóm chương khác nhau có thể cùng trả về một cặp `(a, b, from_chapter)` với
nội dung khác nhau.

Điều này KHÔNG thể giải quyết ở tầng lưu: khoá chính
`(ebook_slug, a_source, b_source, from_chapter)` khiến bản thứ hai lặng lẽ ghi
đè bản thứ nhất qua `ON CONFLICT DO UPDATE`. Vì vậy luật ưu tiên phải chạy trong
`merge_extractions`, trước khi vào hàng chờ:

1. `confidence` cao hơn thắng (`high` > `medium` > `low`).
2. Bằng điểm: bản có `a_calls_b_raw` hoặc `a_self_raw` khác rỗng thắng (có trích
   dẫn trực tiếp).
3. Vẫn bằng: bản có `evidence` dài hơn thắng (nhiều ngữ cảnh hơn).
4. Vẫn bằng: giữ bản đầu tiên VÀ đánh dấu `conflict: true` kèm bản bị loại trong
   `conflict_with`, để UI hiện cả hai cho người dùng chọn.

Không được âm thầm chọn khi không có luật phân định. Quy tắc 4 tồn tại để bảo
đảm điều đó.

Riêng nhân vật đã nằm trong DB: mục đã duyệt luôn thắng — AI không đề xuất lại
(luật 5), nên tình huống này chỉ phát sinh với `update_only`, và ở đó thao tác
là nối thêm alias nên không có xung đột.

## 9. Kiến trúc module

| File | Trách nhiệm | Trạng thái |
|---|---|---|
| `novel2epub/characters_ai.py` | Prompt, parse JSON, gộp nhóm, chia nhóm chương | mới |
| `app/routes/characters.py` | Route hàng chờ + duyệt (nối vào file có sẵn của A) | sửa |
| `app/templates/characters.html` | Tab "Đề xuất" | sửa |
| `app/routes/chapters.py` | Nút chạy + đấu nối JobQueue | sửa |
| `novel2epub/db.py` | 6 cột mới, `SCHEMA_VERSION` 5 → 6 | sửa |
| `novel2epub/storage.py` | Đọc/ghi cột mới + hàng chờ | sửa |
| `novel2epub/characters.py` | `resolve_relations` tôn trọng `to_chapter` | sửa |

`characters_ai.py` soi gương `glossary_ai.py`: mọi thứ trừ đúng một hàm gọi mạng
đều là logic thuần, test không cần mạng.

- `EXTRACT_PROMPT` — hằng chuỗi.
- `group_chapters(chapters, max_chars)` — chia chương thành nhóm vừa ngân sách.
  Thuần.
- `format_chapters_block(group)` — render `## Chương N` + nội dung. Thuần.
- `parse_extraction(text)` — parse khoan dung (code fence, JSON lẫn prose), lọc
  mục rỗng theo luật 2, cắt `evidence` quá 200 ký tự. Thuần.
- `merge_extractions(results)` — gộp nhóm theo §8. Thuần.
- `extract_characters(ai_cfg, chapters, existing_chars, glossary, *, genre)` —
  hàm DUY NHẤT gọi mạng; điều phối bốn hàm trên.

## 10. Hàng chờ

`ebook_extra_json`, khoá `characters_pending` — cùng cơ chế `glossary_pending`
mà A đã dùng lại được từ trước.

```json
{
  "characters": [
    {"source","target","aliases_raw","aliases_vi","gender","self_pronoun",
     "narrator_ref","role_note","importance","reason","confidence",
     "update_only","new_aliases_raw","new_aliases_vi"}
  ],
  "relations": [
    {"a_source","b_source","from_chapter","to_chapter",
     "a_calls_b_raw","a_calls_b_vi","a_self_raw","a_self_vi",
     "evidence","inferred","confidence","reason","conflict","conflict_with"}
  ]
}
```

**Ánh xạ hàng chờ → cột DB khi duyệt** (JSON của AI dùng hậu tố `_raw`/`_vi`,
cột DB không):

| Trường JSON | Cột DB |
|---|---|
| `aliases_raw` | `characters.aliases` |
| `aliases_vi` | `characters.aliases_vi` |
| `a_calls_b_vi` | `character_relations.a_calls_b` |
| `a_self_vi` | `character_relations.a_self` |
| `a_calls_b_raw` | `character_relations.a_calls_b_raw` |
| `a_self_raw` | `character_relations.a_self_raw` |

Các trường chỉ phục vụ việc duyệt (`reason`, `conflict`, `conflict_with`) không
được lưu vào bảng — chúng biến mất cùng mục khỏi hàng chờ sau khi duyệt.
`evidence`, `inferred`, `confidence` thì CÓ lưu, để về sau còn truy được vì sao
một mốc xưng hô tồn tại.

Route, theo đúng khuôn ba route glossary sẵn có:

- `GET  /api/ebooks/{slug}/characters/pending`
- `POST /api/ebooks/{slug}/characters/pending/approve`
- `POST /api/ebooks/{slug}/characters/pending/clear`

**Thứ tự duyệt bắt buộc.** Duyệt nhân vật TRƯỚC, quan hệ SAU — trong cùng một
lời gọi approve. Nếu một quan hệ được tick mà đầu nào đó vừa không được tick vừa
chưa có trong bảng, trả lỗi nêu đích danh:

> Quan hệ "Lâm Phàm → Tô Thanh Tuyết" không lưu được: nhân vật 苏清雪 (Tô Thanh
> Tuyết) chưa có trong bảng và không được chọn duyệt.

Không tạo quan hệ mồ côi, không im lặng bỏ qua. Nhân vật hợp lệ vẫn được lưu;
lỗi chỉ chặn đúng những quan hệ thiếu đầu, và phản hồi liệt kê rõ cái nào bị
chặn.

## 11. Giao diện

Tab **Đề xuất** trên `/ebook/<slug>/characters`, nhãn kèm số lượng. Hai bảng con
(Nhân vật / Quan hệ), checkbox từng dòng, chọn tất cả, nút Duyệt và Bỏ.

Mỗi dòng quan hệ PHẢI hiện bằng chứng — đó là toàn bộ điểm của §4:

```
☑ Lâm Phàm → Huyền Trần Tử · từ ch.1
  gọi "sư phụ" (师父) · xưng "đồ nhi" (弟子)
  bằng chứng: 师父，弟子回来了。          [high]

☑ Lâm Phàm → Tô Thanh Tuyết · từ ch.2
  gọi "Tô cô nương" (suy luận) · xưng "tại hạ" (suy luận)
  bằng chứng: 林公子，请自重。            [medium · suy luận]
```

Mục `inferred` hiện nhãn phân biệt; `confidence: low` hiện cảnh báo. Dòng có
`conflict: true` hiện cả hai bản để người dùng chọn một.

Nút chạy đặt ở trang ebook cạnh "AI gợi ý glossary", dùng lại đúng luồng chọn
chương sẵn có.

## 12. Đấu nối job

`POST /api/ebooks/{slug}/batch/extract-characters`, nhận `indexes` dạng chuỗi
ngăn phẩy, chạy qua `request.app.state.job.start_custom(...)` với
`category="translate"` — y hệt `batch/suggest-glossary`.

Khác biệt so với route đó: **không lặp từng chương**. Job nạp toàn bộ chương đã
chọn, gọi `group_chapters`, chạy từng nhóm, gộp, rồi ghi một lần vào hàng chờ.
Log mỗi nhóm để theo dõi tiến độ.

Đầu vào mỗi nhóm: raw ZH bắt buộc; bản dịch nếu chương đã dịch (giúp tên Việt
khớp văn phong đang dùng); glossary hiện có; danh sách nhân vật đã khai;
`translate.genre` để chọn thanh xưng hô phù hợp thể loại.

## 13. Test

`tests/test_characters_ai.py` — thuần, không mạng:
- `group_chapters` tôn trọng ngân sách; một chương dài hơn ngân sách vẫn thành
  nhóm riêng chứ không bị bỏ.
- `parse_extraction`: bọc code fence; JSON lẫn prose; bỏ mục rỗng (luật 2); cắt
  `evidence` > 200 ký tự; `inferred`/`confidence` thiếu → mặc định an toàn.
- `merge_extractions`: gộp alias giữa các nhóm; giữ hai mốc khác `from_chapter`
  của cùng một cặp; bốn nhánh luật xung đột §8, gồm nhánh 4 đặt `conflict`.
- `update_only` chỉ mang alias, không mang trường khác.

`tests/test_characters.py` (bổ sung) — `resolve_relations` với `to_chapter`:
- `to_chapter` rỗng → hành vi y hệt trước (chống hồi quy cho A).
- `N > to_chapter` và không có mốc sau → không trả mốc nào.
- Mốc có `to_chapter` cùng tồn tại với mốc sau không có.

`tests/test_db_schema.py` (bổ sung) — 6 cột mới, `SCHEMA_VERSION == 6`, và DB v5
cũ được nâng cấp không mất dữ liệu.

`tests/test_routes_characters.py` (bổ sung) — hàng chờ CRUD; duyệt nhân vật
trước quan hệ; quan hệ thiếu đầu bị chặn kèm thông báo nêu tên; `update_only`
chỉ nối alias.

## 14. Ngoài phạm vi B

- Dùng `aliases_vi`/`target` để lọc nhân vật trên đường export bản `translated`
  (§6 tạo cột, không đổi logic lọc).
- Nạp lại bảng nhân vật giữa job đang chạy.
- Sub-project C: post-check thống kê phát hiện chương lệch xưng hô.
- Backend `hachimimt`/`google`/`libretranslate` — không nhận chỉ dẫn, không liên
  quan.
