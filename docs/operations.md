# Vận Hành

## Tạo Ebook

Quy trình khuyến nghị trên Web UI:

1. Mở Thư viện và tạo ebook từ kết quả tìm kiếm hoặc URL.
2. Chọn source preset phù hợp, kiểm tra `toc_url` và selector.
3. Giới hạn `max_chapters` ở 2-3 chương, lấy TOC rồi crawl thử.
4. Kiểm tra raw; sửa selector hoặc strip pattern nếu nội dung lẫn quảng cáo.
5. Chọn backend dịch, dịch thử và kiểm tra glossary/xưng hô.
6. Bỏ giới hạn chương và chạy pipeline đầy đủ.

## Swagger Và OpenAPI

FastAPI tạo tài liệu API trực tiếp từ route/schema:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

Khi gọi từ localhost, middleware cho phép thao tác không cần token. Khi backend được truy cập từ máy khác, gửi `Authorization: Bearer <token>`; không dán token vào URL hoặc log. Endpoint trích tên riêng có schema đầy đủ trong nhóm **Glossary** tại `POST /api/ebooks/{slug}/glossary/proper-names/extract`.

## CLI

Mọi lệnh theo ebook dùng `-e <slug>`; DB khác mặc định dùng `-c <path>`.

```sh
python -m novel2epub list
python -m novel2epub -e book toc
python -m novel2epub -e book crawl --from 1 --to 10
python -m novel2epub -e book translate --missing
python -m novel2epub -e book cleanup-han --from 1 --to 10
python -m novel2epub -e book build
python -m novel2epub -e book run
```

Chọn chương theo danh sách đã sort/filter:

```sh
python -m novel2epub -e book chapters --sort title --filter raw:no
python -m novel2epub -e book crawl --filter raw:no --range 1:20
python -m novel2epub -e book translate --search "Chương 10" --range 1:5
```

Các lệnh bổ sung: `evaluate`, `reindex`, `search`, `models`, `backup`, `restore`, `service`, `baseline-backfill`.

`baseline-backfill` tạo baseline cho ledger hai chiều (schema v13): snapshot
từng nhánh chương đã khởi tạo vào `chapter_revisions` với `revision_number` =
revision hiện hành của nhánh, hash canonical full SHA-256, không đổi dữ liệu
hiện hành. Idempotent — chạy lại không sinh trùng, có thể chạy theo nhánh:

```sh
python -m novel2epub -e book baseline-backfill            # cả hai nhánh
python -m novel2epub -e book baseline-backfill --branch ai
python -m novel2epub -e book baseline-backfill --branch local_mt
```

### WireGuard / wgcf (không cần ebook)

```sh
python -m novel2epub wireguard config          # cấu hình toàn cục (không chứa key)
python -m novel2epub wireguard set enabled true
python -m novel2epub wireguard set wgcf.executable C:/tools/wgcf.exe
python -m novel2epub wireguard set wgcf.argv "register,--token,ABC"
python -m novel2epub wireguard provision --label warp.conf   # chạy wgcf trong cwd tạm, nhập profile, dọn artifact
python -m novel2epub wireguard import path/to/x.conf --name x
python -m novel2epub wireguard list --scan
python -m novel2epub wireguard status
python -m novel2epub wireguard enable <id|filename>
python -m novel2epub wireguard disable <id|filename>
python -m novel2epub wireguard activate <id|filename>
python -m novel2epub wireguard rotate
python -m novel2epub wireguard remove <id|filename>
```

WireGuard/wgcf hoạt động độc lập với ebook. `wgcf.argv` và `wgcf.executable` phải do người dùng cấu hình tường minh (hệ thống không tự bịa cờ). Kích hoạt profile (`activate`/`rotate`) chạy vòng đời tunnel service thật của WireGuard for Windows và đòi hỏi `wireguard.manage_service=true` (ngược lại bị từ chối). Scope mạng (`wireguard_network_scope`) chỉ chọn id profile + giữ khóa, metadata-only — không thay đổi trạng thái active hay service.

Ngoài CLI, có Web UI toàn cục tại **`/wireguard`** (menu WireGuard): hiển thị cấu hình đã làm sạch + metadata profile, lưu cấu hình toàn cục, nhập `.conf` (giới hạn kích thước), quét thư mục, cung cấp wgcf, enable/disable/set thứ tự/activate/rotate/xóa. Mọi lỗi domain map về HTTP status sạch; xóa profile đang active bị từ chối (`409`); không endpoint nào hiển thị/tải nội dung cấu hình hoặc private key — URL thao tác dùng id profile opaque.

