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

## Frontend (React + Vite)

```sh
cd frontend
npm install
npm run dev        # dev server http://localhost:5183/app/ (proxy API → 8011)
npm run build      # bản web → app/webui/ (kèm PWA: sw.js, manifest, icons)
npm run tauri:build  # bản desktop → src-tauri/target/release/bundle/
```

- Bản web chạy dưới `/app/`; bản Tauri dùng base `./` (đường dẫn tương đối vì nạp từ `tauri://`). Hai lệnh build cùng ghi vào `app/webui/`, lệnh chạy sau cùng sẽ quyết định nội dung ở đó.
- PWA: `vite-plugin-pwa` generateSW — precache toàn bộ asset (đã hash), `navigateFallback` trỏ `index.html`, không cache `/api/*`. Service worker chỉ có scope `/app/` nên không hoạt động trên `tauri://`.
- Build Tauri cần Rust toolchain (`rustup` + MSVC): `npm run tauri:icon` để sinh đủ bộ icon từ một ảnh nguồn; `bundle.icon` trong `src-tauri/tauri.conf.json` phải liệt kê `.ico`/`.icns`/PNG tương ứng.


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

Chạy toàn bộ backend từ thư mục gốc (`pytest.ini` giới hạn discovery trong `tests/`):

```sh
python -m pytest -q
```

Chạy nhóm liên quan trong lúc phát triển:

```sh
python -m pytest tests/test_crawler_extract_text.py tests/test_scrapling.py -q
python -m pytest tests/test_translator.py -q
python -m pytest tests/test_automation.py -q
```

Tên file thực tế có thể chi tiết hơn; dùng `pytest --collect-only -q` để xem danh sách hiện tại. Với thay đổi route, kiểm tra cả response HTML/API và hành vi queue. Với migration, luôn test DB cũ lẫn DB mới.

### Helper và fixture

- `tests/conftest.py`: fixture pytest tự động nạp; không import trực tiếp từ file này.
- `tests/helpers/db.py`: import `write_db_config` để dựng DB trong `tmp_path` với defaults, sources và ebooks riêng cho test.
- `tests/helpers/routes.py`: `make_config` và `make_client` dùng chung cho nhóm route batch. Client cài dependency/job bằng `monkeypatch` để khôi phục sau test; không khởi động lifespan/worker/scheduler.
- `FakeJob` mặc định chỉ ghi nhận job trong `started`. Chỉ bật `run_jobs=True` trên client khi muốn chạy target đồng bộ và đã mock các lời gọi bên ngoài.
- `tests/helpers/jobs.py`: `wait_until` dùng monotonic clock; `wait_for_persisted_job` chờ commit lịch sử của worker trước khi kiểm tra khôi phục queue.
- Dữ liệu seed và assertion đặc thù vẫn đặt cạnh từng test. Khi cần giả lập remote client cho auth/CORS, truyền `client=("203.0.113.1", 12345)` tường minh.
- Test thời gian dùng clock giả riêng cho module để tránh phụ thuộc scheduler hệ điều hành. Test queue persistence chờ bản ghi commit vào SQLite trước khi dựng queue mới; trạng thái `done` trong RAM chưa đảm bảo đã ghi DB.

## Kiểm Tra Thủ Công

### Kiểm Thử Soát Lỗi

```sh
pytest tests/test_proofreading.py tests/test_proofreading_routes.py tests/test_build_validation.py tests/test_chapter_versions.py tests/test_baseline_backfill.py tests/test_db_schema.py -q
npm --prefix frontend run typecheck
cd frontend
npx vitest run src/lib/validation.test.ts src/components/chapter/ProofreadingPanel.test.tsx --environment node --pool forks --maxWorkers 1 --minWorkers 1
npm run build
```

`tests/fixtures/proofreading_validation.json` dùng chung Python/JS: mã detector,
Unicode/newline/UTF-16 và false positive. Đổi luật phải cập nhật cả
`build_validation.py` và `frontend/src/lib/validation.ts`. Domain thuần
`proofreading.py` không rebuild từ paragraphs đã lọc; thuật toán phải idempotent,
giữ dòng trống/CRLF, `.../…/!!!/???` và ZWJ/ZWNJ có ý nghĩa.

`proofreading_service.py` điều phối publication resolver, exact confirmation,
draft hash, candidate pending TTL 14 ngày và ghi canonical. AI chỉ dùng mock trong
test; offsets edits là **Unicode codepoints**, offsets highlight API là **UTF-16**.
Từ chối malformed/rỗng/wrong original/outside scope/overlap; full diff frontend dựng
từ edits O(n), không dùng LCS word cả chương hoặc cắt 2000 ký tự. Revision/hash/nhánh
publication/title/draft đổi thì tạo lại, không merge hoặc tự retry.

Tái sử dụng `ai_revisions`, `ebook_extra_json`, queue SQLite và history hiện hành,
không cần cột/schema mới. Baseline chỉ lazy-initialize đúng index/nhánh khi người dùng
xác nhận ghi; baseline đã có nhưng diverged thì fail closed. Test nâng schema DB cũ
phải giữ raw, hai nhánh, title/revision, history và candidate legacy.

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
