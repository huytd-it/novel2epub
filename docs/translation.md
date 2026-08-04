# Dịch Và Biên Tập

## Luồng Nội Dung

Mỗi chương có ba lớp nội dung:

- Raw: văn bản nguồn sau crawl.
- MT snapshot: kết quả dịch ban đầu, dùng để đối chiếu và phục hồi.
- Translated: bản đang biên tập và là nguồn để build EPUB.

Biên tập không ghi đè snapshot MT. Có thể so sánh nguồn, bản máy và bản sửa trong trình đọc ba cột.

## Chọn Backend

| Backend | Phù hợp |
| --- | --- |
| `openai` | Chất lượng văn phong, prompt/ngữ cảnh phong phú |
| `hachimimt` | Offline, chi phí thấp, xử lý số lượng lớn |
| `google` | Thử nhanh, không ưu tiên văn phong |
| `libretranslate` | Hạ tầng self-hosted |
| `none` | Nguồn tiếng Việt hoặc kiểm thử pipeline |

Với nguồn tiếng Việt, đặt `source_language=vi`; hệ thống tự passthrough và không gọi model.

## Ngữ Cảnh Dịch

Glossary theo ebook dùng để cố định tên riêng và thuật ngữ đặc thù. Không đưa từ đời thường vào glossary. Matching ưu tiên source dài để tên dài không bị mục ngắn thay trước.

Idioms là từ điển dùng chung cho mọi ebook. Với LLM, idiom được đưa vào prompt như tham chiếu; với MT cục bộ, hệ thống có thể chuẩn hóa bản literal hoặc bảo vệ source qua placeholder.

Bảng nhân vật lưu tên, alias, giới tính, cách tự xưng và cách người kể gọi. Quan hệ có hướng lưu cách xưng hô theo mốc chương, giúp thay đổi quan hệ không áp ngược cho toàn truyện.

Genre và style cung cấp luật xưng hô, mức Hán Việt, tông giọng và cách xử lý tiêu đề. Ngữ cảnh cụ thể và bảng nhân vật có ưu tiên cao hơn preset thể loại.

## AI Hỗ Trợ

Backend `ai.openai` phục vụ:

- Review và rewrite bản dịch.
- Đề xuất glossary và xử lý thay đổi cần duyệt.
- Trích nhân vật/quan hệ theo nhóm chương.
- Cleanup chữ Hán còn sót.
- Sửa đoạn, giải thích và ghi chú chất lượng.

Đề xuất thay đổi glossary hoặc quan hệ nên được duyệt trước khi lan truyền. Các thao tác hàng loạt chạy qua job queue để có log và khả năng hủy/retry.

## Checklist Chất Lượng

- Không thêm, bỏ hoặc giải thích nội dung ngoài nguyên tác.
- Câu tiếng Việt tự nhiên, không giữ máy móc trật tự từ nguồn.
- Ngôi kể và xưng hô đúng quan hệ, thân phận, thời điểm.
- Tên riêng và thuật ngữ nhất quán với glossary.
- Thành ngữ được dịch theo nghĩa và sắc thái, không ghép từng chữ.
- Hán Việt đủ giữ không khí nhưng không làm câu khó hiểu.
- Không còn lời mở đầu của model, Markdown fence hoặc chữ Hán chưa xử lý.
- Giữ cấu trúc đoạn hợp lý và tiêu đề chương rõ nghĩa.

## Quy Trình Khuyến Nghị

1. Dịch thử vài chương đại diện trước khi chạy toàn bộ.
2. Xây glossary và bảng nhân vật từ đầu truyện.
3. Kiểm tra xưng hô ở các mốc quan hệ thay đổi.
4. Dùng cleanup Hán sau dịch, không thay cho việc review nội dung.
5. Biên tập các chương quan trọng và dùng batch export/import khi làm ngoài hệ thống.
6. Build EPUB thử, đọc trên thiết bị thật rồi mới phát hành bản cuối.
