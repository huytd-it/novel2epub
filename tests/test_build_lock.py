"""Khoá build mồ côi: DB nói "đang build" nhưng hàng đợi không có job nào.

`build_artifacts` là mutex bền vững trong SQLite nhưng job build chỉ sống
trong RAM và không có `spec` nên không được `job_queue_pending` ghi lại. Nếu
tiến trình/thread chết giữa chừng, `release_build` không chạy → hàng kẹt
`building` vĩnh viễn trong khi hàng đợi trống rỗng, và mọi lần build sau bị
chặn với thông báo "đang có build khác chạy" dù không tồn tại job nào.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from novel2epub.storage import (
    ORPHAN_BUILD_ERROR,
    Storage,
    release_orphan_build_locks,
)

from app import deps


def _storage(tmp_path, slug: str = "t") -> Storage:
    return Storage(tmp_path, slug)


def _building(storage: Storage, owner: str = "job") -> None:
    """Ghi khoá build như thể `step_build_selected` vừa giành được."""
    assert storage.acquire_build(owner, manifest_snapshot=[]) is True


def _finished(storage: Storage, status: str, error: str = "") -> None:
    """Hàng build đã kết thúc — `release_build` chỉ UPDATE nên cần giành trước."""
    _building(storage)
    storage.release_build(status=status, error=error)


# ── Storage.release_orphan_build (bản theo slug, chạy lúc request) ──────────


def test_release_orphan_build_giai_phong_khoa_building(tmp_path):
    storage = _storage(tmp_path)
    _building(storage)

    assert storage.read_build()["status"] == "building"
    assert storage.release_orphan_build() is True

    build = storage.read_build()
    assert build["status"] == "failed"
    assert build["lock_owner"] == ""
    assert build["finished_at"]
    assert build["error"] == ORPHAN_BUILD_ERROR


def test_release_orphan_build_khong_pha_khoa_dang_chay(tmp_path):
    """Hàng không ở `building` thì không được ghi — idempotent + an toàn."""
    storage = _storage(tmp_path)
    assert storage.release_orphan_build() is False  # chưa có hàng nào

    _finished(storage, "done")
    before = storage.read_build()

    assert storage.release_orphan_build() is False
    assert storage.read_build() == before


def test_release_orphan_build_chi_giai_phong_ebook_duoc_hoi(tmp_path):
    other = _storage(tmp_path, "khac")
    _building(other)

    storage = _storage(tmp_path, "t")
    _building(storage)

    assert storage.release_orphan_build() is True
    assert storage.read_build()["status"] == "failed"
    assert other.read_build()["status"] == "building", "ebook khác phải giữ khoá"


# ── release_orphan_build_locks (bản toàn cục, chạy lúc khởi động) ───────────


def test_release_orphan_build_locks_quet_toan_db(tmp_path):
    a = _storage(tmp_path, "a")
    b = _storage(tmp_path, "b")
    _building(a)
    _building(b)
    c = _storage(tmp_path, "c")
    _finished(c, "done")
    d = _storage(tmp_path, "d")
    _finished(d, "failed", error="lỗi thật")

    released = release_orphan_build_locks(tmp_path / "novel2epub.db")

    assert sorted(released) == ["a", "b"]
    assert a.read_build()["status"] == "failed"
    assert b.read_build()["status"] == "failed"
    # Ebook đã xong/không lỗi phải giữ nguyên lịch sử.
    assert c.read_build()["status"] == "done"
    assert c.read_build()["error"] == ""
    assert d.read_build()["status"] == "failed"
    assert d.read_build()["error"] == "lỗi thật", "không được ghi đè lý do lỗi cũ"


def test_release_orphan_build_locks_idempotent(tmp_path):
    storage = _storage(tmp_path, "a")
    _building(storage)

    assert release_orphan_build_locks(tmp_path / "novel2epub.db") == ["a"]
    assert release_orphan_build_locks(tmp_path / "novel2epub.db") == []


# ── route /build/confirm: hàng đợi mới là nguồn sự thật ─────────────────────


class _Storage:
    """Storage giả — chỉ cần đúng bề mặt mà `ebook_build_confirm` dùng."""

    def __init__(self, *_args, status: str = "none"):
        self.status = status
        self.released = 0

    def load_manifest(self):
        return SimpleNamespace(chapters=[])

    def build_blockers(self, _chapters):
        return []

    def read_build(self):
        return {"status": self.status}

    def release_orphan_build(self):
        self.released += 1
        self.status = "failed"
        return True


class _Queue:
    """Hàng đợi giả. `has_active_ebook` là câu hỏi duy nhất route dùng."""

    def __init__(self, has_build_job: bool = False):
        self.enqueued = []
        self._has_build_job = has_build_job

    def has_active_ebook(self, ebook: str) -> bool:
        return self._has_build_job

    def enqueue(self, category, step, target, **kwargs):
        self.enqueued.append((category, step, target, kwargs))
        return SimpleNamespace(id="build-job-id")


def _client(monkeypatch, tmp_path, *, status: str, has_build_job: bool):
    cfg = SimpleNamespace(
        novel=SimpleNamespace(slug="test-book", title="Test Book"),
        output=SimpleNamespace(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "resolved_cfg", lambda _slug: cfg)

    from app.main import app
    from app.routes import webui

    storage = _Storage(status=status)
    monkeypatch.setattr(webui, "Storage", lambda *_a: storage)
    queue = _Queue(has_build_job=has_build_job)
    # monkeypatch tự khôi phục `app.state.job` — đây là global dùng chung, để
    # lại stub sẽ làm các test sau nhận queue giả.
    monkeypatch.setattr(app.state, "job", SimpleNamespace(queue=queue))
    return TestClient(app), storage, queue


def test_confirm_cho_phep_khi_khoa_mo_coi_nhung_hang_doi_trong(monkeypatch, tmp_path):
    """Bug: DB kẹt `building` từ tiến trình chết, hàng đợi trống → vẫn build được."""
    client, storage, queue = _client(
        monkeypatch, tmp_path, status="building", has_build_job=False
    )

    response = client.post("/api/ui/ebooks/test-book/build/confirm", json={"force": True})

    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == "build-job-id"
    assert storage.released == 1, "phải giải phóng khoá mồ côi"
    assert len(queue.enqueued) == 1


def test_confirm_van_chan_khi_hang_doi_co_job_build(monkeypatch, tmp_path):
    client, storage, queue = _client(
        monkeypatch, tmp_path, status="building", has_build_job=True
    )

    response = client.post("/api/ui/ebooks/test-book/build/confirm", json={"force": True})

    assert response.status_code == 409
    assert "Đang có build khác chạy" in response.json()["detail"]
    assert storage.released == 0, "khoá của job đang chạy không được đụng"
    assert queue.enqueued == []


def test_confirm_khong_ha_khoa_cua_automation_dang_build(monkeypatch, tmp_path):
    """Automation gọi `step_build_selected` trong job `step='automation'`.

    Nếu route lọc `step == 'build'` để quyết định khoá còn sống hay không thì
    nó sẽ không thấy job automation, tưởng khoá mồ côi và hạ khoá — để 2 build
    cùng ghi một file EPUB. Vì vậy route hỏi `has_active_ebook` (mọi job).
    """
    from app.queue import JobQueue

    q = JobQueue(workers={c: 0 for c in
                          ("crawl", "local-mt", "ai-translate", "ai-edit", "build", "automation")})
    q.enqueue("automation", "automation", lambda log: None, ebook="test-book")

    assert q.has_pending_step("build", "test-book") is False, "premise của bug hồi quy"
    assert q.has_active_ebook("test-book") is True


def test_confirm_khong_hoi_khoa_khi_db_khong_building(monkeypatch, tmp_path):
    client, storage, queue = _client(
        monkeypatch, tmp_path, status="done", has_build_job=False
    )

    response = client.post("/api/ui/ebooks/test-book/build/confirm", json={"force": True})

    assert response.status_code == 200
    assert storage.released == 0
    assert len(queue.enqueued) == 1


def test_confirm_voi_storage_that_giai_phong_khoa_that(monkeypatch, tmp_path):
    """E2E qua `Storage` thật + schema thật: khoá mồ côi được gỡ, job được xếp.

    Các test trên dùng stub để cô lập logic route; test này chạy SQL thật nên
    bắt được lỗi sai tên bảng/cột mà stub không thấy.
    """
    from app.main import app
    from app.routes import webui

    storage = Storage(tmp_path, "test-book")
    storage.ensure_dirs()
    _building(storage)
    assert storage.read_build()["status"] == "building"

    cfg = SimpleNamespace(
        novel=SimpleNamespace(slug="test-book", title="Test Book"),
        output=SimpleNamespace(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "resolved_cfg", lambda _slug: cfg)
    queue = _Queue(has_build_job=False)
    monkeypatch.setattr(app.state, "job", SimpleNamespace(queue=queue))

    response = TestClient(app).post(
        "/api/ui/ebooks/test-book/build/confirm", json={"force": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert len(queue.enqueued) == 1
    build = webui.Storage(tmp_path, "test-book").read_build()
    assert build["status"] == "failed"
    assert build["error"] == ORPHAN_BUILD_ERROR


# ── hook khởi động ────────────────────────────────────────────────────────


def test_lifespan_don_khoa_mo_coi_truoc_khi_scheduler_chay(monkeypatch, tmp_path):
    """`lifespan` dọn khoá mồ côi TRƯỚC `scheduler.start()` (automation có build).

    Cũng là bằng chứng rằng việc dọn KHÔNG nằm ở module scope: `lifespan` là
    async context manager nên không thể chạy lúc import — import `app.main`
    (test/tooling) không được sửa DB.
    """
    from app import main

    db = tmp_path / "novel2epub.db"
    _building(Storage(tmp_path, "t"))
    monkeypatch.setattr(deps, "DB_PATH", db)

    order: list[str] = []
    monkeypatch.setattr(
        main, "_release_orphan_build_locks", lambda: order.append("dọn") or ["t"]
    )

    class _Scheduler:
        def start(self):
            order.append("scheduler")

        def stop(self):
            pass

    monkeypatch.setattr(main.app.state, "scheduler", _Scheduler())

    with TestClient(main.app):
        pass

    assert order == ["dọn", "scheduler"]
    assert main.app.state.orphan_build_locks == ["t"]
