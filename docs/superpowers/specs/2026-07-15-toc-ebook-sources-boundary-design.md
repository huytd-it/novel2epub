# Refactor ranh giới TOC · Ebook · Sources (Change 1)

Ngày: 2026-07-15
Trạng thái: đã chốt design, chờ viết plan

## Bối cảnh

Dữ liệu crawl của một ebook đến từ ba tầng: `defaults` (settings chung) →
`source preset` (cấu hình theo site) → `ebook overrides` (riêng từng ebook).
`load_config` đã resolve đúng ba tầng này lúc load thông qua
`_resolve_source_overrides` (`novel2epub/config.py:413`): ebook chỉ lưu tên
preset ở cột `source_preset`, giá trị lấy từ preset khi load — ngữ nghĩa
**tham chiếu**.

`add_ebook` (`novel2epub/config_writer.py:154`) tuân thủ đúng: khi có
`source_name` thì KHÔNG copy field preset vào `crawl_overrides_json`.

Nhưng nhiều đường ghi khác lại vi phạm chính quy ước đó, gây ra các triệu
chứng người dùng báo: dữ liệu source và ebook ghi đè lẫn nhau không đúng, và
API lấy TOC làm hỏng metadata đã chỉnh tay.

## Vấn đề

### P1 — `propagate_preset_update` mâu thuẫn với kiến trúc resolve-lúc-load

`novel2epub/sources.py:196` copy `preset.crawl_overrides()` vào
`crawl_overrides_json` của mọi ebook có `source_preset` trùng, với điều kiện
`if key not in crawl`.

Ba hệ quả, đều xấu:

1. **Thừa** — `load_config` đã merge preset rồi; copy không thêm thông tin gì.
2. **Tự khoá** — sau lần propagate đầu tiên, mọi field preset trở thành override
   cứng của ebook. Lần sửa preset *sau* bị bỏ qua vì `key` đã tồn tại. Preset chỉ
   "ăn" đúng một lần rồi vĩnh viễn ngưng tác dụng lên ebook đó.
3. **Mất tín hiệu chủ đích** — không còn phân biệt được `delay_seconds = 2` do user
   cố ý đặt hay do propagate chép sang.

### P2 — `fetch-toc` ghi đè metadata

`_refresh_manifest(force_meta=True)` (`novel2epub/pipeline.py:341-348`) gán lại
`title`/`author` từ `cfg.novel` và `description`/`cover_url` từ trang vừa crawl,
đè lên nội dung user đã sửa. Nút "Lấy toàn bộ danh mục" (`ebook.html`) gửi
`force=true` → mỗi lần đồng bộ danh sách chương là một lần mất metadata.

Nguồn dữ liệu còn trộn lẫn thiếu nhất quán: title/author lấy từ config, còn
description/cover lấy từ kết quả crawl.

### P3 — `deps.py` sáu tên cho một file

`WORKSPACE_PATH`, `CONFIG_PATH`, `LIBRARY_PATH`, `SOURCES_PATH`,
`AUTOMATIONS_PATH`, `LIBRARY_STATE_PATH` đều trỏ vào cùng `DB_PATH`
(`app/deps.py:30-36`), lại còn lệch kiểu: bốn cái đầu là `str`, hai cái sau là
`Path`.

## Mục tiêu

- Ebook lưu đúng hai thứ: `source_preset` (tên) và field user **cố ý** override.
  Không bao giờ lưu bản sao giá trị preset.
- Sửa preset → mọi ebook dùng nó cập nhật ngay lần load kế, không cần propagate.
- `fetch-toc` chỉ đồng bộ danh sách chương; không đụng metadata.
- Form thêm ebook hiển thị đầy đủ config, tách rõ khối EBOOK (sửa được) và khối
  SOURCE (chỉ đọc), kèm preview TOC thật trước khi tạo.
- JSON endpoint tập trung dưới `/api/v1`, mỗi file cầm vừa một domain.

## Ngoài phạm vi

- Không đổi schema DB (trừ việc dọn *nội dung* `crawl_overrides_json`).
- Không thêm tính năng AI — xem Change 2 và Change 3 ở cuối tài liệu.
- Không refactor `pipeline.py`, `crawler.py`, `translator.py`.
- Không thêm auth / rate-limiting.

## Quyết định

