"""Alias "Biên tập AI" (cũ `/ai-edit-draft`) xếp thẳng job ghi trực tiếp.

Request shape cũ giữ nguyên nhưng semantics đã đổi sang GHI TRỰC TIẾP vào
nhánh `local_mt` (đồng bộ với canonical `/ai-edit`) — không còn sinh bản nháp
chờ duyệt. Route phải tự lọc chương chưa có bản dịch Local MT và báo lại số bị
bỏ qua; job chạy `step_ai_edit_local_mt_bulk` (CAS từng chương lúc thực thi).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub import revisions
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t", title="Truyện Thử"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeQueue:
    """Ghi lại lời gọi enqueue; `run=True` chạy luôn target để test kiểm tác dụng phụ."""

    def __init__(self, run: bool = False):
        self.enqueued: list[dict] = []
        self.run = run

    def enqueue(self, category, step, target, **kwargs):
        self.enqueued.append({"category": category, "step": step, **kwargs})
        if self.run:
            target(lambda msg: None)
        return type("Job", (), {"id": f"job-{len(self.enqueued)}"})()


class _FakeJob:
    def __init__(self, run: bool = False):
        self.queue = _FakeQueue(run=run)

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }


def _client(cfg, monkeypatch, *, run_job: bool = False):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob(run=run_job)
    return TestClient(app), app.state.job


def _seed(tmp_path, *, local_mt_indexes=(1, 2)):
    """3 chương; chỉ những index trong `local_mt_indexes` có bản dịch Local MT."""
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=i, url=f"http://x/{i}", title=f"Chương {i}") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        if ch.index in local_mt_indexes:
            storage.write_branch_text(ch, revisions.BRANCH_LOCAL_MT, f"MT {ch.index}")
    return storage, chapters


def test_bam_mot_cai_la_co_job_khong_can_token(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client, job = _client(cfg, monkeypatch)

    res = client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": [1, 2]})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["queued"] == 2
    assert data["skipped"] == 0
    assert data["job_id"]
    assert len(job.queue.enqueued) == 1
    assert job.queue.enqueued[0]["category"] == "ai-edit"
    assert job.queue.enqueued[0]["chapter_indexes"] == [1, 2]
    assert job.queue.enqueued[0]["ebook"] == "t"


def test_chuong_chua_co_local_mt_bi_bo_qua_va_bao_lai(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, local_mt_indexes=(1,))
    client, job = _client(cfg, monkeypatch)

    res = client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": [1, 2, 3]})

    assert res.status_code == 200
    data = res.json()
    assert data["queued"] == 1
    assert data["skipped"] == 2
    assert data["indexes"] == [1]
    assert [b["index"] for b in data["blocked"]] == [2, 3]
    # Chỉ chương đủ điều kiện mới vào job — không đốt lượt gọi AI cho chương trống.
    assert job.queue.enqueued[0]["chapter_indexes"] == [1]


def test_khong_chuong_nao_du_dieu_kien_thi_409_va_khong_enqueue(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, local_mt_indexes=())
    client, job = _client(cfg, monkeypatch)

    res = client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": [1, 2, 3]})

    assert res.status_code == 409
    assert "Local MT" in res.json()["detail"]
    assert job.queue.enqueued == []


def test_nhan_job_mot_chuong_ghi_ro_so_chuong(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client, job = _client(cfg, monkeypatch)

    client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": [1]})

    label = job.queue.enqueued[0]["label"]
    assert label.startswith("AI biên tập · Truyện Thử")
    assert "1.Chương 1" in label


def test_nhan_job_nhieu_chuong_ghi_so_luong(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client, job = _client(cfg, monkeypatch)

    client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": [1, 2]})

    assert job.queue.enqueued[0]["label"] == "AI biên tập · Truyện Thử · 2 chương"


def test_thieu_indexes_tra_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client, job = _client(cfg, monkeypatch)

    assert client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={}).status_code == 400
    assert client.post(
        "/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": []}
    ).status_code == 400
    assert client.post(
        "/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": ["abc"]}
    ).status_code == 400
    assert job.queue.enqueued == []


def test_job_chay_voi_bulk_direct_write(tmp_path, monkeypatch):
    """Job phải gọi `step_ai_edit_local_mt_bulk` (ghi trực tiếp, CAS từng chương
    lúc thực thi — chương mất bản Local MT trong lúc chờ hàng đợi bị bỏ qua)."""
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    seen: dict = {}

    from novel2epub import pipeline

    def _fake(cfg_arg, log, *, selected_indexes):
        seen["indexes"] = list(selected_indexes)
        return [1]

    monkeypatch.setattr(pipeline, "step_ai_edit_local_mt_bulk", _fake)
    client, _job = _client(cfg, monkeypatch, run_job=True)

    res = client.post("/api/ui/ebooks/t/chapters/ai-edit-draft", json={"indexes": [1, 2]})

    assert res.status_code == 200
    assert seen == {"indexes": [1, 2]}


def test_canonical_ai_edit_bat_buoc_confirm(tmp_path, monkeypatch):
    """Canonical `/ai-edit` GHI ĐÈ bản dịch nên bắt buộc `confirm: true`."""
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client, job = _client(cfg, monkeypatch)

    res = client.post("/api/ui/ebooks/t/chapters/ai-edit", json={"indexes": [1, 2]})

    assert res.status_code == 400
    assert "confirm" in res.json()["detail"].lower()
    assert job.queue.enqueued == []


def test_canonical_ai_edit_co_confirm_thi_xep_job(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client, job = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ui/ebooks/t/chapters/ai-edit",
        json={"indexes": [1, 2], "confirm": True},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert data["queued"] == 2
    assert job.queue.enqueued[0]["category"] == "ai-edit"
    assert job.queue.enqueued[0]["chapter_indexes"] == [1, 2]
