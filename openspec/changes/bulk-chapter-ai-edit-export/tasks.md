## 1. Logic module (thuần Python)

- [x] 1.1 Tạo `novel2epub/bulk_transfer.py` với hằng marker chương + glossary và regex parse (`^=+\s*CHƯƠNG\s+(\d+)\s*=+$`, `^=+\s*GLOSSARY\s*=+$`)
- [x] 1.2 Soạn template prompt biên tập (hằng trong module) chắt lọc nguyên tắc từ `docs/rule.md`: đối chiếu bản gốc, ngôi xưng theo quan hệ, ngữ pháp Việt, cân bằng Hán–Việt, tên riêng Hán Việt viết hoa, giữ marker, yêu cầu xuất khối `GLOSSARY` (`[NAMES]`/`[VIETPHRASE]`, `source = target`)
- [x] 1.3 Viết `build_export(items, glossary, prompt=...) -> str`: prepend prompt → render glossary hiện có (`source = target`) → bọc các chương theo marker, sắp theo index
- [x] 1.4 Viết `parse_import(text) -> list[(index, content)]`: tách theo marker chương, trim nội dung, bỏ phần prompt/glossary/đầu khối trước marker chương đầu tiên
- [x] 1.5 Viết `parse_glossary(text) -> {names, vietphrase}`: tách khối `GLOSSARY`, phân nhóm `[NAMES]`/`[VIETPHRASE]`, bỏ dòng thiếu `source`/`target`
- [x] 1.6 Viết `validate_import(parsed, expected_indexes, manifest_indexes) -> {matched, missing, extra, unknown}` để đối chiếu chương dư/thiếu/không thuộc manifest

## 2. Backend routes/API

- [x] 2.1 Thêm `POST /api/ebooks/{slug}/batch/export` trong `app/routes/chapters.py`: nhận `indexes`, đọc `translated/` + glossary (`names.txt`/`vietphrase.txt`) qua `Storage`, bỏ qua chương chưa có bản dịch, trả `{text, skipped}`
- [x] 2.2 Thêm `POST /api/ebooks/{slug}/batch/import` mode `preview`: parse chương + glossary + validate, trả danh sách chương cập nhật / không đổi / lỗi + mục glossary sẽ thêm, KHÔNG ghi file
- [x] 2.3 Thêm xử lý mode `confirm`: ghi nội dung biên tập vào `translated/` cho các chương khớp bằng `Storage.write_translated` (KHÔNG đụng `translated_mt/`), và merge glossary vào `names.txt`/`vietphrase.txt` (tái dùng logic append/dedup của `_append_glossary_entry`)
- [x] 2.4 Báo lỗi rõ ràng cho các ca: chưa chọn chương, thiếu marker hoàn toàn, marker không khớp manifest

## 3. UI trên trang ebook

- [x] 3.1 Thêm 2 nút "Xuất chương đã chọn" và "Nhập bản biên tập" vào thanh `selected-actions` trong `app/templates/ebook.html`
- [x] 3.2 Thêm modal xuất: textarea read-only hiển thị khối export (prompt + glossary + chương) + nút "Copy", hiện tổng số chương + số ký tự + danh sách chương bị bỏ qua
- [x] 3.3 Thêm modal nhập: textarea dán, nút "Preview" (hiện diff theo chương + glossary sẽ thêm) và nút "Xác nhận ghi đè"
- [x] 3.4 JS gom index từ `.chapter-check` đã tick (tái dùng cơ chế `batch-form`); chặn submit khi chưa chọn chương

## 4. Tests & tài liệu

- [x] 4.1 Unit test `bulk_transfer`: round-trip build→parse khớp nội dung; parse glossary đúng nhóm; ca thiếu marker; ca dư/thiếu chương; ca marker không thuộc manifest; ca không có khối glossary
- [x] 4.2 Test route export/import (export có prompt+glossary; preview không ghi; confirm ghi đúng chương + merge glossary dedup; giữ nguyên `translated_mt/`)
- [x] 4.3 Cập nhật `CLAUDE.md` (mục `app/routes/chapters.py` + module mới `bulk_transfer.py`) mô tả luồng xuất/nhập biên tập hàng loạt
