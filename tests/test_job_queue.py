import json
import threading
import time

import pytest

from app.queue import JobQueue


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_has_active_ebook_detects_pending_and_ignores_other_ebook():
    queue = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0})
    queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")

    assert queue.has_active_ebook("book-a") is True
    assert queue.has_active_ebook("book-b") is False


def test_has_active_ebook_detects_running_job():
    started = threading.Event()
    release = threading.Event()
    queue = JobQueue(workers={"crawl": 1, "translate": 0, "build": 0})

    def target(log):
        started.set()
        release.wait(timeout=2)

    queue.enqueue("crawl", "crawl", target, ebook="book-a")
    assert started.wait(timeout=2)
    try:
        assert queue.has_active_ebook("book-a") is True
    finally:
        release.set()


def test_has_active_ebook_ignores_cancelled_history_job():
    queue = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0})
    job = queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")
    assert queue.cancel(job.id) is True

    assert queue.has_active_ebook("book-a") is False


def test_retire_ebook_rejects_new_jobs_until_restored():
    queue = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0})
    assert queue.retire_ebook("book-a") is True

    with pytest.raises(ValueError, match="đã bị xóa"):
        queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")

    queue.restore_ebook("book-a")
    queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")


def test_retire_ebook_rejects_existing_job():
    queue = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0})
    queue.enqueue("crawl", "crawl", lambda log: None, ebook="book-a")

    assert queue.retire_ebook("book-a") is False


def test_second_job_enqueues_and_auto_starts_when_free():
    q = JobQueue(workers={"crawl": 1, "translate": 1})
    gate = threading.Event()
    order = []

    def make_target(name):
        def _target(log):
            order.append(f"start:{name}")
            gate.wait(timeout=5)
            order.append(f"end:{name}")
        return _target

    j1 = q.enqueue("crawl", "crawl", make_target("a"))
    assert _wait_until(lambda: order == ["start:a"])

    j2 = q.enqueue("crawl", "crawl", make_target("b"))
    snap = q.snapshot()
    assert any(j["id"] == j2.id for j in snap["pending"]["crawl"])

    gate.set()
    assert _wait_until(lambda: "end:b" in order)
    assert order == ["start:a", "end:a", "start:b", "end:b"]
    assert j1.state == "done"


def test_crawl_and_translate_run_in_parallel():
    q = JobQueue(workers={"crawl": 1, "translate": 1})
    started = {"crawl": threading.Event(), "translate": threading.Event()}
    gate = threading.Event()

    def make_target(cat):
        def _target(log):
            started[cat].set()
            gate.wait(timeout=5)
        return _target

    q.enqueue("crawl", "crawl", make_target("crawl"))
    q.enqueue("translate", "translate", make_target("translate"))

    assert started["crawl"].wait(timeout=5)
    assert started["translate"].wait(timeout=5)
    gate.set()


def test_n_worker_concurrency_within_category():
    q = JobQueue(workers={"crawl": 3, "translate": 1})
    concurrent = {"n": 0, "max": 0}
    lock = threading.Lock()
    gate = threading.Event()

    def _target(log):
        with lock:
            concurrent["n"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["n"])
        gate.wait(timeout=5)
        with lock:
            concurrent["n"] -= 1

    for _ in range(3):
        q.enqueue("crawl", "crawl", _target)

    assert _wait_until(lambda: concurrent["max"] == 3)
    gate.set()


def test_both_job_waits_for_exclusive_access_and_blocks_others():
    q = JobQueue(workers={"crawl": 1, "translate": 1})
    crawl_started = threading.Event()
    crawl_gate = threading.Event()
    both_started = threading.Event()
    both_gate = threading.Event()
    events = []

    def _crawl_target(log):
        crawl_started.set()
        events.append("crawl-start")
        crawl_gate.wait(timeout=5)
        events.append("crawl-end")

    def _both_target(log):
        both_started.set()
        events.append("both-start")
        both_gate.wait(timeout=5)
        events.append("both-end")

    q.enqueue("crawl", "crawl", _crawl_target)
    assert crawl_started.wait(timeout=5)

    q.enqueue("both", "build", _both_target)
    # both job phải đợi crawl xong, không chạy ngay.
    time.sleep(0.2)
    assert not both_started.is_set()

    # job crawl mới không được chạy trong khi both job đang chờ độc quyền.
    second_crawl_started = threading.Event()
    q.enqueue("crawl", "crawl", lambda log: second_crawl_started.set())
    time.sleep(0.2)
    assert not second_crawl_started.is_set()

    crawl_gate.set()
    assert both_started.wait(timeout=5)
    both_gate.set()
    assert _wait_until(lambda: second_crawl_started.is_set())