## Automation

Một automation gồm ebook, cron năm trường và danh sách có thứ tự từ:

```text
fetch-toc, crawl-new, translate-pending, cleanup-han, build, publish-reader
```

Ví dụ `0 3 * * *` chạy lúc 03:00 mỗi ngày. Scheduler polling khoảng 30 giây, không chạy trùng một chuỗi cho cùng thời điểm và chạy bù tối đa một lần sau downtime.

Tại trang chi tiết ebook, thanh pipeline có nút **Tự động**. Nếu ebook đã có workflow, UI hiển thị trước thứ tự bước, lịch và số luồng rồi mới cho chạy. Nếu chưa có, UI cho chọn bước, tạo workflow lịch `manual` và chạy ngay; cron có thể chỉnh tiếp tại trang **Tự động hóa**. Nút **Tải EPUB** trên cùng thanh chỉ bật sau khi ebook đã được build và tải qua `/ebooks/{slug}/download`.

## Chạy Nền

```sh
python -m novel2epub service install --host 127.0.0.1 --port 8010
python -m novel2epub service status
python -m novel2epub service uninstall
```

Windows dùng Task Scheduler theo phiên đăng nhập. Linux dùng systemd user service; chạy trước khi đăng nhập cần bật linger cho user.

## Nhật Ký

Nhật ký runtime của crawler/dịch/biên tập/build/queue/scheduler được lưu **trong DB SQLite thống nhất**, bảng `app_logs` (từ schema v22) — không còn file `logs/app.log` xoay vòng như trước. Log đi cùng bản backup `.db` và lọc/xoá được bằng SQL.

Đặc điểm vận hành:

- **Ghi bất đồng bộ theo lô**: dòng log được đệm trong RAM rồi flush mỗi giây (hoặc khi đủ 100 dòng). Crash cứng có thể mất ≤ 1 giây log cuối; job history vẫn ghi transactional riêng nên không ảnh hưởng.
- **Retention tự động**: giữ tối đa ~100.000 dòng mới nhất; prune chạy định kỳ khi ghi.
- Job đang chạy hiển thị log trực tiếp trên UI Hàng đợi qua buffer trong bộ nhớ — bản trong `app_logs` là nơi lưu trữ dài hạn.

Trang **Nhật ký** (`/logs`) trên Web UI hỗ trợ:

- Mỗi dòng log hiển thị gọn trên **một hàng**; nội dung dài (đặc biệt traceback lỗi) được rút gọn bằng dấu "…" — bấm vào dòng để mở chi tiết đầy đủ, bấm lần nữa để thu gọn.
- Rê chuột lên dòng hiện nút **Copy** (sao chép nguyên dòng kèm thời gian/mức/nguồn) và **Xoá** (xoá đúng dòng đó khỏi DB).
- Lọc server-side theo mức (CRITICAL/ERROR/WARNING/INFO/DEBUG, chip kèm số đếm), theo nguồn (logger, vd `novel2epub.crawler`) và tìm chuỗi trong nội dung.
- Theo dõi trực tiếp (tự tải lại mỗi 3 giây) hoặc tạm dừng để cuộn tự do; "Tải dòng cũ hơn" phân trang theo con trỏ ổn định kể cả khi log mới cứ ghi thêm.
- **Xuất** file `.txt` đúng bộ lọc đang mở; **Dọn** xoá theo lựa chọn: toàn bộ / cũ hơn 7–30 ngày / chỉ dòng khớp bộ lọc.

API tương ứng (đều dưới tiền tố `/api/ui`, cần token khi gọi từ máy khác):

| Endpoint | Ý nghĩa |
| --- | --- |
| `GET /api/ui/logs?q=&levels=&source=&limit=&before_id=` | Trang log mới nhất khớp bộ lọc |
| `GET /api/ui/logs/stats` | Tổng số dòng, đếm theo mức, biên thời gian |
| `GET /api/ui/logs/sources` | Danh sách logger đã ghi kèm số dòng |
| `GET /api/ui/logs/{id}` | Chi tiết đầy đủ 1 dòng |
| `DELETE /api/ui/logs/{id}` | Xoá đúng 1 dòng |
| `DELETE /api/ui/logs?older_than_days=30` | Xoá nhật ký (toàn bộ hoặc theo mốc/bộ lọc), trả số dòng đã xoá |
| `GET /api/ui/logs/export` | Tải `.txt` định dạng giống app.log cũ |

