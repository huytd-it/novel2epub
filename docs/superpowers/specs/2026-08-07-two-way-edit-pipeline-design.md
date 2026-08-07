# Pipeline hai chiều — biên tập nhiều người, đồng bộ Xưởng ⇄ Reader

Ngày: 2026-08-07
Trạng thái: đề xuất thiết kế, chưa duyệt
Sửa đổi: 2026-08-07 — bổ sung §8 đường ghi từ app editor, §9.4 luật kéo-trước-đẩy-sau, §10 glossary chỉ đọc

## 1. Bối cảnh

Pipeline hiện tại là một băng chuyền **một chiều**: `fetch-toc → crawl-new → translate-pending → cleanup-han → build → publish-reader`. Nó ngầm giả định **một người ghi duy nhất** — cái máy, do một người điều khiển. Mọi bước đều được phép ghi đè `chapters.translated_text` vì không có ai khác chạm vào đó.

Yêu cầu mới phá vỡ giả định đó: một đội editor sửa nội dung từ app đọc (có lúc offline), trong khi chủ Xưởng vẫn crawl, dịch và sửa trên máy mình. Dòng chảy trở thành **vòng tròn**, mà vòng tròn thì cần *trạng thái*, không chỉ cần *các bước*.

Ba dữ kiện từ code hiện tại định hình thiết kế:

1. **Vòng lặp hàng ngày đã an toàn sẵn.** `step_translate_selected` bỏ qua chương đã dịch (`if not force and storage.has_translated(ch)`, [pipeline.py:1104]). Crawl thêm chương mới rồi dịch pending **không** đụng chương editor đã sửa. Vấn đề không nằm ở đường chạy thường ngày.
2. **`cleanup-han` mới là mối nguy thật.** Nó nằm trong chuỗi automation chạy theo cron ([library.py:20]), bỏ qua chương đã cleanup nhờ cờ `han_cleanup_complete`, nhưng chương *vừa được editor sửa mà chưa từng cleanup* sẽ bị AI viết lại nguyên khối ([pipeline.py:1301]).
3. **Có 17 chỗ gọi `write_translated`** rải khắp `pipeline.py`, `routes/chapters.py`, `glossary.py`, `notes.py`, `opds.py`, `reader.py`. Bất kỳ cơ chế bảo vệ nào rải theo call site cũng sẽ sót.

## 2. Phạm vi

### Thuộc phạm vi

- Máy trạng thái quyền ghi của mỗi chương và bảng quy tắc "step nào được ghi vào đâu".
- Chốt bảo vệ tập trung ở tầng `Storage`.
- Đường ghi từ app editor: áp ngay khi online, xếp hàng khi offline.
- Bước pipeline mới `pull-edits`, vị trí của nó trong chuỗi, và luật kéo-trước-đẩy-sau.
- Thuật toán định vị đoạn văn chịu được việc thêm/xoá đoạn.
- Đồng bộ glossary một chiều xuống Supabase để app gợi ý thuật ngữ.
- Lược đồ dữ liệu hai phía (SQLite v9, Supabase).

### Không thuộc phạm vi

- UI của app editor (spec riêng) — §8 chỉ định nghĩa hợp đồng ghi, không định nghĩa màn hình.
- Sửa glossary từ app editor: một chiều xuống, biên tập glossary vẫn ở Xưởng.
- Sửa tiêu đề chương từ app editor — `chapter_edits` chỉ có `para_index`. Cần loại mutation riêng, spec sau.
- Xác thực/RLS chi tiết phía Supabase (spec riêng).
- Neo `para_anchors` — là **tiền đề bắt buộc**, có spec riêng, phải xong trước.
- Đường OPDS/readest và `/api/v1` PATCH hiện có: giữ nguyên, chỉ chịu thêm chốt ở §5.
- Hoàn tác (undo) một bản sửa đã áp dụng.

## 3. Nguyên tắc nền

