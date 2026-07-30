# Bảng nhân vật & ngôi xưng (sub-project A)

Ngày: 2026-07-30

## 1. Vấn đề

Prompt dịch hiện tại (`config.DEFAULT_PROMPT`, luật 2) yêu cầu chọn ngôi xưng
"theo quan hệ và ngữ cảnh", nhưng model không hề nhận được thông tin quan hệ.
Tiếng Trung chỉ có 我/你/他/她; tiếng Việt cần biết giới tính, vai vế, độ thân
sơ và **giai đoạn** quan hệ — không thứ nào nằm trong văn bản chunk.

Bốn dạng lỗi được xác nhận đang xảy ra:

1. **Không nhất quán giữa các chương** — cùng một quan hệ, chương này "sư phụ /
   đồ nhi", chương kia "ông ta / tôi".
2. **Sai vai vế ngay trong một chương** — đồ đệ xưng "ta" với sư phụ.
3. **Ta/ngươi sai thể loại** — đô thị hiện đại ra giọng cổ trang và ngược lại.
4. **Nhầm người / nhầm giới tính** — alias (林凡 / 凡儿 / 林少爷) bị xử lý như ba
   nhân vật khác nhau.

Nguyên nhân trong code:

- `glossary_entries` chỉ là `source|target|note|position` phẳng — không mang
  giới tính, vai vế, hay alias. Ba alias của một người là ba dòng rời rạc.
- `translator._build_prompt(text)` không nhận context nào ngoài chunk hiện tại,
  cũng không biết đang ở chương số mấy.
- `TranslationStyleConfig.pronoun_policy` mặc định là chuỗi `"contextual"` và
  được `.replace()` nguyên văn vào prompt — model đọc được đúng một từ vô nghĩa.
- Luật 2 của `DEFAULT_PROMPT` ghi `"KHÔNG bê nguyên ta/ngươi"` như luật cứng
  toàn cục. Với tiên hiệp/cổ trang đây là chỉ dẫn **sai**, đang chủ động đẩy
  model đi nhầm hướng (nguyên nhân trực tiếp của dạng lỗi 3).

## 2. Phạm vi

**Thuộc sub-project A (spec này):**

- Hai bảng SQLite `characters` + `character_relations` (per-ebook).
- Module logic thuần `novel2epub/characters.py`.
- Module logic thuần `novel2epub/genre.py` (preset xưng hô theo thể loại).
- Đấu nối vào prompt dịch API (`translator.py`) và vào Xuất RAW
  (`bulk_transfer.py`).
- Sửa `DEFAULT_PROMPT`: luật 2 và khối phân tầng lời nói.
- Trang web CRUD `/ebook/<slug>/characters` + dropdown Thể loại ở Settings→Dịch.

**KHÔNG thuộc phạm vi A** (mỗi cái một spec riêng sau này):

- **Sub-project B** — AI trích nhân vật & quan hệ tự động → hàng chờ duyệt.
  Phụ thuộc A (cần schema để đổ vào).
- **Sub-project C** — post-check thống kê phát hiện chương lệch xưng hô, đổ vào
  tab Nghi vấn. Phụ thuộc A (cần bảng làm baseline).
- Import/export dạng text cho `characters` — đường nhập chính sẽ là B, viết
  parser text bây giờ là công thừa.
- Cột `category` cho `glossary_entries` — hữu ích nhưng độc lập, không thuộc A.

## 3. Kiến trúc module

Bám nếp có sẵn của dự án: logic thuần tách hẳn khỏi I/O, mỗi module một file
test.

| File | Trách nhiệm | Trạng thái |
|---|---|---|
| `novel2epub/characters.py` | **Thuần.** Dataclass + lọc + resolve mốc + render khối prompt | mới |
| `novel2epub/genre.py` | **Thuần.** `GENRE_PRESETS` + render luật xưng hô | mới |
| `app/routes/characters.py` | CRUD web per-ebook | mới |
| `app/templates/characters.html` | Giao diện bảng | mới |
| `novel2epub/db.py` | 2 bảng mới, `SCHEMA_VERSION` 4 → 5 | sửa |
| `novel2epub/config_writer.py` | gỡ `genre` khỏi danh sách deprecated (§7) | sửa |
| `novel2epub/storage.py` | `read/write/upsert/delete_character*` + relations | sửa |
| `novel2epub/translator.py` | Nạp + chèn khối, kwarg `chapter_idx` | sửa |
| `novel2epub/pipeline.py` | Truyền `chapter_idx` xuống translator | sửa |
| `novel2epub/bulk_transfer.py` | Chèn khối vào export, vá `{idioms}` rò | sửa |
| `novel2epub/config.py` | `TranslateConfig.genre` mặc định `"auto"`, sửa `DEFAULT_PROMPT` | sửa |

