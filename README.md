# novel2epub

Crawl truyện chữ tiếng Trung → **dịch sang tiếng Việt** → đóng gói thành **EPUB**.

Pipeline 3 bước, mỗi bước **cache trên đĩa** nên có thể dừng và chạy lại bất cứ lúc
nào mà không crawl/dịch lại những chương đã xong (quan trọng để tiết kiệm chi phí dịch).

```
mục lục  ──crawl──▶  raw/*.md (tiếng Trung)  ──dịch──▶  translated/*.md (tiếng Việt)  ──build──▶  .epub
```

EPUB xuất ra tạo **mỗi chương = 1 spine document**, khớp với cách
[`epub-audiobook-app`](../epub-audiobook-app) tách chương để làm audiobook → video.

## Cài đặt

Yêu cầu Python ≥ 3.10.

```bash
cd novel2epub
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`crawl4ai` và `firecrawl-py` là dependency tùy chọn, không cài mặc định để
tránh lỗi build `lxml` trên Windows. Chỉ cài khi cần:
```bash
pip install crawl4ai && crawl4ai-setup   # cài Playwright + Chromium
pip install firecrawl-py
```
Engine mặc định `http` chỉ cần `requests` + `beautifulsoup4`.
`fastapi`/`uvicorn`/`jinja2`/`python-multipart` chỉ cần nếu dùng Web UI (xem dưới).

## Cấu hình

```bash
cp config.example.yaml config.yaml   # rồi chỉnh sửa
```

Các phần chính trong `config.yaml`:

### Quản lý nhiều ebook

Tool hỗ trợ một `library.yaml` ở root để quản lý nhiều truyện/ebook, mỗi truyện trỏ
tới một file config riêng:

```yaml
ebooks:
  xich-tam-tuan-thien:
    name: "Xích Tâm Tuần Thiên"
    config: "configs/xich-tam-tuan-thien.yaml"
```

CLI và Web UI đều có thể chọn theo slug ebook. Nếu không dùng `library.yaml`, bạn
vẫn có thể chạy như cũ với `config.yaml`.

### `crawl` — lấy truyện

| Khóa | Ý nghĩa |
|------|---------|
| `engine` | `http` (mặc định, free, không cần API key) / `crawl4ai` / `firecrawl` |
| `toc_url` | URL trang mục lục chứa danh sách link chương |
| `chapter_link_pattern` | Regex lọc link chương trên URL đầy đủ |
| `max_chapters` | Giới hạn số chương (0 = tất cả) — đặt nhỏ để test trước |
| `content_selector` | (http, crawl4ai) CSS selector vùng nội dung chương, vd `#content` |
| `toc_selector` | (http) CSS selector vùng danh sách chương, loại link rác |
| `encoding` | (http) bảng mã — nhiều site Trung dùng `gbk`/`gb2312` |
| `headless` / `magic` / `js_code` | (crawl4ai) trình duyệt ẩn / vượt bot detection / JS tùy chọn |
| `strip_patterns` | Regex các dòng rác cần bỏ (quảng cáo, "đọc tiếp tại...") |

**Mẹo tìm selector:** mở chương trong trình duyệt → F12 → chuột phải phần nội
dung → Inspect → xem `id`/`class` của thẻ bao quanh.

**Khi nào dùng `crawl4ai`?** Khi engine `http` bị site redirect sang trang xác
minh "tôi không phải bot" hoặc trả nội dung rỗng do load bằng JavaScript —
`crawl4ai` chạy trình duyệt Chromium thật (qua Playwright) nên vượt được các
chặn đó. Đổi `crawl.engine: crawl4ai` là dùng được ngay, các khóa `toc_url`,
`content_selector`, `chapter_link_pattern`... giữ nguyên ý nghĩa.

### `translate` — phần quan trọng nhất

`type` chọn engine dịch:

- **`cli`** *(mặc định)* — gọi một **AI CLI bất kỳ**, rẻ/miễn phí:

  ```yaml
  translate:
    type: cli
    cli:
      command: "opencode run"     # hoặc: llm -m gpt-4o-mini  /  ollama run qwen2.5
      model: "cliproxyapi/gpt-5.5" # tùy chọn; opencode nhận dạng provider/model
      mode: stdin                 # prompt đưa vào qua stdin (hợp văn bản dài)
      prompt_template: |          # đã có sẵn prompt "edit" chuẩn convert truyện
        ...
  ```

  `prompt_template` mặc định đã mã hóa các **nguyên tắc edit truyền thống**
  (tên riêng để Hán Việt, chọn ngôi xưng tiếng Việt, đảo trật tự câu cho tự
  nhiên...). `{text}` = nội dung cần dịch, `{glossary}` = bảng thuật ngữ.
  Với `opencode`, dùng `command: "opencode run"`; nếu đặt `model`, chương trình
  sẽ tự thêm `--model <provider/model>` vào lệnh.

  Bạn cũng có thể cấu hình thêm `style`, `glossary_files`, `retry`, `chunk` để
  phù hợp từng truyện và từng model.

