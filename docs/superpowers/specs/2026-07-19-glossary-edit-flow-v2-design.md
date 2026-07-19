# Glossary edit flow v2 — thiết kế

**Ngày:** 2026-07-19 · **Trạng thái:** đã duyệt (hướng A)

## Bối cảnh & mục tiêu

Glossary hiện sửa được ở 2 nơi: trang Glossary (bảng phân trang server-side,
autosave từng mục khi blur) và trang chương (panel AI gợi ý). 3 chỗ đau đã
xác nhận với người dùng:

1. **Đang đọc chương thấy tên dịch sai** — phải rời trang chương sang trang
   Glossary để sửa.
2. **Đổi tên + đồng bộ bản dịch cũ** — modal "Áp dụng lại" nhiều bước
   (mở modal → gõ tìm/thay → Xem trước → Áp dụng).
3. **Dọn bảng lớn** (~1.7k mục) — khó phát hiện mục trùng/mâu thuẫn; xóa
   từng dòng một, mỗi dòng một confirm.

Giải pháp: MỘT pattern thống nhất **"sửa → hiện số chỗ khớp → chọn phạm vi
lan truyền"** dùng chung cho mọi nơi sửa glossary, cộng bulk delete và view
"Nghi vấn" cho bảng lớn.

## Quyết định đã chốt

- Popover bôi đen ở trang chương (không phải click-từ-tô-sáng).
- Sau khi lưu mục: hỏi + cho chọn phạm vi thay (chương này / tất cả / chỉ lưu),
  số đếm chính là preview — không có bước "Xem trước" riêng.
- **Bỏ hẳn** modal "Áp dụng lại" + 2 route `reapply-preview`, `reapply`
  (propagate thay thế). Không giữ song song.
- Tab Nghi vấn gồm đủ 3 nhóm: trùng-Việt, Hán-lồng-nhau, conflicts.
- "Thay chương này" cập nhật DOM tại chỗ (re-fetch), KHÔNG reload trang.
- Không đổi schema DB.

## 1. Backend chung

### `GET /api/ebooks/{slug}/glossary/match-count`

Query: `find` (bắt buộc, non-empty sau trim → 400 nếu rỗng),
`chapter_index` (tùy chọn).

Trả:

```json
{
  "find": "Vô Diện",
  "chapter_count": 3,        // số chỗ trong chương chapter_index (0 nếu không truyền)
  "total_count": 47,          // tổng số chỗ trong mọi chương đã dịch
  "chapter_total": 12         // số chương đã dịch có chứa chuỗi
}
```

Quét `translated/` qua helper `_reapply_chapters` hiện có (đổi tên thành
`_matching_chapters` cho trung lập). Không ghi gì.

### `POST /api/ebooks/{slug}/glossary/propagate`

Form: `find`, `replace` (cả hai bắt buộc, trim), `scope` = `chapter` | `all`,
`chapter_index` (bắt buộc khi scope=chapter).

- `scope=chapter`: thay literal `find`→`replace` đồng bộ NGAY trong 1 chương —
  đọc `translated/`, backup bản trước vào meta `before_find_replace` (đúng
  format `step_find_replace` đang ghi để nút khôi phục trên trang chương dùng
  được), ghi lại. Trả `{replaced: n}`.
- `scope=all`: enqueue job `step_find_replace` sẵn có (category `translate`,
  giống route `reapply` cũ). Queue bận → 409. Trả `{ok: true}`.

Lưu ý: propagate KHÔNG tự sửa mục glossary — client đã upsert qua
`POST .../glossary/entry` trước đó (route sẵn có, giữ nguyên).

### Route bị xóa

- `POST /api/ebooks/{slug}/glossary/reapply-preview`
- `POST /ebooks/{slug}/glossary/reapply`

### `GET /api/ebooks/{slug}/glossary/suspects`

Quét toàn bộ glossary trong bộ nhớ (names.txt sau consolidate; ~2k mục là
nhẹ), trả 3 nhóm:

