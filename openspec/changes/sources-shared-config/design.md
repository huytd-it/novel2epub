## Context

Hệ thống hiện tại dùng mô hình **copy-once**: khi tạo ebook từ source preset, các field crawl (selector, delay, pagination...) được copy phẳng vào ebook config trong YAML. Sau đó ebook và preset hoàn toàn độc lập — không có liên kết nào.

**Luồng config hiện tại:**
```
defaults ──┐
           ├── deep_merge → load_config() → dataclass
ebooks[slug] ┘
```

**Vấn đề:**
- `SourcePreset.crawl_overrides()` trả ~15 field, nhưng `CrawlConfig` có cấu trúc nested khác (scrapling.mode vs scrapling_mode). Mapping legacy nằm rải rác trong `load_config()`.
- `_preset_usage()` brute-force so sánh từng field để đoán liên kết — O(ebooks × presets × fields).
- Không có cách propagate update từ preset sang ebook.
- YAML chứa field không có UI (`strip_patterns`, `ai_fallback`, `auto_glossary`, `batch_size`, `glossary_files`, `profile`, `genre`).

**Stakeholders:** Người dùng web UI quản lý ebook + source preset.

## Goals / Non-Goals

**Goals:**
- Ebook config lưu **tham chiếu** (`source: ten-preset`) thay vì copy field.
- Config resolution tự động merge: source preset fields → ebook override.
- Khi cập nhật preset → propagate sang ebook (giữ nguyên ebook override).
- Khi sửa ebook crawl trong UI → có nút sync ngược về preset.
- Loại bỏ field YAML không có UI counterpart.

**Non-Goals:**
- Không thay đổi cấu trúc `SourcePreset` dataclass (giữ nguyên field, chỉ thay cách dùng).
- Không migrate storage format (chapter files, glossary, manifest).
- Không thay đổi CLI behavior — CLI vẫn dùng config YAML trực tiếp.
- Không thêm UI mới cho các field YAML-only (chúng bị xóa, không được đưa lên UI).

## Decisions

### D1: Ebook lưu `source` name, không lưu copy field

**Lựa chọn:** Thêm `source: str` vào ebook config block. Khi load, resolve preset → deep_merge với ebook override.

**Thay vì:** Giữ copy field + thêm sync metadata (quá phức tạp, dễ lệch state).

**Lý do:** Đơn giản, single source of truth. Ebook chỉ override field khác preset.

```yaml
# Trước (copy)
ebooks:
  truyen-abc:
    crawl:
      toc_url: https://...
      content_selector: ".chapter-content"
      delay_seconds: 2.0
      scrapling:
        mode: stealthy

# Sau (reference)
ebooks:
  truyen-abc:
    source: aixdzs          # ← tham chiếu
    crawl:
      toc_url: https://...   # ← chỉ field đặc thù
      content_selector: ".custom"  # ← override khác preset
```

### D2: Config resolution flow mới

```
defaults
  ↓ deep_merge
source_preset.crawl_overrides()   ← mới
  ↓ deep_merge
ebooks[slug].crawl (override)      ← ghi đè cuối
  ↓
CrawlConfig dataclass
```

**Implement trong `load_config()`:** Sau khi merge defaults + ebook, nếu ebook có `source` → lookup preset → merge crawl fields từ preset vào trước khi ebook override ghi đè.

**Tracking override:** Khi load, lưu set các key mà ebook đã override (nằm trong ebooks[slug].crawl). Dùng set này để:
- Hiển thị trong UI: field nào từ source, field nào override.
- Khi sync preset → chỉ update field ebook CHƯA override.

### D3: Sync preset → ebook (propagate)

Khi lưu source preset trong `/sources` POST:
1. Load tất cả ebook có `source == preset_name`.
2. Với mỗi ebook, chỉ update field crawl mà ebook **chưa override** (không có trong ebook.crawl block).
3. Ghi lại YAML.

**Không propagate nếu:** ebook đã override field đó thủ công (tồn tại trong ebook.crawl block).

### D4: Sync ebook → preset (reverse)

Trong ebook settings UI, tab Nguồn (crawl settings):
- Thêm nút "Lưu vào nguồn" nếu ebook có `source`.
- POST `/ebooks/{slug}/settings/sync-to-source`: lấy crawl config hiện tại (đã resolve), ghi đè lên preset.
- Chỉ sync field mà ebook đã override (không ghi đè field preset từ ebook dùng default).

### D5: Dọn rác YAML

**Audit kết quả — field cần xóa khỏi output:**

| Field | Lý do |
|---|---|
| `translate.auto_glossary` | Không có UI, experimental |
| `translate.glossary_filter` | Không có UI |
| `translate.batch_size` | Không có UI |
| `translate.auto_cleanup_han` | Không có UI |
| `translate.cleanup_han.*` | Không có UI |
| `translate.glossary` (inline dict) | UI dùng file-based glossary |
| `translate.glossary_files` | Auto-resolve trong load_config |
| `translate.profile` | Không có UI |
| `translate.genre` | Không có UI |
| `crawl.strip_patterns` | Không có UI trong ebook settings |
| `crawl.ai_fallback` | Không có UI, experimental |
| `crawl.ai_fallback_max_html` | Không có UI |
| `crawl.concurrency_cap` | Có trong source preset UI nhưng không trong ebook settings |

**Approach:** Không xóa khỏi dataclass (tránh break code đang dùng). Chỉ:
1. `config_writer` không ghi các field này khi tạo/sửa ebook.
2. `load_config()` vẫn đọc được (backward compat).
3. Template UI hiển thị warning nếu field deprecated tồn tại trong YAML.

### D6: Migration strategy

**Backward compat:** Ebook cũ không có `source` field → hoạt động như hiện tại (copy field). Không cần migrate ngay.

**Lazy migration:** Khi user sửa ebook settings trong UI lần đầu → detect preset match → gợi ý gán `source` field. User confirm → gán + xóa copy field thừa.

**CLI:** Không thay đổi. CLI dùng YAML trực tiếp, không cần biết source reference.

## Risks / Trade-offs

- **[Rủi ro] Breaking change cho user edit YAML thủ công** → Mitigation: backward compat, ebook cũ hoạt động bình thường. Lazy migration, không force.
- **[Rủi ro] Preset bị xóa khi ebook đang tham chiếu** → Mitigation: validation hiện tại đã chặn delete preset đang dùng. Giữ nguyên logic này.
- **[Rủi ro] Override tracking phức tạp** → Mitigation: chỉ track ở YAML level (key tồn tại trong ebook.crawl block hay không), không cần runtime tracking.
- **[Trade-off] Copy field cũ vẫn tồn tại trong YAML** → Mitigation: lazy migration, dần dần clean up khi user edit ebook.
- **[Trade-off] Field YAML-only bị xóa** → Nếu user đã customize field đó qua CLI, mất config. Mitigation: chỉ xóa output, không xóa dataclass; load vẫn đọc được.

## Open Questions

- Có nên hiển thị indicator trong ebook UI khi field nào đến từ source vs override? (Có, nhưng là nice-to-have, không block MVP.)
- `crawl.concurrency_cap` — giữ trong ebook settings UI hay chỉ trong source preset? (Đề xuất: chỉ trong source preset, ebook dùng default.)
