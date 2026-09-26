"""Sync preset hai chiều giữa DB và file `sources.yaml`.

Trọng tâm: không mất dữ liệu. Mọi preset chỉ tồn tại ở một bên đều phải được gom
về, và preset người dùng chọn `skip` phải được giữ nguyên trong file.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from novel2epub import sources_sync
from novel2epub.sources import load_presets, preset_from_mapping

from tests.conftest import write_db_config


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _db(tmp_path, sources, ebooks=None) -> Path:
    return write_db_config(tmp_path / "novel2epub.db", sources=sources, ebooks=ebooks)


def _apply(db: Path, file_path: Path, choices: dict[str, str]):
    """Đọc file rồi apply — mirror đúng thứ tự route làm."""
    layout, file_presets, warnings = sources_sync.read_sources_file(file_path)
    return sources_sync.apply_sync(
        db, file_path, file_presets, choices=choices, layout=layout, warnings=warnings
    )


def _statuses(plan) -> dict[str, str]:
    return {d.name: d.status for d in plan.diffs}


def _actions(plan) -> dict[str, str]:
    return {d.name: d.action for d in plan.diffs}


class TestReadSourcesFile:
    def test_flat(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "biquge:\n  url: https://bqg.test/\n  domains: bqg.test\n")
        layout, presets, warnings = sources_sync.read_sources_file(f)
        assert layout == sources_sync.FLAT
        assert list(presets) == ["biquge"]
        assert presets["biquge"].domains == "bqg.test"
        assert warnings == []

    def test_wrapped(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "sources:\n  biquge:\n    domains: bqg.test\n")
        layout, presets, _ = sources_sync.read_sources_file(f)
        assert layout == sources_sync.WRAPPED
        assert list(presets) == ["biquge"]

    def test_thieu_file_thi_bao_va_khong_loi(self, tmp_path):
        layout, presets, warnings = sources_sync.read_sources_file(tmp_path / "khong-co.yaml")
        assert (layout, presets) == (sources_sync.FLAT, {})
        assert warnings and "tạo mới" in warnings[0]

    def test_file_rong(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "")
        _, presets, warnings = sources_sync.read_sources_file(f)
        assert presets == {} and warnings

    def test_yaml_hong(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "a: [1,\n")
        with pytest.raises(sources_sync.SyncError, match="Không đọc được"):
            sources_sync.read_sources_file(f)

    def test_khong_phai_mapping(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "- a\n- b\n")
        with pytest.raises(sources_sync.SyncError, match="mapping"):
            sources_sync.read_sources_file(f)

    def test_khoa_lan_khong_phai_preset_thi_chan(self, tmp_path):
        """`sources.yaml` lẫn cấu hình khác thì phải báo chứ không ghi đè mất."""
        f = _write(tmp_path / "sources.yaml", "defaults:\n  translate:\n    type: openai\n")
        with pytest.raises(sources_sync.SyncError, match="không phải file nguồn"):
            sources_sync.read_sources_file(f)

    def test_khoa_scalar_lan_khong_phai_preset_thi_chan(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "version: 2\nbiquge:\n  domains: a.test\n")
        with pytest.raises(sources_sync.SyncError, match="không phải file nguồn"):
            sources_sync.read_sources_file(f)

    def test_preset_khong_phai_mapping(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "biquge: 123\n")
        with pytest.raises(sources_sync.SyncError, match="phải là mapping"):
            sources_sync.read_sources_file(f)

    def test_field_la_bi_bo_nhung_co_warning(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "biquge:\n  domains: a.test\n  field_bo_quen: 1\n")
        _, presets, warnings = sources_sync.read_sources_file(f)
        assert presets["biquge"].domains == "a.test"
        assert warnings and "field_bo_quen" in warnings[0]

    def test_strip_patterns_string_nhieu_dong(self, tmp_path):
        f = _write(tmp_path / "sources.yaml", "biquge:\n  strip_patterns: |\n    a.*\n    b.*\n")
        _, presets, _ = sources_sync.read_sources_file(f)
        assert presets["biquge"].strip_patterns == ["a.*", "b.*"]


class TestResolvePath:
    def test_mac_dinh_la_sources_yaml_canh_db(self, tmp_path):
        db = _db(tmp_path, {})
        assert sources_sync.resolve_path(db) == tmp_path / "sources.yaml"

    def test_duong_dan_tuong_doi_theo_db(self, tmp_path):
        db = _db(tmp_path, {})
        assert sources_sync.resolve_path(db, "sub/other.yaml") == tmp_path / "sub" / "other.yaml"

    def test_duong_dan_tuyet_doi(self, tmp_path):
        db = _db(tmp_path, {})
        target = tmp_path / "x.yaml"
        assert sources_sync.resolve_path(db, str(target)) == target.resolve()

    def test_duoi_sai_thi_chan(self, tmp_path):
        db = _db(tmp_path, {})
        with pytest.raises(sources_sync.SyncError, match="đuồi"):
            sources_sync.resolve_path(db, "sources.txt")


class TestPlanSync:
    def _plan(self, tmp_path, db_sources, yaml_text, name="sources.yaml"):
        db = _db(tmp_path, db_sources)
        f = _write(tmp_path / name, yaml_text) if yaml_text is not None else tmp_path / name
        layout, file_presets, warnings = sources_sync.read_sources_file(f)
        return sources_sync.plan_sync(
            db, f, file_presets, layout=layout, file_order=list(file_presets), warnings=warnings
        )

    def test_phan_loai_4_trang_thai(self, tmp_path):
        plan = self._plan(
            tmp_path,
            {"same": {"domains": "a.test"}, "changed": {"domains": "db.test"}, "dbonly": {"domains": "c.test"}},
            "same:\n  domains: a.test\nchanged:\n  domains: file.test\nfileonly:\n  domains: f.test\n",
        )
        assert _statuses(plan) == {
            "same": "same", "changed": "changed",
            "dbonly": "db_only", "fileonly": "added",
        }

    def test_chi_liet_ke_field_khac(self, tmp_path):
        plan = self._plan(
            tmp_path,
            {"a": {"domains": "db.test", "delay_seconds": 1.0}},
            "a:\n  domains: file.test\n  delay_seconds: 1.0\n",
        )
        (diff,) = plan.diffs
        assert [f.key for f in diff.fields] == ["domains"]
        assert diff.fields[0].file_value == "file.test"
        assert diff.fields[0].db_value == "db.test"

    def test_action_mac_dinh(self, tmp_path):
        plan = self._plan(
            tmp_path,
            {"same": {"domains": "a.test"}, "changed": {"domains": "db.test"}, "dbonly": {"domains": "c.test"}},
            "same:\n  domains: a.test\nchanged:\n  domains: file.test\nfileonly:\n  domains: f.test\n",
        )
        assert _actions(plan) == {
            "same": "skip", "changed": "import",
            "dbonly": "export", "fileonly": "import",
        }

    def test_action_hop_le(self, tmp_path):
        plan = self._plan(
            tmp_path,
            {"changed": {"domains": "db.test"}, "dbonly": {"domains": "c.test"}},
            "changed:\n  domains: file.test\nfileonly:\n  domains: f.test\n",
        )
        actions = {d.name: d.actions for d in plan.diffs}
        assert actions["changed"] == ["import", "export", "skip"]
        # Chỉ có trong file thì không thể "lấy từ DB" (DB không có nó).
        assert actions["fileonly"] == ["import", "skip"]
        # Chỉ có trong DB thì không thể "lấy từ file".
        assert actions["dbonly"] == ["export", "skip"]


class TestApplySync:
    def test_import_vao_db(self, tmp_path):
        db = _db(tmp_path, {})
        f = _write(tmp_path / "sources.yaml", "biquge:\n  domains: bqg.test\n  content_selector: '#content'\n")
        report = _apply(db, f, {"biquge": "import"})
        assert report.imported == ["biquge"]
        assert load_presets(db)["biquge"].content_selector == "#content"

    def test_import_ghi_de_preset_da_co(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "db.test", "delay_seconds": 9.0}})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: file.test\n")
        report = _apply(db, f, {"a": "import"})
        assert report.imported == ["a"]
        got = load_presets(db)["a"]
        assert got.domains == "file.test"
        # Field không có trong file về MẶC ĐỊNH của preset, không phải giữ giá
        # trị DB — file là bản đầy đủ của preset đó.
        assert got.delay_seconds == 1.0

    def test_export_ra_file_khong_doi_db(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "db.test"}})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: file.test\n")
        report = _apply(db, f, {"a": "export"})
        assert report.exported == ["a"]
        assert load_presets(db)["a"].domains == "db.test"
        assert yaml.safe_load(f.read_text(encoding="utf-8"))["a"]["domains"] == "db.test"

    def test_preset_chi_co_trong_db_thi_vao_file(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "a.test"}, "b": {"domains": "b.test"}})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: a.test\n")
        report = _apply(db, f, {"a": "skip", "b": "export"})
        assert report.exported == ["b"]
        assert set(yaml.safe_load(f.read_text(encoding="utf-8"))) == {"a", "b"}

    def test_skip_gi_nguyen_ca_hai_ben(self, tmp_path):
        original = "a:\n  domains: file.test\n  content_selector: '#keep'\n"
        db = _db(tmp_path, {"a": {"domains": "db.test"}})
        f = _write(tmp_path / "sources.yaml", original)
        report = _apply(db, f, {"a": "skip"})
        assert report.skipped == ["a"]
        assert not report.imported and not report.exported
        # File KHÔNG bị ghi lại -> giữ nguyên từng ký tự.
        assert f.read_text(encoding="utf-8") == original
        assert load_presets(db)["a"].domains == "db.test"

    def test_preset_khong_co_trong_choices_thi_khong_dong_gi(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "db.test"}})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: file.test\nb:\n  domains: b.test\n")
        report = _apply(db, f, {})
        assert sorted(report.skipped) == ["a", "b"]
        assert not report.file_written
        assert set(load_presets(db)) == {"a"}

    def test_tao_file_moi_khi_chua_co(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "a.test"}})
        f = tmp_path / "sources.yaml"
        assert not f.exists()
        report = sources_sync.apply_sync(db, f, {}, choices={"a": "export"})
        assert report.file_written and report.backup == ""
        assert list(yaml.safe_load(f.read_text(encoding="utf-8"))) == ["a"]

    def test_giu_dinh_dang_wrapped(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "a.test"}})
        f = _write(tmp_path / "sources.yaml", "sources:\n  b:\n    domains: b.test\n")
        _apply(db, f, {"a": "export", "b": "import"})
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert set(data) == {"sources"}
        assert set(data["sources"]) == {"a", "b"}

    def test_giu_thu_tu_preset_cu(self, tmp_path):
        db = _db(tmp_path, {"zzz": {"domains": "z.test"}, "aaa": {"domains": "a.test"}})
        f = _write(tmp_path / "sources.yaml", "zzz:\n  domains: z.test\nmmm:\n  domains: m.test\n")
        _apply(db, f, {"mmm": "import", "aaa": "export"})
        assert list(yaml.safe_load(f.read_text(encoding="utf-8"))) == ["zzz", "mmm", "aaa"]

    def test_backup_ban_cu(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "a.test"}})
        f = _write(tmp_path / "sources.yaml", "b:\n  domains: b.test\n")
        report = _apply(db, f, {"b": "import"})
        assert report.backup
        backup = Path(report.backup)
        assert backup.exists() and backup.name.startswith("sources.bak-")
        assert yaml.safe_load(backup.read_text(encoding="utf-8")) == {"b": {"domains": "b.test"}}

    def test_file_va_gi_nguyen_gia_tri_bo_sau(self, tmp_path):
        """Round-trip: export xong đọc lại phải cho diff = same (không mất field)."""
        db = _db(tmp_path, {"a": {"domains": "a.test", "strip_patterns": ["x.*"], "proxy": "socks5://h:1"}})
        f = tmp_path / "sources.yaml"
        sources_sync.apply_sync(db, f, {}, choices={"a": "export"})
        layout, file_presets, _ = sources_sync.read_sources_file(f)
        plan = sources_sync.plan_sync(db, f, file_presets, layout=layout)
        assert _statuses(plan) == {"a": "same"}
        assert file_presets["a"].strip_patterns == ["x.*"]
        assert file_presets["a"].proxy == "socks5://h:1"

    def test_action_khong_hop_le_thi_chan(self, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "db.test"}})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: file.test\n")
        with pytest.raises(sources_sync.SyncError, match="không hợp lệ"):
            _apply(db, f, {"a": "import-hack"})

    def test_preset_khong_co_trong_file_thi_khong_hop_le_export(self, tmp_path):
        db = _db(tmp_path, {})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: a.test\n")
        with pytest.raises(sources_sync.SyncError, match="không hợp lệ"):
            _apply(db, f, {"a": "export"})

    def test_ten_preset_gho_thi_bi_ban(self, tmp_path):
        """Gõ nhầm tên phải báo lỗi chứ không bỏ qua âm thầm."""
        db = _db(tmp_path, {"a": {"domains": "a.test"}})
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: a.test\n")
        with pytest.raises(sources_sync.SyncError, match="kiểm tra lại tên"):
            _apply(db, f, {"aa": "export"})

    def test_sync_khong_lam_rung_ebook_dung_nguon(self, tmp_path):
        db = _db(
            tmp_path,
            {"a": {"domains": "a.test"}},
            ebooks={"novel-1": {"source": "a", "novel": {"title": "A"}}},
        )
        f = _write(tmp_path / "sources.yaml", "a:\n  domains: a.test\n  content_selector: '#c'\n")
        _apply(db, f, {"a": "import"})
        from novel2epub.db import get_connection

        conn = get_connection(str(db))
        assert conn.execute("SELECT source_preset FROM ebooks").fetchone()["source_preset"] == "a"
        conn.close()


class TestRoutes:
    @pytest.fixture()
    def client(self, monkeypatch, tmp_path):
        db = _db(tmp_path, {"a": {"domains": "db.test"}})
        _write(tmp_path / "sources.yaml", "a:\n  domains: file.test\nb:\n  domains: b.test\n")
        from app import deps

        monkeypatch.setattr(deps, "DB_PATH", db)
        monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
        monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
        from app.main import app

        return TestClient(app, follow_redirects=False), db, tmp_path

    def test_preview_khong_ghi_gi(self, client):
        tc, db, _ = client
        before = (db.parent / "sources.yaml").read_text(encoding="utf-8")
        res = tc.post("/api/ui/sources/sync/preview", json={})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["counts"] == {"added": 1, "changed": 1, "db_only": 0, "same": 0}
        assert (db.parent / "sources.yaml").read_text(encoding="utf-8") == before
        assert set(load_presets(db)) == {"a"}

    def test_apply_import(self, client):
        tc, db, _ = client
        res = tc.post("/api/ui/sources/sync/apply", json={"choices": {"a": "import", "b": "import"}})
        assert res.status_code == 200, res.text
        data = res.json()
        assert sorted(data["imported"]) == ["a", "b"]
        assert data["file_written"] and data["backup"]
        assert set(load_presets(db)) == {"a", "b"}
        assert load_presets(db)["a"].domains == "file.test"

    def test_apply_ten_path_tuong_doi(self, client):
        tc, db, _ = client
        res = tc.post("/api/ui/sources/sync/apply", json={"path": "khong-co.yaml", "choices": {"a": "export"}})
        assert res.status_code == 200, res.text
        assert (db.parent / "khong-co.yaml").exists()

    def test_file_sai_dinh_dang_thi_400(self, client):
        tc, _, tmp = client
        (tmp / "bad.yaml").write_text("- a\n", encoding="utf-8")
        res = tc.post("/api/ui/sources/sync/preview", json={"path": "bad.yaml"})
        assert res.status_code == 400
        assert "mapping" in res.json()["detail"]

    def test_choices_sai_kieu_thi_400(self, client):
        tc, _, _ = client
        res = tc.post("/api/ui/sources/sync/apply", json={"choices": ["a"]})
        assert res.status_code == 400

    def test_choices_sai_ten_preset_thi_400(self, client):
        tc, _, _ = client
        res = tc.post("/api/ui/sources/sync/apply", json={"choices": {"khong-co": "import"}})
        assert res.status_code == 400
        assert "kiểm tra lại tên" in res.json()["detail"]


class TestPresetFromMapping:
    def test_ten_trong_mapping_bi_ten_thuong_thay_the(self):
        p = preset_from_mapping("ten-that", {"name": "khac", "domains": "a.test"})
        assert p.name == "ten-that"
