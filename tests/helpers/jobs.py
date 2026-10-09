"""Chờ worker và SQLite theo điều kiện thật, với timeout hữu hạn."""
import time

from novel2epub.db import get_thread_connection


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def wait_for_persisted_job(db_path, job_id):
    """State/history trong RAM có trước commit SQLite của worker."""
    conn = get_thread_connection(db_path)
    assert wait_until(lambda: conn.execute(
        "SELECT 1 FROM job_queue_history WHERE id = ?", (job_id,)
    ).fetchone() is not None), f"Job {job_id} chưa được lưu vào SQLite"
