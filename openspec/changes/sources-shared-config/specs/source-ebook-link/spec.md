## ADDED Requirements

### Requirement: Ebook config lưu tham chiếu source preset
Mỗi ebook config SHALL có field `source` (string, optional) chứa tên source preset. Field này là single source of truth cho crawl settings dùng chung — ebook KHÔNG lưu bản copy của preset fields.

#### Scenario: Tạo ebook mới với source preset
- **WHEN** user tạo ebook mới qua web UI với URL mục lục khớp domain của preset "aixdzs"
- **THEN** ebook config SHALL được ghi với `source: aixdzs` và chỉ chứa field đặc thù (`toc_url`) trong block `crawl:`

#### Scenario: Tạo ebook không khớp preset nào
- **WHEN** user tạo ebook mới với URL mục lục không khớp domain nào trong presets
- **THEN** ebook config SHALL được ghi KHÔNG có field `source`, crawl settings ghi đầy đủ như hiện tại (backward compat)

#### Scenario: Ebook cũ không có source field
- **WHEN** load config cho ebook đã tồn tại mà không có field `source`
- **THEN** hệ thống SHALL hoạt động bình thường như hiện tại — dùng crawl fields đã copy trong ebook config

### Requirement: Config resolution merge source preset
`load_config()` SHALL resolve crawl settings theo thứ tự: (1) source preset fields → (2) ebook crawl override. Ebook override ghi đè preset fields.

#### Scenario: Ebook có source và override một số field
- **WHEN** ebook có `source: aixdzs` và `crawl.content_selector: ".custom"`
- **THEN** resolved crawl config SHALL có `content_selector` = `".custom"` (từ ebook), các field khác lấy từ preset "aixdzs"

#### Scenario: Ebook có source, không override field nào
- **WHEN** ebook có `source: aixdzs` và block `crawl:` chỉ chứa `toc_url`
- **THEN** resolved crawl config SHALL dùng toàn bộ crawl fields từ preset "aixdzs", chỉ `toc_url` từ ebook

#### Scenario: Ebook có source nhưng preset không tồn tại
- **WHEN** ebook có `source: deleted-preset` nhưng preset đó không có trong sources
- **THEN** hệ thống SHALL log warning và dùng crawl fields từ ebook config (fallback như ebook không có source)

### Requirement: Override tracking ở YAML level
Hệ thống SHALL xác định ebook override bằng cách kiểm tra key có tồn tại trong block `crawl:` của ebook trong YAML. Không cần runtime tracking mechanism.

#### Scenario: Field tồn tại trong ebook.crawl → là override
- **WHEN** ebook YAML có `crawl.delay_seconds: 3.0` và preset cũng có `delay_seconds: 1.0`
- **THEN** field `delay_seconds` được coi là ebook override, resolved value = 3.0

#### Scenario: Field không tồn tại trong ebook.crawl → lấy từ preset
- **WHEN** ebook YAML không có `crawl.headless` và preset có `headless: true`
- **THEN** resolved value = true (từ preset)

### Requirement: Web UI hiển thị source indicator
Ebook settings page SHALL hiển thị nguồn của crawl field: field nào từ source preset, field nào ebook đã override.

#### Scenario: Ebook có source, field từ preset
- **WHEN** user mở ebook settings tab Nguồn, ebook có `source: aixdzs` và `content_selector` không override
- **THEN** UI SHALL hiển thị `content_selector` với indicator "từ nguồn: aixdzs"

#### Scenario: Ebook có source, field đã override
- **WHEN** user mở ebook settings tab Nguồn, ebook có `source: aixdzs` và `content_selector: ".custom"` trong YAML
- **THEN** UI SHALL hiển thị `content_selector` với indicator "ghi đè" (khác preset)

### Requirement: YAML cleanup — không ghi field deprecated
`config_writer` SHALL KHÔNG ghi các field YAML-only deprecated khi tạo hoặc sửa ebook. Các field bị loại bỏ: `translate.glossary` (inline dict), `translate.glossary_files`, `translate.profile`, `translate.genre`, `crawl.ai_fallback`, `crawl.ai_fallback_max_html`.

Các field sau ĐÃ CÓ UI (tab Dịch) nên KHÔNG deprecated, config_writer ghi bình thường: `translate.auto_glossary`, `translate.glossary_filter`, `translate.batch_size`, `translate.auto_cleanup_han`, `translate.cleanup_han.*` (và `crawl.strip_patterns` — tab Nguồn).

#### Scenario: Tạo ebook mới không có field deprecated
- **WHEN** user tạo ebook mới qua web UI
- **THEN** ebook YAML block SHALL KHÔNG chứa bất kỳ field deprecated nào trong danh sách trên

#### Scenario: Sửa ebook không ghi thêm field deprecated
- **WHEN** user sửa ebook settings qua web UI và lưu
- **THEN** `update_ebook()` SHALL chỉ ghi các field có UI control, KHÔNG ghi thêm field deprecated

#### Scenario: Ebook cũ có field deprecated vẫn đọc được
- **WHEN** ebook YAML cũ chứa `translate.profile: traditional_cn_novel`
- **THEN** `load_config()` vẫn đọc được field này (backward compat), nhưng KHÔNG ghi lại khi user sửa ebook qua UI

### Requirement: Preset auto-detect khi tạo ebook
Khi tạo ebook mới, hệ thống SHALL tự động detect preset từ URL mục lục và gán field `source`.

#### Scenario: URL khớp preset
- **WHEN** user nhập `https://www.aixdzs.com/novel/xxx/` trong form tạo ebook
- **THEN** hệ thống detect domain "aixdzs" khớp preset "aixdzs" → ghi `source: aixdzs`

#### Scenario: URL không khớp preset nào
- **WHEN** user nhập URL từ site chưa có preset
- **THEN** ebook được tạo không có field `source`, crawl settings ghi đầy đủ