- **`google`** — Google Translate miễn phí (`deep-translator`), nhanh nhưng văn
  phong kém tự nhiên, hay sai tên riêng.

- **`none`** — không dịch, giữ tiếng Trung (để test bước crawl/build).

**Bảng thuật ngữ (`glossary`)** — đóng vai trò như `Name.txt` của Quick Translator:
giữ nhất quán tên nhân vật / công pháp / địa danh. Áp dụng cả trong prompt cho LLM
lẫn thay thế literal sau khi dịch.

```yaml
  glossary:
    "陆压": "Lục Áp"
    "金丹": "Kim Đan"
```

## Sử dụng

```bash
# Chạy từng bước (khuyên dùng — kiểm tra kết quả mỗi bước):
python -m novel2epub -c config.yaml crawl       # lấy mục lục + nội dung chương
python -m novel2epub -c config.yaml translate   # dịch các chương đã crawl
python -m novel2epub -c config.yaml build        # đóng gói EPUB

# Chỉ lấy metadata + toàn bộ mục lục/chapter list, không tải nội dung chương:
python -m novel2epub -c config.yaml toc
python -m novel2epub -c config.yaml meta         # dịch title/author/description theo rule Hán Việt

# Xem/lọc/sort danh sách chương (Web UI dùng cùng table này, có checkbox từng row
# và nút Crawl/Dịch ở từng dòng):
python -m novel2epub -c config.yaml chapters --sort title --search "章" --filter raw:no

# Chọn range theo danh sách đang sort/filter; --force = override old cache:
python -m novel2epub -c config.yaml crawl --sort title --search "章" --range 1:3
python -m novel2epub -c config.yaml translate --sort source --range 1:1 --force

# AI đánh giá glossary + bản dịch (chỉ xem, không sửa file):
python -m novel2epub -c config.yaml evaluate --from 1 --to 2

# Hoặc chạy tất cả:
python -m novel2epub -c config.yaml run

# Với nhiều ebook:
python -m novel2epub list
python -m novel2epub -e xich-tam-tuan-thien run
python -m novel2epub -e xich-tam-tuan-thien translate --missing
python -m novel2epub -e xich-tam-tuan-thien translate --chapter 12
```

Dữ liệu lưu tại `data/<slug>/`:

```
data/ten-truyen/
  manifest.json        # danh sách chương + tiêu đề đã dịch
  raw/0001.md          # bản tiếng Trung đã crawl
  translated/0001.md   # bản tiếng Việt đã dịch
```

Có thể **mở trực tiếp** các file `translated/*.md` để soát/sửa tay trước khi
`build` — chính là khâu "edit" cuối cùng.

## Web UI (tùy chọn)

Thay vì gõ lệnh, có thể chạy giao diện web để bấm nút crawl/dịch/build, theo
dõi log, và **sửa tay bản dịch ngay trên trình duyệt**:

```bash
python -m pip install fastapi uvicorn jinja2 python-multipart
uvicorn app.main:app --reload --port 8010
```

Mở `http://127.0.0.1:8010`. UI ưu tiên `library.yaml` để hiển thị thư viện ebook;
nếu không có, có thể dùng `NOVEL2EPUB_CONFIG=duong/dan/khac.yaml` cho chế độ
1 truyện. Trang thư viện hiển thị trạng thái từng ebook, còn trang ebook cho phép
crawl/dịch/build và sửa tay từng chương ngay trên web.

Biến môi trường liên quan:

- `NOVEL2EPUB_CONFIG`: file config mặc định khi không dùng library.
- `NOVEL2EPUB_LIBRARY`: đường dẫn `library.yaml`.

## Quy trình khuyên dùng cho truyện mới

1. Đặt `max_chapters: 2` và `translate.type: none`, chạy `crawl` → kiểm tra
   `raw/*.md` lấy đúng nội dung (chỉnh `content_selector`/`encoding` nếu cần).
2. Đổi `translate.type: cli`, chạy `translate` 2 chương → xem chất lượng dịch,
   bổ sung `glossary` cho tên riêng hay bị sai.
3. Đặt `max_chapters: 0` (toàn bộ), chạy `run`.

Khi ebook đã ổn, có thể dùng UI để chỉnh glossary, soát chương lỗi, và build lại
ngay sau khi sửa tay.

## Hạn chế

- Engine `http` chỉ đọc HTML tĩnh; site dùng JavaScript/chống bot nên thử
  `engine: crawl4ai`; chương VIP/cần đăng nhập có thể cần `engine: firecrawl`
  hoặc nguồn khác.
- Chất lượng dịch phụ thuộc model của AI CLI bạn cắm vào.
- Tôn trọng bản quyền & điều khoản của trang nguồn; chỉ dùng cho mục đích cá nhân.
