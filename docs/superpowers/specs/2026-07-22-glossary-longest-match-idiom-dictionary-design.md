# Thiết kế: Glossary longest-match + Từ điển idiom dùng chung

Ngày: 2026-07-22
Trạng thái: chờ duyệt

## Bối cảnh & mục tiêu

Nâng chất lượng dịch, ưu tiên hai đòn bẩy rẻ/hiệu quả:

- **Phần A — Glossary longest-match:** đảm bảo glossary (tên riêng, thuật ngữ)
  luôn được áp đúng, không bị chồng lấn phá hỏng tên dài.
- **Phần B — Từ điển idiom dùng chung:** kho thành ngữ/khẩu ngữ dùng chung MỌI
  ebook, giúp cả LLM lẫn MT 57M dịch idiom tự nhiên thay vì dịch từng chữ.

Ràng buộc then chốt: model MT 57M (`moxhimt`) **chỉ dịch**, không nhận
instruction — kênh mang tri thức miền duy nhất là thay-chuỗi.

## Phần A — Glossary longest-match

### Vấn đề

`novel2epub/translator.py::_apply_glossary` hiện lặp theo thứ tự insertion của
dict:

```python
def _apply_glossary(text, glossary):
    for zh, vi in glossary.items():
        if zh and vi:
            text = text.replace(zh, vi)
    return text
```

Nếu glossary chứa cả `韩 = Hàn` và `韩溯 = Hàn Tố`, khi `韩` được áp trước thì
`韩溯` bị biến thành `Hàn溯` → hỏng tên dài. Vì mọi source là tiếng Trung còn
target là tiếng Việt nên không có nhiễm chéo Việt→Trung; chỉ cần áp source dài
trước source ngắn (longest-match) là khắc phục triệt để.

### Giải pháp

Sort theo độ dài `source` giảm dần trước khi replace:

```python
def _apply_glossary(text, glossary):
    for zh, vi in sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True):
        if zh and vi:
            text = text.replace(zh, vi)
    return text
```

Nguyên tắc longest-first này dùng lại cho bước áp idiom ở Phần B.

### Test

- `test_apply_glossary_longest_match`: glossary `{"韩": "Hàn", "韩溯": "Hàn Tố"}`
  áp lên `"韩溯"` → `"Hàn Tố"` (không phải `"Hàn溯"`).
- Giữ nguyên các test hiện có (không đổi hành vi khi không chồng lấn).

## Phần B — Từ điển idiom dùng chung

### Mô hình dữ liệu

Idiom = 3 phần (khớp bảng đối chiếu trong `test.md`):

| Phần | Ví dụ | Vai trò |
|---|---|---|
| `zh` | 千方百计 | Nguồn Hán — dùng cho LLM (prompt) + protect (pre-MT) |
| `natural_vi` | Trăm phương nghìn kế | Kết quả đích cuối cùng cho cả 2 backend |
| `literal_vi` (nhiều biến thể) | Ngàn phương trăm kế | Bản MT hay ra — dùng hậu-chuẩn-hoá MT |

### Nơi lưu (tái dùng hạ tầng sẵn có)

Dùng bảng `glossary_entries` với `ebook_slug = "__global__"` (slug sentinel,
không thuộc ebook nào) và `list_name = "idioms.txt"`. Không thêm bảng DB mới,
tái dùng `Storage.read_glossary_entries` / `write_glossary_entries` /
`write_glossary_file` / `parse_glossary_line`.

Định dạng dòng (tái dùng `parse_glossary_line` → `source = target | note`):

```
千方百计 = Trăm phương nghìn kế | Ngàn phương trăm kế
一举两得 = Một mũi tên trúng hai đích | Một lần được hai lợi
势不可挡 = Thế như chẻ tre | @protect
```

- `source` = `zh`, `target` = `natural_vi`.
- `note` = danh sách `literal_vi` ngăn bằng `|` phụ (parse thêm ở tầng idiom),
  HOẶC token đặc biệt `@protect` để bật chế độ protect cho entry đó.