> **Máy ghi đè được bản của máy. Máy không bao giờ ghi đè bản của người — nó ghi vào cột đối chiếu và để người quyết định.**

Mọi quyết định phía dưới đều suy ra từ câu này.

## 4. Hai trục trạng thái, không gộp

Có hai câu hỏi khác nhau về một chương, và gộp chúng vào một enum sẽ sinh ra tổ hợp trạng thái vô nghĩa:

| Trục | Câu hỏi | Lưu ở đâu |
|---|---|---|
| **Quyền ghi** | Lần cuối ai viết văn bản này — máy hay người? | **Cột mới** `chapters.edit_state` |
| **Xuất bản** | Bản hiện tại đã lên Reader chưa? | **Đã có sẵn** — `meta_json["reader"]["hash"]` |

Trục xuất bản **không cần gì mới**: `reader_sync.classify_chapters` đã so `content_hash(title, content)` với `state["hash"]` trong `meta_json` để phân loại MỚI/SỬA/KHÔNG ĐỔI. Tái dùng nguyên trạng.

**Quyết định: `edit_state` ở mức CHƯƠNG, không phải mức ĐOẠN.**

Mức đoạn chính xác hơn (máy có thể dịch lại những đoạn chưa ai chạm), nhưng nó buộc phải đổi mô hình lưu trữ từ "Markdown nguyên khối" sang "bảng đoạn văn" — đúng cái giá mà spec GĐ1 đã cân nhắc và loại bỏ, kéo theo `translator.py`, `bulk_transfer.py`, `glossary`, `notes` và toàn bộ editor 3 cột. Giữ nguyên quyết định đó.

Hai giá trị:

- `machine` (mặc định) — chưa ai sửa tay. Máy toàn quyền.
- `human` — đã có người sửa. Máy cấm ghi `translated_text`.

Chuyển `machine → human` khi và chỉ khi có người ghi: web UI, `/api/v1` PATCH, hoặc `pull-edits` áp dụng thành công. **Không có đường tự động quay về `machine`** — chỉ có thao tác có ý thức "trả chương này về cho máy" trên trang `/chapter`.

## 5. Chốt bảo vệ đặt ở đâu

**Quyết định: chốt nằm trong `Storage.write_translated`, tham số `by` là keyword BẮT BUỘC, không có giá trị mặc định.**

```python
def write_translated(self, ch: Chapter, content: str, *, by: str) -> None:
    """`by` = "machine" | "human". Không có mặc định: 17 call site phải tự
    khai báo mình là ai. Đặt mặc định "machine" sẽ chặn nhầm bản sửa tay;
    đặt mặc định "human" sẽ mở toang cho máy ghi đè. Cả hai đều sai âm thầm,
    nên thà lỗi to ngay lúc chạy test còn hơn mất dữ liệu lúc 3 giờ sáng."""
```

Vì sao không rải `if edit_state == "human": return` ở từng call site: 17 chỗ, và mỗi tính năng mới lại thêm một chỗ. Chốt ở tầng dưới cùng thì đường nào cũng phải đi qua.

Hành vi khi `by="machine"` gặp chương `human`: **không ghi `translated_text`**, mà ghi vào `translated_mt_text` và trả về cờ báo đã chuyển hướng. Bên gọi log lại.

`translated_mt_text` là lựa chọn có sẵn chứ không phải chỗ chứa tạm: docstring của `write_translated_mt` nói rõ nó là cột "VI (máy)" của editor 3 cột, độc lập với cột "Biên tập". Nên bản máy mới rơi đúng vào ô đối chiếu mà `/chapter` đã hiển thị — **không cần dựng UI mới nào**.

Đánh đổi đã chấp nhận: bản MT *nguyên thuỷ* (lần dịch đầu) bị đè bởi bản MT mới. Bản mới hữu ích hơn khi đối chiếu, và bản cũ không có ai dùng.

## 6. Quy tắc từng bước