Endpoint cũ `GET /api/logs[/{source}]` và `DELETE /api/logs/{source}` vẫn hoạt động nhưng giờ truy vấn SQLite thay vì đọc file; `source=app` được hiểu là toàn bộ nhật ký.

File log cũ `logs/app.log*` không bị xoá khi nâng cấp — dọn tay khi không còn cần đối chiếu.

## Backup Và Restore

```sh
python -m novel2epub backup
python -m novel2epub backup --out D:/backup/library.db
python -m novel2epub restore --from D:/backup/library.db
```

Restore tự tạo pre-restore backup và yêu cầu xác nhận. Dùng `--yes` chỉ trong automation đã kiểm soát.

Nên backup định kỳ và giữ ít nhất một bản ở ổ đĩa khác. DB có thể chứa API key và Reader service-role key, vì vậy backup phải được bảo vệ như secret.

## Đọc Bằng Readest Qua OPDS

novel2epub lộ một catalog OPDS (`/opds`) liệt kê mọi ebook đã build, cho phép readest (web, desktop, mobile) tải và cập nhật EPUB trực tiếp mà không cần copy file thủ công.

**1. Sinh token API**

Vào Cài đặt > API trong Web UI, bấm sinh token mới rồi lưu lại. Token này dùng để xác thực mọi request đến `/opds` và `/api/v1/...` từ máy khác — request từ chính máy chạy server (localhost) luôn được miễn token.

**2. Chạy server cho máy khác truy cập được**

Mặc định `uvicorn --reload` chỉ bind `127.0.0.1`, máy khác trong LAN không vào được. Bind `0.0.0.0` để mở ra LAN:

```sh
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Tìm IP LAN của máy (`ipconfig` trên Windows, `ip addr` trên Linux) để dùng ở bước sau, ví dụ `192.168.1.50`.

> **Cảnh báo:** bind `0.0.0.0` mở ra LAN **toàn bộ Web UI**, không riêng gì OPDS — ai vào được `/opds` từ cùng mạng thì cũng vào được `/settings`, `/queue` và mọi route khác. Chỉ làm việc này trên mạng tin cậy (nhà riêng). Trên mạng không tin cậy (quán café, mạng công ty dùng chung, v.v.), đặt server sau một reverse proxy có TLS + xác thực riêng, hoặc dùng Tailscale/VPN để chỉ thiết bị của bạn thấy được server — không bind thẳng `0.0.0.0` ra mạng đó.

**3. Thêm catalog trong readest**

Trong readest, thêm nguồn OPDS mới với:

- URL: `http://<IP-LAN>:8010/opds`
- Username: để trống
- Password: dán token đã sinh ở bước 1

readest sẽ hiện danh sách ebook đã build, kèm bìa và metadata (tiêu đề, tác giả, mô tả lấy từ feed — feed được readest ưu tiên hơn metadata nhúng trong EPUB).

**4. Ebook phải được build trước**

Chỉ ebook đã build EPUB (có file `.epub` tồn tại) mới xuất hiện trong catalog. Ebook mới tạo hoặc chưa build sẽ không hiện.

### Tự Động Build Khi Gọi Catalog

Mặc định **bật** (Cài đặt > API > `auto_build`). Mỗi lần readest gọi `/opds` hoặc `/opds/books`, novel2epub soi mọi ebook chưa archive và đẩy job build **nền** cho ebook nào:

- chưa từng build EPUB, hoặc
- có bản dịch mới hơn file EPUB hiện có.

Bốn điều cần biết về hành vi này:

**Feed không chờ build.** Request trả về ngay lập tức; job chạy trong hàng đợi category `build`. Ebook vừa được đẩy job chưa có file nên **chưa lên feed lần này** — nó xuất hiện ở lần readest làm mới kế tiếp. Đây là cố ý: ebook lớn nhất 2907 chương, build ngay trong request sẽ khiến readest timeout và người dùng chỉ thấy "Failed to load OPDS feed".