`characters.py` và `genre.py` soi gương `idioms.py` / `glossary_review.py`:
không import `Storage`, không đụng filesystem, test chạy không cần DB.

## 4. Schema

Dùng tên cột `source` / `target` giống `glossary_entries` để nguồn tiếng Anh
(`EN_DEFAULT_PROMPT`) cũng dùng được bảng này, không chỉ nguồn Hán.

```sql
CREATE TABLE IF NOT EXISTS characters (
    ebook_slug   TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
    source       TEXT NOT NULL,                    -- 林凡
    target       TEXT NOT NULL DEFAULT '',         -- Lâm Phàm
    aliases      TEXT NOT NULL DEFAULT '',         -- '|'-sep: 凡儿|林少爷|Phàm Nhi
    gender       TEXT NOT NULL DEFAULT '',         -- 'nam' | 'nu' | ''
    self_pronoun TEXT NOT NULL DEFAULT '',         -- ta / tôi / tại hạ / bổn tọa
    narrator_ref TEXT NOT NULL DEFAULT '',         -- hắn / anh / gã / nàng / cô
    role_note    TEXT NOT NULL DEFAULT '',         -- văn xuôi tự do
    importance   TEXT NOT NULL DEFAULT 'side',     -- 'main' | 'side'
    position     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ebook_slug, source)
) WITHOUT ROWID
```

```sql
CREATE TABLE IF NOT EXISTS character_relations (
    ebook_slug   TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
    a_source     TEXT NOT NULL,                    -- tên gốc nhân vật A
    b_source     TEXT NOT NULL,                    -- tên gốc nhân vật B
    from_chapter INTEGER NOT NULL DEFAULT 0,       -- 0 = từ đầu truyện
    a_calls_b    TEXT NOT NULL DEFAULT '',         -- "sư phụ" / "em"
    a_self       TEXT NOT NULL DEFAULT '',         -- "đồ nhi" / "anh"
    note         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (ebook_slug, a_source, b_source, from_chapter)
) WITHOUT ROWID
```

Ba quyết định cần nêu rõ:

**Quan hệ có hướng.** `(A,B)` tách khỏi `(B,A)`. Bắt buộc: đồ đệ gọi sư phụ
khác hẳn chiều ngược lại. Ghi cả hai chiều là việc của người nhập/AI, không tự
suy ra.

**`from_chapter` nằm trong khoá chính** → cùng một cặp có nhiều mốc. Đây là
thứ duy nhất trong thiết kế thật sự cần cấu trúc chặt, vì LLM không có cách nào
đoán được thời điểm quan hệ chuyển giai đoạn.

**`role_note` cố ý không có schema.** Không enum vai vế, không rank. Lý do: vai
vế trong truyện Trung không phải thuộc tính tuyệt đối của một người (A là sư
phụ của B đồng thời là đồ đệ của C và huynh của D), nên mọi enum đơn trường đều
sai; còn mã hoá đúng thì phải thành đồ thị nhiều nhóm — phức tạp ngang bảng cặp
N² mà lại vòng vo hơn. LLM đọc văn xuôi `"đồ đệ của Huyền Trần Tử, huynh của
Lâm Nhi"` chính xác hơn bất kỳ cấu trúc nào ép được, và người dùng gõ nhanh hơn.

**Xoá nhân vật kéo theo relations.** Không dùng FK ghép khoá tới `characters`;
dọn tường minh ở tầng `storage` khi `delete_character`.

## 5. `novel2epub/characters.py` — logic thuần

```python
@dataclass(frozen=True)
class Character:
    source: str
    target: str
    aliases: tuple[str, ...] = ()
    gender: str = ""
    self_pronoun: str = ""
    narrator_ref: str = ""
    role_note: str = ""
    importance: str = "side"

@dataclass(frozen=True)
class Relation:
    a_source: str
    b_source: str
    from_chapter: int = 0
    a_calls_b: str = ""
    a_self: str = ""
    note: str = ""
```

