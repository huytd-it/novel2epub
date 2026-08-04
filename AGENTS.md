<!-- CODEGRAPH_START -->
## CodeGraph

Nếu `.codegraph/` có index hợp lệ, dùng CodeGraph trước grep/read khi cần hiểu call path. Nếu CLI báo index không tồn tại, tiếp tục bằng công cụ tìm kiếm thông thường và không tự khởi tạo index.
<!-- CODEGRAPH_END -->

# novel2epub Agent Guide

novel2epub crawl tiểu thuyết web, dịch/biên tập tiếng Việt và xuất EPUB. Đọc `README.md` và `docs/architecture.md` trước thay đổi lớn.

## Kiến Trúc Hiện Tại

- SQLite DB là nguồn sự thật duy nhất cho config và runtime data.
- Config hiệu lực: defaults -> source preset -> ebook override.
- Scrapling là crawler duy nhất: `fetcher`, `stealthy`, `dynamic`.
- Pipeline: TOC -> raw -> MT snapshot/translated -> cleanup/edit -> EPUB.
- FastAPI/Jinja2 Web UI dùng job queue và cron scheduler.
- `translate` và `ai` có thể override theo ebook; credential Reader là global.

## Khu Vực Chính

- `novel2epub/config.py`, `db.py`, `storage.py`: config và persistence.
- `novel2epub/crawler.py`, `pipeline.py`: crawl và orchestration.
- `novel2epub/translator.py`: backend dịch và prompt context.
- `novel2epub/epub_builder.py`: EPUB.
- `app/routes/`: Web UI/API theo domain.
- `app/queue.py`, `app/scheduler.py`: job và automation.
- `scripts/init_db.py`, `scripts/migrate_to_sqlite.py`: setup/migration.

## Lệnh

```sh
python scripts/init_db.py
python -m novel2epub list
python -m novel2epub -e <slug> run
uvicorn app.main:app --reload --port 8010
pytest tests -v
```

## Nguyên Tắc

- Không đưa runtime state trở lại YAML, Markdown hoặc sidecar JSON.
- Không commit DB, raw/bản dịch, EPUB, log hay secret.
- Giữ route mỏng; đặt domain logic có thể test trong `novel2epub/`.
- Thay schema phải có migration và test dữ liệu cũ.
- Không log API key hoặc Supabase service-role key.
- Cập nhật tài liệu khi thay CLI, config, pipeline hoặc hành vi vận hành.
- Không sửa dữ liệu người dùng theo cách phá hủy nếu chưa có yêu cầu rõ ràng.

## Tài Liệu

- `docs/configuration.md`: mô hình và field cấu hình.
- `docs/operations.md`: CLI, automation, backup và troubleshooting.
- `docs/translation.md`: glossary, idiom, nhân vật và biên tập.
- `docs/development.md`: quy ước phát triển và kiểm thử.