**EPUB tự build chỉ chứa chương ĐÃ DỊCH.** Khác đường build tay (nút Build, CLI `build`) vốn rơi về `raw_text` chữ Hán khi chương chưa dịch. Chương rơi-về-raw không được gắn neo `data-n2e-p` nên cũng không sửa được từ readest — đưa vào chỉ tổ làm bẩn sách.

**Ebook đang có job dịch chạy thì được để yên.** Build giữa lúc bản dịch còn đang chảy vào DB chỉ đóng gói một ảnh chụp cũ ngay lập tức.

**Mỗi ebook nghỉ 5 phút giữa hai lần build.** readest hỏi lại catalog mỗi lần mở app và mỗi lần kéo-để-làm-mới; không có mốc nghỉ này thì mỗi cú kéo lại đẻ thêm một job cho cùng cuốn sách. Mốc nghỉ giữ trong RAM nên restart server sẽ xoá — cùng lắm tốn thêm một lần build dư.

Theo dõi tiến độ ở `/queue` (job tên `opds-autobuild:<slug>`) và `/logs`. Tắt cờ `auto_build` thì quay về build tay hoàn toàn qua nút Build hoặc Automation.

## Bảng Chương Ở Trang Truyện

`GET /api/ui/ebooks/{slug}/chapters` nhận `offset`/`limit` (limit tối đa 500) cùng
các bộ lọc dưới đây; web UI cho chọn 25/50/100/200/500 dòng mỗi trang và có thanh
phân trang ở cả đầu lẫn chân bảng. Bộ lọc, cỡ trang và trang hiện tại được nhớ theo
từng truyện trong `localStorage`.

| Tham số | Ý nghĩa |
| --- | --- |
| `filter_raw` | Có bản gốc đã crawl. |
| `filter_translated` | Nhánh **đang hoạt động** có bản dịch — thứ đi vào EPUB/Reader. |
| `filter_local_mt` | Nhánh `local_mt` có bản dịch, không phụ thuộc nhánh nào đang hoạt động. |
| `filter_ai` | Nhánh `ai` có bản dịch, không phụ thuộc nhánh nào đang hoạt động. |
| `filter_title_error` | `yes` = chỉ chương có tiêu đề sai mẫu. |
| `filter_missing` | Manifest thiếu trường (url/title/duplicate). |
| `filter_skipped` | Chương bị đánh dấu bỏ qua. |

Ba bộ lọc nhánh độc lập nhau nên kết hợp được, ví dụ `filter_local_mt=yes&filter_ai=no`
ra đúng tập chương đã có bản dịch máy nhưng chưa có bản AI.

### Tiêu đề đúng mẫu

`novel2epub.toc.title_format_ok` coi ba dạng sau là hợp lệ (không phân biệt hoa
thường, số chương cho phép hậu tố `.1`/`-2`):

- `Chương 5`
- `Chương 5: Tên chương`
- `Chương 5 Tên chương`

Tiêu đề rỗng cũng tính là lỗi. Cờ nằm ở trường `title_format_ok` của mỗi dòng và
tính trên tiêu đề thật của nhánh đang hoạt động, không tính trên `visible_title`
(trường đó có fallback `Chương {index}` nên luôn đúng mẫu). Bảng chương hiện badge
"Tiêu đề lỗi" ở cột trạng thái; dùng **Chuẩn hóa TOC** hoặc **Dịch tiêu đề** để sửa.

## Hành Động Hàng Loạt Chương (Bulk)

Web UI thao tác nhiều chương qua hai bước *preview → confirm* thay vì ghi thẳng:

- `POST /api/ui/ebooks/{slug}/chapters/bulk-preview` — KHÔNG đổi trạng thái, không gọi
  model. Trả token có hạn (30 phút, dùng một lần) kèm danh sách từng chương đủ điều
  kiện/lý do từ chối và vân tay workspace (`config_hash` + fingerprint mỗi chương).
- `POST /api/ui/ebooks/{slug}/chapters/bulk-confirm` — nhận token, xác thực rồi mới
  thực thi. Token hết hạn/đã dùng, hoặc config/chương đổi kể từ lúc preview → `409`,
  phải preview lại. Action dài (`translate`, `local-mt`, `ai-edit`, `build`) chạy
  qua job nền; `switch-branch`, `skip`, `unskip`, `delete-translation` chạy đồng bộ.