**`characters_from_rows(rows)` / `relations_from_rows(rows)`** — dựng từ row DB,
bỏ row thiếu `source` (hoặc thiếu `a_source`/`b_source`). Đối xứng
`idioms.idioms_from_rows`.

**`filter_for_text(chars, text, *, source_language="zh")`** — giữ nhân vật khi:

- `importance == "main"` → **luôn** giữ, kể cả không xuất hiện trong text; hoặc
- `source` hoặc bất kỳ alias nào xuất hiện trong text.

Khớp substring với `source_language="zh"` (chữ Hán không có ranh giới từ, giống
`idioms.filter_for_text`); khớp theo ranh giới từ với nguồn Latin để "Lin"
không trúng "Linda".

Luật "main luôn giữ" xử lý ca thật và hay gặp: cả chunk chỉ có "他… 他…" không
nêu tên lần nào, không match được gì, và thế là mất đúng `narrator_ref` cần
nhất. Main thường ≤ 8 người nên chi phí token nhỏ.

**`resolve_relations(relations, chapter_idx)`** — với mỗi cặp `(a,b)`, chọn row
có `from_chapter <= chapter_idx` lớn nhất; không row nào thoả → bỏ cặp đó.
`chapter_idx is None` → chỉ lấy `from_chapter == 0`. Chọn mốc 0 khi không biết
số chương là có chủ đích: đoán "quan hệ chưa thân" gây hại ít hơn đoán ngược
lại.

**`format_llm_block(chars, relations)`** — trả `""` khi rỗng để placeholder biến
mất sạch (như `idioms.format_llm_block`). Dòng quan hệ chỉ render khi **cả hai**
nhân vật đều nằm trong `chars` đã lọc; tên hiển thị của nhân vật B tra ngược từ
chính `chars` (`source` → `target`), không cần tham số phụ.

```
BẢNG NHÂN VẬT & NGÔI XƯNG (bắt buộc, không tự ý đổi):
林凡 = Lâm Phàm (còn gọi: 凡儿 Phàm Nhi, 林少爷 Lâm thiếu gia) · nam
  · tự xưng "ta" · lời kể gọi "hắn"
  · đồ đệ của Huyền Trần Tử, huynh của Lâm Nhi
  · với Tô Thanh Tuyết: gọi "em", tự xưng "anh"
```

**`format_pin_line(chars, genre_forbidden)`** — dòng nhắc ngắn nối vào **cuối**
prompt (sau `{text}`), tối đa 2 dòng, chỉ nhân vật `main` có mặt:

```
NHẮC LẠI: Lâm Phàm = tự xưng "ta", lời kể "hắn". Tô Thanh Tuyết = "nàng".
CẤM dùng anh/em/cậu/bạn.
```

Lý do đặt sau `{text}`: chỉ dẫn cuối prompt được tuân thủ tốt hơn chỉ dẫn ở
giữa. Hiện `KIỂM TRA CUỐI` của `DEFAULT_PROMPT` đang nằm giữa prompt, phía sau
nó còn `{glossary}`, `{idioms}`, `{text}`.

## 6. `novel2epub/genre.py` — preset thể loại

```python
@dataclass(frozen=True)
class GenrePreset:
    key: str
    label: str
    use_words: str        # danh sách từ NÊN dùng
    forbid_words: str     # danh sách từ CẤM
    han_viet_hint: str
    extra_rules: tuple[str, ...] = ()
```

Sáu giá trị: `auto` (mặc định — không ép luật, giữ nguyên hành vi hiện tại),
`xianxia`, `urban`, `romance`, `system_game`, `western`.

Nội dung chính từng preset:

- **`xianxia`** (tiên hiệp / huyền huyễn / cổ trang) — dùng: ta, ngươi, hắn, y,
  gã, nàng, tại hạ, bổn tọa, lão phu, thiếp, tiểu nữ, đạo hữu, tiền bối, vãn
  bối, sư phụ/sư huynh/sư tỷ/sư đệ/sư muội. Cấm: tôi, cậu, bạn, anh ấy, cô ấy.
  Lời kể dùng hắn/y/gã (nam), nàng (nữ) — **không** dùng anh/cô ấy. Hán Việt
  cao. Luật riêng: đơn vị đo cổ (里/丈/尺/两/更/时辰) giữ hệ cổ — dặm, trượng,
  thước, lượng, canh, canh giờ.
