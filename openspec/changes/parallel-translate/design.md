## Context

JobQueue dùng 1 worker thread / category mặc định. Category "translate" chỉ chạy được 1 job tại 1 thời điểm. Khi translate ebook A đang chạy, mọi nỗ lực translate ebook B khác đều bị xếp hàng đợi — button trên Web UI disabled. Hai ebook khác nhau có `Storage` riêng (data_dir/slug khác nhau), không xung đột I/O, nên hoàn toàn có thể chạy song song.

- `JobQueue.__init__`: `self._workers = {c: max(1, int((workers or {}).get(c, 1))) for c in CATEGORIES}`
- `_can_start(category)`: Không kiểm tra `_active[category] < _workers[category]` — chỉ trả job nếu không bị "both" chặn và queue không rỗng
- `_worker_loop`: 1 thread / worker, loop forever, gọi `_can_start`, nếu có job thì `_active[category] += 1`, chạy xong `_active[category] -= 1`
- Web UI dùng `category_status("translate")` để quyết định disable nút: `running=True` nếu có bất kỳ job translate nào đang chạy

## Goals / Non-Goals

**Goals:**
- Cho phép 2+ job translate trên các ebook khác nhau chạy song song
- Chặn 2 job translate trên cùng 1 ebook chạy đồng thời (xung đột ghi file)
- Web UI hiển thị trạng thái translate per-ebook (không disable nhầm)
- Tương thích ngược: API queue public giữ nguyên chữ ký

**Non-Goals:**
- Song song hóa translate trong cùng 1 ebook (đã có `max_workers` pipeline)
- Thay đổi cơ chế crawl/build — chỉ translate bị ảnh hưởng bởi UX, crawl vẫn 1 worker là đủ
- Load balancing hay priority queue phức tạp

## Decisions

### D1: Tăng worker translate mặc định lên 2

`JobRunner.__init__` nhận `workers` dict. Mặc định `None` → mỗi category 1 worker. Đổi default thành `{"translate": 2}`.

**Ưu điểm**: Đơn giản, chỉ cần sửa 1 dòng default. User có thể override qua `workers` param.

**Nhược điểm**: Worker 2 luôn chạy kể cả khi chỉ có 1 ebook. Chi phí không đáng kể (1 thread idle).

### D2: `_can_start` kiểm tra slot worker

Sửa `_can_start` để trả job chỉ khi `_active[category] < self._workers[category]`. Hiện tại `_can_start` không hề kiểm tra _active.

```python
def _can_start(self, category: str) -> Job | None:
    if category == "both":
        if not self._pending["both"]:
            return None
        if self._active["crawl"] or self._active["translate"] or self._both_active:
            return None
        return self._pending["both"][0]
    if self._both_active or self._both_waiting:
        return None
    if self._active[category] >= self._workers[category]:
        return None                    # <-- thêm dòng này
    if not self._pending[category]:
        return None
    return self._pending[category][0]
```

**Alternatives considered**:
- Không check slot → worker sẽ dequeue job extra nhưng không chạy (mất job khỏi queue)
- Tạo worker thread động → phức tạp, không cần thiết

### D3: Per-ebook lock — cấm 2 job cùng ebook + cùng category

Thêm `self._ebook_locks: dict[str, set[str]]` mapping category → set ebook slug đang chạy. `_can_start` kiểm tra: nếu `pending.ebook` đã có trong `_ebook_locks[category]` thì skip.

```python
# Trong _can_start (sau khi đã xác định job candidates):
ebook = self._pending[category][0].ebook
if ebook and ebook in self._ebook_locks.get(category, set()):
    # Có job khác cùng category + ebook đang chạy → skip
    return None
```

Khi start: `self._ebook_locks[category].add(job.ebook)`
Khi done: `self._ebook_locks[category].discard(job.ebook)`

**Tại sao đặt ở _can_start thay vì enqueue?** Vì muốn xếp hàng chờ (pending) thay vì từ chối — job cho ebook thứ 2 sẽ tự động chạy khi job đầu hoàn tất.

**Tại sao per-category?** Vì cùng ebook có thể crawl + translate song song vô hại (crawl ghi raw/, translate đọc raw/ và ghi translated/ — file khác nhau).

### D4: Web UI — trạng thái per-ebook

`category_status` hiện chỉ trả về running/step cho category. Thêm field `ebook_slug` vào status response. Web UI check: disable nút translate chỉ khi `running=True AND ebook_slug == current_slug`.

Chi tiết:
- `category_status` trả về `ebook_slug` của job đang chạy (empty string nếu không có)
- Template so sánh `job.translate.ebook_slug` với `slug` của ebook hiện tại
- Nếu khác slug → nút translate vẫn active

**Tách route translate thành per-ebook endpoint**: Route `/ebooks/{slug}/translate` đã có qua `enqueue_step` (xem `app/routes/jobs.py`). Chỉ cần status hiển thị đúng.

### D5: Xử lý category "both"

Job "both" (build/run) vẫn chặn toàn bộ category khác — đây là behavior đúng vì build đọc cả raw + translated. Không thay đổi.

## Risks / Trade-offs

- **Worker tăng nhưng CPU-bound**: NMT local (HachimiMT) dùng CPU nhiều, chạy 2 job NMT song song có thể làm chậm. Pipeline đã tự set `workers=1` cho NTM (dòng 860 pipeline.py), nên worker thread chỉ dùng cho API-based translator (OpenAI/Google). Chấp nhận được.
- **Deadlock tiềm năng**: Nếu một job translate treo (timeout API), nó chiếm worker và lock ebook. Mitigation: cancel event + `_execute` đã có try/except. Thêm timeout ở tầng job nếu cần sau.
- **Độ phức tạp `_can_start` tăng**: Từ 10 dòng lên ~20 dòng. Có thể tách thành helper method `_ebook_slot_available`.
