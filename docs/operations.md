# Vận Hành

## Tạo Ebook

Quy trình khuyến nghị trên Web UI:

1. Mở Thư viện và tạo ebook từ kết quả tìm kiếm hoặc URL.
2. Chọn source preset phù hợp, kiểm tra `toc_url` và selector.
3. Giới hạn `max_chapters` ở 2-3 chương, lấy TOC rồi crawl thử.
4. Kiểm tra raw; sửa selector hoặc strip pattern nếu nội dung lẫn quảng cáo.
5. Chọn backend dịch, dịch thử và kiểm tra glossary/xưng hô.
6. Bỏ giới hạn chương và chạy pipeline đầy đủ.

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

Các lệnh bổ sung: `evaluate`, `reindex`, `search`, `models`, `backup`, `restore`, `service`.

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

## Chạy Nền

```sh
python -m novel2epub service install --host 127.0.0.1 --port 8010
python -m novel2epub service status
python -m novel2epub service uninstall
```

Windows dùng Task Scheduler theo phiên đăng nhập. Linux dùng systemd user service; chạy trước khi đăng nhập cần bật linger cho user.

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