- **`urban`** (đô thị / hiện đại) — dùng: tôi, cậu, anh, chị, em, ông, bà, nó,
  tao, mày. Cấm: ta, ngươi, hắn, nàng, chàng, tiểu tử, tại hạ. Hán Việt thấp:
  `心动` → "tim đập loạn", không "tâm động". Xưng hô gia đình và công sở theo
  đúng thứ bậc.
- **`romance`** (ngôn tình / đam mỹ) — như `urban`, nhấn: xưng hô **đổi theo
  tiến triển quan hệ**, tuân thủ mốc `from_chapter` trong bảng nhân vật; ưu
  tiên câu mềm, nhiều nội tâm.
- **`system_game`** (võng du / hệ thống / vô hạn lưu) — khối thông báo hệ thống
  giữ nguyên cấu trúc ngoặc, chuẩn hoá `【】` → `[ ]`, **không đổi số liệu**.
  Giọng hệ thống: "Ký chủ" / "Người chơi", máy móc, không cảm xúc. Thuật ngữ
  game giữ nguyên hoặc thuần Việt nhất quán (HP, MP, buff, kỹ năng).
- **`western`** (khoa huyễn / dị giới Tây phương) — tên riêng dạng Latin, chức
  danh Tây (bá tước, hiệp sĩ, pháp sư), thuật ngữ kỹ thuật **không** Hán Việt
  hoá (`基因` → gen, không "cơ nhân"). Cấm giọng cổ trang.

### 6.1. Va chạm với `hachimimt/honorific_normalize.py`

Nhánh MT **đã có** một lớp chuẩn hoá xưng hô độc lập: `HONORIFIC_MAP` ánh xạ
`drift → hv` trên bản dịch VI (`anh ấy` → `hắn`, `chị` → `tỷ`), ba chế độ
`off` / `safe` / `xianxia_strict`, cộng `is_classical(zh)` tự đoán cổ trang hay
hiện đại từ `WUXIA_SIGNALS` / `MODERN_SIGNALS`.

Hai hệ quả bắt buộc phải xử lý, nếu không hai lớp sẽ đánh nhau:

**Xung đột thật.** Tầng `pronoun` của `normalize_honorifics` tự khoá khi
`is_classical()` sai, nhưng tầng `kinship` thì **không** — với `genre="urban"`,
`chị` vẫn bị viết lại thành `tỷ` dù preset đô thị cấm giọng cổ trang. Preset
thể loại phải điều khiển luôn chế độ honorific: `xianxia` → `xianxia_strict`,
`auto` → giữ hành vi hiện tại, `urban` / `romance` / `western` / `system_game`
→ `off`. Người dùng đặt tay chế độ honorific thì tôn trọng lựa chọn đó.

**Tái sử dụng thay vì viết lại.** `genre="auto"` không tự phát minh cách đoán
thể loại — gọi thẳng `honorific_normalize.genre_score()` / `is_classical()`.
Chúng đã có sẵn danh sách tín hiệu và đã được dùng thật trong nhánh MT.

Lưu ý đặt tên: `hachimimt/postprocess_policy.py` đã có `classify_genre()` cho
mục đích khác (chính sách hậu xử lý MT). Module mới tên `novel2epub/genre.py`,
không nhập nhằng, nhưng khi đọc code cần phân biệt hai thứ.

### 6.2. API

**`format_pronoun_rules(genre, user_policy="")`** — render preset thành text,
nối thêm `user_policy` nếu người dùng đặt khác giá trị mặc định `"contextual"`.
`auto` trả chuỗi trung tính như hiện tại.

Ngoài ra `genre.py` giữ `format_style_value(field, value)` — map các enum style
(`tone`, `han_viet_level`, `title_mode`) sang câu mô tả đầy đủ trước khi
`.replace()` vào prompt, thay vì rò chuỗi enum trần (`"balanced"`, `"creative"`)
tới model.

## 7. Đấu nối vào luồng dịch

**Config — hồi sinh `translate.genre`, không tạo field mới.**

`TranslateConfig.genre` **đã tồn tại** (`config.py:328`) nhưng đang bị coi là
deprecated: `config_writer.py:26` liệt nó trong danh sách field bị loại khi ghi,
và `openspec/changes/sources-shared-config/design.md:113` ghi lý do deprecate
đúng một dòng — *"Không có UI"*.

