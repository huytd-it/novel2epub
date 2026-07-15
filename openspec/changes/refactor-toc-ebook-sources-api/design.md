## Context

Codebase hiện tại tích lũy 3 nhóm vấn đề kỹ thuật sau nhiều lần mở rộng tính năng:

1. **Path alias thừa** — `deps.py` khai báo 6 tên (`WORKSPACE_PATH`, `CONFIG_PATH`, `LIBRARY_PATH`, `SOURCES_PATH`, `AUTOMATIONS_PATH`, `LIBRARY_STATE_PATH`) đều trỏ vào cùng một `DB_PATH`. Call site phải đoán "dùng tên nào" dẫn đến import nhầm và code khó đọc.

2. **Sources không atomic** — `save_presets()` thực hiện `DELETE FROM sources` rồi INSERT lại toàn bộ. Nếu app crash hoặc có request đồng thời giữa chừng, toàn bộ preset bị xóa. `propagate_preset_update()` cũng đọc rồi ghi lại từng ebook theo vòng lặp, không wrapped trong transaction đủ rộng.

3. **TOC trộn display với data** — `chapter_rows()` tính `bientap`, `bientap_tooltip`, `word_count`, `zh_char_count` trực tiếp trong vòng lặp data access. Những field này là presentation concern; khi cần thêm/sửa display logic phải đọc hiểu toàn bộ data pipeline.

4. **Route phân tán** — 14 file route, JSON endpoint rải rác ở `chapters.py` (700+ dòng), `library.py`, `settings.py`, `sources.py`. Không có versioning; client code không biết endpoint nào ổn định.

## Goals / Non-Goals

**Goals:**
- Xóa toàn bộ path alias thừa, chỉ dùng `DB_PATH` (hoặc truyền thẳng qua tham số)
- `save_preset()` (số ít) và `save_presets()` dùng UPSERT per-row, không DELETE-all
- `chapter_rows()` trả về `ChapterRow` thuần data; display fields (`bientap`, `word_count`) tính ở route layer
- Gộp 14 → 6 route file; tất cả JSON endpoint vào `api_v1.py` với prefix `/api/v1/`
- Giữ back-compat: form-POST URL cũ không đổi; JSON URL cũ redirect 308 → `/api/v1/`

**Non-Goals:**
- Không thay đổi database schema
- Không đổi format template Jinja2
- Không refactor pipeline (`pipeline.py`, `crawler.py`, `translator.py`)
- Không thêm authentication hay rate-limiting

## Decisions

### D1: Xóa path alias — chỉ dùng `DB_PATH`

**Quyết định**: Xóa `WORKSPACE_PATH`, `CONFIG_PATH`, `LIBRARY_PATH`, `SOURCES_PATH`, `AUTOMATIONS_PATH`, `LIBRARY_STATE_PATH` khỏi `deps.py`. Mọi call site truyền thẳng `deps.DB_PATH`.

**Lý do**: 6 alias = 6 cách viết khác nhau cho cùng 1 giá trị. Gây nhầm lẫn khi đọc code ("SOURCES_PATH khác WORKSPACE_PATH không?"). Xóa bỏ thay vì alias để compiler/grepper bắt lỗi ngay.

**Thay thế đã xem xét**: Giữ 1 alias `WORKSPACE_PATH` cho backward-compat — bị loại vì vẫn tạo ra 2 tên cho 1 thứ.

### D2: UPSERT per-preset thay vì DELETE-all + INSERT

**Quyết định**: `save_preset(path, preset)` dùng `INSERT OR REPLACE INTO sources`; `save_presets()` gọi `save_preset()` cho từng item, bọc trong transaction duy nhất. Thêm `delete_preset(path, name)` riêng.

**Lý do**: DELETE-all + INSERT không atomic nếu crash giữa chừng. UPSERT per-row giữ tính atomic ở mức row; transaction bao ngoài đảm bảo tính nhất quán khi ghi nhiều row.

**Thay thế đã xem xét**: WAL mode + BEGIN IMMEDIATE — cần thêm ở mọi writer, phức tạp hơn; UPSERT đơn giản và đủ.

### D3: Tách display fields ra khỏi `chapter_rows()`

**Quyết định**: `chapter_rows()` trả `ChapterRow` không có `bientap`, `bientap_tooltip`, `word_count`, `zh_char_count`. Route `ebook_home` tính 4 field này từ `stats_map` sau khi nhận list `ChapterRow`.

**Lý do**: `chapter_rows()` hiện đọc `meta_json` từ DB để build `bientap` — đây là display logic. Tách ra giúp `toc.py` chỉ là query/filter helper thuần túy, dễ test.

**Thay thế đã xem xét**: Giữ nguyên nhưng thêm flag `with_display=False` — thêm complexity cho `chapter_rows()` mà không giải quyết coupling.

### D4: Route consolidation 14 → 6 + `api_v1.py`

**Quyết định**:
```
app/routes/
  ebooks.py      # / index, /ebooks/{slug}, archive/unarchive, bulk-action, import/export
  chapters.py    # /ebooks/{slug}/chapters/... (page render + form-POST)
  sources.py     # /sources (page render + form-POST)
  settings.py    # /ebooks/{slug}/settings/... (page render + form-POST)
  system.py      # /jobs, /storage, /notes, /reader, /automation, /dashboard
  api_v1.py      # /api/v1/... (tất cả JSON endpoint)
```

`library.py` gộp vào `ebooks.py` (tạo ebook mới = action trên library). `glossary.py` gộp vào `chapters.py` (glossary gắn với chapter editor). `automation.py`, `jobs.py`, `storage.py`, `notes.py`, `reader.py`, `dashboard.py` gộp vào `system.py`.

**Back-compat**: Các URL `/api/ebooks/{slug}/...` cũ giữ nguyên trong `api_v1.py` với decorator `@router.post("/api/ebooks/...")` song song `@router.post("/api/v1/ebooks/...")` — KHÔNG redirect (tránh method change với POST).

**Lý do**: 14 file với overlap (glossary helper dùng ở chapters, library logic dùng ở ebooks) tạo ra circular import tiềm ẩn. 6 module theo domain rõ hơn.

## Risks / Trade-offs

- **[Risk] Import paths thay đổi khi gộp route** → test file import trực tiếp function từ route module sẽ vỡ → Mitigate: cập nhật tất cả import trong `tests/` cùng lúc với gộp route.

- **[Risk] `chapter_rows()` interface change ảnh hưởng CLI** → `pipeline.py` hoặc `cli.py` nếu gọi `chapter_rows()` trực tiếp → Mitigate: grep toàn bộ call site trước khi sửa.

- **[Trade-off] Dual URL cho JSON endpoint** → giữ cả URL cũ lẫn `/api/v1/` làm tăng surface area → Chấp nhận ngắn hạn; URL cũ đánh dấu `deprecated` trong docstring, xóa sau 1 release.

## Migration Plan

1. Sửa `sources.py` (data layer) — không ảnh hưởng UI, test được độc lập
2. Sửa `toc.py` + cập nhật route `ebook_home` — test visual không đổi
3. Xóa path alias trong `deps.py` + update tất cả call site trong `app/routes/`
4. Gộp route 14 → 6 + tạo `api_v1.py` — cập nhật `main.py`
5. Chạy `pytest tests/ -v` sau mỗi bước

Rollback: mỗi bước là commit riêng, revert từng commit nếu cần.

## Open Questions

- Không có câu hỏi mở — scope đủ rõ để triển khai.
