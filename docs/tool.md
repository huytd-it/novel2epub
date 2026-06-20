---
pm-task: true
projectId: "e6s3o01gmqkzxa3b"
parentId:
id: "ykjd5sg0mql09jb6"
title: "Dịch truyền thống"
type: "task"
status: "todo"
priority: "medium"
start: "2026-06-19"
due: ""
progress: 0
assignees: []
tags: []
subtaskIds: []
dependencies: []
createdAt: "2026-06-19T14:09:45.474Z"
updatedAt: "2026-06-19T14:17:39.349Z"
---

1. Convert truyện là gì?
Convert truyện nói nôm na là chuyển 1 đầu truyện từ ngôn ngữ này sang ngôn ngữ khác mà không cần ( có thì càng tốt ) đảm bảo chất lượng của nội dung truyện. Từ, cấu trúc, ngôn ngữ…vẫn giữ lại đặc đặc điểm của ngôn ngữ cần convert. Nói gọn lại nó là Chuyển Ngữ sang ngôn ngữ mình hiểu.
2. Làm thế nào để convert?
Hiện nay có rất nhiều chương trình convert nhưng phổ biến nhất thì có hai loại. Đó là Chinese Conbert Pro (CCP) và Quick Translator.
Thông dụng nhất và được phần lớn các converter sử dụng hiện nay là chương trình Quick Translator. Ở đây mình sẽ hướng dẫn các bạn sơ qua vể chương trình này và 1 số thao tác chủ yếu để convert từng chương truyện cũng như convert 1 bộ truyện hoàn chỉnh!
*Chú ý: Để có thể sử dụng các phần mềm này, máy của các bạn bắt buộc phải có cài chương trình NET Framework 3.5 và cài font tiếng Trung trong máy
Có thể download phần mềm Net Framework 3.5 tại đây: http://www.microsoft.com/en-us/download/details.aspx?id=22
3. Cách convert.
Để tiện lợi mình sẽ đưa bản Quick Translator của mình lên để các bạn tham khảo.
Link down : http://www.mediafire.com/?8kdf4bbj0box9fn
Các bạn giải nén ra.

Các file quan trọng cần chú ý sẽ là:
Name.txt
Vietphrase.txt
QuickTranslator
QuickConverter
QuickAnalyzer
QuickVietPhraseMerger
Hai file đầu là file data, là huyết mạch của mỗi converter. Muốn có bản convert đẹp thì hoàn thiện data mỗi ngày là không thể thiếu. Có bạn từng hỏi: Sao bạn convert chương truyện này 5p đã xong mà tớ làm 15 phút cũng không được như bạn? Đó là nhờ data họ tốt!

I - Đặc điểm của từng file

1 - File name.txt
Đây là file được lưu dưới dạng txt, dùng để lưu giữ và update các tên, chiêu thức, linh thú, danh sơn...của truyện. Nếu bộ name của bạn phong phú thì quá trình convert sẽ rất nhanh vì bạn không phải edit nhiều.

Để hoàn thiện file name có hai cách update là thủ công và tự động. Thủ công là khi convert từng chương bạn thấy có tên hay địa danh mới thì copy phần tiếng Trung và viết TV viết hoa vào file name.
Còn tự động bạn có thể tham khảo hướng dẫn của Lana bên TTV:
Muốn Edit Names hay từ vietphrase mới thì Bôi đen từ cần/muốn update click chuột phải hiện ra một cái bảng cho mình chọn muốn update cái gì

Thí dụ : update names chẳng hạn !
Sau đó click chuột vào Update Name nó lại hiện ra một bảng khác :

Bạn muốn viết hoa hay sửa chữa gì đều được.

Từ chưa có trong data thì chọn nút Add , nếu có rồi mà muốn thay đổi thì chọn Update , Muốn xóa thì chọn Delete

2 - File Vietphrase.txt
Là nơi lưu trữ các cấu trúc từ, cũng bao gồm cả name luôn.
Ví dụ: ngã môn = ta nhóm ( đám bọn họ) khi chỉnh lại sẽ là chúng ta
Update file này thường là thủ công khi trong quá trình cv thấy có nhiều cấu trúc từ không hay và mạch lạc.

Cả 2 file này đều được lưu ở dạng Encoding UTF - 8

3- QuickTranslator

Đây là chương trình mà các converter hay dùng nhất, dùng để convert các chương lẻ trong truyện. Các dịch giả cũng hay dùng để dịch truyện vì nó có vp, hv, và cả từ điển kèm theo!

Nhiệm vụ của các bạn sẽ là copy 1 doạn txt tiếng trung và làm theo hướng dẫn.

1. Kích vào phần Translate From Clipboad nó sẽ hiện lên cái bảng trên ( mình lấy 1 chương TCTG làm thử)
2.Bên trái có hai phần, kích vào Hán việt sẽ ra txt hán việt, kích vào TTrung sẽ ra txt trung
3.Bên phải có 3 phần
-vp : ít dùng
-vp 1 nghĩa: cvter thường dùng cái này
-Quick Web: Các bạn có thể xem 1 trang web tiếng trung bằng ngôn ngữ VP

4 - QuickConverter

Chủ yếu là dùng để convert các file truyện có dung lượng lớn, gọi nôm na là file gộp!
Khi mở QC sẽ có dạng:

Để sử dụng chương trình này các bạn phải down txt trung rồi cho vào 1 folder nào đó ( A )
1. Thư mục nguồn, kick vào tìm đến A
2. Thư mục ra sản phẩm, thường có dạng A_QuickConverter
3. Các định dạng: QC có 6 định dạng nhưng thường chỉ sử dụng 3-4 định dạng thôi. Phổ biến nhất là Vp cho độc giả, HV cho độc giả, dạng cột cho dịch giả. Dạng Trung (TXT) cũng thỉnh thoảng sử dụng vì khi down txt cả cục nó sẽ ra định dạng mình không đọc được.

Sau khi chọn xong định dạng, bấm Run mà ngồi đợi sản phẩm thôi!

Rất dễ phải không các bạn!

Có time mình sẽ chia sẻ kinh nghiệm lấy txt ở 1 số trang thông dụng như qidian, book.zongheng. kenwen...và cả những trường hợp đi tìm txt nữa!

Project: [[Text-To-Speech|Novel AI translate]]