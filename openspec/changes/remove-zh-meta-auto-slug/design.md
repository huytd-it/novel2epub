## Context

Hiện tại, hệ thống crawl metadata tiếng Trung (title, author, description) từ trang mục lục nguồn, sau đó dịch sang tiếng Việt qua `step_translate_meta`. Người dùng muốn bỏ qua bước crawl metadata zh và nhập trực tiếp thông tin tiếng Việt (tên truyện, tác giả, mô tả). Đồng thời, slug nên được sinh tự động từ tiêu đề tiếng Việt thay vì yêu cầu nhập riêng.

`Manifest` hiện có 2 tầng field cho cùng 1 thông tin: `title` (zh, crawl từ TOC) và `title_vi` (vi, AI dịch). Tương tự với `author`/`author_vi` và `description`/`description_vi`. Chapter cũng có `title_zh` + `title_vi`. Việc có 2 tầng gây phức tạp không cần thiết khi người dùng nhập metadata vi trực tiếp.

## Goals / Non-Goals

**Goals:**
- Gộp field metadata zh và vi thành 1 field duy nhất trên Manifest và Chapter (đều là tiếng Việt)
- Người dùng nhập title/author tiếng Việt trực tiếp trong form "Thêm Ebook" và trang Settings
- Slug tự động sinh từ title tiếng Việt, hỗ trợ chuyển ký tự có dấu → không dấu
- Xóa bước dịch metadata zh→vi (`step_translate_meta`) khỏi pipeline
- Tương thích ngược với manifest.json cũ (tự động migrate field cũ khi load)

**Non-Goals:**
- Không thay đổi cách crawl nội dung chương (vẫn crawl raw tiếng Trung để dịch)
- Không thay đổi cấu trúc `NovelConfig` trong YAML (vẫn có `title`, `author`, `language`, `slug`)
- Không thay đổi cách hiển thị nội dung chương gốc (cột ZH trong editor)

## Decisions

### Decision 1: Gộp field zh/vi trên Manifest

**Chọn**: Giữ lại `title_vi`, `author_vi`, `description_vi` và đổi tên thành `title`, `author`, `description`. Xóa field zh gốc (`title`, `author`, `description` cũ). Field `title_note` giữ nguyên.

**Lý do**: Vì người dùng nhập tiếng Việt trực tiếp, không cần phân biệt zh/vi nữa. Đổi tên field `_vi` → không hậu tố giúp code rõ ràng hơn (manifest.title là tiếng Việt, không còn mơ hồ).

**Alternatives considered**:
- Giữ nguyên cấu trúc 2 tầng nhưng đánh dấu field zh là optional → vẫn phức tạp không cần thiết
- Thêm field mới và giữ field cũ để backward compat → tăng debt code, không rõ ràng

### Decision 2: Gộp Chapter.title_zh và Chapter.title_vi

**Chọn**: Xóa `Chapter.title_zh`, đổi tên `Chapter.title_vi` → `Chapter.title`. Giữ `title_note`.

**Lý do**: Nhất quán với Manifest. Chapter title sau khi dịch là tiếng Việt và là field duy nhất cần lưu.

### Decision 3: Backward compat cho manifest.json cũ

**Chọn**: Khi `load_manifest()` đọc manifest.json cũ (có field `title_zh` và `title_vi` riêng), tự động merge: lấy `title_vi` nếu có, nếu không thì lấy `title` (zh cũ) → gán vào `title` mới. Khi save, luôn ghi theo schema mới (chỉ có `title`).

**Lý do**: Người dùng có sẵn manifest.json từ các lần crawl trước. Không muốn mất dữ liệu đã dịch. Migration tự động khi load, không cần script riêng.

### Decision 4: Slugify hỗ trợ tiếng Việt

**Chọn**: Viết `vn_slugify()` — chuyển đổi ký tự có dấu tiếng Việt sang không dấu trước khi strip non-ASCII:
- `đ` → `d`
- `àáảãạăằắẳẵặâầấẩẫậ` → `a`
- `èéẻẽẹêềếểễệ` → `e`
- `ìíỉĩị` → `i`
- `òóỏõọôồốổỗộơờớởỡợ` → `o`
- `ùúủũụưừứửữự` → `u`
- `ỳýỷỹỵ` → `y`
- Các ký tự non-ASCII khác → strip
- Sau đó: thay thế non-alphanumeric thành `-`, lowercase

**Alternatives considered**:
- Dùng thư viện `unidecode` → thêm dependency, không cần thiết cho 1 bảng map nhỏ
- Giữ nguyên slugify cũ và yêu cầu user nhập slug riêng → mất tiện ích tự động

### Decision 5: Form "Thêm Ebook" không có field slug riêng

**Chọn**: Form chỉ có title (vi), author (vi), toc_url. Slug sinh tự động từ title bằng `vn_slugify()`. Người dùng có thể sửa slug sau trong trang Settings nếu muốn.

**Lý do**: Slug là technical detail, không nên bắt user nghĩ về nó khi tạo ebook. Vẫn cho phép chỉnh sửa qua Settings.

### Decision 6: step_translate_meta không còn dịch metadata zh→vi

**Chọn**: `step_translate_meta` chỉ gán `cfg.novel.title` vào `manifest.title`, `cfg.novel.author` vào `manifest.author`. Không gọi translator. Không đọc TOC metadata zh.

**Lý do**: Metadata vi đã do người dùng nhập trong `NovelConfig`, không cần dịch.

## Risks / Trade-offs

- **[Risk] Manifest cũ có title_vi trống nhưng title (zh) có dữ liệu** → Migration logic dùng `title` cũ (zh) làm fallback, người dùng có thể thấy tiếng Trung trong EPUB. Mitigation: sau migrate, người dùng vào Settings nhập lại title tiếng Việt.
- **[Risk] Người dùng muốn giữ metadata zh để đối chiếu** → Non-goal. Nếu cần, có thể thêm sau dưới dạng optional field riêng.
- **[Risk] Slug trùng khi 2 ebook có title vi giống nhau** → Giữ logic kiểm tra trùng slug (HTTP 409) trong `create_ebook`.
- **[Risk] Source_language mặc định rỗng có thể gây lỗi translator** → Translator backends cần xử lý trường hợp source_language rỗng (fallback về default của model, thường là auto-detect).

## Migration Plan

1. Triển khai migration logic trong `Storage.load_manifest()` — tự động map field cũ → mới
2. Khi người dùng mở ebook cũ, manifest được load và tự động migrate schema
3. Lần save đầu tiên ghi theo schema mới
4. Không cần script migration riêng
5. Rollback: nếu cần, có thể revert code và manifest.json cũ vẫn đọc được (field mới vẫn map ngược)

## Open Questions

- Không có
