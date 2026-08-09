"""Test API ghi chú lỗi dịch của trang đọc (app/routes/notes.py)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub import glossary_ai
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
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, translated="Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc.", mt=None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if translated is not None:
        storage.write_translated(ch, translated)
    if mt is not None:
        storage.write_translated_mt(ch, mt)
    return storage, ch


def _client(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def _create_note(client, **overrides):
    payload = {
        "chapter_index": 7,
        "para_index": 1,
        "selected_text": "hắn nói",
        "para_text": "Rồi hắn nói một câu.",
        "note": "sai ngôi xưng",
    }
    payload.update(overrides)
    res = client.post("/api/ebooks/t/notes", data=payload)
    assert res.status_code == 200, res.text
    return res.json()


def test_crud_round_trip(tmp_path, monkeypatch):
    storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)

    note = _create_note(client)
    assert note["status"] == "open"
    assert note["suggestion"] is None

    # list toàn ebook + filter theo chương
    res = client.get("/api/ebooks/t/notes")
    assert [n["id"] for n in res.json()["notes"]] == [note["id"]]
    assert client.get("/api/ebooks/t/notes?chapter=99").json()["notes"] == []

    # update text ghi chú
    res = client.post(f"/api/ebooks/t/notes/{note['id']}/update", data={"note": "đổi mô tả"})
    assert res.json()["note"] == "đổi mô tả"

    # dismiss rồi delete
    res = client.post(f"/api/ebooks/t/notes/{note['id']}/dismiss")
    assert res.json()["status"] == "dismissed"
    res = client.post(f"/api/ebooks/t/notes/{note['id']}/delete")
    assert res.json() == {"ok": True}
    assert storage.read_notes() == []


def test_create_note_validates(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    res = client.post("/api/ebooks/t/notes", data={
        "chapter_index": 99, "para_index": 0, "selected_text": "x", "note": "",
    })
    assert res.status_code == 404
    res = client.post("/api/ebooks/t/notes", data={
        "chapter_index": 7, "para_index": 0, "selected_text": "   ", "note": "",
    })
    assert res.status_code == 400


def test_ai_fix_persists_suggestions(tmp_path, monkeypatch):
    storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    n1 = _create_note(client)
    n2 = _create_note(client, selected_text="Kết thúc.", para_index=2, para_text="Kết thúc.")

    def fake_fix(ai_cfg, raw, translated, notes, glossary, **kwargs):
        assert {n["id"] for n in notes} == {n1["id"], n2["id"]}
        # AI chỉ trả lời 1 mục — mục kia giữ suggestion=None
        return [{"id": n1["id"], "fixed_text": "anh ta nói", "explanation": "đúng ngôi"}]

    monkeypatch.setattr(glossary_ai, "fix_passages", fake_fix)
    res = client.post("/api/ebooks/t/notes/ai-fix", data={
        "note_ids": f"{n1['id']},{n2['id']}", "chapter_index": 7,
    })
    assert res.status_code == 200, res.text

    # Đề xuất đã persist vào notes.json (không chỉ nằm trong response)
    saved = {n["id"]: n for n in storage.read_notes()}
    assert saved[n1["id"]]["suggestion"]["fixed_text"] == "anh ta nói"
    assert saved[n2["id"]]["suggestion"] is None


def test_ai_fix_rejects_mixed_chapters_and_ai_error(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    ch7, ch8 = Chapter(index=7, url="u7"), Chapter(index=8, url="u8")
    storage.save_manifest(Manifest(slug="t", chapters=[ch7, ch8]))
    storage.write_translated(ch7, "hắn nói")
    storage.write_translated(ch8, "hắn nói")
    client = _client(tmp_path, monkeypatch)
    n1 = _create_note(client, para_index=0, para_text="hắn nói")
    n2 = _create_note(client, chapter_index=8, para_index=0, para_text="hắn nói")

    res = client.post("/api/ebooks/t/notes/ai-fix", data={
        "note_ids": f"{n1['id']},{n2['id']}", "chapter_index": 7,
    })
    assert res.status_code == 400

    def boom(*args, **kwargs):
        raise RuntimeError("AI hỏng")

    monkeypatch.setattr(glossary_ai, "fix_passages", boom)
    res = client.post("/api/ebooks/t/notes/ai-fix", data={
        "note_ids": n1["id"], "chapter_index": 7,
    })
    assert res.status_code == 502
    assert "AI hỏng" in res.json()["detail"]


def test_apply_happy_path_keeps_mt_snapshot(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, mt="Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc.")
    client = _client(tmp_path, monkeypatch)
    note = _create_note(client)

    monkeypatch.setattr(
        glossary_ai, "fix_passages",
        lambda *a, **k: [{"id": note["id"], "fixed_text": "anh ta nói", "explanation": ""}],
    )
    client.post("/api/ebooks/t/notes/ai-fix", data={"note_ids": note["id"], "chapter_index": 7})

    res = client.post(f"/api/ebooks/t/notes/{note['id']}/apply")
    assert res.status_code == 200, res.text
    assert res.json()["note"]["status"] == "resolved"
    assert storage.read_translated(ch) == "Mở đầu.\n\nRồi anh ta nói một câu.\n\nKết thúc."
    # Snapshot MT không bị đụng tới
    assert storage.read_translated_mt(ch) == "Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc."

    # Apply lần 2 → 409 (đã resolved)
    assert client.post(f"/api/ebooks/t/notes/{note['id']}/apply").status_code == 409


def test_apply_writes_active_local_mt_branch(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, translated="AI giữ nguyên.")
    local_text = "Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc."
    storage.write_branch_text(ch, "local_mt", local_text)
    storage.mark_branch_complete(ch, "local_mt")
    storage.set_active_branch(ch, "local_mt")
    revision = storage.read_branch_revision(ch, "local_mt")
    client = _client(tmp_path, monkeypatch)
    note = _create_note(client)

    monkeypatch.setattr(
        glossary_ai, "fix_passages",
        lambda *a, **k: [{"id": note["id"], "fixed_text": "anh ta nói", "explanation": ""}],
    )
    client.post("/api/ebooks/t/notes/ai-fix", data={"note_ids": note["id"], "chapter_index": 7})
    res = client.post(f"/api/ebooks/t/notes/{note['id']}/apply")

    assert res.status_code == 200, res.text
    assert storage.read_branch_text(ch, "local_mt") == local_text.replace("hắn nói", "anh ta nói")
    assert storage.read_branch_revision(ch, "local_mt") == revision + 1
    assert storage.read_branch_text(ch, "ai") == "AI giữ nguyên."


def test_apply_stale_after_external_edit(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    note = _create_note(client)
    monkeypatch.setattr(
        glossary_ai, "fix_passages",
        lambda *a, **k: [{"id": note["id"], "fixed_text": "anh ta nói", "explanation": ""}],
    )
    client.post("/api/ebooks/t/notes/ai-fix", data={"note_ids": note["id"], "chapter_index": 7})

    # Bản dịch bị sửa ngoài luồng → đoạn được chọn biến mất
    storage.write_translated(ch, "Toàn bộ nội dung đã thay đổi.")
    res = client.post(f"/api/ebooks/t/notes/{note['id']}/apply")
    assert res.status_code == 409
    saved = storage.read_notes()[0]
    assert saved["status"] == "stale"


def test_apply_without_suggestion_conflicts(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)
    note = _create_note(client)
    assert client.post(f"/api/ebooks/t/notes/{note['id']}/apply").status_code == 409


def test_translated_mt_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path, mt="BẢN MÁY")
    client = _client(tmp_path, monkeypatch)
    res = client.get("/api/ebooks/t/chapters/7/translated-mt")
    assert res.status_code == 200
    assert res.json() == {"text": "BẢN MÁY", "has_mt_snapshot": True}


def test_translated_mt_endpoint_fallback(tmp_path, monkeypatch):
    _seed(tmp_path)  # không có snapshot MT
    client = _client(tmp_path, monkeypatch)
    data = client.get("/api/ebooks/t/chapters/7/translated-mt").json()
    assert data["has_mt_snapshot"] is False
    assert "Rồi hắn nói" in data["text"]