`action` nhận: `translate`, `local-mt`, `ai-edit` (chỉ biên tập bản dịch Local
MT), `switch-branch`, `skip`, `unskip`, `delete-translation`, `build` (build strict —
chặn chương chưa có bản dịch ở nhánh đang hoạt động). Logic đánh giá nằm trong
`novel2epub/bulk_contract.py`; token lưu bảng `bulk_tokens`.

Endpoint `/chapters/bulk` cũ (ghi thẳng) vẫn chạy nhưng **deprecated** — client mới
nên dùng preview/confirm. `set-branch` của nó map sang `switch-branch` của hợp đồng mới.

### Biên tập AI ghi trực tiếp (có xác nhận)

Nút "Biên tập AI" (trang chương và trang truyện) không đi qua preview/confirm: nó bắn
thẳng `POST /api/ui/ebooks/{slug}/chapters/ai-edit` với body `{"indexes": [...], "confirm": true}`
và nhận về `{status: "queued", job_id, queued, skipped, indexes, blocked}` — một cú bấm
là một job trong category `ai-edit`, không có hộp thoại token.

Thiếu `confirm: true` → `400`. Bỏ được hai vòng token vì hành động này được chấp nhận
rủi ro ghi đè có chủ đích: kết quả AI **ghi đè trực tiếp nhánh `local_mt`** (bản Local
MT gốc được lưu vào snapshot trước lần biên tập đầu tiên và không bị đè lại), nhánh
`ai` và `active_branch` không đổi. Việc ghi dùng optimistic lock — nếu bản dịch đổi
đồng thời lúc job chạy thì chương bị bỏ qua (log lỗi) thay vì ghi đè nhầm.

Vân tay workspace của hợp đồng bulk sinh ra để chặn ghi đè nhầm nên ở đây không có
việc để làm. Route tự lọc chương chưa có bản dịch Local MT (đọc file, không gọi model)
để trả ngay `skipped`/`blocked`; job vẫn chạy
`step_ai_edit_local_mt_bulk` nên chương mất bản Local MT trong lúc chờ hàng đợi vẫn bị
chặn đúng lúc thực thi. Không chương nào đủ điều kiện → `409`, không enqueue.

Alias `POST /api/ui/ebooks/{slug}/chapters/ai-edit-draft` (body cũ `{"indexes": [...]}`,
không cần `confirm`) giữ nguyên path cho client cũ nhưng có cùng hành vi ghi trực tiếp;
action `ai-edit-draft` của hợp đồng bulk cũng còn cho CLI/API cũ. Cả hai map sang action
canonical `ai-edit`.

## Tách Giao Diện Khỏi Máy Chạy Backend

SPA (`/app`) là file tĩnh nên có thể để trên Vercel/Cloudflare Pages, còn
backend nằm trên máy ở nhà và ra ngoài qua Tailscale.

### Dùng `serve`, không dùng `funnel`

```sh
tailscale serve --bg 8010
```

Lệnh này cấp `https://<máy>.<tailnet>.ts.net` có chứng chỉ thật nhưng **chỉ
thiết bị trong tailnet mới resolve và tới được**. Trang trên Vercel là công
khai — không sao, nó chỉ là HTML/JS — nhưng lời gọi API từ đó chỉ thành công
trên máy đã bật Tailscale.

`tailscale funnel` thì mở backend ra Internet công cộng. Chỉ dùng nếu bạn thực
sự cần, và hiểu rằng lúc đó token API là thứ duy nhất đứng giữa người lạ và
quyền điều khiển crawler.

### Cấu hình phía server

1. **Đặt token** ở Cài đặt > API. Bắt buộc: mọi request `/api/*` và `/opds/*`
   từ ngoài localhost đều bị từ chối nếu chưa có token (`api_token_gate` trong
   `app/main.py`). Chưa đặt token thì trả 503 chứ không phải 401 — đó là lỗi
   cấu hình server, không phải lời mời đăng nhập.
2. **Thêm origin** của frontend vào `api.cors_origins` (cùng trang Cài đặt >
   API), ví dụ `https://xuong.vercel.app`. Không bao giờ dùng `*`.

Hai giá trị này đọc lại mỗi request nên sửa xong có hiệu lực ngay, không cần
restart.

### Cấu hình phía frontend

