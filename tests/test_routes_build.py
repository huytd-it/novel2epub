from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import deps


class _Storage:
    def __init__(self, *_args):
        pass

    def load_manifest(self):
        return SimpleNamespace(chapters=[])

    def build_blockers(self, _chapters):
        return []

    def read_build(self):
        return {"status": "none"}


class _Queue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, category, step, target, **kwargs):
        self.enqueued.append((category, step, target, kwargs))
        return SimpleNamespace(id="build-job-id")


def test_build_confirm_enqueues_job_and_returns_job_id(monkeypatch, tmp_path):
    cfg = SimpleNamespace(
        novel=SimpleNamespace(slug="test-book", title="Test Book"),
        output=SimpleNamespace(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "resolved_cfg", lambda _slug: cfg)

    from app.main import app
    from app.routes import webui

    monkeypatch.setattr(webui, "Storage", _Storage)
    queue = _Queue()
    app.state.job = SimpleNamespace(queue=queue)

    response = TestClient(app).post(
        "/api/ui/ebooks/test-book/build/confirm",
        json={"force": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "job_id": "build-job-id",
        "ebook": "test-book",
    }
    assert queue.enqueued[0][0:2] == ("build", "build")
    assert queue.enqueued[0][3]["ebook"] == "test-book"
