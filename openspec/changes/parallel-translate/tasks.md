## 1. JobQueue — multi-worker + per-ebook lock

- [x] 1.1 Thêm `self._ebook_locks: dict[str, set[str]]` trong `JobQueue.__init__`, khởi tạo `{c: set() for c in (*CATEGORIES, "both")}`
- [x] 1.2 Sửa `_can_start`: thêm check `self._active[category] >= self._workers[category]` → return None
- [x] 1.3 Sửa `_can_start`: thêm check per-ebook lock — nếu `pending.ebook in self._ebook_locks[category]` → return None
- [x] 1.4 Sửa `_worker_loop`: sau khi dequeue job, thêm `self._ebook_locks[category].add(job.ebook)` cạnh `self._active[category] += 1`
- [x] 1.5 Sửa `_worker_loop`: sau khi job hoàn tất, thêm `self._ebook_locks[category].discard(job.ebook)` cạnh `self._active[category] -= 1`

## 2. JobRunner — default workers

- [x] 2.1 Đổi default `workers` trong `JobRunner.__init__` từ `None` thành `{"translate": 2}`
- [x] 2.2 Đảm bảo `workers=None` (từ callers cũ) vẫn fallback về default bằng logic `workers or {"translate": 2}`

## 3. Category status — per-ebook field

- [x] 3.1 Sửa `category_status` trong `JobQueue`: thêm field `ebook_slug` + `running_ebooks` vào dict trả về
- [x] 3.2 Cập nhật route/template kiểm tra `running_ebooks` để quyết định disable nút

## 4. Web UI templates

- [x] 4.1 Xác định template nào render nút translate (ebook.html, glossary.html, chapter.html)
- [x] 4.2 Sửa template: disable nút translate chỉ khi `running AND current_slug in running_ebooks`

## 5. Tests

- [x] 5.1 Viết test cho `_can_start` với multi-worker: 2 translate job ebook khác nhau chạy song song
- [x] 5.2 Viết test cho per-ebook lock: cùng ebook translate bị xếp hàng chờ
- [x] 5.3 Viết test cho per-ebook lock khác category: crawl + translate cùng ebook chạy song song
- [x] 5.4 Viết test cho default workers: `JobRunner()` khởi tạo `_workers["translate"] == 2`
- [x] 5.5 Viết test cho worker full: 2 job translate chạy + job thứ 3 pending
- [x] 5.6 Chạy `pytest tests/test_job_queue.py -v` đảm bảo không regression
