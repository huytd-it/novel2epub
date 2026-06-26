import threading
import time

from app.queue import JobQueue


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


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