Spec này chính là phần cấp UI cho nó. Vì vậy: **gỡ `genre` khỏi danh sách
deprecated trong `config_writer.py`**, đổi mặc định `""` → `"auto"`, và dùng lại
field sẵn có.

Cân nhắc đã bác bỏ: thêm `TranslationStyleConfig.genre` như field mới. Làm vậy
sẽ có hai đường dẫn cùng tên `genre` trong một cây config (`translate.genre`
deprecated + `translate.style.genre` sống), một cái bị `config_writer` âm thầm
nuốt khi ghi — đây là loại bẫy tốn hàng giờ để tìm ra. Một field, một chỗ.

Việc gỡ khỏi danh sách deprecated đảo một quyết định đã ghi trong openspec, nên
cần được xác nhận khi review spec chứ không làm lặng lẽ.

**Nạp dữ liệu.** `translator.py` thêm `load_characters(cfg, storage)` +
`load_relations(cfg, storage)` đối xứng `load_idioms_list`; trả `[]` khi
`storage is None`.

**Kwarg mới.** `Translator.translate(...)` thêm `chapter_idx: int | None = None`
(tùy chọn, tương thích ngược). `pipeline.py` truyền số chương thật xuống. Đây
là thay đổi xâm lấn duy nhất của spec.

**Chèn vào prompt.** Trong `_build_prompt`:

1. `chars = filter_for_text(self.characters, text, source_language=cfg.source_language)`
2. `rels = resolve_relations(self.relations, chapter_idx)`
3. `.replace("{characters}", format_llm_block(chars, rels))`
4. `.replace("{pronoun_policy}", format_pronoun_rules(cfg.genre, style.pronoun_policy))`
5. sau khi build xong, **nối** `format_pin_line(...)` vào cuối chuỗi prompt.

Vị trí `{characters}` trong `DEFAULT_PROMPT`: ngay sau `{idioms}`, trước
`--- Nội dung cần dịch ---`.

**Back-compat với template đã pin.** Prompt người dùng tự sửa/autosave sẽ không
có `{characters}`; `.replace()` khi đó là no-op và bảng nhân vật im lặng vô tác
dụng. Xử lý: nếu template thiếu `{characters}`, chèn khối ngay trước `{text}`
(đúng chỗ mong muốn về mặt recency) và ghi log một lần. Dòng ghim thì luôn nối
bằng code, không qua placeholder, nên chạy được với mọi template.

Đấu nối `{pronoun_policy}` cố ý **không** đổi template — preset thể loại đi qua
placeholder đã tồn tại, nên prompt pin cũ vẫn nhận luật mới ngay.

**Ngân sách chunk.** `_shrink_budget` (translator.py:546) hiện tính template +
glossary khi thu nhỏ budget nội dung. Phải cộng thêm độ dài khối characters,
bỏ sót sẽ tràn prompt ở chương đông nhân vật.

## 8. Đấu nối vào Xuất RAW (`bulk_transfer.py`)

Người dùng preview và dùng file export để dịch tay qua web chat, nên khối nhân
vật phải có mặt ở đó, nếu không bản dịch tay sẽ lệch xưng hô so với bản dịch
API.

- `build_export(items, *, glossary=None, characters="", prompt=EDIT_PROMPT)` —
  thêm tham số `characters` (khối đã render sẵn), chèn ngay sau khối glossary,
  bỏ qua nếu rỗng. Cả `POST .../batch/export` (preview thủ công) và
  `POST .../batch/translate` (job tự động) đều đi qua hàm này nên preview luôn
  khớp đúng thứ job gửi — tính chất này phải giữ nguyên.
- Một lô export trải nhiều chương, nên không có một `chapter_idx` duy nhất.
  Route (`app/routes/chapters.py`) render khối trước khi gọi `build_export`,
  dùng **index nhỏ nhất trong lô** làm mốc `resolve_relations` (giữ trạng thái
  quan hệ ở đầu lô — an toàn hơn lấy mốc cuối), và lọc `filter_for_text` trên
  **toàn bộ raw của lô nối lại**, cộng các nhân vật `main` theo luật §5. Nếu lô
  vắt qua một mốc `from_chapter`, người dùng thấy trạng thái đầu lô; chia lô nhỏ
  hơn quanh mốc là cách xử lý, không tự động tách.
- `build_translate_prompt_from_cfg(cfg)` — bổ sung
  `.replace("{pronoun_policy}", genre.format_pronoun_rules(...))` để prompt xuất
  ra khớp prompt API.
