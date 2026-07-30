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


# ----- route: phân trang + autosave từng mục (data table server-side) -----

def test_list_paginates_and_reports_total(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_entries(
        "names.txt", [(f"S{i:03d}", f"T{i}", "") for i in range(25)]
    )
    client = _client(cfg, monkeypatch)

    res = client.get("/api/ebooks/t/glossary/list", params={"page": 2, "per_page": 10})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 25
    assert data["pages"] == 3
    assert data["page"] == 2
    assert len(data["entries"]) == 10
    assert data["entries"][0]["source"] == "S010"


def test_list_search_and_consolidates_legacy(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n")
    storage.write_glossary_file("vietphrase.txt", "斗气 = Đấu khí\n")
    client = _client(cfg, monkeypatch)

    res = client.get("/api/ebooks/t/glossary/list", params={"q": "Đấu"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["entries"][0]["source"] == "斗气"
    # Legacy list được consolidate vào names.txt sau khi list.
    assert storage.read_glossary_entries("vietphrase.txt") == []


def test_upsert_entry_inserts_then_renames(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    client = _client(cfg, monkeypatch)

    # Insert mới (original_source rỗng).
    res = client.post(
        "/api/ebooks/t/glossary/entry",
        data={"source": "张三", "target": "Trương Tam", "note": "nv"},
    )
    assert res.status_code == 200
    assert storage.read_glossary_entries("names.txt") == [("张三", "Trương Tam", "nv")]

    # Đổi tên source: original_source cũ bị xoá, chỉ còn source mới.
    res = client.post(
        "/api/ebooks/t/glossary/entry",
        data={"source": "李四", "target": "Lý Tứ", "original_source": "张三"},
    )
    assert res.status_code == 200
    assert storage.read_glossary_entries("names.txt") == [("李四", "Lý Tứ", "")]


def test_upsert_entry_rejects_blank(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/glossary/entry", data={"source": "张三", "target": "   "})
    assert res.status_code == 400


def test_delete_entry_removes_from_db(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n斗气 = Đấu khí\n")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/glossary/entry/delete", data={"source": "萧炎"})
    assert res.status_code == 200
    assert storage.read_glossary_entries("names.txt") == [("斗气", "Đấu khí", "")]


def test_clean_reports_removed_count(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    # 1 mục hợp lệ trong names + 1 dòng thiếu Việt sẽ bị dọn + 1 legacy trùng.
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n斗气 = Đấu khí\n")
    storage.write_glossary_file("vietphrase.txt", "萧炎 = trùng\n")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/glossary/clean")
    assert res.status_code == 200
    data = res.json()
    assert data["before"] == 3
    assert data["after"] == 2
    assert data["removed"] == 1
    assert storage.read_glossary_entries("vietphrase.txt") == []


# ----- route: xóa hàng loạt -----

def test_bulk_delete_removes_selected_sources(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n斗气 = Đấu khí\n林动 = Lâm Động\n")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/entries/delete",
        json={"sources": ["萧炎", "林动", "不存在"]},
    )
    assert res.status_code == 200
    assert res.json()["deleted"] == 2  # "不存在" không có → không tính
    assert storage.read_glossary_entries("names.txt") == [("斗气", "Đấu khí", "")]


def test_bulk_delete_rejects_empty_list(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/glossary/entries/delete", json={"sources": ["  "]})
    assert res.status_code == 400


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


# ----- route: hàng chờ duyệt đề xuất auto-glossary (tab Đề xuất AI) -----

def test_pending_lists_normalized_entries(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_extra_json(
        "glossary_pending",
        [
            {"source": "叶凡", "target": "Diệp Phàm", "chapter_index": 3},
            {"source": "  ", "target": "rác"},  # row hỏng → bỏ
            "not-a-dict",
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.get("/api/ebooks/t/glossary/pending")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["entries"] == [
        {"source": "叶凡", "target": "Diệp Phàm", "chapter_index": 3}
    ]


def test_pending_approve_upserts_and_removes_from_queue(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "斗气 = Đấu khí\n")
    storage.write_extra_json(
        "glossary_pending",
        [
            {"source": "叶凡", "target": "Diệp Phàm", "chapter_index": 3},
            {"source": "林动", "target": "Lâm Động", "chapter_index": 4},
        ],
    )
    client = _client(cfg, monkeypatch)

    # Duyệt 1 mục, target đã sửa tay trên UI trước khi duyệt.
    res = client.post(
        "/api/ebooks/t/glossary/pending/approve",
        json={"entries": [{"source": "叶凡", "target": "Diệp Phàm Sửa", "note": "nv chính", "original_source": "叶凡"}]},
    )
    assert res.status_code == 200
    assert res.json() == {"approved": 1, "remaining": 1}
    names = storage.read_glossary_entries("names.txt")
    assert ("叶凡", "Diệp Phàm Sửa", "nv chính") in names
    remaining = storage.read_extra_json("glossary_pending")
    assert [p["source"] for p in remaining] == ["林动"]


def test_pending_approve_rejects_empty(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/glossary/pending/approve", json={"entries": []})
    assert res.status_code == 400


def test_pending_clear_selected_and_all(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_extra_json(
        "glossary_pending",
        [
            {"source": "叶凡", "target": "Diệp Phàm", "chapter_index": 1},
            {"source": "林动", "target": "Lâm Động", "chapter_index": 2},
            {"source": "萧炎", "target": "Tiêu Viêm", "chapter_index": 3},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/glossary/pending/clear", json={"sources": ["叶凡"]})
    assert res.status_code == 200
    assert res.json()["cleared"] == 1
    assert [p["source"] for p in storage.read_extra_json("glossary_pending")] == ["林动", "萧炎"]
    # Bỏ qua KHÔNG đưa gì vào glossary.
    assert storage.read_glossary_entries("names.txt") == []

    res = client.post("/api/ebooks/t/glossary/pending/clear", json={"all": True})
    assert res.status_code == 200
    assert res.json()["cleared"] == 2
    assert storage.read_extra_json("glossary_pending") == []


def test_bulk_conflicts_take_upserts_edited_values_and_keeps_unselected(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "叶凡 = Diệp Phàm cũ\n")
    storage.write_extra_json(
        "glossary_conflicts",
        [
            {"source": "叶凡", "existing": "Diệp Phàm cũ", "new": "Diệp Phàm"},
            {"source": "林动", "existing": "Lâm Động", "new": "Lâm Động mới"},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={
            "action": "take",
            "entries": [
                {
                    "source": "叶凡",
                    "original_new": "Diệp Phàm",
                    "target": "Diệp Phàm hiệu chỉnh",
                    "note": "nhân vật chính",
                }
            ],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"resolved": 1, "remaining": 1}
    assert ("叶凡", "Diệp Phàm hiệu chỉnh", "nhân vật chính") in storage.read_glossary_entries("names.txt")
    assert storage.read_extra_json("glossary_conflicts") == [
        {"source": "林动", "existing": "Lâm Động", "new": "Lâm Động mới"}
    ]


def test_bulk_conflicts_take_ignores_stale_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "叶凡 = Giá trị hiện tại\n")
    storage.write_extra_json(
        "glossary_conflicts",
        [{"source": "叶凡", "existing": "Giá trị hiện tại", "new": "Đề xuất mới hơn"}],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={
            "action": "take",
            "entries": [
                {
                    "source": "叶凡",
                    "original_new": "Đề xuất cũ đã biến mất",
                    "target": "Không được ghi",
                    "note": "",
                }
            ],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"resolved": 0, "remaining": 1}
    assert storage.read_glossary_file("names.txt") == {"叶凡": "Giá trị hiện tại"}


def test_bulk_conflicts_keep_resolves_without_changing_glossary(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file("names.txt", "叶凡 = Giữ nguyên\n")
    storage.write_extra_json(
        "glossary_conflicts",
        [{"source": "叶凡", "existing": "Giữ nguyên", "new": "Không lấy"}],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={
            "action": "keep",
            "entries": [{"source": "叶凡", "original_new": "Không lấy"}],
        },
    )

    assert res.status_code == 200
    assert res.json() == {"resolved": 1, "remaining": 0}
    assert storage.read_glossary_file("names.txt") == {"叶凡": "Giữ nguyên"}


def test_bulk_conflicts_rejects_invalid_action_and_empty_entries(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)

    bad_action = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={"action": "delete", "entries": [{"source": "叶凡", "original_new": "x"}]},
    )
    empty = client.post(
        "/api/ebooks/t/glossary/conflicts/bulk-resolve",
        json={"action": "take", "entries": []},
    )

    assert bad_action.status_code == 400
    assert empty.status_code == 400


def test_pending_approve_preserves_suggestions_outside_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_extra_json(
        "glossary_pending",
        [
            {"source": "叶凡", "target": "Diệp Phàm", "chapter_index": 1},
            {"source": "Mới", "target": "Được thêm đồng thời", "chapter_index": 2},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/pending/approve",
        json={
            "entries": [
                {
                    "source": "叶凡",
                    "target": "Diệp Phàm sửa",
                    "note": "",
                    "original_source": "叶凡",
                }
            ]
        },
    )

    assert res.status_code == 200
    assert [row["source"] for row in storage.read_extra_json("glossary_pending")] == ["Mới"]


# ----- route: nghi vấn (suspects) + resolve conflicts -----

def test_suspects_returns_groups_and_count(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_file(
        "names.txt", "张三 = Trương Tam\n张叁 = Trương Tam\n张三爷 = Trương Tam gia\n"
    )
    storage.write_extra_json(
        "glossary_conflicts",
        [{"source": "斗气", "existing": "Đấu khí", "new": "Đẩu khí"}],
    )
    client = _client(cfg, monkeypatch)

    res = client.get("/api/ebooks/t/glossary/suspects")
    assert res.status_code == 200
    data = res.json()
    assert len(data["same_target"]) == 1          # 张三 + 张叁 → cùng "Trương Tam"
    assert len(data["nested_source"]) == 1        # chỉ 张三 ⊂ 张三爷 (张叁 là chữ khác)
    assert data["conflicts"] == [
        {"source": "斗气", "kept": "Đấu khí", "new": "Đẩu khí"}
    ]
    assert data["count"] == (
        len(data["same_target"]) + len(data["nested_source"]) + len(data["conflicts"])
    )


def test_conflict_resolve_removes_matching_entry(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_extra_json(
        "glossary_conflicts",
        [
            {"source": "斗气", "existing": "Đấu khí", "new": "Đẩu khí"},
            {"source": "张三", "existing": "Trương Tam", "new": "Trương Tân"},
        ],
    )
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/conflicts/resolve",
        data={"source": "斗气", "new": "Đẩu khí"},
    )
    assert res.status_code == 200
    assert res.json()["removed"] == 1
    remaining = storage.read_extra_json("glossary_conflicts")
    assert len(remaining) == 1
    assert remaining[0]["source"] == "张三"


# ----- route: match-count + propagate (pattern "sửa → lan truyền") -----

def test_match_count_counts_all_and_chapter(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ. Trương Tam về nhà.")
    storage.write_translated(chapters[1], "Trương Tam ngủ.")
    client = _client(cfg, monkeypatch)

    res = client.get(
        "/api/ebooks/t/glossary/match-count",
        params={"find": "Trương Tam", "chapter_index": 1},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["chapter_count"] == 2      # trong chương 1
    assert data["total_count"] == 3        # toàn bộ đã dịch
    assert data["chapter_total"] == 2      # số chương chứa chuỗi


def test_match_count_rejects_blank_find(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1")]))
    client = _client(cfg, monkeypatch)
    res = client.get("/api/ebooks/t/glossary/match-count", params={"find": "  "})
    assert res.status_code == 400


def test_propagate_chapter_writes_and_backs_up(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ.")
    storage.write_translated(chapters[1], "Trương Tam ngủ.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "Trương Tam", "replace": "Trần Tam", "scope": "chapter", "chapter_index": 1},
    )
    assert res.status_code == 200
    assert res.json()["replaced"] == 1
    # Chỉ chương 1 bị thay; backup đúng format before_find_replace.
    assert storage.read_translated(chapters[0]) == "Trần Tam đi chợ."
    assert storage.read_meta(chapters[0])["before_find_replace"] == "Trương Tam đi chợ."
    assert storage.read_translated(chapters[1]) == "Trương Tam ngủ."


def test_propagate_all_runs_find_replace_job(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "Trương Tam", "replace": "Trần Tam", "scope": "all"},
    )
    assert res.status_code == 200
    # _FakeJob chạy target sync → file đã đổi ngay trong test.
    assert storage.read_translated(chapters[0]) == "Trần Tam đi chợ."


def test_match_count_regex_counts_pattern(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Chương 1 và Chương 12.")
    storage.write_translated(chapters[1], "Không số.")
    client = _client(cfg, monkeypatch)

    res = client.get(
        "/api/ebooks/t/glossary/match-count",
        params={"find": r"Chương \d+", "regex": 1, "chapter_index": 1},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["chapter_count"] == 2
    assert data["total_count"] == 2
    assert data["chapter_total"] == 1


def test_match_count_regex_invalid_pattern_returns_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1")]))
    client = _client(cfg, monkeypatch)
    res = client.get(
        "/api/ebooks/t/glossary/match-count", params={"find": "[unclosed", "regex": 1}
    )
    assert res.status_code == 400


def test_propagate_chapter_regex_uses_backreference(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Chương 1 rồi Chương 2.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={
            "find": r"Chương (\d+)",
            "replace": r"Hồi \1",
            "scope": "chapter",
            "chapter_index": 1,
            "regex": 1,
        },
    )
    assert res.status_code == 200
    assert res.json()["replaced"] == 2
    assert storage.read_translated(chapters[0]) == "Hồi 1 rồi Hồi 2."
    assert storage.read_meta(chapters[0])["before_find_replace"] == "Chương 1 rồi Chương 2."


def test_propagate_all_regex_runs_job(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Chương 1 xong.")
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": r"Chương (\d+)", "replace": r"Hồi \1", "scope": "all", "regex": 1},
    )
    assert res.status_code == 200
    assert storage.read_translated(chapters[0]) == "Hồi 1 xong."


def test_propagate_rejects_bad_scope_and_missing_chapter(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1")]))
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "a", "replace": "b", "scope": "everything"},
    )
    assert res.status_code == 400
    # scope=chapter nhưng chương chưa dịch → 404.
    res = client.post(
        "/api/ebooks/t/glossary/propagate",
        data={"find": "a", "replace": "b", "scope": "chapter", "chapter_index": 1},
    )
    assert res.status_code == 404


def test_old_reapply_routes_removed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    client = _client(cfg, monkeypatch)
    assert client.post(
        "/api/ebooks/t/glossary/reapply-preview", data={"find": "x"}
    ).status_code == 404
    assert client.post(
        "/ebooks/t/glossary/reapply", data={"find": "x", "replace": "y"}
    ).status_code == 404