### D1 — Xoá hẳn `propagate_preset_update`, không thay thế

Xoá hàm khỏi `novel2epub/sources.py` và mọi call site
(`app/routes/sources.py`, `app/routes/settings.py:365`).

**Lý do**: `_resolve_source_overrides` lúc load đã làm đúng việc này, live và
luôn đúng. Đây là fix bằng cách *xoá* code chứ không thêm.

**Đã cân nhắc và loại**: thêm cột đánh dấu field nào do preset chép sang vs user
tự đặt — giải quyết triệu chứng, giữ nguyên nguyên nhân (vẫn copy dữ liệu thừa),
và thêm một chiều trạng thái phải đồng bộ.

### D2 — Migration dọn override do propagate để lại

Với mỗi ebook có `source_preset` trỏ tới preset đang tồn tại: xoá khỏi
`crawl_overrides_json` những key có giá trị **trùng khít** giá trị preset hiện
tại. Key khác giá trị được giữ — đó là override thật của user.

`toc_url` luôn được giữ: nó không nằm trong `SourcePreset` nên không bao giờ
xuất hiện trong `preset.crawl_overrides()`, migration tự nhiên không chạm tới.

**Chạy ở đâu**: một script chạy tay `scripts/cleanup_preset_overrides.py`, theo
đúng tiền lệ `scripts/migrate_to_single_yaml.py`. Có cờ `--dry-run` in ra những
key sẽ xoá kèm ebook slug trước khi động vào dữ liệu.

Chỉ cần chạy MỘT LẦN chứ không cần hook lúc khởi động: một khi D1 xoá
`propagate_preset_update` thì không còn đường nào sinh thêm override bẩn nữa.
Ebook có `source_preset` trỏ tới preset không tồn tại được bỏ qua (không có gì
để so sánh) — `_resolve_source_overrides` vốn đã cảnh báo trường hợp này.

**Đây chính là quy ước code hiện có**: `save_source`
(`app/routes/settings.py:277-304`) đã lọc bỏ field trùng preset trước khi lưu.
Migration chỉ áp dụng cùng luật đó cho dữ liệu cũ.

**Đánh đổi đã chấp nhận**: nếu user cố ý đặt một giá trị trùng y hệt preset,
migration sẽ xoá override đó. Kết quả resolve không đổi (vẫn ra đúng giá trị ấy
từ preset), nên hành vi không đổi; chỉ khác ở chỗ về sau field đó sẽ đi theo
preset thay vì đứng yên. Chấp nhận được, nhưng phải ghi rõ trong changelog.

### D3 — `fetch-toc` không đụng metadata

- Bỏ tham số `force_meta` khỏi `_refresh_manifest`. Nhánh `manifest is None`
  (lần đầu) giữ nguyên — vẫn điền metadata. Nhánh `else` bỏ sạch bốn dòng gán
  `title`/`author`/`description`/`cover_url`; chỉ còn `source_url`,
  `metadata_missing` và phần trộn chương.
- Bỏ tham số `force` khỏi `step_fetch_toc`.
- `app/routes/jobs.py:332` bỏ nhánh `if step == "fetch-toc" and force`.
- `ebook.html:165` bỏ `<input type="hidden" name="force" value="true">`.

**Làm mới metadata** trở thành hành động riêng, và là hành động **đề xuất chứ
không ghi**:

```
POST /api/v1/ebooks/{slug}/meta/refresh
  → { title, author, description, cover_url }   // lấy từ trang TOC, KHÔNG lưu
```

Trang settings hiện kết quả cạnh giá trị hiện tại để user tự chọn field nào lấy;
áp dụng thì đi qua đúng form `POST /ebooks/{slug}/settings/novel` sẵn có. Không
sinh thêm đường ghi metadata mới — giữ đúng bất biến "chỉ form settings mới được
ghi metadata ebook", và cũng là lý do bug P2 không thể tái diễn.

### D4 — `sync-to-source` trở về tham chiếu thuần

`/ebooks/{slug}/settings/sync-to-source` là đường ghi ngược ebook → preset.
Hành động này **hợp lệ** (user cố ý nâng override riêng thành cấu hình chung),
giữ lại nhưng sửa:

