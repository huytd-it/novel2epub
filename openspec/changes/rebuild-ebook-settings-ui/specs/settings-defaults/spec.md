## ADDED Requirements

### Requirement: Mỗi field hiển thị giá trị mặc định gốc
Mỗi input/select trong settings SHALL hiển thị giá trị mặc định từ dataclass config (trong `novel2epub/config.py`) dưới dạng badge/chip mờ bên cạnh label, với nhãn "Mặc định: <value>".

#### Scenario: Field chưa override hiển thị default badge
- **WHEN** field `engine` chưa được override trong YAML (giá trị hiện tại == default)
- **THEN** badge "Mặc định: http" hiển thị bên cạnh label
- **AND** input không được highlight

#### Scenario: Field đã override không hiển thị default badge
- **WHEN** field `engine` đã được set thành "crawl4ai" trong YAML
- **THEN** badge "Mặc định: http" KHÔNG hiển thị
- **AND** input được highlight hoặc có dấu hiệu đã override (icon/class)

### Requirement: Jinja2 filter `is_default` và `default_value`
Hệ thống SHALL cung cấp Jinja2 filter `is_default(current, section, field)` và `default_value(section, field)` để template kiểm tra và lấy default.

#### Scenario: Filter hoạt động trong template
- **WHEN** template gọi `{{ cfg.crawl.engine | default_value('crawl', 'engine') }}`
- **THEN** trả về `"http"` (giá trị mặc định của `CrawlConfig.engine`)