| Bước | Chương `machine` | Chương `human` |
|---|---|---|
| `fetch-toc` | không đụng nội dung | không đụng nội dung |
| `crawl-new` | ghi `raw_text` | ghi `raw_text` — an toàn, khác cột |
| `translate-pending` | bỏ qua (đã có bản dịch) | bỏ qua |
| `translate --force` | ghi đè | → `translated_mt_text`, giữ nguyên bản người |
| **`cleanup-han`** | ghi đè | **chỉ PHÁT HIỆN, không sửa** |
| AI rewrite / find-replace hàng loạt | ghi đè | bỏ qua + báo cáo |
| `pull-edits` (mới) | áp dụng, đổi sang `human` | áp dụng |
| `build` | chỉ đọc | chỉ đọc |
| `publish-reader` | chỉ đọc | chỉ đọc |

**`cleanup-han` với chương `human` — chỉ phát hiện.** `han_cleanup.count_han()` không tốn lời gọi AI nào. Chạy đếm, không chạy sửa, rồi báo "3 chương đã biên tập vẫn còn chữ Hán sót" để người quyết định từng cái. Bỏ qua hoàn toàn thì mất tín hiệu; sửa tự động thì phá bản người. Đếm là điểm giữa đúng, và nó miễn phí.

## 7. Định vị đoạn văn: chỉ số là gợi ý, `expected` là chân lý

Spec GĐ1 chọn neo theo **vị trí** và ghi rõ đánh đổi: thêm/xoá một đoạn giữa chương thì mọi neo phía sau lệch một bậc, `expected` bắt được và trả 409. Với một người dùng thì chấp nhận được. Với một đội có sửa nằm chờ trong hàng đợi offline, mỗi lần lệch sẽ tạo ra một loạt 409 vô cớ.

**Quyết định: đổi thuật toán áp dụng thành bốn bước, dùng chỉ số làm gợi ý còn `expected` làm chân lý.**

```
1. Đổi chỉ số plaintext → chỉ số split_paras qua para_anchors.       (gợi ý)
2. split_paras[i] == expected?           → áp dụng tại i.            (~99% ca)
3. Không khớp → tìm expected trong cả chương.
     đúng MỘT dòng khớp                  → áp dụng tại đó.           (chịu được lệch)
4. Không dòng nào, hoặc NHIỀU dòng khớp  → stale, kèm văn bản hiện tại tại i.
```

Bước 3 là thứ làm nó chịu được việc thêm/xoá đoạn — đúng ca mà GĐ1 đã đành chấp nhận hỏng. Bước 4 giữ nguyên tính an toàn: nhiều dòng trùng nhau (truyện hay có dòng `"…"` lặp lại) thì **không đoán**, trả stale.

Hàm này **thuần** — vào `(markdown, anchor_index, expected, new_text)`, ra `(markdown_mới, lý_do)`. Không I/O, test được không cần DB. Đặt cạnh `notes.replace_para` và dùng lại nó ở bước cuối.

### Vì sao KHÔNG chặn theo hash cả chương

Cách đơn giản hơn là cho mỗi bản sửa mang `base_hash` của chương lúc editor nhìn thấy, lệch thì từ chối ngay. Loại bỏ vì **quá chặt**: editor A sửa đoạn 5, editor B sửa đoạn 17 cùng chương; A lên trước làm đổi hash cả chương → B bị từ chối dù hai người không hề đụng nhau. Với một đội thì đây là kiểu từ chối làm người ta bỏ dùng công cụ.

`expected` ở mức đoạn cho đúng thứ cần: hai người sửa hai đoạn khác nhau **không bao giờ** xung đột.

## 8. Đường ghi từ app editor

Phần này định nghĩa **hợp đồng ghi** — cái gì xảy ra giữa lúc editor bấm lưu và lúc Xưởng kéo bản sửa về. Bỏ qua nó thì tính năng đúng về kỹ thuật mà hỏng về vận hành.

### 8.1 Vấn đề