1. Bỏ lời gọi `propagate_preset_update` (`settings.py:365`).
2. Dùng `save_preset()` thay `save_presets()` — sửa 1 preset không đụng preset khác.
3. **Sau khi đẩy field lên preset, xoá chính các key đó khỏi
   `crawl_overrides_json` của ebook.** Preset đã mang giá trị ấy; giữ lại chỉ là
   override thừa — đúng thứ làm ebook đông cứng. Sync xong ebook về tham chiếu thuần.

### D5 — `deps.py` chỉ còn `DB_PATH`

Xoá năm alias, giữ `DB_PATH` (kiểu `Path`). Cập nhật mọi call site. Xoá bỏ thay
vì giữ alias để lỗi lộ ra ngay lúc import chứ không âm thầm.

`WORKSPACE_DIR` (`DB_PATH.parent / ".n2e"`) là thư mục khác, **giữ nguyên**.

### D6 — Preview TOC: endpoint thuần đọc

```
POST /api/v1/toc/preview
  in : toc_url, scrapling_mode?
  out: { meta:   {title, author, description, cover_url},
         source: {matched, name, engine, …},
         chapters: [{index, title, url}],
         chapter_count }
```

Thay `/library/ebooks/preview` (hiện chỉ trả `chapter_count`, không trả danh
sách chương). Tên nói đúng việc: xem, không lưu. Endpoint không ghi gì xuống DB.

### D7 — Form thêm ebook chia hai khối

- **Khối EBOOK** (sửa được — dữ liệu riêng ebook): title, author, description,
  slug, language, publisher, series, series_index, subjects, cover.
- **Khối SOURCE** (chỉ đọc — thuộc preset): hiện giá trị preset khớp + link
  "Sửa tại /sources". Không cho sửa tại đây để tránh vô tình sinh override riêng,
  đúng tinh thần tham chiếu thuần.
- URL không khớp preset nào: báo rõ và mời tạo source mới. **Không** lặng lẽ ghi
  field crawl vào ebook.
- **Preview TOC**: hiện danh sách chương lấy được để kiểm tra selector trước khi tạo.

### D8 — `api_v1` là package, không phải một file

Openspec cũ đề xuất dồn toàn bộ JSON endpoint vào một `api_v1.py`. Đếm thực tế
có ~50 endpoint JSON (chapters ~20, queue ~15, batch ~10, notes 7, glossary 3)
→ file 1500+ dòng. Đó là đổi chỗ đống lộn xộn, không phải dọn dẹp.

```
app/routes/
  ebooks.py       # / , /ebooks/{slug}, library CRUD (gộp library.py), archive, bulk
  chapters.py     # trang chương + form-POST (gộp glossary.py)
  sources.py      # /sources
  settings.py     # /ebooks/{slug}/settings/*
  system.py       # jobs, queue, logs, storage, reader, automation, dashboard
  api_v1/
    __init__.py   # gom sub-router, prefix /api/v1
    toc.py        # preview TOC (mới)
    chapters.py · batch.py · queue.py · notes.py · glossary.py · dashboard.py
```

13 file → 6 module. URL cũ giữ song song bằng duplicate decorator, **không
redirect** (308 với POST có thể đổi method ở một số client). URL cũ đánh dấu
deprecated trong docstring.

## Rủi ro

- **Migration xoá nhầm override cố ý trùng giá trị preset** (D2) → hành vi resolve
  không đổi; ghi rõ trong changelog. Migration idempotent, chạy lại vô hại.
- **Gộp route làm vỡ import trong `tests/`** → cập nhật toàn bộ import cùng commit
  gộp; commit này thuần di chuyển, không đổi logic, nên bug (nếu có) là ImportError
  lộ ngay chứ không âm thầm.
- **Working tree đang bẩn** — 1790 dòng restyle 14 template chưa commit, trong đó có
  `index.html` (form thêm ebook) và `ebook.html` (nút TOC). Phải giải quyết trước
  khi bắt đầu, xem "Điều kiện tiên quyết".

## Điều kiện tiên quyết

Working tree hiện có việc dở dang chồng lấn:

- `novel2epub/sources.py` — `save_preset`/`delete_preset`/UPSERT **đã làm rồi**
  (openspec task 1.1–1.3). Change 1 dùng lại, không làm lại.