- Không có `note` → chỉ dùng cho LLM + protect mặc định tắt (chỉ literal rỗng =
  không hậu-chuẩn-hoá được cho MT; entry vẫn có ích cho LLM).

Một module thuần mới `novel2epub/idioms.py` chịu trách nhiệm:
- `load_idioms(storage_factory) -> list[Idiom]` đọc list global.
- `parse_idiom_note(note) -> (literals: list[str], protect: bool)`.
- `apply_idioms_llm_block(idioms, zh_text) -> str` (khối tham chiếu, đã lọc).
- `protect_source(text, idioms) -> (protected_text, restore_map)`.
- `restore_and_normalize(text, idioms, restore_map) -> str`.

Tách thuần (không đụng DB/OS) để test dễ, theo đúng phong cách các module
`glossary_review.py`, `bulk_transfer.py`.

### Áp dụng theo backend

**LLM (`OpenAITranslator`)** — idiom là *tham chiếu mềm*, không ép cứng:

- Thêm placeholder `{idioms}` vào `DEFAULT_PROMPT` / `EN_DEFAULT_PROMPT`, ngay
  trước hoặc sau `{glossary}`, dưới tiêu đề "Thành ngữ tham chiếu (dịch thoát ý
  tự nhiên, không bắt buộc nguyên văn)".
- `_build_prompt` điền `{idioms}` bằng danh sách `zh → natural_vi` đã **lọc theo
  đoạn** (chỉ idiom có `zh` xuất hiện trong chunk — giống `_filter_glossary`),
  tiết kiệm token.
- Back-compat: template cũ pin trong config không có `{idioms}` → bỏ qua an toàn
  (giống cách xử lý `{auto_glossary_block}` / `{fixup_warning}`).

**MT 57M (`HachimiMTTranslator`)** — literal chính + protect dự phòng:

- **Chế độ mặc định (literal → natural, hậu xử lý):** sau khi MT dịch xong, quét
  output VI thay `literal_vi → natural_vi` (longest-first). Tin cậy, test được,
  vì literal_vi là tiếng Việt khớp đúng output máy.
- **Chế độ protect (entry gắn `@protect`):** TRƯỚC khi đưa vào MT, thay `zh` bằng
  placeholder trung tính; sau khi MT xong, khôi phục placeholder → `natural_vi`.
  Dùng cho idiom mà bản máy quá thất thường, literal không bắt xuể.

**Vì sao tách theo entry, không chạy cả hai trên cùng một lần xuất hiện:**
nếu vừa protect (thay zh bằng placeholder ở nguồn) vừa kỳ vọng literal bắt ở
đích, mà placeholder bị model 57M nghiền thành `<unk>`, thì đích KHÔNG còn chuỗi
literal để bắt (idiom chưa từng đi qua MT dưới dạng tiếng Trung) → hỏng nặng hơn.
Nên: mỗi idiom chọn ĐÚNG MỘT chế độ. Mặc định literal (an toàn), `@protect` chỉ
bật thủ công cho idiom cứng đầu.

**Placeholder cho protect:** chuỗi hiếm gặp, ổn định qua SentencePiece, ví dụ
`" IDIOMZERO "` → không khả thi với model nhỏ. Thay vào đó dùng **số kèm ký tự
phân giới ít bị tách**: đánh giá 2 ứng viên khi implement — `〇N〇` (ký tự Hán
"linh" bao quanh số) và ` [N] `. Chốt bằng một smoke test nhỏ trên model thật
(dịch câu có placeholder, xem có sống sót). Nếu cả hai đều bị nghiền, protect
xem như best-effort: khi placeholder không khôi phục được nguyên vẹn, để literal
hậu xử lý bắt (fallback tự nhiên) và log cảnh báo. Đây là lý do literal luôn là
lớp cuối cùng chạy sau protect.

### Thứ tự áp dụng tổng thể trong `translate()`

