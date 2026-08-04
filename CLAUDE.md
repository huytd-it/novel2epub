# novel2epub Development Context

Đọc [README.md](README.md) để bắt đầu và [docs/architecture.md](docs/architecture.md) trước khi thay đổi kiến trúc.

## Hệ Thống Hiện Tại

- Runtime state và config nằm trong một SQLite DB, mặc định `novel2epub.db`.
- Scrapling là crawler duy nhất với mode `fetcher`, `stealthy`, `dynamic`.
- Config hiệu lực: defaults -> source preset -> ebook override.
- `translate` và `ai` hỗ trợ override theo ebook; kết nối Reader là global.
- CLI: `python -m novel2epub -e <slug> <command>`.
- Web UI: `uvicorn app.main:app --reload --port 8010`.
- Tests: `pytest tests -v`.

## Quy Tắc

- Không khôi phục kiến trúc YAML/sidecar đã bỏ.
- Không commit DB, dữ liệu truyện, EPUB hoặc secret.
- Giữ domain logic ngoài route FastAPI khi có thể.
- Thêm migration và test khi thay schema SQLite.
- Cập nhật tài liệu trong `docs/` khi thay đổi hành vi public hoặc vận hành.