- `novel2epub/toc.py` + `app/routes/ebooks.py` — đang sửa dở `stats_map`.
- 14 template — restyle UI, **không liên quan** refactor này.

Phải chốt cách xử lý (commit riêng đợt restyle, hay stash) trước khi bắt đầu, để
diff của Change 1 không lẫn với diff restyle.

## Kế hoạch commit

Mỗi bước một commit, chạy `pytest tests/ -v` sau từng bước:

1. Xoá `propagate_preset_update` + call site + migration dọn override (D1, D2)
2. `fetch-toc` bỏ `force_meta`/`force` (D3)
3. `sync-to-source` về tham chiếu thuần (D4)
4. `deps.py` chỉ còn `DB_PATH` (D5)
5. `/api/v1/toc/preview` + form hai khối + preview TOC (D6, D7)
6. Gộp route → 6 module + package `api_v1` (D8)

Bước 6 để cuối: đụng nhiều file nhất nhưng rủi ro logic thấp nhất (thuần di chuyển).

## Kiểm thử

Test mới cần có:

- Sửa preset → `load_config(slug)` phản ánh ngay, `crawl_overrides_json` của ebook
  **không đổi** (thay cho `TestPropagatePresetUpdate` bị xoá).
- Migration: override trùng preset bị xoá; override khác preset được giữ; `toc_url`
  luôn được giữ; chạy hai lần cho cùng kết quả (idempotent).
- `fetch-toc` trên manifest đã có metadata do user sửa → metadata **không đổi**;
  danh sách chương vẫn được đồng bộ.
- `fetch-toc` lần đầu (chưa có manifest) → metadata vẫn được điền.
- `sync-to-source` → preset nhận field mới, `crawl_overrides_json` của ebook rỗng đi
  đúng các key vừa đẩy lên, ebook khác cùng preset không bị ghi vào DB.
- `/api/v1/toc/preview` → trả danh sách chương, và **không ghi gì** xuống DB
  (khẳng định bằng cách so DB trước/sau).
- `/api/v1/ebooks/{slug}/meta/refresh` → trả metadata đề xuất, và **không ghi gì**
  xuống DB (so DB trước/sau) — đây là bất biến chặn P2 tái diễn.

Test hiện có sẽ vỡ và cần cập nhật: `tests/test_source_ebook_link.py`
(`TestPropagatePresetUpdate`), `tests/test_pipeline_meta.py`
(`test_step_fetch_toc_saves_metadata_no_content`), `tests/test_routes_sources_import.py`
(monkeypatch `propagate_preset_update`), `tests/test_add_ebook_flow.py`.

## Việc tách ra làm sau

Bốn tính năng AI người dùng yêu cầu, tách khỏi Change 1 vì chúng *xây cái mới*
trong khi Change 1 *sửa cái hỏng*, và vì cả hai đều ghi vào đúng ranh giới mà
Change 1 đang định nghĩa lại — làm song song thì hỏng không truy được nguyên nhân.

**Change 2 — AI cho SOURCE** (tái dùng `novel2epub/selector_ai.py` đã có):
- Tự dò selector khi URL không khớp preset nào, ngay trong form thêm ebook
- Tự đề xuất sửa preset khi crawl hỏng (TOC 0 chương / nội dung rỗng)
- Soát chất lượng TOC sau preview (link rác, chương thiếu, sai thứ tự, trùng)

Ba việc cùng xoay quanh "selector đúng chưa", dùng chung `selector_ai` +
validate trên trang thật.

**Change 3 — AI cho EBOOK**:
- Chuẩn hoá metadata: dịch tên/tác giả/mô tả Trung→Việt, gợi ý slug, subjects, series

Ghi vào ebook meta — vùng Change 1 vừa chốt luật sở hữu.

## Quan hệ với openspec cũ

`openspec/changes/refactor-toc-ebook-sources-api/` (chưa commit) đề xuất một
phạm vi khác: path alias, atomic save, tách display khỏi `chapter_rows`, gộp
route. Phần atomic save đã làm xong trong working tree. Phần path alias và gộp
route được Change 1 tiếp thu (D5, D8 — D8 có sửa: package thay vì một file).
Phần tách display khỏi `chapter_rows` không nằm trong Change 1.

Openspec change đó cần được cập nhật cho khớp, hoặc đánh dấu superseded bởi tài
liệu này.
