# Phát Triển

## Thiết Lập

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
scrapling install
python scripts/init_db.py
pytest tests -v
```

Không commit `novel2epub.db`, API key, EPUB, log hoặc dữ liệu truyện.

## Cấu Trúc Mã

| Khu vực | Trách nhiệm |
| --- | --- |
| `novel2epub/config.py` | Dataclass và resolve config từ DB |
| `novel2epub/db.py` | Schema, connection và migration SQLite |
| `novel2epub/storage.py` | API dữ liệu ebook/chương/ngữ cảnh |
| `novel2epub/crawler.py` | Scrapling crawl và pagination |
| `novel2epub/translator.py` | Backend dịch và dựng prompt |
| `novel2epub/pipeline.py` | Điều phối các bước |
| `novel2epub/blocks.py` | Logic thuần thao tác KHỐI trong khung đối chiếu 3 cột (sửa/xóa, map block → dòng gốc) |
| `novel2epub/epub_builder.py` | Đóng gói EPUB |
| `novel2epub/bulk_contract.py` | Logic thuần hợp đồng bulk-preview/bulk-confirm (đánh giá đủ điều kiện, vân tay config/chương) |
| `app/routes/` | Route HTML/API theo domain |
| `app/queue.py` | Job queue đa nhóm worker |
| `app/scheduler.py` | Automation cron |

## Nguyên Tắc Thay Đổi

- SQLite là nguồn sự thật; không thêm sidecar runtime mới nếu dữ liệu thuộc trạng thái hệ thống.
- Domain logic nên nằm trong `novel2epub/`; route chỉ parse request, gọi logic và render response.
- Hàm xử lý dữ liệu nên thuần khi có thể; tách network/DB boundary để dễ test.
- Giữ tương thích DB bằng schema migration, không sửa dữ liệu người dùng theo kiểu phá hủy.
- Secret không được xuất hiện trong log, response HTML hoặc fixture commit.
- Source preset chứa đặc thù website; không hard-code domain vào pipeline chung nếu có thể cấu hình.

## Kiểm Thử

Chạy toàn bộ:

```sh
pytest tests -v
```

Chạy nhóm liên quan trong lúc phát triển:

```sh
pytest tests/test_crawler.py -v
pytest tests/test_translator.py -v
pytest tests/test_automation.py -v
```

Tên file thực tế có thể chi tiết hơn; dùng `pytest --collect-only -q` để xem danh sách hiện tại. Với thay đổi route, kiểm tra cả response HTML/API và hành vi queue. Với migration, luôn test DB cũ lẫn DB mới.

## Kiểm Tra Thủ Công

1. Tạo DB tạm bằng `scripts/init_db.py --db <path>`.
2. Khởi động Web UI với `NOVEL2EPUB_DB` trỏ đến DB tạm.
3. Tạo ebook thử, lấy TOC và crawl 1-2 chương.
4. Kiểm tra giao diện ở desktop và mobile.
5. Chạy translate passthrough hoặc mock endpoint trước khi dùng API tính phí.
6. Build và mở EPUB bằng ít nhất một reader thực tế.

## Migration Cũ

- `scripts/migrate_to_sqlite.py`: chuyển cấu hình và dữ liệu file cũ sang SQLite.
- `scripts/migrate_to_single_yaml.py`: migration trung gian của kiến trúc YAML cũ, không dùng cho cài đặt mới.
- `scripts/cleanup_preset_overrides.py`: dọn override crawl thừa sau khi dùng source preset.

Luôn backup trước khi chạy migration trên dữ liệu thật.
