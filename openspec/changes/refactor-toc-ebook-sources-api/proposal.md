## Why

Codebase hiện tại có nhiều vấn đề tích lũy: `deps.py` khai báo 6 alias path đều trỏ vào cùng một file DB (gây nhầm lẫn), `save_presets()` dùng DELETE+INSERT không atomic, `chapter_rows()` trong `toc.py` trộn lẫn display logic với data access, và 14 route file có trách nhiệm chồng chéo khó theo dõi. Cần refactor để giảm xung đột dữ liệu, làm rõ ranh giới sở hữu, và dọn dẹp API/UI.

## What Changes

- **Config path aliases**: Xóa 5 alias thừa (`CONFIG_PATH`, `LIBRARY_PATH`, `SOURCES_PATH`, `WORKSPACE_PATH`, `AUTOMATIONS_PATH`) trong `deps.py` — chỉ giữ `DB_PATH` duy nhất; cập nhật tất cả call site
- **Sources atomic save**: Sửa `save_presets()` từ DELETE-all + INSERT thành UPSERT per-preset để tránh mất data nếu crash giữa chừng; thêm `save_preset()` (số ít) cho single-preset update
- **TOC/display separation**: Tách display concern ra khỏi `chapter_rows()` — `toc.py` chỉ giữ pure query helpers; `bientap`/`word_count` tính ở route layer
- **Route consolidation**: Gộp 14 route file → 6 module (`ebooks`, `chapters`, `sources`, `settings`, `system`, `api_v1`); move tất cả JSON endpoint vào `api_v1.py` với prefix `/api/v1/`
- **Back-compat redirect**: Giữ các `/api/ebooks/{slug}/...` cũ redirect sang `/api/v1/ebooks/{slug}/...` trong thời gian chuyển đổi

## Capabilities

### New Capabilities

- `atomic-source-preset-save`: Lưu từng source preset độc lập (UPSERT) thay vì ghi lại toàn bộ — tránh race condition và mất data khi nhiều request đồng thời
- `api-v1-routing`: Tất cả JSON endpoint tập trung tại `/api/v1/` với versioning rõ ràng; form-POST routes giữ nguyên URL cũ

### Modified Capabilities

- `chapter-pagination`: Không thay đổi behavior, nhưng helper `chapter_rows()` refactor nội bộ — cần cập nhật spec nếu interface thay đổi

## Impact

- `deps.py`: Xóa 5 constant, thêm helper `db_path()` nếu cần
- `novel2epub/sources.py`: Thêm `save_preset()`, sửa `save_presets()` dùng UPSERT
- `novel2epub/toc.py`: Tách `bientap`/`word_count` ra khỏi `chapter_rows()` core
- `app/routes/`: Gộp 14 → 6 file; tạo `api_v1.py`
- `app/main.py`: Cập nhật router includes
- Test files: Cập nhật import paths nếu route file đổi tên