Nếu bản sửa chỉ nằm trong `chapter_edits` chờ Xưởng kéo, app render lại từ `chapter_contents` và **bản sửa biến mất trước mắt editor**. Họ sẽ tưởng bấm hụt, sửa lại lần nữa, rồi mất lòng tin vào công cụ trước khi kịp báo lỗi. Editor phải thấy kết quả **ngay**, kể cả khi máy Xưởng đang tắt.

### 8.2 Hai chế độ, cùng một log

**Online — áp ngay qua Edge Function `submit-edit`.** Trong một transaction:

1. `insert into chapter_edits (...) values (..., status='applied_remote')` — trùng `client_uuid` thì bỏ qua, trả về bản ghi cũ.
2. Định vị đoạn bằng **đúng thuật toán §7** rồi thay vào `chapter_contents.content`.
3. Cập nhật `content_hash`. `para_anchors` **không đổi** — thay nội dung một đoạn không làm đổi số đoạn.

Không định vị được → không ghi gì vào `chapter_contents`, đặt `status='stale'` kèm `current_text`, trả 409 cho client.

**Offline — hàng đợi cục bộ.** Bản sửa nằm trong IndexedDB, app render đè lên văn bản gốc kèm dấu hiệu "đang chờ đồng bộ". Có mạng thì đẩy lần lượt lên `submit-edit`. `client_uuid` sinh lúc tạo bản sửa, không phải lúc gửi — đó là thứ khiến gửi lại nhiều lần vẫn chỉ áp một lần.

Lớp phủ cục bộ tự tan khi văn bản nền đã khớp với bản sửa. Không cần logic dọn dẹp riêng.

### 8.3 Bất biến hội tụ

Cùng một bản sửa được áp ở hai nơi — Edge Function áp lên **plaintext**, Xưởng áp lên **Markdown** — phải cho ra cùng một plaintext:

```
md_to_plaintext(áp_vào_markdown(md, i, new_text)) == áp_vào_plaintext(md_to_plaintext(md), j, new_text)
```

Vi phạm bất biến này sẽ sinh ping-pong đẩy-kéo vô tận: Xưởng thấy hash lệch nên đẩy xuống, Supabase lại lệch tiếp, lặp mãi.

**Ca phá vỡ bất biến: dòng heading.** Trong Markdown là `## Tiểu mục`, trong plaintext là `Tiểu mục` (`md_to_plaintext` bỏ dấu `#`). Editor sửa thành `Tiểu mục mới`; nếu Xưởng ghi thẳng chuỗi đó vào dòng Markdown thì **dấu `##` biến mất** — plaintext vẫn khớp nên không ai phát hiện, nhưng heading đã thành đoạn văn thường và EPUB render sai từ đó về sau.

**Quyết định: khi áp dụng, giữ nguyên tiền tố Markdown của dòng.** Tách `^#{1,6}\s+` ra trước, chỉ thay phần chữ, rồi ghép lại. Cho phép editor sửa lỗi trong tiêu đề tiểu mục mà không phá cấu trúc. Đây phải là một test riêng, không chỉ là một dòng bình luận.

Heading **đầu tiên** của chương không nằm trong plaintext (`md_to_plaintext` bỏ hẳn — nó trùng cột `title` bên Reader) nên không có đường sửa từ app. Nhất quán với việc sửa tiêu đề chương nằm ngoài phạm vi.

### 8.4 Ranh giới quyền

RLS phải đặt đúng chỗ này:

| Bảng | editor | Edge Function (service_role) |
|---|---|---|
| `chapter_edits` | `insert` | toàn quyền |
| `chapter_contents` | `select` | `update` |

Editor **không bao giờ** được `update` thẳng `chapter_contents`. Mọi thay đổi nội dung đi qua log. Đây là ranh giới biến "sửa nội dung" thành thao tác kiểm toán được và dựng lại được — mất nó là mất luôn lý do để có log.

### 8.5 Vòng đời `status`

