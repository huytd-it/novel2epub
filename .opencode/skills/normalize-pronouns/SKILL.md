---
name: normalize-pronouns
description: Chuẩn hóa xưng hô không đồng nhất trong truyện võ hiệp/tiên hiệp về ta/ngươi, ưu tiên quy tắc offline không tốn token; xem diff trước khi ghi.
---

# Chuẩn hóa xưng hô ít chi phí

## Nguyên tắc

- Dùng `novel2epub.pronouns`/CLI sẵn có, không gọi AI để viết lại toàn chương.
- “Ta/ngươi” là lựa chọn phong cách võ hiệp ít phân biệt vai vế, không phải đại từ trung tính cho mọi thể loại. Không ép cho truyện hiện đại/tình cảm khi chưa được yêu cầu.
- Hỏi hoặc xác định rõ slug, nhánh `ai`/`local_mt` và phạm vi index. Không suy đoán nhánh xuất bản từ tên truyện.
- Chỉ thay các dạng rõ ràng `tôi/tao/tớ → ta`, `mày → ngươi` trong cặp ngoặc kép cùng dòng. Số nhiều `chúng/bọn/tụi + tôi/tao/tớ → bọn ta`; `chúng/bọn/tụi mày → các ngươi`. Không đổi `chúng tôi` thành `chúng ta` vì sẽ mất phân biệt người nghe có thuộc nhóm hay không.
- Giữ lời kể, `hắn/nàng/y`, `anh/em/bạn/mình/mi`, vai vế `sư phụ/đệ tử/huynh/muội`, tên riêng và entity đã protect. Không suy luận giới tính hoặc người nói.
- Ngoặc thiếu, ngoặc lồng, thoại nhiều dòng/thoại gạch đầu dòng bị bỏ qua; không thay bằng regex toàn sách để tăng độ phủ.

## Quy trình

Có thể dùng giao diện thay CLI: trang truyện → nút **Chuẩn hóa xưng hô** ở đầu
bảng Chương → chọn nhánh, chương đang chọn hoặc khoảng index trong kết quả lọc →
**Xem trước thay đổi** → duyệt diff → tích xác nhận → **Áp dụng**. Mỗi lượt tối đa
50 chương/2 MB. Trong **Chỉ sửa bên trong dấu**, có thể chọn **Chỉ nháy đơn / dấu
thoại Trung** (`'…'`, `‘…’`, `“…”`, `「…」`, `『…』`), hoặc **Chỉ ngoặc đơn** (`(…)`,
`（…）` — có thể là chú thích, không chắc là thoại). Bộ lọc dùng dấu trong bản dịch,
không căn chỉnh raw Trung. Ngoặc lồng/thiếu/nhiều dòng bị bỏ qua, không sửa phần
ngoài vùng được chọn. CLI tương ứng: `--dialogue-marks single_chinese` hoặc
`--dialogue-marks parentheses`; mặc định `standard` giữ hành vi cũ.
Không cần gọi model; approval cũ bị từ chối nếu nội dung/phạm vi/kiểu dấu/entity
thay đổi. Không bấm Áp dụng khi chưa có sự đồng ý sửa dữ liệu của người dùng.

1. Xem trước 5–10 chương đại diện (dùng Python trong `.venv` nếu có):

   ```sh
   python -m novel2epub -e <slug> normalize-pronouns --branch local_mt --from 1 --to 10
   ```

2. Đọc **toàn bộ diff**, kiểm tra từ đồng âm (`cái tôi`, `tôi luyện`, `thanh tao`, `lông mày`...), trích dẫn không phải thoại, và tên nhân vật. Detector chỉ là heuristic, không bảo đảm hiểu ngữ cảnh. Nếu có tên cần bảo vệ, thêm entity protect qua giao diện có sẵn rồi xem lại diff.
3. Cho người dùng xem số chương/chỗ thay, giới hạn của thuật toán và xin duyệt trước khi ghi. Không coi yêu cầu tạo tính năng là yêu cầu sửa ngay dữ liệu truyện.
4. Khi được duyệt, sao lưu DB bằng lệnh `python -m novel2epub backup`, sau đó chạy cùng phạm vi với `--apply`.
5. Mỗi chương được commit qua `ChapterVersionService` với revision/hash CAS và lịch sử bất biến. Nếu xung đột, dừng; báo các chương đã lưu, xem lại diff mới trước khi chạy tiếp. Không force hoặc ghi SQL trực tiếp. Raw, snapshot MT và nhánh còn lại không bị sửa.
6. Trường hợp còn lại: báo unresolved, chỉ đề nghị AI xét đoạn nhỏ khi người dùng đồng ý. Không tự bật dịch lại, build EPUB hay publish Reader.

## Phạm vi toàn sách

Bỏ `--from`/`--to` để quét tất cả chương chưa skipped có bản dịch hoàn chỉnh trong nhánh được chỉ định. Mặc định luôn preview; chỉ có `--apply` mới sửa nội dung. Ghi theo từng chương, không phải transaction toàn sách.