def test_cancel_pending_and_running():
    q = JobQueue(workers={"crawl": 1})
    gate = threading.Event()
    started = threading.Event()

    j1 = q.enqueue("crawl", "crawl", lambda log: (started.set(), gate.wait(timeout=5)))
    assert started.wait(timeout=5)

    j2 = q.enqueue("crawl", "crawl", lambda log: None)
    assert q.cancel(j2.id) is True
    assert j2.state == "cancelled"

    assert q.cancel(j1.id) is True
    assert j1.cancel_event.is_set()
    gate.set()


def test_retry_clones_job_with_same_params():
    q = JobQueue(workers={"crawl": 1})
    calls = []

    def _target(log):
        calls.append(1)

    j1 = q.enqueue("crawl", "crawl", _target, label="my-step")
    assert _wait_until(lambda: len(calls) == 1)

    j2 = q.retry(j1.id)
    assert j2 is not None
    assert j2.id != j1.id
    assert j2.label == "my-step"
    assert _wait_until(lambda: len(calls) == 2)


def test_reorder_pending_jobs():
    q = JobQueue(workers={"crawl": 1})
    gate = threading.Event()
    started = threading.Event()

    q.enqueue("crawl", "crawl", lambda log: (started.set(), gate.wait(timeout=5)))
    assert started.wait(timeout=5)

    j_a = q.enqueue("crawl", "crawl", lambda log: None)
    j_b = q.enqueue("crawl", "crawl", lambda log: None)

    assert q.reorder(j_b.id, j_a.id) is True
    pending_ids = [j["id"] for j in q.snapshot()["pending"]["crawl"]]
    assert pending_ids == [j_b.id, j_a.id]
    gate.set()


def test_history_cap_bounded():
    q = JobQueue(workers={"crawl": 1}, history_limit=2)
    for _ in range(5):
        done = threading.Event()
        q.enqueue("crawl", "crawl", lambda log, _e=done: _e.set())
        assert _wait_until(lambda: done.is_set())
    time.sleep(0.1)
    assert len(q.snapshot()["history"]) <= 2


def test_target_outcome_appears_in_history_snapshot():
    q = JobQueue(workers={"crawl": 1})
    outcome = {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"đã có raw": 1},
    }

    job = q.enqueue("crawl", "crawl", lambda log: outcome)

    assert _wait_until(lambda: job.state == "done")
    history = q.snapshot()["history"]
    assert next(item for item in history if item["id"] == job.id)["outcome"] == outcome


def test_target_outcome_survives_history_persistence(tmp_path):
    db_path = tmp_path / "novel2epub.db"
    outcome = {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"đã có raw": 1},
    }
    q = JobQueue(workers={"crawl": 1}, db_path=db_path)
    job = q.enqueue("crawl", "crawl", lambda log: outcome)

    assert _wait_until(lambda: job.state == "done")
    q._save_history()

    restored = JobQueue(workers={"crawl": 0}, db_path=db_path)
    history = restored.snapshot()["history"]
    assert next(item for item in history if item["id"] == job.id)["outcome"] == outcome


def test_load_history_without_outcome_defaults_to_none(tmp_path):
    db_path = tmp_path / "novel2epub.db"
    from novel2epub.db import get_thread_connection

    old_record = {
        "id": "legacy-job",
        "category": "crawl",
        "step": "crawl",
        "state": "done",
        "enqueued_at": 1.0,
        "ended_at": 2.0,
        "error": "",
    }
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO job_queue_history (id, data_json, ended_at) VALUES (?, ?, ?)",
            ("legacy-job", json.dumps(old_record), 2.0),
        )

    q = JobQueue(workers={"crawl": 0}, db_path=db_path)
    assert q._jobs["legacy-job"].outcome is None
    assert "outcome" not in q.snapshot()["history"][0]