Đặt biến môi trường lúc build trong dashboard Vercel/Cloudflare Pages:

```text
N2E_API_BASE=https://<máy>.<tailnet>.ts.net
```

Build command `npm --prefix frontend run build`, thư mục xuất `app/webui`.
Token nhập một lần ở trang **Kết nối** trong app và lưu ở `localStorage` —
không nung vào bundle, vì bundle là file công khai.

### Điều còn hạn chế

Web UI Jinja2 vẫn là công cụ chạy tại chỗ. Mở qua `http://localhost:8010` thì
không đổi gì, nhưng mở qua địa chỉ tailnet thì các lời gọi `/api/*` của nó sẽ
nhận 401 — nó không có chỗ nào để nhập token. Các trang chưa được port sang
SPA cũng vậy: SPA link sang chúng bằng URL tuyệt đối trỏ về backend, mở được
nhưng phần JavaScript gọi API bên trong sẽ hỏng khi truy cập từ xa. Cho tới
khi port xong, hãy dùng SPA từ xa và để dành UI cũ cho lúc ngồi tại máy.

## Vị Trí WireGuard Trong Pipeline

Phiên bản WireGuard hiện tại cung cấp bộ quản lý profile + cung cấp wgcf qua CLI và một context manager **tái sử dụng** (`novel2epub.wireguard.wireguard_network_scope`) để dùng ĐÚNG **một** profile cho toàn bộ một thao tác mạng (toc/crawl), khóa liên tiến trình. Scope này **metadata-free**: chỉ chọn id profile và giữ khóa; nó KHÔNG ghi DB active và KHÔNG tự nhận đã kích hoạt. Vòng đời tunnel service thật (cài/gỡ WireGuard for Windows) là việc riêng của `activate_profile`/`rotate_profile`, chỉ chạy khi `wireguard.manage_service=true` (ngược lại bị TỪ CHỐI).

**Giới hạn có chủ đích:** pipeline `crawl`/`toc` **chưa tự** gọi scope này — rotation giữa request là không an toàn và bị loại ở v1. Nếu cần, tích hợp ở tầng job-level: bọc toàn bộ job crawl/toc bằng context manager và giữ nguyên một profile xuyên suốt job, tuyệt đối không rotate giữa chừng.

## Tự Host Model Dịch Trên Colab/Kaggle

`notebooks/novel2epub_zhvi_server.ipynb` dựng một endpoint OpenAI-Compatible trên GPU miễn phí của Colab/Kaggle, expose qua tunnel để dùng làm **Dịch API** và **AI biên tập**. Hữu ích khi provider ngoài hết quota hoặc muốn dịch hàng loạt không tốn token.

Quy trình:

1. Mở notebook trên Colab (`Runtime > Change runtime type > T4 GPU`) hoặc Kaggle (`Accelerator = GPU T4 x2`, bật `Internet`).
2. Sửa `API_KEY` trong cell CONFIG rồi `Run all`. Lần đầu mất 10–20 phút (cài engine + tải model).
3. Cell **Verify** in ra khối `base_url` / `api_key` / `model` — dán vào **Cài đặt > Dịch API** và **Cài đặt > AI biên tập**.
4. Để cell **Monitor** chạy trong lúc dịch; cell **Stop** giải phóng VRAM khi xong.

Notebook tự nhận GPU rồi chọn preset; ép thủ công bằng `PRESET` / `ENGINE`:

| Preset | Engine | VRAM | Dùng khi |
| --- | --- | --- | --- |
| `qwen3-14b-awq` | vLLM | ~10GB | mặc định 1×T4 — tiếng Trung mạnh, throughput tốt |
| `qwen2.5-14b-awq` | vLLM | ~10GB | đường lui an toàn nhất trên Turing |
| `qwen3.5-9b-awq` | vLLM | ~6.5GB | GPU nhỏ hoặc muốn nhiều request song song |
| `qwen3.5-35b-a3b-awq` | vLLM (tp=2) | ~20GB | Kaggle T4×2 — MoE nên vẫn nhanh |
| `sailor2-20b-gguf` | llama.cpp | ~12GB | ưu tiên tiếng Việt tự nhiên (model train cho Đông Nam Á) |
| `sailor2-8b-gguf` | llama.cpp | ~6.5GB | bản nhẹ của hướng trên |

