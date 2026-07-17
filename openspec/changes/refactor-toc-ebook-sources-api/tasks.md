## 1. Sửa data layer: Sources atomic save

- [x] 1.1 Thêm hàm `save_preset(path, preset)` vào `novel2epub/sources.py` dùng `INSERT OR REPLACE INTO sources`
- [x] 1.2 Thêm hàm `delete_preset(path, name)` vào `novel2epub/sources.py` xóa đúng 1 row
- [x] 1.3 Sửa `save_presets(path, presets)` dùng transaction + UPSERT per-row thay vì DELETE-all + INSERT
- [ ] 1.4 Cập nhật `app/routes/sources.py` dùng `save_preset()` khi lưu/clone 1 preset; dùng `delete_preset()` khi xóa

## 2. Sửa TOC: tách display logic ra khỏi `chapter_rows()`

- [ ] 2.1 Xóa fields `bientap`, `bientap_tooltip`, `word_count`, `zh_char_count` khỏi dataclass `ChapterRow` trong `novel2epub/toc.py`
- [ ] 2.2 Xóa logic tính 4 fields đó ra khỏi hàm `chapter_rows()`
- [ ] 2.3 Thêm hàm `enrich_chapter_rows(rows, stats_map)` trong `novel2epub/toc.py` tính 4 fields display từ `stats_map` và trả về list dict (hoặc dataclass mở rộng)
- [ ] 2.4 Cập nhật `app/routes/ebooks.py` gọi `enrich_chapter_rows()` sau `chapter_rows()` trước khi render template
- [ ] 2.5 Đảm bảo template `ebook.html` vẫn nhận đủ fields (không vỡ display)

## 3. Xóa path alias thừa trong `deps.py`

- [ ] 3.1 Xóa 5 alias `WORKSPACE_PATH`, `CONFIG_PATH`, `LIBRARY_PATH`, `SOURCES_PATH`, `AUTOMATIONS_PATH`, `LIBRARY_STATE_PATH` khỏi `deps.py`
- [ ] 3.2 Grep toàn bộ `app/routes/` thay thế mọi `deps.WORKSPACE_PATH`, `deps.CONFIG_PATH`, `deps.LIBRARY_PATH`, `deps.SOURCES_PATH`, `deps.AUTOMATIONS_PATH`, `deps.LIBRARY_STATE_PATH` → `deps.DB_PATH`
- [ ] 3.3 Grep `novel2epub/` và `tests/` kiểm tra không còn import alias cũ

## 4. Gộp route 14 → 6 file

- [ ] 4.1 Tạo `app/routes/system.py` — move router + handlers từ `jobs.py`, `storage.py`, `notes.py`, `reader.py`, `automation.py`, `dashboard.py`
- [ ] 4.2 Gộp `app/routes/library.py` vào `app/routes/ebooks.py` — move tất cả handler tạo/xóa ebook, search, preview, bulk
- [ ] 4.3 Gộp `app/routes/glossary.py` vào `app/routes/chapters.py` — move glossary route handlers và helper `_append_glossary_entry`
- [ ] 4.4 Tạo `app/routes/api_v1.py` — move tất cả JSON endpoint (`/api/ebooks/...`) từ `chapters.py` sang, đổi prefix thành `/api/v1/ebooks/...`; giữ nguyên URL cũ như alias (duplicate decorator, không redirect)
- [ ] 4.5 Xóa 6 file route cũ: `library.py`, `glossary.py`, `jobs.py`, `storage.py`, `notes.py`, `reader.py`, `automation.py`, `dashboard.py`
- [ ] 4.6 Cập nhật `app/main.py`: thay `include_router` cũ bằng 5 router mới (`ebooks`, `chapters`, `sources`, `settings`, `system`, `api_v1`)

## 5. Cập nhật tests và kiểm tra

- [ ] 5.1 Cập nhật tất cả import trong `tests/` trỏ đúng module mới sau khi gộp route
- [ ] 5.2 Chạy `pytest tests/ -v` và đảm bảo toàn bộ test pass