def test_multi_worker_different_ebooks_run_in_parallel():
    q = JobQueue(workers={"translate": 2, "crawl": 1})
    started = {"a": threading.Event(), "b": threading.Event()}
    gate = threading.Event()

    def make_target(name):
        def _target(log):
            started[name].set()
            gate.wait(timeout=5)
        return _target

    q.enqueue("translate", "translate", make_target("a"), ebook="ebook-a")
    q.enqueue("translate", "translate", make_target("b"), ebook="ebook-b")

    assert started["a"].wait(timeout=5)
    assert started["b"].wait(timeout=5)
    gate.set()


def test_same_ebook_translate_queued_not_parallel():
    q = JobQueue(workers={"translate": 2, "crawl": 1})
    started_1 = threading.Event()
    gate = threading.Event()
    order = []

    def target_1(log):
        order.append("start-1")
        started_1.set()
        gate.wait(timeout=5)
        order.append("end-1")

    def target_2(log):
        order.append("start-2")

    q.enqueue("translate", "translate", target_1, ebook="ebook-a")
    assert started_1.wait(timeout=5)

    q.enqueue("translate", "translate", target_2, ebook="ebook-a")
    time.sleep(0.3)
    assert "start-2" not in order, "Job 2 không được chạy khi cùng ebook đang dịch"

    assert q.is_ebook_busy("translate", "ebook-a") is True
    assert q.is_ebook_busy("translate", "ebook-b") is False

    gate.set()
    assert _wait_until(lambda: "start-2" in order)


def test_crawl_and_translate_same_ebook_parallel():
    q = JobQueue(workers={"crawl": 1, "translate": 1})
    crawl_started = threading.Event()
    translate_started = threading.Event()
    gate = threading.Event()

    def _crawl(log):
        crawl_started.set()
        gate.wait(timeout=5)

    def _translate(log):
        translate_started.set()
        gate.wait(timeout=5)

    q.enqueue("crawl", "crawl", _crawl, ebook="ebook-a")
    q.enqueue("translate", "translate", _translate, ebook="ebook-a")

    assert crawl_started.wait(timeout=5)
    assert translate_started.wait(timeout=5)
    gate.set()


def test_worker_full_third_job_pending():
    q = JobQueue(workers={"translate": 2, "crawl": 1})
    started_1 = threading.Event()
    started_2 = threading.Event()
    gate = threading.Event()

    def _target_1(log):
        started_1.set()
        gate.wait(timeout=5)

    def _target_2(log):
        started_2.set()
        gate.wait(timeout=5)

    def _target_3(log):
        pass  # không nên chạy

    j1 = q.enqueue("translate", "translate", _target_1, ebook="ebook-a")
    j2 = q.enqueue("translate", "translate", _target_2, ebook="ebook-b")
    assert started_1.wait(timeout=5)
    assert started_2.wait(timeout=5)

    j3 = q.enqueue("translate", "translate", _target_3, ebook="ebook-c")
    time.sleep(0.3)
    snap = q.snapshot()
    pending_ids = [j["id"] for j in snap["pending"]["translate"]]
    assert j3.id in pending_ids, "Job thứ 3 phải ở pending khi workers=2 đã đầy"

    gate.set()


def test_default_workers_in_job_runner():
    from app.job import JobRunner

    runner = JobRunner()
    assert runner.queue._workers["translate"] == 2
    assert runner.queue._workers["crawl"] == 1

    runner2 = JobRunner(workers={"translate": 4, "crawl": 2})
    assert runner2.queue._workers["translate"] == 4
    assert runner2.queue._workers["crawl"] == 2


# ── Resume sau restart: job pending/running có spec được lưu ra đĩa và có
# thể enqueue lại (xem JobQueue.register_kind/load_pending). ──────────────


def test_pending_job_with_spec_persisted_to_disk(tmp_path):
    db_path = tmp_path / "novel2epub.db"
    q = JobQueue(workers={"translate": 1}, db_path=db_path)
    gate = threading.Event()
    started = threading.Event()

    # Chiếm worker duy nhất để job thứ 2 (có spec) ở lại pending.
    q.enqueue("translate", "busy", lambda log: (started.set(), gate.wait(timeout=5)))
    assert started.wait(timeout=5)

    q.enqueue(
        "translate", "demo-job", lambda log: None,
        spec={"kind": "demo", "params": {"n": 1}},
    )

    from novel2epub.db import get_thread_connection

    def _pending_rows():
        conn = get_thread_connection(db_path)
        return conn.execute("SELECT spec_json FROM job_queue_pending").fetchall()

    assert _wait_until(lambda: len(_pending_rows()) == 1)
    rows = _pending_rows()
    assert json.loads(rows[0]["spec_json"]) == {"kind": "demo", "params": {"n": 1}}

    gate.set()