| Giá trị | Nghĩa |
|---|---|
| `applied_remote` | Đã áp lên `chapter_contents`, Xưởng chưa kéo |
| `applied` | Xưởng đã áp vào `translated_text` — khép vòng |
| `stale` | Không định vị được, kèm `current_text` để editor xử lý |

Không có `pending`: `submit-edit` áp ngay hoặc từ chối ngay. Trạng thái "chờ" chỉ tồn tại trong IndexedDB của client, không nằm trên server.

## 9. Bước mới: `pull-edits`

Kéo các bản `applied_remote` từ Supabase về, áp vào `translated_text` bằng thuật toán §7, rồi đánh dấu `applied`.

### 9.1 Quy tắc áp dụng

**Thứ tự áp dụng: tăng dần theo `id`, gom theo chương.** Không tuỳ tiện. Hai bản sửa nối tiếp trên cùng một đoạn (`A→B` rồi `B→C`) chỉ cùng thành công khi áp đúng thứ tự; đảo lại thì bản thứ hai `expected=B` gặp văn bản `A` và chết oan.

**Idempotency bằng `client_uuid`.** Mạng chập chờn khiến client gửi lại; `unique(client_uuid)` phía Supabase và con trỏ `last_pulled_edit_id` phía Xưởng đảm bảo mỗi bản sửa áp đúng một lần.

**Con trỏ: `ebooks.last_pulled_edit_id`.** Theo từng ebook chứ không toàn cục — xoá và đồng bộ lại một truyện thì không kéo theo các truyện khác.

**Kết quả mỗi bản sửa:** `applied` hoặc `stale` (xem §8.5). Với `stale`, ghi kèm **văn bản hiện tại** ngược lên Supabase. Đây không phải chi tiết phụ: thiếu nó thì công của editor biến mất im lặng, và họ sẽ mất lòng tin vào công cụ trước khi kịp báo lỗi.

`stale` ở bước này hiếm hơn ở `submit-edit`, vì Edge Function đã lọc trước — nó chỉ xảy ra khi Xưởng cũng sửa cùng đoạn đó trong khoảng giữa hai lần kéo.

### 9.2 Ứng xử khi hỏng

**Chương bị dịch lại thì vô hiệu hoá cả cụm.** Khi `translate --force` chạy trên một chương, mọi bản sửa đang chờ của chương đó được đánh `stale` **chủ động**, với lý do riêng "chương đã được dịch lại", thay vì để chúng chết lẻ tẻ với thông báo khó hiểu.

**Lỗi mạng KHÔNG được chặn chuỗi.** `run_automation_steps` dừng ở step lỗi đầu tiên. `pull-edits` phải tự bắt lỗi mạng, log, và trả về bình thường. Lý do: mất mạng lúc 2 giờ sáng không được phép chặn `build` và `publish-reader`. Đẩy xuống bản chưa có sửa mới là đúng — đó vẫn là sự thật hiện tại.

### 9.3 Vị trí trong chuỗi

```
fetch-toc → crawl-new → translate-pending → cleanup-han → pull-edits → build → publish-reader
```

`pull-edits` đặt **sau** `cleanup-han` và **trước** `build`:

- Sau cleanup: để bản sửa của người là thứ cuối cùng chạm vào văn bản, không bị AI cleanup đi sau đè lên.
- Trước build và publish: để bản sửa lên thẳng EPUB, và được đẩy ngược xuống Reader — đó là cách editor **nhìn thấy** sửa của mình đã vào hệ thống.

Không sinh vòng lặp: đẩy xuống là idempotent theo `content_hash`, chu kỳ sau sẽ phân loại là KHÔNG ĐỔI.

### 9.4 Luật kéo-trước-đẩy-sau

Vì §8 cho phép Supabase ghi nội dung, bản trên Reader có lúc **mới hơn** bản ở Xưởng. Đẩy mù khi đó sẽ đè bản cũ lên bản mới.