```json
{
  "same_target": [ { "target": "Trương Tam", "entries": [{source, target, note}, ...] } ],
  "nested_source": [ { "outer": {source, target, note}, "inner": {source, target, note} } ],
  "conflicts": [ { "source": "张三", "kept": "Trương Tam", "new": "Trương Tân" } ]
}
```

- `same_target`: nhóm 2+ source có cùng target (so sánh sau trim,
  case-insensitive).
- `nested_source`: cặp mà source này là chuỗi con thực sự của source kia.
- `conflicts`: đọc qua `read_extra_json("glossary_conflicts")` — list các
  dict `{"source", "existing", "new"}` (do `translator.extend_glossary` ghi;
  entry cũ có thể mang thêm `target_file`, bỏ qua field đó). Map thẳng về
  `{source, kept: existing, new}`.

Logic gom nhóm là **hàm thuần** trong `novel2epub/` (nhận list entries, trả
dict) để test không cần DB/route.

### `POST /api/ebooks/{slug}/glossary/conflicts/resolve`

Form: `source`, `new` (khóa dedup `(source, new)` — trùng key mà pipeline
dùng khi ghi). Gỡ conflict khớp khỏi `glossary_conflicts` (extra json) rồi
ghi lại. Cả `Giữ cũ` lẫn `Lấy mới` đều gọi route này (Lấy mới upsert mục
trước, resolve sau) — để conflict không hiện lại ở lần mở tab sau và badge
đếm trên trang Glossary giảm đúng.

### `POST /api/ebooks/{slug}/glossary/entries/delete`

Body JSON `{"sources": ["张三", ...]}` → xóa từng source qua
`delete_glossary_entry` sẵn có (cả names + vietphrase legacy). Trả
`{deleted: n}`.

## 2. Trang chương — popover bôi đen

- Lắng nghe `mouseup`/`selectionchange` giới hạn trong vùng bảng so sánh
  (cột ZH raw + cột VI biên tập). Selection không rỗng (sau trim, ≤ 100 ký
  tự) → hiện nút nổi **"+ Glossary"** cạnh vùng chọn.
- Click nút → popover nhỏ (absolute, gần selection) với 3 ô: Hán / Việt /
  Ghi chú + nút Lưu, Đóng.
  - Bôi ở cột **ZH** → điền ô Hán = selection; tra glossary
    (`GET .../glossary/list?q=<selection>`) → nếu có mục source khớp chính
    xác thì điền sẵn Việt + Ghi chú (ca "sửa mục có sẵn").
  - Bôi ở cột **VI** → điền ô Việt = selection; tra ngược
    (`q=<selection>`, so target khớp chính xác) → điền sẵn Hán nếu tìm thấy.
- Bấm **Lưu** → `POST .../glossary/entry` (kèm `original_source` khi là ca
  sửa) → popover chuyển sang bước lan truyền:
  - Xác định `find` = target CŨ (nếu mục tồn tại trước đó và target đổi)
    hoặc = selection VI (mục mới, selection ở cột VI). Nếu không có chuỗi cũ
    nào để thay (mục mới từ selection ZH, target gõ tay) → bỏ qua bước này,
    chỉ toast "Đã lưu".
  - Fetch `match-count(find, chapter_index)` → hiện 3 nút:
    `Thay chương này (3)` · `Thay tất cả (47 chỗ · 12 chương)` · `Chỉ lưu`.
    Nút có số 0 thì disable.
- `Thay chương này` → `propagate(scope=chapter)` → re-fetch bản dịch qua
  `TRANSLATED_API_URL` sẵn có → cập nhật các cell VI trong DOM tại chỗ
  (giữ vị trí đọc, không reload) → toast.
- `Thay tất cả` → `propagate(scope=all)` → toast "Đã bắt đầu job, theo dõi ở
  Queue" (409 → toast lỗi).
- Esc hoặc click ngoài → đóng popover.

