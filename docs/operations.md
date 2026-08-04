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