### Cache model giữa các phiên

Mặc định model tải vào đĩa tạm (`/content/hf`, `/kaggle/tmp/hf`) và mất khi hết phiên. Cell *Lưu cache model cho phiên sau* xử lý việc giữ lại; notebook tự dò cache khi khởi động và **ưu tiên preset đã có sẵn** thay vì tải bản khác.

| Nền tảng | Cách làm | Lần sau |
| --- | --- | --- |
| Colab | Đặt `MODEL_CACHE = "drive"` — model tải thẳng vào `MyDrive/novel2epub-models/hf` | Run all, không tải lại (Drive free 15GB, đủ preset ~10GB) |
| Kaggle | Chạy cell cache để chép vào `/kaggle/working/model-cache`, rồi `Save Version > Save & Run All` | `Add Input > Your Work >` output notebook này |
| Kaggle (gọn hơn) | `Add Input > Models`, attach model có sẵn trên Kaggle | Đặt `MODEL_LOCAL_PATH` trỏ vào thư mục đó, khỏi tốn 20GB output |
| Bất kỳ | `MODEL_LOCAL_PATH = "/đường/dẫn"` | Dùng thẳng thư mục model hoặc file `.gguf` đó |

Notebook nhận layout cache của `huggingface_hub` (`models--org--repo/snapshots/<hash>`) ở bất kỳ độ sâu nào trong `/kaggle/input` hoặc thư mục cache, nên bản chép ra dataset vẫn dùng lại được.

Cache đáng giá nhất trên Kaggle: input đã attach mount sẵn, mất 0 giây. Trên Colab, `hf_transfer` đang bật nên tải mới model ~10GB thường chỉ 2–5 phút — đọc từ Drive đôi khi còn chậm hơn, nên đo một lần rồi hãy quyết.

Vài điểm vận hành cần nhớ:

- **URL tunnel đổi mỗi lần chạy lại** — phải cập nhật `base_url` trong Settings. Session Colab ~12h (idle ~90 phút), Kaggle 9h/session và 30h/tuần. Đây là công cụ chạy theo phiên, không phải server 24/7.
- **Đặt `translate.max_workers` bằng số slot engine báo** (cell Verify in sẵn). Đặt cao hơn chỉ làm request xếp hàng chứ không nhanh thêm.
- **Temperature**: shim kẹp trần 0.35 dù app gửi 0.7, nhưng nên đặt 0.3 ngay trong Settings cho khớp.
- **T4 là Turing (sm75)**: không bf16, không FlashAttention. Nếu vLLM chết vì thiếu kernel, đặt `ENGINE = "llamacpp"` rồi chạy lại — llama.cpp chạy được trên mọi GPU.
- Kiểm tra endpoint từ máy chạy novel2epub bằng chính code của app:

```bash
python scripts/check_openai_endpoint.py --base-url https://xxx.trycloudflare.com/v1 --api-key n2e-...
```

Script báo lỗi nếu tunnel chết, `/models` sai định dạng, hoặc kết quả còn thẻ `<think>` / fence Markdown / sót chữ Hán.

## Xử Lý Sự Cố

TOC rỗng:

- Kiểm tra URL, source preset và `chapter_link_pattern`.
- Chuyển `fetcher` sang `dynamic` nếu nội dung render bằng JavaScript.
- Dùng `stealthy` và `solve_cloudflare` nếu gặp trang thử thách Cloudflare.

Raw sai hoặc rỗng:

- Kiểm tra `content_selector` trên đúng trang chương.
- Kiểm tra encoding, phân trang và strip pattern.
- Crawl lại một chương với `--force` trước khi chạy hàng loạt.

Bị 429 hoặc anti-bot:

- Giảm `max_workers`, tăng `delay_seconds` và retry delay.
- Đặt `concurrency_cap` thấp hơn.
- Dùng proxy hợp lệ hoặc mode browser khi cần.

Dịch lỗi hoặc timeout:

- Kiểm tra endpoint bằng lệnh `models`.
- Giảm chunk/batch, tăng timeout, giảm worker.
- Kiểm tra API key, quota và log của job.

EPUB thiếu chương:

- Lọc chương `translated:no` hoặc `missing:yes`.
- Kiểm tra chương bị skip và trạng thái bản dịch.
- Build lại sau khi hoàn tất dữ liệu thiếu.