## 3. Trang Glossary — banner lan truyền inline

- Autosave khi blur giữ nguyên. Sau khi save thành công, nếu **target đổi**
  (client đã có `data-orig`): chèn 1 hàng banner ngay dưới dòng vừa sửa:

  > Thay "Vô Diện" → "Mặt Nạ" trong bản dịch cũ?
  > `[Tất cả (47 chỗ · 12 chương)]` `[Bỏ qua]`

  Số đếm fetch async từ `match-count` (find = target cũ); trong lúc chờ hiện
  "đang đếm…". `total_count` = 0 → không hiện banner. Không có nút "chương
  này" (không đứng trong chương nào).
- `Tất cả` → `propagate(scope=all)`; xong/lỗi → toast, gỡ banner.
- Sửa tiếp dòng khác khi banner đang mở → banner cũ tự gỡ (chỉ 1 banner
  tại 1 thời điểm).
- **Xóa**: modal "Áp dụng lại", nút "Áp dụng lại" trên từng dòng, và toàn bộ
  JS liên quan.

## 4. Trang Glossary — bulk delete

- Thêm cột checkbox đầu bảng; checkbox ở header chọn/bỏ cả trang hiện tại.
- Có ≥1 tick → hiện nút `Xóa đã chọn (N)` trên toolbar. 1 `confirm()` →
  `POST .../glossary/entries/delete` → `loadPage()` lại trang hiện tại →
  toast "Đã xóa N mục".
- Nút Xóa từng dòng giữ nguyên (vẫn tiện cho 1 mục).

## 5. Trang Glossary — tab "Nghi vấn"

- Toggle 2 nút trên toolbar: `Tất cả` | `Nghi vấn (n)` (n = tổng nhóm, fetch
  lười khi bấm lần đầu).
- View Nghi vấn thay vùng bảng bằng danh sách nhóm:
  - **Trùng Việt**: mỗi nhóm 1 khung — target chung làm tiêu đề, các dòng
    member render đúng kiểu dòng bảng chính (sửa inline + autosave + checkbox
    + xóa hoạt động y hệt).
  - **Hán lồng nhau**: mỗi cặp 1 khung 2 dòng (outer/inner), cùng khả năng
    sửa/tick/xóa.
  - **Conflicts**: mỗi conflict 1 dòng `source · giữ "X" · AI đề xuất "Y"` +
    2 nút `Giữ cũ` / `Lấy mới`. Cả hai gọi `conflicts/resolve` để gỡ hẳn
    khỏi file (không hiện lại lần sau); `Lấy mới` upsert target=Y trước rồi
    hiện banner lan truyền như mục 3.
- Search/sort/phân trang chỉ áp dụng cho view Tất cả; view Nghi vấn hiển thị
  trọn (số nhóm thực tế nhỏ).

## Lỗi & edge case

- `find` rỗng → 400. `scope=chapter` thiếu `chapter_index` hoặc chương chưa
  dịch → 400/404.
- Propagate all khi queue bận → 409, client toast detail.
- Selection rỗng/quá dài (>100 ký tự) → không hiện nút nổi.
- Mất mạng ở bất kỳ bước nào → toast "Lỗi kết nối mạng", không thay đổi UI
  dở dang.

## Test

- **Thuần** (không DB): hàm gom suspects (same_target case-insensitive,
  nested_source, conflicts mapping); hàm thay 1 chương (backup meta đúng
  format `before_find_replace`).
- **Route** (pytest + TestClient theo pattern tests/ hiện có): match-count
  đếm đúng; propagate chapter ghi file + meta; propagate all enqueue job;
  entries/delete xóa nhiều source; suspects trả đủ 3 nhóm; conflicts/resolve
  gỡ đúng key `(source, new)`; 2 route reapply cũ đã gỡ (404).

## Ngoài phạm vi

- Keyboard nav kiểu spreadsheet, virtual scroll, wizard gộp trùng tự động.
- Không đổi schema DB, không đổi format meta chương.