Cho MT (`HachimiMTTranslator.translate`):

1. protect_source (chỉ idiom `@protect`) → text' đưa vào MT.
2. MT dịch text' → out.
3. `_apply_glossary(out, glossary)` (longest-first — glossary ưu tiên cao nhất).
4. restore placeholder → natural_vi.
5. normalize literal → natural (longest-first) cho idiom mặc định.

Cho LLM (`OpenAITranslator`): idiom vào prompt (bước dịch), sau dịch vẫn chạy
`_apply_glossary` như cũ; không hậu-chuẩn-hoá literal (LLM đã cho bản đẹp).

### Cấu hình

- `translate.use_idioms: bool = True` — bật/tắt toàn bộ tính năng idiom.
- Không thêm cờ per-ebook phức tạp; kho idiom là global, bật/tắt là đủ.

### UI — trang "Từ điển chung"

- Route mới `app/routes/idioms.py`, mount không gắn slug: `GET /idioms`,
  `GET /api/idioms/list` (phân trang), `POST /api/idioms/entry`,
  `.../entry/delete`, `.../entries/delete`, `POST /idioms` (import dạng text),
  `POST /api/idioms/export`. Tái dùng gần như nguyên `glossary.py` nhưng đọc/ghi
  `Storage(data_dir, "__global__")` list `idioms.txt`.
- Template mới `app/templates/idioms.html` clone từ `glossary.html`, thêm cột
  "Bản máy hay ra (literal)" và toggle "protect". Bảng 3 cột: Hán · Bản đẹp ·
  Bản máy/(protect).
- Link vào trang từ menu điều hướng chung (nơi có link Glossary/Storage).

### Seed dữ liệu

Seed sẵn 6 mục từ bảng `test.md` khi list `idioms.txt` global còn trống (chạy
một lần, idempotent — kiểm tra rỗng trước khi seed, không đè khi user đã có dữ
liệu). Nút "Nạp bộ mẫu" trên UI để nạp lại thủ công.

```
千方百计 = Trăm phương nghìn kế | Ngàn phương trăm kế
一举两得 = Một mũi tên trúng hai đích | Một lần được hai lợi
有目共睹 = Mọi người đều thấy rõ | Có mắt cùng thấy
势不可挡 = Thế như chẻ tre | Thế không thể cản
深入人心 = Ăn sâu vào lòng người | Đi sâu vào lòng người
防患未然 = Phòng ngừa từ trước | Phòng bệnh khi chưa xảy ra
```

## Kiểm thử

Module thuần `idioms.py` được test độc lập (không cần DB/model):

- `parse_idiom_note`: tách literal variants + cờ protect.
- `apply_idioms_llm_block`: lọc theo đoạn, format đúng.
- `protect_source` + `restore_and_normalize`: round-trip protect; và literal
  normalize longest-first.
- Phần A: `_apply_glossary` longest-match.
- Integration nhẹ: `HachimiMTTranslator` với MT giả (monkeypatch inner) xác nhận
  thứ tự áp dụng (glossary → restore → literal).

## Phạm vi KHÔNG bao gồm (để lần sau)

- Auto-học idiom từ cặp dịch LLM.
- Hybrid MT→LLM biên tập (ý tưởng #3).
- Prompt theo thể loại (ý tưởng #4).

## Rủi ro & giảm thiểu

- **Placeholder protect bị model nghiền:** literal là lớp fallback cuối; log
  cảnh báo khi khôi phục thất bại. Smoke test chọn placeholder tốt nhất.
- **literal_vi drift (máy ra khác biến thể):** cho nhiều biến thể/entry; UI dễ
  bổ sung; về sau auto-học.
- **Chi phí token LLM khi kho idiom lớn:** đã lọc theo đoạn, chỉ gửi idiom xuất
  hiện trong chunk.
- **`__global__` lẫn vào danh sách ebook:** đảm bảo các route liệt kê ebook lọc
  bỏ slug sentinel này.