- **Vá lỗi sẵn có:** hàm này hiện không xử lý `{idioms}`, nên placeholder rò
  nguyên văn vào file export. Thêm `.replace("{idioms}", "")` cùng
  `.replace("{characters}", "")` (khối được `build_export` gắn riêng bên dưới,
  giống cách glossary đang làm).

## 9. Sửa `DEFAULT_PROMPT`

**Luật 2** — bỏ vế `"KHÔNG bê nguyên ta/ngươi"`. Vế này sai với cổ trang và là
nguyên nhân trực tiếp của dạng lỗi 3; nó chuyển xuống preset `urban` /
`romance`, nơi nó đúng. Luật 2 thành:

> Ngôi xưng theo quan hệ và ngữ cảnh — tuân thủ BẢNG NHÂN VẬT và quy tắc xưng
> hô bên dưới.

**Thêm khối phân tầng** (4 dòng, dùng chung mọi thể loại, đặt cạnh luật 2):

```
- [LỜI KỂ] ngôi 3 nhất quán theo bảng nhân vật.
- [THOẠI] ngôi xưng theo quan hệ người nói ↔ người nghe, độc lập với lời kể.
- [NỘI TÂM] dùng cách nhân vật tự gọi mình.
- [HỆ THỐNG] giọng máy, xưng "Ký chủ"/"Người chơi", không cảm xúc.
```

Áp cùng thay đổi cho `EN_DEFAULT_PROMPT` (thêm `{characters}`, sửa luật tương
ứng) để nguồn tiếng Anh không bị bỏ lại.

`presets/go.py` (`GO_PROMPT`) cũng thêm `{characters}`; nếu không, ebook dùng
preset `go` sẽ rơi vào nhánh back-compat ở §7 — vẫn chạy nhưng vị trí khối kém
tối ưu hơn.

## 10. Web UI

**Trang `/ebook/<slug>/characters`** — per-slug, đúng khuôn trang `/glossary`
(route `app/routes/characters.py`, template `characters.html`), có link vào từ
trang ebook cạnh Glossary.

Bảng chính: Tên gốc · Tên Việt · Alias · Giới · Tự xưng · Lời kể gọi · Vai trò ·
⭐main · thao tác. Bulk delete + chọn nhiều như trang Glossary.

Quan hệ **không** làm cột riêng (bảng chính đã 8 cột) mà mở trong hàng con
`<details>` theo từng nhân vật, mỗi dòng: `→ Tô Thanh Tuyết | từ ch.120 | gọi
"em" | xưng "anh"`, kèm nút thêm/xoá.

Lưu ý kỹ thuật: Pico CSS v2 bắt buộc bọc nội dung `<dialog>` trong `<article>`,
nếu không sẽ render thành khung trắng full-viewport.

**Settings→Dịch** thêm dropdown **Thể loại** (6 giá trị của `genre.py`), lưu
per-ebook.

## 11. Migration

Hai bảng mới dùng `CREATE TABLE IF NOT EXISTS` như phần còn lại của `db.py`, DB
cũ tự có bảng khi mở — không cần migrate dữ liệu. `SCHEMA_VERSION` ở
`db.py:14` bump 4 → 5.

## 12. Test

File mới:

**`tests/test_characters.py`** (thuần, không cần DB)
- `characters_from_rows` bỏ row thiếu `source`; parse `aliases` theo `|`.
- `filter_for_text`: khớp qua alias; nhân vật `main` được giữ dù không xuất
  hiện trong text; nguồn Latin khớp theo ranh giới từ ("Lin" không trúng
  "Linda").
- `resolve_relations`: nhiều mốc → chọn đúng mốc `<= N` lớn nhất; `None` → mốc
  0; cặp không có mốc hợp lệ → bỏ.
- `format_llm_block`: rỗng trả `""`; dòng quan hệ chỉ hiện khi cả hai nhân vật
  cùng có mặt.
- `format_pin_line`: rỗng trả `""`; chỉ liệt kê `main`.

**`tests/test_genre.py`**
- Mỗi preset có `use_words`/`forbid_words` khác rỗng; `auto` không ép luật.
- `format_pronoun_rules` nối đúng phần `user_policy` do người dùng đặt, và
  không nối khi `user_policy` còn là mặc định `"contextual"`.
