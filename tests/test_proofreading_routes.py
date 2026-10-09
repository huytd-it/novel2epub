from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import webui
from novel2epub.proofreading_service import snapshot
from novel2epub.storage import Chapter, Manifest, Storage
from tests.helpers.db import write_db_config


@pytest.fixture
def route_book(tmp_path, monkeypatch):
    write_db_config(tmp_path / "n.db", ebooks={"t": {"novel": {"title": "Thử"}}})
    storage = Storage(str(tmp_path), "t")
    chapters = [Chapter(index=i, url=f"http://test/{i}", title=f"Chương {i}: Thử") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        storage.write_raw(ch, "raw untouched")
        storage.write_branch_text(ch, "local_mt", "😀  中\n\nCuối.")
        storage.write_branch_titles(ch, "local_mt", ch.title, "")
        storage.mark_branch_complete(ch, "local_mt")
    cfg = SimpleNamespace(output=SimpleNamespace(data_dir=str(tmp_path)), novel=SimpleNamespace(slug="t"), ai=SimpleNamespace(openai=SimpleNamespace(base_url="", model="")))
    monkeypatch.setattr(webui.deps, "resolved_cfg", lambda slug: cfg)
    pending = []
    class Queue:
        def enqueue(self, category, step, target, **kwargs):
            job = SimpleNamespace(id=f"mock-{len(pending)}", category=category, target=target, kwargs=kwargs)
            pending.append(job)
            return job
    app = FastAPI()
    app.include_router(webui.router)
    app.state.job = SimpleNamespace(queue=Queue())
    return TestClient(app), storage, pending


def test_analyze_confirmation_queue_results_selected_only(route_book):
    client, storage, jobs = route_book
    response = client.post("/api/ui/ebooks/t/proofreading/analyze", json={"indexes": [1, 3], "codes": ["double_space", "han_remaining"]})
    assert response.status_code == 200
    report = response.json()
    payload = {"chapters": report["chapters"], "codes": report["codes"], "token": report["token"], "confirmed": True}
    modified = {**payload, "chapters": report["chapters"][:1]}
    assert client.post("/api/ui/ebooks/t/proofreading/run", json=modified).status_code == 400
    assert client.post("/api/ui/ebooks/t/proofreading/run", json=payload).status_code == 200
    assert jobs[0].kwargs["chapter_indexes"] == [1, 3]
    assert "secret" not in str(jobs[0].kwargs["spec"])
    outcome = jobs[0].target(lambda _: None)
    assert "chapters" not in outcome  # Queue poll không gửi full blobs.
    fetched = client.get("/api/ui/ebooks/t/proofreading/results/" + outcome["proofreading_report_id"]).json()
    assert [i["index"] for i in fetched["chapters"]] == [1, 3]
    assert all(i["committed"] and i["unresolved"] for i in fetched["chapters"])
    assert snapshot(storage, 2)["text"] == "😀  中\n\nCuối."
    assert client.post("/api/ui/ebooks/t/proofreading/run", json=payload).status_code == 400


def test_no_indexes_no_codes_no_confirmation_and_bad_candidates(route_book):
    client, storage, jobs = route_book
    assert client.post("/api/ui/ebooks/t/proofreading/analyze", json={}).status_code == 400
    report = client.post("/api/ui/ebooks/t/proofreading/analyze", json={"indexes": [1], "codes": []}).json()
    payload = {"chapters": report["chapters"], "codes": [], "token": report["token"], "confirmed": True}
    assert client.post("/api/ui/ebooks/t/proofreading/run", json=payload).status_code == 400
    assert client.post("/api/ui/ebooks/t/proofreading/decide", json={"items": [{"id": "bad"}], "action": "apply"}).status_code == 400
    assert not jobs


def test_book_check_on_demand_only(route_book, monkeypatch):
    client, storage, jobs = route_book
    from novel2epub import proofreading_service
    calls = []
    original = proofreading_service.book_check
    def check(storage):
        calls.append(True)
        return original(storage)
    monkeypatch.setattr(proofreading_service, "book_check", check)
    client.post("/api/ui/ebooks/t/proofreading/analyze", json={"indexes": [1], "codes": ["double_space"]})
    assert not calls
    assert client.post("/api/ui/ebooks/t/proofreading/book-check").status_code == 200
    assert not calls  # Background, không đọc blobs trong request/render.
    assert jobs[0].category == "validation"
    outcome = jobs[0].target(lambda _: None)
    report = client.get("/api/ui/ebooks/t/proofreading/results/" + outcome["proofreading_report_id"]).json()
    assert calls and report["checked"] == 3


def test_one_click_scan_all_codes_read_only_and_compact(route_book):
    client, storage, jobs = route_book
    before = [snapshot(storage, i) for i in (1, 2, 3)]
    response = client.post("/api/ui/ebooks/t/proofreading/scan")
    assert response.status_code == 200 and len(jobs) == 1
    assert jobs[0].category == "validation"
    assert jobs[0].kwargs["spec"]["params"]["scan"] is True
    outcome = jobs[0].target(lambda _: None)
    assert "chapters" not in outcome
    report = client.get("/api/ui/ebooks/t/proofreading/results/" + outcome["proofreading_report_id"]).json()
    assert report["scan"] and report["checked"] == 3
    assert [row["index"] for row in report["chapters"]] == [1, 2, 3]
    codes = {issue["code"] for row in report["chapters"] for issue in row["issues"]}
    assert {"han_remaining", "double_space", "identical_content"} <= codes
    assert all("text" not in row and "token" not in row for row in report["chapters"])
    assert [snapshot(storage, i) for i in (1, 2, 3)] == before
    assert storage.read_extra_json("proofreading_confirmations") is None
    assert storage.conn.execute("SELECT count(*) FROM ai_revisions").fetchone()[0] == 0


def test_scan_marks_unavailable_publication_and_still_includes_all_indexes(route_book):
    client, storage, jobs = route_book
    storage.write_meta(storage.get_chapter(1), {"local_mt_complete": False})
    client.post("/api/ui/ebooks/t/proofreading/scan")
    outcome = jobs[0].target(lambda _: None)
    report = client.get("/api/ui/ebooks/t/proofreading/results/" + outcome["proofreading_report_id"]).json()
    assert report["chapters"][0]["error"]
    assert "han_remaining" not in {i["code"] for i in report["chapters"][0]["issues"]}
    assert len(report["chapters"]) == 3


def test_canonical_draft_save_cas_history_and_no_raw_changes(route_book):
    client, storage, jobs = route_book
    before = snapshot(storage, 1)
    payload = {"translated": "Draft saved\n\nCuối.", "expected_rev": before["revision"], "expected_hash": before["hash"], "branch": before["branch"], "operation_id": "draft-save-test"}
    saved = client.post("/api/ui/ebooks/t/chapters/1/translated", json=payload)
    assert saved.status_code == 200
    assert saved.json()["content_hash"] == snapshot(storage, 1)["hash"]
    assert storage.read_raw(storage.get_chapter(1)) == "raw untouched"
    assert client.post("/api/ui/ebooks/t/chapters/1/translated", json={**payload, "operation_id": "new-op"}).status_code == 409
    assert storage.conn.execute("SELECT count(*) FROM chapter_revisions WHERE ebook_slug='t' AND chapter_index=1").fetchone()[0] == 2


def test_manual_proofreading_save_correct_publication_and_history_provenance(route_book):
    client, storage, jobs = route_book
    before = snapshot(storage, 1)
    response = client.post("/api/ui/ebooks/t/chapters/1/translated", json={
        "translated": "😀 Trung\n\nCuối.", "title": before["title"], "expected_rev": before["revision"],
        "expected_hash": before["hash"], "branch": before["branch"], "expected_publication_branch": before["branch"],
        "expected_publication_title": before["display_title"], "operation_id": "manual-proofreading", "proofreading_codes": ["han_remaining", "double_space"],
    })
    assert response.status_code == 200
    row = storage.conn.execute("SELECT o.message, o.metadata_json FROM chapter_revisions r JOIN chapter_operations o ON o.id=r.operation_id WHERE r.ebook_slug='t' AND r.chapter_index=1 ORDER BY r.revision_number DESC LIMIT 1").fetchone()
    assert "Soát lỗi thủ công" in row["message"] and "proofreading_manual" in row["metadata_json"]
    assert "han_remaining" in row["metadata_json"]
    assert storage.read_raw(storage.get_chapter(1)) == "raw untouched"
    assert not jobs
    state = client.get("/api/ui/ebooks/t/proofreading/state").json()
    assert state["checked"] == 1 and state["unchecked"] == 2
    assert {"han_remaining", "double_space"}.isdisjoint({i["code"] for i in state["chapters"][0]["issues"]})


def test_saved_state_survives_scans_and_updates_after_each_algorithm_commit(route_book):
    client, storage, jobs = route_book
    assert client.get("/api/ui/ebooks/t/proofreading/state").json()["checked"] == 0
    client.post("/api/ui/ebooks/t/proofreading/scan")
    jobs[0].target(lambda _: None)
    old = client.get("/api/ui/ebooks/t/proofreading/state").json()
    assert old["persisted"] and old["checked"] == 3
    preview = client.post("/api/ui/ebooks/t/proofreading/analyze", json={"indexes": [1], "codes": ["double_space"]}).json()
    response = client.post("/api/ui/ebooks/t/proofreading/run", json={"chapters": preview["chapters"], "codes": ["double_space"], "token": preview["token"], "confirmed": True})
    assert response.status_code == 200
    jobs[1].target(lambda _: None)
    current = client.get("/api/ui/ebooks/t/proofreading/state").json()
    assert "double_space" not in {i["code"] for i in current["chapters"][0]["issues"]}
    assert "double_space" in {i["code"] for i in current["chapters"][1]["issues"]}
    assert current["chapters"][0]["source"]["revision"] > old["chapters"][0]["source"]["revision"]


def test_toc_error_filter_applies_before_pagination_and_select_all(route_book):
    from novel2epub.content_validation import refresh_book
    from novel2epub.proofreading_service import run
    client, storage, _ = route_book
    cfg = SimpleNamespace(ai=SimpleNamespace(openai=SimpleNamespace(base_url="", model="")))
    refresh_book(storage)
    run(storage, cfg, [snapshot(storage, 1)], ["double_space"])
    result = client.get("/api/ui/ebooks/t/chapters", params={"proofreading_code": "double_space", "limit": 1}).json()
    assert result["indexes"] == [2, 3] and result["matched"] == 2
    assert [row["index"] for row in result["rows"]] == [2]
    page_two = client.get("/api/ui/ebooks/t/chapters", params={"proofreading_code": "double_space", "limit": 1, "offset": 1}).json()
    assert [row["index"] for row in page_two["rows"]] == [3]
    assert client.get("/api/ui/ebooks/t/chapters", params={"proofreading_code": "unknown"}).json()["matched"] == 0
    manifest = storage.load_manifest()
    manifest.chapters[1].skipped = True
    storage.save_manifest(manifest)
    assert client.get("/api/ui/ebooks/t/chapters", params={"proofreading_code": "double_space", "filter_skipped": "any"}).json()["indexes"] == [3]


def test_no_publication_does_not_fallback_active(route_book):
    client, storage, jobs = route_book
    ch = storage.get_chapter(1)
    storage.write_meta(ch, {"local_mt_complete": False})
    report = client.post("/api/ui/ebooks/t/proofreading/analyze", json={"indexes": [1], "codes": ["han_remaining"]}).json()
    assert report["chapters"][0]["error"]
    validation = client.get("/api/ui/ebooks/t/chapters/1/validation").json()
    assert "han_remaining" not in {i["code"] for i in validation["issues"]}
    assert "empty_content" in {i["code"] for i in validation["issues"]}