Phạm vi nguy hiểm hẹp hơn tưởng tượng, và cần nói chính xác. `classify_chapters` so `content_hash` **hiện tại của Xưởng** với `meta_json["reader"]["hash"]` — tức bản Xưởng đẩy lần trước. Nó **không** nhìn nội dung thật trên remote. Hệ quả:

| Xưởng có sửa chương này? | Kết quả phân loại | Bản sửa của editor |
|---|---|---|
| Không | KHÔNG ĐỔI → không đẩy | **an toàn** |
| Có | SỬA → đẩy nguyên chương | **bị đè** nếu chưa kéo |

Nghĩa là mối nguy chỉ xuất hiện ở chương mà **cả hai bên cùng chạm vào**. Nhưng đó chính là chương quý nhất — nơi bạn và editor cùng để tâm.

**Quyết định: `publish-reader` không bao giờ chạy một mình. Nó luôn kéo trước.**

- Chuỗi automation đã đúng sẵn nhờ thứ tự ở §9.3.
- **Nút đẩy tay** `POST /api/ebooks/{slug}/publish/push` ([ebooks.py:265]) hiện đẩy thẳng. Phải đổi thành job ghép: kéo bản sửa của ebook đó, rồi mới đẩy — **trong cùng một job**, không phải hai job nối nhau trong hàng đợi. Hai job rời nhau thì ai đó sẽ kéo job đẩy lên trước trong `/queue` và luật vỡ trong im lặng.

Không chọn phương án "chặn nút đẩy khi còn bản sửa đang chờ": nó bắt người dùng xử lý một tình huống mà máy tự xử lý được, và cái giá của việc quên là mất dữ liệu.

## 10. Glossary chỉ đọc xuống Supabase

### 10.1 Vì sao thuộc spec này

Editor làm việc trong app sẽ **không thấy** glossary, bảng nhân vật hay bản MT — những công cụ mạnh nhất của Xưởng. Với truyện dịch, glossary là đòn bẩy chất lượng số một: nhiều người sửa mà không ai thấy bảng thuật ngữ thì tên riêng và ngôi xưng sẽ trôi dạt trong vài tuần, và trôi dạt thuật ngữ là loại lỗi **không thể phát hiện bằng cách đọc một chương** — chỉ lộ ra khi đọc liền mạch, lúc đã muộn.

Nó thuộc spec này chứ không phải spec sau, vì nó là điều kiện để việc biên tập nhiều người *không làm giảm* chất lượng.

### 10.2 Một chiều, chỉ đọc

Glossary đi **xuống** và chỉ đi xuống. Biên tập glossary vẫn hoàn toàn ở Xưởng, nơi có AI review, duyệt hàng loạt và bảng nhân vật. Không có đường ghi ngược từ app.

Lý do: glossary là dữ liệu **toàn truyện**, sửa một mục ảnh hưởng mọi chương. Cho 5 người sửa đồng thời mà không có cơ chế duyệt là công thức tạo mâu thuẫn thuật ngữ — đúng thứ nó sinh ra để ngăn.

### 10.3 Cơ chế

Nguồn: `storage.read_glossary_notes()` — chính hàm mà `footnotes.annotate` đang dùng lúc build, nên app editor và chú thích trong EPUB nói cùng một thứ tiếng.

```sql
create table glossary_terms (
  book_id    uuid not null references books(id) on delete cascade,
  term_zh    text not null,
  term_vi    text not null,
  note       text,
  updated_at timestamptz default now(),
  primary key (book_id, term_zh)
);
```

RLS: ai đọc được sách thì đọc được glossary của sách đó; chỉ `service_role` ghi.

**Đồng bộ gộp vào `publish-reader`, không thành step riêng.** Glossary nhỏ, và nó phải luôn đi cùng nhịp với nội dung: đẩy chương mới mà glossary cũ thì app gợi ý sai thuật ngữ ngay trên chương vừa đẩy. Gộp vào một bước thì không bao giờ lệch pha.

Đẩy toàn bộ theo kiểu upsert + xoá mục không còn — glossary một truyện hiếm khi quá vài trăm mục, không đáng làm đồng bộ tăng dần.