def test_load_pending_reenqueues_job_with_registered_kind(tmp_path):
    """Mô phỏng khởi động lại app: DB còn 1 job pending từ lần chạy trước,
    register_kind rồi load_pending() phải enqueue lại và chạy."""
    db_path = tmp_path / "novel2epub.db"
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO job_queue_pending (id, category, step, label, ebook, spec_json) "
            "VALUES ('job1', 'translate', 'demo-job', 'demo-job', '', ?)",
            (json.dumps({"kind": "demo", "params": {"n": 7}}),),
        )

    q = JobQueue(workers={"translate": 1}, db_path=db_path)
    executed = []

    def factory(params):
        def _target(log):
            executed.append(params["n"])
        return _target

    q.register_kind("demo", factory)
    restored = q.load_pending()
    assert restored == 1
    assert _wait_until(lambda: executed == [7])


def test_load_pending_skips_unregistered_kind(tmp_path):
    """Job pending có kind chưa register (vd version cũ hơn/thiếu registration)
    bị bỏ qua thay vì raise lỗi lúc khởi động."""
    db_path = tmp_path / "novel2epub.db"
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO job_queue_pending (id, category, step, label, ebook, spec_json) "
            "VALUES ('job1', 'translate', 'mystery', 'mystery', '', ?)",
            (json.dumps({"kind": "unknown-kind", "params": {}}),),
        )

    q = JobQueue(workers={"translate": 1}, db_path=db_path)
    restored = q.load_pending()
    assert restored == 0
    assert q.snapshot()["pending"]["translate"] == []


def _call_with_timeout(fn, timeout=5.0):
    """Chạy fn() trong thread riêng — phát hiện deadlock mà không treo cả suite."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("value", fn()), daemon=True)
    t.start()
    t.join(timeout)
    return (not t.is_alive()), box.get("value")


def test_start_now_job_finishes_without_deadlocking_queue(tmp_path):
    """Job chạy qua start_now đi theo nhánh "extra worker" lúc kết thúc. Nhánh
    này từng gọi _save_pending() khi vẫn giữ self._cv (Lock không reentrant) →
    worker treo vĩnh viễn và mọi request web UI đọc snapshot() đứng theo."""
    q = JobQueue(
        workers={"crawl": 0, "translate": 0, "build": 0},
        db_path=tmp_path / "novel2epub.db",
    )
    ran = threading.Event()
    job = q.enqueue(
        "crawl", "crawl", lambda log: ran.set(), spec={"kind": "noop", "params": {}}
    )

    assert q.start_now(job.id) is True
    assert ran.wait(timeout=5)
    assert _wait_until(lambda: job.state == "done")

    ok, snap = _call_with_timeout(q.snapshot)
    assert ok, "snapshot() treo → worker chưa nhả lock hàng đợi"
    assert any(item["id"] == job.id for item in snap["history"])

    ok, _ = _call_with_timeout(lambda: q.enqueue("crawl", "crawl", lambda log: None))
    assert ok, "enqueue() treo sau khi job start_now kết thúc"
    assert q.snapshot()["workers"]["crawl"] == 0


def test_delete_removes_job_from_history_table(tmp_path):
    from novel2epub.db import get_thread_connection

    db_path = tmp_path / "novel2epub.db"
    q = JobQueue(workers={"crawl": 1, "translate": 0, "build": 0}, db_path=db_path)
    job = q.enqueue("crawl", "crawl", lambda log: None)
    assert _wait_until(lambda: job.state == "done")

    conn = get_thread_connection(db_path)

    def _row_count():
        return conn.execute(
            "SELECT COUNT(*) AS n FROM job_queue_history WHERE id = ?", (job.id,)
        ).fetchone()["n"]

    assert _wait_until(lambda: _row_count() == 1)
    assert q.delete(job.id) is True
    assert _row_count() == 0

    restored = JobQueue(workers={"crawl": 0, "translate": 0, "build": 0}, db_path=db_path)
    assert job.id not in restored._jobs
