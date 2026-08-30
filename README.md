# novel2epub

> Crawl tiểu thuyết web · Dịch sang tiếng Việt · Biên tập · Xuất EPUB — CLI + Web UI + SPA React, lưu toàn bộ trong một file SQLite.

```text
fetch TOC → crawl raw → translate (OpenAI / Local MT) → cleanup / AI edit → build EPUB → (optional) publish Reader / OPDS
```

Mỗi bước ghi kết quả vào DB nên có thể dừng, chạy tiếp hoặc chạy lại một phạm vi chương mà không cần bắt đầu lại từ đầu.

---

## Mục Lục

- [Khởi động nhanh (scripts dev / build / run)](#khởi-động-nhanh-scripts-dev--build--run)
- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cài đặt thủ công](#cài-đặt-thủ-công)
- [Cách dùng: Web UI + CLI](#cách-dùng-web-ui--cli)
- [Kiến trúc & Pipeline](#kiến-trúc--pipeline)
- [Cấu hình (3 tầng)](#cấu-hình-3-tầng)
- [Dịch & Biên tập](#dịch--biên-tập)
- [Frontend SPA & Tauri](#frontend-spa--tauri)
- [Backup / Restore](#backup--restore)
- [OPDS cho readest](#opds-cho-readest)
- [WireGuard / wgcf](#wireguard--wgcf)
- [API Docs](#api-docs)
- [Phát triển & Kiểm thử](#phát-triển--kiểm-thử)
- [Xử lý sự cố](#xử-lý-sự-cố)
- [Tài liệu chi tiết](#tài-liệu-chi-tiết)

---

## Khởi Động Nhanh (scripts dev / build / run)

Ba scripts bọc toàn bộ thao tác cài đặt, build và chạy — **Windows dùng `.ps1`, Linux/macOS dùng `.sh`**. Chỉ cần 1 lệnh từ thư mục gốc.

| Script | Chức năng | Cổng | Khi nào dùng |
|---|---|---|---|
| `dev` | Dev mode: backend reload + Vite HMR | backend `8011` + Vite `5183` | Code hằng ngày |
| `build` | Build production SPA → `app/webui/` | — | Trước khi deploy / test prod |
| `run` | Chạy production (tự build nếu chưa có) | `8010` | Demo / chạy thật |

### Windows (PowerShell)

```powershell
# DEV — backend 8011 + Vite 5183 (khuyen nghi khi code)
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

# BUILD — bien dich SPA ra app/webui
powershell -ExecutionPolicy Bypass -File scripts/build.ps1

# RUN — chay production tai 8010 (SPA /app + Jinja2 /)
powershell -ExecutionPolicy Bypass -File scripts/run.ps1
# mo http://127.0.0.1:8010/app/  (SPA)
# mo http://127.0.0.1:8010/      (Jinja2 legacy)
```

Tùy chọn thêm:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Port 8011 -SkipInstall
powershell -ExecutionPolicy Bypass -File scripts/run.ps1 -Port 8010 -HostAddr 127.0.0.1 -NoBuild -Reload
powershell -ExecutionPolicy Bypass -File scripts/run.ps1 -HostAddr 0.0.0.0 -Port 8010  # mo ra LAN (can than)
```

### Linux / macOS (bash)

```bash
./scripts/dev.sh              # dev: 8011 + 5183
./scripts/build.sh            # build -> app/webui
./scripts/run.sh              # prod: 8010

# tuy chon
./scripts/dev.sh --port 8011 --skip-install
./scripts/run.sh --port 8010 --host 127.0.0.1 --no-build --reload
```

### Script làm gì tự động?

- Tạo `.venv` nếu chưa có, `pip install -r requirements.txt`, `scrapling install` (best-effort).
- `npm install` cho `frontend/` nếu thiếu `node_modules`.
- `python scripts/init_db.py` nếu chưa có `novel2epub.db`.
- `dev`: chạy backend `--reload` ở background rồi `npm run dev` ở foreground (Ctrl+C dừng cả hai).
- `build`: `npm run build` → `app/webui/` (Vite outDir).
- `run`: kiểm tra build, tự build nếu thiếu (trừ khi `--no-build`), rồi `uvicorn app.main:app --host 127.0.0.1 --port 8010`.

> Prefer `dev` khi code SPA (Vite proxy `/api` → `127.0.0.1:8011`). Prefer `run` khi muốn test đúng bundle production mà FastAPI sẽ phục vụ tại `/app`.

---

## Yêu Cầu Hệ Thống

| Thành phần | Yêu cầu |
|---|---|
| Python | 3.10+ (khuyên 3.11) |
| Node.js | 18+ (khuyên 20 LTS) + npm 9+ |
| DB | SQLite (đã có sẵn theo Python, file `novel2epub.db`) |
| Crawl | `scrapling[fetchers]` + `scrapling install` (tự động bởi scripts) |
| Build desktop | Rust toolchain (chỉ khi `tauri:build`) |

---

## Cài Đặt Thủ Công

Nếu không dùng scripts quick-start:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
scrapling install
python scripts/init_db.py           # tao novel2epub.db tu novel2epub.example.yaml
```

Local MT (tùy chọn, cho `translate.type=localmt`):

```powershell
pip install ctranslate2 sentencepiece huggingface_hub
```

Frontend (lần đầu):

```powershell
cd frontend
npm install
npm run dev       # http://localhost:5183 (can backend o 8011)
```

Backend thủ công:

```powershell
uvicorn app.main:app --reload --port 8011   # dev (cho Vite proxy)
uvicorn app.main:app --reload --port 8010   # prod/Jinja2
# hoac
python -m uvicorn app.main:app --reload --port 8010
```

Build production thủ công:

```powershell
cd frontend
npm run build            # -> ../app/webui/ (ban web, base /app/)
npm run build:tauri      # -> ../app/webui/ (ban Tauri, base ./)
```

---

## Cách Dùng: Web UI + CLI

### Web UI

1. Mở `http://127.0.0.1:8010/app/` (SPA) hoặc `http://127.0.0.1:8010/` (Jinja2).
2. **Thư viện** → tạo ebook: chọn source preset hoặc dán URL mục lục → kiểm tra `toc_url`/selector.
3. Chạy lần lượt **TOC → Crawl → Translate → Build** (có thể chạy trọn pipeline `run`).
4. Vào trang **Chương** để đọc, sửa từng đoạn, đối chiếu 3 cột, duyệt bản nháp AI.

SPA dev: `scripts/dev.ps1` hoặc `npm run dev` trong `frontend/` + backend ở `8011`. Vite proxy mọi `/api`, `/opds`, `/ebooks`... sang backend (xem `frontend/vite.config.ts`).

### CLI

Mọi lệnh theo ebook dùng `-e <slug>`; DB khác mặc định dùng `-c <path>`.

```powershell
python -m novel2epub list
python -m novel2epub -e <slug> toc
python -m novel2epub -e <slug> crawl --from 1 --to 10
python -m novel2epub -e <slug> translate --missing
python -m novel2epub -e <slug> cleanup-han --from 1 --to 10
python -m novel2epub -e <slug> build
python -m novel2epub -e <slug> run          # tron pipeline
```

Lọc/chọn chương nâng cao:

```powershell
python -m novel2epub -e <slug> chapters --sort title --filter raw:no
python -m novel2epub -e <slug> crawl --filter raw:no --range 1:20
python -m novel2epub -e <slug> translate --search "Chương 10" --range 1:5
```

Lệnh khác: `evaluate`, `reindex`, `search`, `models`, `backup`, `restore`, `service`, `baseline-backfill`, `dataset-backfill`, `wireguard`, `clean-toc`.

```powershell
# Tim truyen tren cac source
python -m novel2epub search "ten truyen" --limit 5

# Kiem endpoint OpenAI-compatible
python -m novel2epub models
python -m novel2epub models --free --format json
```

Đổi vị trí DB:

```powershell
$env:NOVEL2EPUB_DB = "D:\data\novel2epub.db"
uvicorn app.main:app --port 8010
# NOVEL2EPUB_FILE / NOVEL2EPUB_CONFIG van hoat dong nhu fallback nhung phai tro toi file .db
```

---

## Kiến Trúc & Pipeline

```
novel2epub/        domain logic: pipeline, crawler, translator, storage, EPUB
app/               FastAPI + Jinja2 + SPA mount + job queue + scheduler
  routes/          route theo domain (ebooks, chapters, glossary, jobs, ...)
  queue.py         JobQueue: crawl / local-mt / ai-translate / ai-edit / build / automation
  scheduler.py     AutomationScheduler (cron, chay bu toi da 1 lan)
frontend/          SPA React (Vite + TS + TanStack Query + Tailwind v4 + daisyUI)
scripts/           init_db, migrate, check_openai_endpoint + dev/build/run quick-start
tests/             unit + integration + route
```

Pipeline idempotent theo trạng thái chương (`force`, range, filter để chạy lại có chủ đích):

1. `fetch-toc` — đọc metadata + danh sách chương → cập nhật manifest trong DB.
2. `crawl` — tải raw cho chương chưa có hoặc phạm vi được chọn (hỗ trợ TOC/chương phân trang).
3. `translate` — tạo MT snapshot + bản dịch có thể biên tập (theo nhánh `local_mt` / `ai`).
4. `cleanup-han` — (tùy chọn) AI biên tập xử lý chữ Hán còn sót (`local_mt` mặc định, có thể `openai`).
5. `build` — đóng gói chương hợp lệ thành EPUB (kèm bìa, metadata, series, chú thích glossary).
6. `publish-reader` — (tùy chọn) đồng bộ tăng dần sang novel-reader qua Supabase (giữ nguyên `chapters.id`).

Xem chi tiết: [Kiến trúc hệ thống](docs/architecture.md)

### Diagrams (out/)

6 interactive Archify diagrams (showcase validated) trong `out/archify/` — mo truc tiep file HTML de doi theme, pan/zoom, search, trace:

| Diagram | File | Mo ta |
|---|---|---|
| Architecture | `out/archify/architecture.html` | SPA + FastAPI + Queue + Scrapling + SQLite + EPUB + Reader |
| Pipeline | `out/archify/pipeline.html` | fetch-toc → crawl → translate → duyet → build → publish |
| Queue | `out/archify/queue.html` | cron / UI → JobQueue phan loai → Pool Gate → Worker |
| Sequence | `out/archify/crawl_translate.html` | user → Web UI → FastAPI → Queue → Scrapling → Translator |
| Dataflow | `out/archify/context.html` | Raw/TOC → MT Stream → SQLite → Segments → EPUB/Reader |
| Lifecycle | `out/archify/chapter.html` | Vong doi chuong: discovered → ready |

Mo tong hop: `out/index.html` (gallery) — tat ca JSON nguon ke ben (`*.json`). Anh chup desktop 1440x900 & 2048x1320 nam trong `*.visual-check.png` (pending review).

---

## Cấu Hình (3 Tầng)

```
defaults → source preset → ebook overrides
```

- **Defaults**: giá trị chung trong `settings` (DB).
- **Source preset**: thiết lập crawl theo website (chỉ crawl).
- **Ebook overrides**: ưu tiên cao nhất; `translate` và `ai` có thể override theo ebook.

`novel2epub.example.yaml` chỉ là **seed** cho `scripts/init_db.py`, không phải runtime config. Runtime chỉnh qua Web UI và có thể export/import YAML theo ebook.

Đổi DB path: `NOVEL2EPUB_DB` (khuyên dùng) hoặc fallback `NOVEL2EPUB_FILE`/`NOVEL2EPUB_CONFIG` (vẫn phải trỏ tới `.db`).

Nhóm config chính:

| Nhóm | Field tiêu biểu |
|---|---|
| `crawl` | `toc_url`, `chapter_link_pattern`, `content_selector`, `max_chapters`, `max_workers`, `concurrency_cap`, `delay_seconds`, `strip_patterns`, `crawl.scrapling` (`mode`, `solve_cloudflare`, `proxy`, ...) |
| `translate` | `type` (`openai`/`localmt`/`none`), `source_language`, `genre`, `chunk.max_chars`, `batch_size`, `auto_glossary`, `cleanup_han.engine` |
| `ai` | `ai.openai` cho review/rewrite/glossary/cleanup (fallback `translate.openai` nếu trống) |
| `output` | `epub_path` (trống = `<data_dir>/data/<slug>/<title> - <author>.epub`), `data_dir` (ép về thư mục chứa DB) |
| `queue` | `crawl_workers`, `translate_workers`, `local_mt_workers`, `ai_edit_workers`, `build_workers`, `automation_workers` |
| `reader` | global: `url`, `service_key`, `batch_size`, `push_anchors`; per-ebook: `slug`, `free_chapters` |
| `wireguard` | global: `enabled`, `profiles_dir`, `wg_exe`, `manage_service`, `wgcf.*` |

Chi tiết: [Cấu hình](docs/configuration.md)

---

## Dịch & Biên Tập

Backend chọn qua `make_translator`:

- `openai` — API OpenAI-compatible (`OpenAITranslator`), dịch tiêu đề + nội dung trong 1 request, prompt kèm glossary/idiom/genre/nhân vật.
- `localmt` — CTranslate2 cục bộ (`LocalMTTranslator`, package `novel2epub.hachimimt`), dịch tiêu đề riêng rồi mới thân chương.
- `none` — passthrough (giữ nguyên). Nếu `source_language=vi` thì luôn passthrough.

Glossary theo ebook, idiom dùng chung, bảng nhân vật/xưng hô → đều được đưa vào prompt. Có thể biên tập từng đoạn, AI review/rewrite, cleanup Hán còn sót, và thao tác hàng loạt (bulk preview → confirm, token 30 phút, fingerprint `config_hash`).

Xem: [Dịch và biên tập](docs/translation.md)

---

## Frontend SPA & Tauri

- **Stack**: Vite + React 19 + TypeScript + TanStack Query + react-router + Tailwind v4 + daisyUI.
- **Dev**: `scripts/dev.ps1` (khuyên) hoặc `cd frontend; npm run dev` (cần backend ở `8011`).
- **Build web**: `scripts/build.ps1` hoặc `cd frontend; npm run build` → `app/webui/` (FastAPI mount tại `/app`).
- **Build Tauri**: `npm run build:tauri` (`--mode tauri`, base `./`) rồi `npm run tauri:build` (cần Rust).
- **PWA**: `vite-plugin-pwa` precache asset đã hash, scope `/app/`, không cache `/api/*`.
- **Trang Chương** (`/app/ebooks/{slug}/chapters/{index}`): đọc + sửa từng đoạn + đối chiếu 3 cột + duyệt nháp AI trong 1 request (`GET /api/ui/ebooks/{slug}/chapters/{index}`).

Khi bundle đã build, `GET /` redirect `307` sang `/app/`; Jinja2 lùi về `/library` nhưng vẫn phục vụ đầy đủ cho phần chưa port.

Chi tiết: [Kiến trúc — SPA](docs/architecture.md#giao-diện-spa-frontend) và [Phát triển](docs/development.md)

---

## Backup / Restore

```powershell
python -m novel2epub backup
python -m novel2epub backup --out D:/backup/library.db
python -m novel2epub restore --from backups/novel2epub-YYYYMMDD-HHMMSS.db
# --yes chi dung trong automation da kiem soat (restore tu tao pre-restore backup)
```

Dùng SQLite backup API nên an toàn khi Web UI đang chạy — không copy file DB trực tiếp. DB có thể chứa API key / Supabase service-role key → bảo vệ file backup như secret.

---

## OPDS cho readest

Catalog tại `/opds` liệt kê ebook đã build để readest tải EPUB trực tiếp.

1. **Tạo token** ở Cài đặt → API.
2. **Bind LAN**: `uvicorn app.main:app --host 0.0.0.0 --port 8010` (mặc định chỉ `127.0.0.1`).
3. Trong readest thêm OPDS: URL `http://<IP-LAN>:8010/opds`, Password = token.
4. Chỉ ebook đã build mới hiện. Có **auto-build** khi gọi catalog (Cài đặt → API → `auto_build`, bật mặc định): job `opds-autobuild:<slug>` chạy nền, EPUB chỉ chứa chương **đã dịch**, feed trả ngay không chờ build, mỗi ebook nghỉ 5 phút giữa 2 lần build.

Chi tiết: [Vận hành — OPDS](docs/operations.md#đọc-bằng-readest-qua-opds)

---

## WireGuard / wgcf

Profile nằm ngoài DB (file trong `profiles_dir`); SQLite chỉ lưu metadata, không bao giờ chứa private key.

```powershell
python -m novel2epub wireguard config
python -m novel2epub wireguard set enabled true
python -m novel2epub wireguard import path/to/x.conf --name x
python -m novel2epub wireguard list --scan
python -m novel2epub wireguard activate <id|filename>
python -m novel2epub wireguard provision --label warp.conf
```

Web UI: `/wireguard`. Pipeline `crawl`/`toc` chưa tự bọc WireGuard — nếu cần, bọc job bằng `wireguard_network_scope` ở tầng job (giữ 1 profile suốt job, không rotate giữa request).

Chi tiết: [Vận hành — WireGuard](docs/operations.md#vị-trí-wireguard-và-pipeline) và [Cấu hình — WireGuard](docs/configuration.md#wireguard-chỉ-toàn-cục)

---

## API Docs

FastAPI tự sinh:

- Swagger UI: `http://127.0.0.1:8010/docs`
- ReDoc: `http://127.0.0.1:8010/redoc`
- OpenAPI JSON: `http://127.0.0.1:8010/openapi.json`

Từ localhost không cần token; từ máy khác gửi `Authorization: Bearer <token>`. `POST /api/ebooks/{slug}/glossary/proper-names/extract` nằm trong nhóm **Glossary**.

---

## Phát Triển & Kiểm Thử

```powershell
# Test
pytest tests -v
pytest tests/test_crawler.py -v
pytest tests/test_translator.py -v
pytest --collect-only -q

# Frontend
cd frontend
npm run typecheck
npm run test        # vitest
npm run build       # -> ../app/webui
```

Nguyên tắc:

- SQLite là nguồn sự thật duy nhất — không thêm sidecar runtime mới nếu dữ liệu thuộc trạng thái hệ thống.
- Domain logic nằm trong `novel2epub/`; route chỉ parse request và gọi logic.
- Thay schema phải có migration + test dữ liệu cũ; không log API key / service-role key.
- Không commit DB, raw/bản dịch, EPUB, log hay secret.

Chi tiết: [Phát triển và kiểm thử](docs/development.md)

**Tự host model dịch trên Colab/Kaggle**: `notebooks/novel2epub_zhvi_server.ipynb` dựng endpoint OpenAI-Compatible miễn phí (Qwen/Sailor), expose qua tunnel để dùng làm Dịch API + AI biên tập. Xem [hướng dẫn](docs/operations.md#tự-host-model-dịch-trên-colabkaggle).

---

## Xử Lý Sự Cố

| Triệu chứng | Kiểm tra |
|---|---|
| TOC rỗng | URL, `chapter_link_pattern`, thử `fetcher` → `dynamic`, `stealthy` + `solve_cloudflare` |
| Raw sai/rỗng | `content_selector`, encoding, phân trang, `strip_patterns`, crawl lại 1 chương `--force` |
| 429 / anti-bot | Giảm `max_workers`, tăng `delay_seconds`, hạ `concurrency_cap`, proxy/mode browser |
| Dịch lỗi/timeout | `python -m novel2epub models`, chunk/batch/timeout/worker, API key/quota, log job |
| EPUB thiếu chương | Lọc `translated:no` / `missing:yes`, chương `skipped`, build lại sau khi đủ dữ liệu |
| Vite proxy lỗi | Backend phải ở `8011` (hoặc đặt `N2E_DEV_API_TARGET` trong `frontend/.env.local`), kiểm tra `vite.config.ts` |
| Cổng bị chiếm | Đổi `-Port` khi gọi `scripts/dev.ps1` / `scripts/run.ps1`, hoặc `N2E_DEV_API_TARGET` |

Thêm nữa: [Vận hành — Xử lý sự cố](docs/operations.md#xử-lý-sự-cố)

---

## Tài Liệu Chi Tiết

- [Kiến trúc hệ thống](docs/architecture.md)
- [Cấu hình](docs/configuration.md)
- [Hướng dẫn vận hành](docs/operations.md)
- [Dịch và biên tập](docs/translation.md)
- [Phát triển và kiểm thử](docs/development.md)
- [Release, Vercel và Tailscale](docs/release.md)
- [Giao diện SPA](docs/architecture.md#giao-diện-spa-frontend)
- [Server dịch zh→vi trên Colab/Kaggle](notebooks/novel2epub_zhvi_server.ipynb)

---

## Giới Hạn

- Nội dung VIP / cần đăng nhập chỉ crawl được khi nguồn và phiên cho phép.
- Cấu trúc website có thể đổi; selector và preset cần bảo trì.
- Chất lượng dịch phụ thuộc backend, model, prompt, glossary và bước biên tập.
- Chỉ sử dụng nội dung khi bạn có quyền truy cập và tuân thủ điều khoản của nguồn.