### 10.4 Dùng để làm gì

Hai chỗ, cùng một dữ liệu:

- **App editor** — gợi ý thuật ngữ khi sửa: chạm vào từ đã có trong glossary thì hiện bản dịch chuẩn và ghi chú.
- **App đọc** — chú thích cho người đọc, đúng tính năng footnote/glossary đã bàn cho novel-reader. Một công đôi việc.

## 11. Lược đồ dữ liệu

### Xưởng — SQLite, `SCHEMA_VERSION` 8 → 9

Khai trong `_SCHEMA_STATEMENTS` cho DB mới và trong `_ADDED_COLUMNS` để `_ensure_columns` vá DB cũ, đúng lối cột `api_json` của v8:

```python
# v9: pipeline hai chiều — quyền ghi mỗi chương + con trỏ kéo bản sửa
("chapters", "edit_state", "TEXT NOT NULL DEFAULT 'machine'"),
("ebooks", "last_pulled_edit_id", "INTEGER NOT NULL DEFAULT 0"),
```

Mặc định `'machine'` khiến toàn bộ dữ liệu cũ (6016 chương) mang đúng nghĩa: chưa ai sửa qua đường editor.

### Supabase

```sql
alter table chapter_contents
  add column para_anchors jsonb,      -- chỉ số plaintext -> chỉ số split_paras
  add column content_hash text;       -- khớp reader_sync.content_hash

create table chapter_edits (
  id           bigserial primary key,
  client_uuid  uuid unique not null,
  chapter_id   uuid not null references chapters(id) on delete cascade,
  para_index   int  not null,
  expected     text not null,
  new_text     text not null,
  editor_id    uuid not null references auth.users,
  status       text not null,       -- applied_remote | applied | stale (§8.5)
  current_text text,                -- điền khi status='stale'
  created_at   timestamptz default now()
);

create index chapter_edits_pull_idx on chapter_edits (id)
  where status = 'applied_remote';  -- pull-edits chỉ quét phần chưa kéo
```

`para_anchors` phải được ghi **cùng transaction** với `content`. Neo của bản cũ áp lên bản mới là sai lệch âm thầm — loại lỗi nguy hiểm nhất trong cả thiết kế này.

`status` không có `default`: `submit-edit` luôn phải quyết định `applied_remote` hay `stale` ngay tại chỗ. Để mặc định thì một Edge Function lỗi giữa chừng sẽ để lại bản ghi ở trạng thái mơ hồ mà không ai chịu trách nhiệm.

## 12. Khả năng quan sát

`pull-edits` log mỗi lần chạy: `áp dụng N / stale M / bỏ qua K`, kèm slug và chỉ số chương của từng ca `stale`. Xuất hiện ở `/queue` và `/logs` như mọi step khác.

Trang `/chapter` hiện thêm: huy hiệu `edit_state`, và danh sách bản sửa `stale` của chương đó — đổ vào hệ thống `notes` sẵn có thay vì dựng UI mới.

Token và `service_key` tuyệt đối không vào log, giữ nguyên nguyên tắc của `reader_client.py`.

## 13. Test

Theo lối tách logic thuần khỏi I/O của `reader_sync.py` và `opds.py`:

| File | Nội dung |
|---|---|
| `test_edit_state.py` | Chuyển `machine → human` đúng lúc; không có đường tự động về `machine` |
| `test_write_guard.py` | `by="machine"` gặp chương `human` → **không** đổi `translated_text`, có đổi `translated_mt_text`; thiếu `by` → `TypeError` |
| `test_cleanup_han_guard.py` | `cleanup-han` **không** nuốt được bản đã biên tập; vẫn đếm và báo cáo Hán sót |
| `test_locate_para.py` | Bốn bước §7: khớp gợi ý; lệch một bậc vẫn tìm ra; nhiều dòng trùng → stale; không thấy → stale |
| `test_edit_convergence.py` | Bất biến §8.3 trên dữ liệu sinh ngẫu nhiên; **dòng heading giữ nguyên `##` sau khi áp** |
| `test_pull_edits.py` | Thứ tự tăng dần theo id; hai sửa nối tiếp cùng đoạn đều thành công; `client_uuid` trùng chỉ áp một lần; lỗi mạng không ném ra ngoài |
| `test_publish_pulls_first.py` | Nút đẩy tay sinh job **ghép**; đẩy không bao giờ chạy mà chưa kéo |
| `test_glossary_sync.py` | Đẩy gộp trong `publish-reader`; mục bị xoá ở Xưởng thì mất trên Supabase |

