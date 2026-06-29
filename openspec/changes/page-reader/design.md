## Context

Trang chapter hiện tại (`chapter.html`) là editor 3 cột phục vụ review/sửa bản dịch. Người dùng muốn một trang đọc riêng — giao diện sạch như sách, có điều hướng, copy, bookmark. Editor hiện tại vẫn giữ nguyên, reader là trang mới tách biệt.

Tech stack hiện tại: FastAPI + Jinja2, vanilla JS (không có framework), CSS thuần trong `base.html`.

## Goals / Non-Goals

**Goals:**
- Trang đọc chương với giao diện sách sạch, dễ đọc
- Điều hướng prev/next chapter, dropdown chọn chương
- Copy toàn bộ chương hoặc từng đoạn
- Tuỳ chỉnh font, cỡ chữ, dark/light theme (localStorage)
- Lưu vị trí đọc (resume khi quay lại)
- Bookmark vị trí đọc dở
- Link nhanh tới editor

**Non-Goals:**
- Không thay đổi editor hiện tại
- Không thêm real-time collaboration
- Không sync bookmark cross-device (chỉ localStorage)
- Không thêm audio/text-to-speech

## Decisions

### 1. Route structure: `/ebooks/{slug}/read/{index}`

Tách biệt hoàn toàn khỏi editor (`/ebooks/{slug}/chapters/{index}`). Route `/ebooks/{slug}/read` redirect tới chương đầu tiên (hoặc chương bookmark gần nhất).

**Lý do**: Giữ editor và reader độc lập, không conflict logic.

### 2. Template: `reader.html` mới (không reuse `chapter.html`)

`chapter.html` nặng về editor logic (compare table, AI actions, form submit). Reader cần layout khác hoàn toàn — single column, book-like.

**Lý do**: Reuse sẽ tạo template quá phức tạp, khó maintain.

### 3. Bookmark: localStorage (client-side)

Lưu `{slug: {index, scrollY, timestamp}}` trong localStorage. Không cần server-side storage.

**Lý do**: Đơn giản, không cần thêm API/storage. Bookmark là tiện ích cá nhân, không cần sync.

### 4. Theme: CSS class trên `<body>`

Dùng `data-theme="light|dark"` trên body, toggle bằng JS, lưu localStorage.

**Lý do**: Pattern đơn giản, không cần thêm dependency.

### 5. Copy: Clipboard API

Dùng `navigator.clipboard.writeText()`. Fallback cho browser cũ: `document.execCommand('copy')`.

## Risks / Trade-offs

- [Risk] Bookmark chỉ hoạt động trên cùng browser → Mitigation: Ghi rõ trong UI, chấp nhận giới hạn
- [Risk] Nội dung chương dài có thể gây lag khi render → Mitigation: Chỉ render text thuần, không dùng heavy DOM
- [Risk] Dark mode có thể không match theme chung của app → Mitigation: CSS variables, dễ adjust sau

## Migration Plan

Không cần migration — đây là feature mới, không thay đổi gì existing. Deploy: thêm route + template, restart server.

## Open Questions

- Có cần hiển thị cả raw (ZH) trong reader mode không, hay chỉ bản dịch? → Đề xuất: chỉ bản dịch, link tới editor nếu muốn xem raw
- Bookmark có nên lưu server-side để sync cross-device không? → Đề xuất: chỉ localStorage cho MVP