- `format_style_value` map enum sang mô tả, giá trị lạ trả về nguyên văn.
- Ánh xạ genre → chế độ honorific (§6.1): `xianxia` → `xianxia_strict`,
  `urban` / `romance` / `western` / `system_game` → `off`, `auto` giữ nguyên
  hành vi cũ; chế độ do người dùng đặt tay không bị ghi đè.

**`tests/test_routes_characters.py`**
- CRUD nhân vật + quan hệ.
- Xoá nhân vật kéo theo relations liên quan.

Bổ sung vào file có sẵn:

- `tests/test_db_schema.py` — hai bảng mới, cột đầy đủ, `SCHEMA_VERSION == 5`.
- `tests/test_pipeline_translate_chunk.py` — prompt chứa khối characters;
  **template thiếu `{characters}` vẫn được chèn trước `{text}`**; dòng ghim nằm
  ở cuối prompt.
- `tests/test_bulk_transfer.py` — `build_export` chèn khối characters sau
  glossary và bỏ qua khi rỗng; `build_translate_prompt_from_cfg` không còn rò
  `{idioms}` / `{characters}`.

Ba ca dễ hỏng âm thầm nhất, phải có test: mốc `from_chapter`, fallback khi
template pin cũ thiếu placeholder, và luật "main luôn chèn".

## 13. Phương án đã cân nhắc và bác bỏ

**Bảng cặp tường minh cho mọi cặp nhân vật.** Quan hệ có hướng nên là N²: 30
nhân vật = 870 dòng. Người dùng không nhập nổi, AI trích sẽ sinh hàng loạt cặp
vô nghĩa, và prompt phình khi một chunk có 6-7 người.

**Suy dẫn ngôi xưng từ `role` + `rank` của từng nhân vật.** Gọn nhất trên giấy,
nhưng vai vế trong truyện Trung không phải thuộc tính tuyệt đối của một người —
một trường `role` đơn không mã hoá nổi. Sửa cho đúng thì phải thành đồ thị
nhiều nhóm, tức quay lại độ phức tạp của phương án trên bằng đường vòng.

**Tách glossary thành 4 khối prompt riêng** (`names` / `terms` / `slang` /
`override`). Đi ngược refactor đã làm ở commit 16dd3e0 — dự án vừa hợp nhất
`names.txt` + `vietphrase.txt` thành một danh sách phẳng có chủ đích. Nếu cần
phân loại thì đúng cách là thêm **cột** `category` (lọc được, không phân mảnh
template), và đó là việc độc lập với spec này. Ngoài ra các ví dụ "override"
điển hình (老六, 社死, 内卷, 摆烂) thực chất là idiom — bảng `idioms` đã xử lý.

**Cột "mức độ thoát ý" cho idioms.** Nhãn chỉ mô tả kết quả đã nằm sẵn trong
`natural`; model không cần được bảo đó là loại thoát nào, và đường MT
(`literals` / `protect`) không đọc nhãn được. Tốn công nhập, không đổi đầu ra.

**Tóm tắt chương trước bằng AI (`prev_chapter_summary`).** Đúng vấn đề, sai
giải pháp: thêm một lời gọi LLM cho mỗi chương (+10–15% chi phí) và có thể bịa,
trong khi mục tiêu là giữ ngôi xưng chứ không phải mạch cốt truyện. Thay thế rẻ
và chắc hơn: mang 2–3 câu thoại cuối bản dịch VI của chương trước sang nguyên
văn làm mẫu chỉ-đọc — không tốn lời gọi, không bịa được, và *cho model xem*
cách xưng hô thay vì *mô tả*. Ghi nhận cho sub-project tương lai, không thuộc A.

**Khối `TONE_PER_SCENE` tĩnh trong prompt dịch.** Model không biết chunk là
cảnh gì cho tới khi đọc xong; đưa cả bốn kiểu cảnh vào mọi request chủ yếu là
nhiễu. Chỗ đúng của nó là pass AI biên tập, nơi gán nhãn được cho từng chương.

**Self-check nhiều bước trong prompt.** Các bước kiểu "đọc to trong đầu" không
phải thao tác LLM thực hiện được. Các bước kiểm tra được bằng máy ("của" thừa,
"một cái" thừa) thì nên là regex hậu kỳ — xác định, miễn phí, đúng khuôn
`han_cleanup.py` — chứ không giao cho model. Thuộc sub-project C.
