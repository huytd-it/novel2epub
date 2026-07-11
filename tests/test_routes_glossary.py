from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage
from app.routes.glossary import _append_glossary_entry


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeJob:
    """start_custom chạy target NGAY (sync) để test assert kết quả ghi file."""

    def __init__(self):
        self.started: list[dict] = []
        self.logs: list[str] = []

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": [], "running_ebooks": []},
        }

    def start_custom(self, name, target, *, category, ebook="", spec=None):
        self.started.append({"name": name, "category": category, "ebook": ebook})
        self.logs = []
        target(self.logs.append)
        return True


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob()
    return TestClient(app)


def test_append_new_entry_writes_line(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()

    changed = _append_glossary_entry(storage, "庄国", "Trang Quốc")

    assert changed is True
    assert storage.read_glossary_file("names.txt") == {"庄国": "Trang Quốc"}


def test_append_skips_when_already_present_with_same_value(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    # Entry cũ nằm ở vietphrase.txt (DB chưa consolidate) → dup-check trên
    # merged vẫn phải nhận ra và skip.
    storage.write_glossary_file("vietphrase.txt", "庄国 = Trang Quốc\n")

    changed = _append_glossary_entry(storage, "庄国", "Trang Quốc")

    assert changed is False
    merged = storage.read_glossary_entries_merged()
    assert [s for s, _t, _n in merged].count("庄国") == 1


def test_append_updates_when_value_differs(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "庄国 = Trang Quốc cũ\n")

    changed = _append_glossary_entry(storage, "庄国", "Trang Quốc mới")

    assert changed is True
    # UPSERT theo source: giá trị mới thắng, không giữ dòng cũ trùng source.
    assert storage.read_glossary_file("names.txt") == {"庄国": "Trang Quốc mới"}


def test_append_rejects_blank_fields(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()

    assert _append_glossary_entry(storage, "", "Trang Quốc") is False
    assert _append_glossary_entry(storage, "庄国", "") is False


# ----- storage entry helpers (data table cần giữ ghi chú + trim/dedup) -----

def test_read_glossary_entries_keeps_note(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm | nhân vật chính\n斗气 = Đấu khí\n")

    entries = storage.read_glossary_entries("names.txt")

    assert entries == [("萧炎", "Tiêu Viêm", "nhân vật chính"), ("斗气", "Đấu khí", "")]


def test_write_glossary_entries_trims_and_dedups(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    storage.write_glossary_entries(
        "names.txt",
        [("  A ", " Aa ", " ghi chú "), ("B", "Bb", ""), ("", "x", ""), ("A", "Zz", "")],
    )

    entries = storage.read_glossary_entries("names.txt")
    # A dedup (mục sau thắng, mất note); dòng thiếu source bị bỏ.
    assert entries == [("A", "Zz", ""), ("B", "Bb", "")]


# ----- route: lưu toàn bộ glossary từ data table (JSON) -----

def test_save_glossary_json_writes_single_list_and_consolidates(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    # Dữ liệu cũ còn trong vietphrase.txt — lưu xong phải được consolidate.
    storage.write_glossary_file("vietphrase.txt", "旧词 = từ cũ\n")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/ebooks/t/glossary",
        json={
            "entries": [
                {"source": "萧炎", "target": "Tiêu Viêm", "note": "chính"},
                {"source": "斗气", "target": "Đấu khí", "note": ""},
            ],
        },
    )
    assert res.status_code == 200

    assert storage.read_glossary_entries("names.txt") == [
        ("萧炎", "Tiêu Viêm", "chính"), ("斗气", "Đấu khí", ""),
    ]
    # vietphrase.txt được dọn sạch sau khi lưu (lazy consolidation).
    assert storage.read_glossary_entries("vietphrase.txt") == []


# ----- route: nhập glossary từ AI (merge) -----

def test_import_glossary_merges(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "萧炎 = Tên cũ | giữ note\n")
    client = _client(cfg, monkeypatch)

    text = "## GLOSSARY\n- 萧炎 = Tiêu Viêm\n- 林动 = Lâm Động\n- 斗气 = Đấu khí\n"
    res = client.post("/api/ebooks/t/glossary/import", data={"text": text})
    assert res.status_code == 200
    data = res.json()
    assert data["added"] == 2  # 林动 + 斗气
    assert data["updated"] == 1  # 萧炎 đổi giá trị

    names = storage.read_glossary_entries("names.txt")
    # 萧炎 cập nhật target nhưng GIỮ ghi chú cũ; mọi mục đều vào names.txt.
    assert ("萧炎", "Tiêu Viêm", "giữ note") in names
    assert ("斗气", "Đấu khí", "") in names
    assert storage.read_glossary_entries("vietphrase.txt") == []


def test_import_glossary_rejects_empty(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/glossary/import", data={"text": "không có gì cả"})
    assert res.status_code == 400


# ----- route: xem trước áp dụng lại (read-only) -----

def test_reapply_preview_lists_affected_chapters(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ. Trương Tam về nhà.")
    storage.write_translated(chapters[1], "Không có tên ở đây.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/reapply-preview",
        data={"find": "Trương Tam", "replace": "Trần Tam"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["chapters"]) == 1
    assert data["chapters"][0]["index"] == 1
    assert data["chapters"][0]["count"] == 2
    # Không ghi gì (read-only).
    assert storage.read_translated(chapters[0]).count("Trương Tam") == 2


def test_reapply_applies_and_updates_glossary(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ.")
    storage.write_glossary_file("names.txt", "张三 = Trương Tam\n")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/ebooks/t/glossary/reapply",
        data={
            "find": "Trương Tam",
            "replace": "Trần Tam",
            "source": "张三",
        },
    )
    assert res.status_code == 200
    # Bản dịch đã thay + backup vào meta.
    assert storage.read_translated(chapters[0]) == "Trần Tam đi chợ."
    assert storage.read_meta(chapters[0])["before_find_replace"] == "Trương Tam đi chợ."
    # Mục glossary được cập nhật target.
    assert storage.read_glossary_file("names.txt") == {"张三": "Trần Tam"}
