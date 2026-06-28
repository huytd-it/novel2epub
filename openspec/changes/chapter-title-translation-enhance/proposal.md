## Why

Giao diện chương (`app/templates/chapter.html`) hiện tại có một số hạn chế: (1) dịch tiêu đề không cho chọn engine/model, (2) không có cơ chế tạo description giải thích tên chương, (3) biên tập paragraph chỉ làm từng cái, (4) prompt_template không preview được, (5) tính năng giải thích từ ngữ đang giải thích toàn bộ nội dung thay vì tập trung vào tên riêng/thành ngữ — mục đích thực sự là hiểu rõ từ Hán đó có nghĩa gì trong tiếng Trung.

## What Changes

- **Dịch tiêu đề với engine/model selector**: Thêm dropdown engine và model vào form "Dịch lại tiêu đề", cho phép chọn backend (hachimimt/openai/google) và model cụ thể khi dùng OpenAI-compatible.
- **Tạo description cho tên chương**: Thêm nút "Giải thích tên chương" dùng nội dung chapter (raw + đã dịch) + raw title để AI tạo description giải thích lý do đặt tên. Hiển thị kết quả trong `title_note` area.
- **Biên tập hàng loạt (batch edit)**: Thêm checkbox chọn nhiều paragraph + nút bulk action (AI polish, AI explain) áp dụng lên các đoạn đã chọn.
- **Preview prompt_template**: Cho phép xem trước prompt template sẽ dùng cho AI polish/explain/rewrite, và custom trực tiếp trong UI trước khi gửi.
- **Tập trung giải thích từ riêng**: Đổi AI explain từ giải thích toàn bộ nội dung sang chỉ tìm và giải thích tên riêng (tên nhân vật, địa điểm), thành ngữ/tiếng lóng Hán-Việt —目的是理解这些中文词汇的含义 và cách dịch.
- **Thêm gợi ý**: Gợi ý cải thiện tổng thể giao diện chương.

## Capabilities

### New Capabilities

- `title-translation-config`: Engine/model selector cho dịch tiêu đề chapter, bao gồm preview prompt template cho title translation.
- `chapter-description-generation`: Tạo description giải thích tên chương dựa trên nội dung chapter + raw title.
- `batch-paragraph-edit`: Checkbox + bulk action cho biên tập nhiều paragraph cùng lúc.
- `prompt-template-preview`: Xem trước và custom prompt_template trong UI trước khi gọi AI.
- `focused-term-explanation`: Refactor AI explain để tập trung vào tên riêng, thành ngữ — chỉ giải thích từ Hán cần hiểu nghĩa.

### Modified Capabilities

(none — đây là feature mới, không thay đổi spec hiện có)

## Impact

- **Files affected**: `app/templates/chapter.html` (template + JS), `app/routes/chapters.py` (new API endpoints), potentially `app/routes/templates/` cho prompt preview.
- **API additions**: `POST /ebooks/{slug}/chapters/{index}/retranslate-title` cần nhận thêm `engine`, `model`, `prompt_template` params. Endpoint mới: `POST .../generate-title-description`, `POST .../batch-explain`, `POST .../batch-polish`.
- **Dependencies**: Không thêm dependency mới — dùng AI backends đã có (openai, hachimimt, google).
