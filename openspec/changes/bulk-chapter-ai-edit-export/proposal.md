## Why

Người dùng muốn biên tập bản dịch hàng loạt bằng các chatbot AI trên web (ChatGPT, Claude, Gemini...) thay vì gọi API tốn phí hoặc sửa từng chương một trong editor. Hiện tại chưa có cách lấy nhiều chương ra một lúc rồi nạp kết quả đã biên tập trở lại — phải copy/paste thủ công từng chương, vừa chậm vừa dễ lẫn lộn thứ tự và mất đồng bộ với manifest. Ngoài ra, để bản biên tập **hay và chính xác**, web chat cần được hướng dẫn theo nguyên tắc edit truyện Trung–Việt (xem `docs/rule.md`) và phải **giữ tên riêng/thuật ngữ nhất quán xuyên suốt**, đồng thời tự sinh glossary để nạp ngược về hệ thống.

## What Changes

- Thêm thao tác **"Xuất chương đã chọn"** trên trang ebook: gom nội dung bản dịch của các chương được tick vào một văn bản duy nhất, có marker phân tách rõ ràng giữa các chương, kèm prompt hướng dẫn AI biên tập để người dùng copy nguyên khối dán lên web chat.
- **Prompt biên tập chuẩn**: prompt chắt lọc nguyên tắc "edit đúng/hay" từ `docs/rule.md` (đối chiếu bản gốc, ngôi xưng theo quan hệ, ngữ pháp Việt, cân bằng Hán–Việt, tên riêng ưu tiên Hán Việt viết hoa) để bản biên tập hay và chính xác.
- **Giữ tên nhất quán**: đính kèm glossary hiện có (`names.txt` + `vietphrase.txt`) vào prompt để web chat dùng đúng tên/thuật ngữ đã chốt — nhất quán cả với chương đã dịch trước và giữa các lần export.
- **Tự sinh glossary xuyên suốt**: prompt yêu cầu web chat xuất thêm một khối `GLOSSARY` (nhóm `[NAMES]` và `[VIETPHRASE]`, format `source = target`) gồm các tên riêng/thuật ngữ mới gặp trong loạt chương.
- Thêm thao tác **"Nhập bản biên tập"**: người dùng dán lại văn bản đã được AI biên tập; hệ thống parse theo marker, đối chiếu với các chương đã chọn, hiển thị preview thay đổi (diff theo chương) trước khi ghi đè vào `translated/`; nếu có khối `GLOSSARY` thì parse và merge vào `names.txt`/`vietphrase.txt` (dedup).
- Định dạng marker round-trip ổn định (chứa `index` chương) để import tách lại đúng chương kể cả khi AI giữ nguyên hay thêm/bớt dòng trong nội dung.
- Xử lý lỗi nhập sai: thiếu marker, sai/thừa chương, marker không khớp chương đã chọn — báo lỗi cụ thể và không ghi đè khi chưa xác nhận.

## Capabilities

### New Capabilities
- `bulk-chapter-export`: Xuất gom bản dịch nhiều chương đã chọn thành một khối văn bản có marker + prompt biên tập (chuẩn theo `docs/rule.md`) + glossary hiện có, sẵn sàng dán lên web chat AI.
- `bulk-chapter-import`: Nhập lại văn bản đã biên tập, parse theo marker, preview diff theo chương, ghi đè bản dịch an toàn, và merge khối glossary do AI sinh vào `names.txt`/`vietphrase.txt`.

### Modified Capabilities
<!-- Không thay đổi requirement của spec hiện có; chỉ thêm capability mới. -->

## Impact

- **Routes/API**: thêm endpoint mới trong `app/routes/chapters.py` (hoặc module batch riêng) — `POST /api/ebooks/{slug}/batch/export` và `POST /api/ebooks/{slug}/batch/import` (preview + confirm).
- **Storage**: dùng lại `Storage.read_translated` / `write_translated`; không đổi layout file.
- **UI**: bổ sung nút vào thanh `selected-actions` trong `app/templates/ebook.html` + một dialog/modal nhập-xuất; JS xử lý gom index đã tick (tái dùng cơ chế `chapter-check` sẵn có).
- **Logic parse/format marker**: module thuần Python mới (vd `novel2epub/bulk_transfer.py`) để dễ unit-test, không phụ thuộc web.
- Không thêm dependency mới; chạy hoàn toàn offline (không gọi API AI từ server).