### Test khứ hồi — quan trọng nhất

Dựng chương thật → đẩy lên (giả lập Supabase) → sinh hai bản sửa từ hai "editor" trên hai đoạn khác nhau → **áp qua đường `submit-edit`** → kéo về → khẳng định **cả hai cùng vào, không đoạn nào khác động, và `content_hash` hai phía bằng nhau**. Rồi lặp lại với hai bản sửa cùng một đoạn → khẳng định bản thứ hai thành `stale` kèm `current_text` đúng.

Vế "hash hai phía bằng nhau" là thứ chứng minh bất biến §8.3 — thiếu nó thì ping-pong đẩy-kéo sẽ chỉ lộ ra khi chạy thật.

Đây là test duy nhất chứng minh cả vòng tròn khép kín. Các test khác chỉ chứng minh từng mảnh rời.

## 14. Rủi ro

| # | Rủi ro | Xử lý |
|---|---|---|
| 1 | Sót một trong 17 call site `write_translated` | `by` là keyword bắt buộc → sót thì `TypeError` ngay lúc chạy test, không im lặng |
| 2 | Neo lệch giữa `md_to_plaintext` và `split_paras` | Tiền đề bắt buộc, có spec riêng, phải xong trước bước này |
| 3 | Editor làm việc trên bản văn cũ → nhiều `stale` | Nhẹ hẳn nhờ §8: bản sửa áp ngay lên Supabase nên editor luôn nhìn bản mới nhất của chính đội mình. Chỉ còn lệch với bản Xưởng sửa tay chưa đẩy |
| 4 | Chương `human` tích tụ, máy không còn cải thiện được | Thao tác có ý thức "trả về cho máy" trên `/chapter`; `cleanup-han` vẫn đếm nên tín hiệu không mất |
| 5 | Crawl lại chương đã dịch làm `raw_text` đổi mà bản dịch thì không | Ngoài phạm vi. Cần một cờ "raw đổi sau khi dịch" ở spec sau |
| 6 | Không hoàn tác được bản sửa đã áp dụng | Log Supabase là append-only nên dựng lại được; UI undo thuộc spec sau |
| 7 | **Ping-pong đẩy-kéo** do vi phạm bất biến §8.3 | `test_edit_convergence.py` + vế hash trong test khứ hồi. Nếu lọt qua, triệu chứng là một chương bị đẩy lại ở **mọi** chu kỳ dù không ai sửa — thêm cảnh báo log khi một chương bị phân loại SỬA quá N lần liên tiếp |
| 8 | Edge Function `submit-edit` thành điểm chết đơn lẻ | Offline queue đã là đường lui: hỏng thì client giữ trong IndexedDB và thử lại, không mất bản sửa |
| 9 | Glossary trôi dạt vì editor không thấy thuật ngữ | §10. Nếu §10 bị cắt khỏi phạm vi thì rủi ro này **quay lại nguyên vẹn** — đó là lý do nó nằm trong spec này chứ không phải spec sau |

## 15. Việc phải làm trước

Thiết kế này đứng trên **`para_anchors`**. Chưa có neo đúng thì `pull-edits` sẽ ghi nhầm đoạn một cách âm thầm — tệ hơn nhiều so với chưa có tính năng. Không khởi công §8 hay §9 trước khi neo có test khứ hồi chạy trên dữ liệu thật.
