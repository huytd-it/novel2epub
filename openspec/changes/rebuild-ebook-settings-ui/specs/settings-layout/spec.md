## ADDED Requirements

### Requirement: Settings page có sidebar navigation 4 nhóm
Trang `/ebooks/{slug}/settings` SHALL hiển thị sidebar dọc bên trái với 4 mục: **Novel**, **Crawl**, **Translate**, **Output**. Mỗi mục là một tab riêng. Nội dung tương ứng hiển thị ở cột phải.

#### Scenario: Click vào tab sẽ chuyển nội dung
- **WHEN** người dùng click vào tab "Crawl" trên sidebar
- **THEN** nội dung tab Crawl được hiển thị, các tab khác bị ẩn
- **AND** tab "Crawl" được đánh dấu active

#### Scenario: Tab Novel là tab mặc định
- **WHEN** người dùng mở trang settings lần đầu
- **THEN** tab "Novel" được active và nội dung của nó hiển thị

### Requirement: Output tab
Tab Output SHALL chứa các field: `data_dir`, `epub_path`, `crawl.max_workers`, `translate.max_workers`. Form POST đến `/ebooks/{slug}/settings/output`.

#### Scenario: Lưu output settings
- **WHEN** người dùng điền `data_dir` và submit form Output
- **THEN** dữ liệu được ghi vào `ebooks.<slug>.output.data_dir` trong YAML config
- **AND** redirect về trang settings với tab Output active

### Requirement: Template được tách thành file partial
Template `settings.html` SHALL dùng Jinja2 `{% include %}` để tách thành 4 file partial: `settings_novel.html`, `settings_crawl.html`, `settings_translate.html`, `settings_output.html`.

#### Scenario: Partial template tồn tại
- **WHEN** settings.html render tab Novel
- **THEN** nội dung là từ file `settings_novel.html`
- **WHEN** settings.html render tab Translate
- **THEN** nội dung là từ file `settings_translate.html`
