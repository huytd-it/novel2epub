"""Tests route /wireguard: render sanitized, settings persistence, import
(valid/invalid/oversize + dọn tạm), discover/provision mock, enable/disable/
order, unknown profile 404, active-delete conflict 409, activate/rotate domain
calls. Không endpoint nào lộ nội dung cấu hình/private key."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from novel2epub.config import load_config
from novel2epub import wireguard as wg
from novel2epub.wireguard import build_config, import_profile
from tests.conftest import write_db_config

FAKE_PRIVATE_KEY = "QJhLxVIfJvM3sXmNjcKkDq9tZrYiYpFwQNTTRUNGTLONGKEYHERE"


def fake_config_text() -> str:
    return build_config(
        {"PrivateKey": FAKE_PRIVATE_KEY, "Address": "172.16.0.2/32"},
        [{
            "PublicKey": "Pp1Kj8LmNpQrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWxYz0",
            "AllowedIPs": "0.0.0.0/0",
            "Endpoint": "engage.cloudflareclient.com:2408",
        }],
    )


def _db(tmp_path: Path, **defaults) -> Path:
    defaults.setdefault("wireguard", {})
    return write_db_config(
        tmp_path / "novel2epub.db",
        defaults=defaults,
        ebooks={"demo": {"novel": {"slug": "demo"}}},
    )


def _profiles_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wireguard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _client(monkeypatch, tmp_path):
    db = _db(tmp_path)
    from app import deps

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))

    from app.main import app

    return db, TestClient(app, follow_redirects=False)


def _attach_profile(db, profiles: Path, stem: str = "v1"):
    src = profiles / f"{stem}-src.conf"
    src.write_text(fake_config_text(), encoding="utf-8")
    return import_profile(str(db), profiles, src, name=stem)


# ── GET render: sanitized config + metadata only ───────────────────────────


def test_page_renders_sanitized_config_and_profiles(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    p = _attach_profile(db, profiles)
    wg.set_enabled(str(db), p["id"], True)

    res = client.get("/api/ui/wireguard")
    assert res.status_code == 200
    data = res.json()
    config = data["config"]
    # Cấu hình toàn cục đã sanitized (không chứa secret/argv value).
    assert config["profiles_dir"] == str(profiles)
    assert "manage_service" in config
    # Metadata profile: filename + opaque id xuất hiện (không phải nội dung).
    rows = data["profiles"]
    assert [r["filename"] for r in rows] == [p["filename"]]
    assert [r["id"] for r in rows] == [p["id"]]
    # Profile mới chưa active → trạng thái mặc định hiện rõ trong metadata.
    assert rows[0]["status"] == "inactive"
    assert rows[0]["enabled"] == 1


def test_page_never_exposes_config_text_or_private_key(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    _attach_profile(db, profiles)

    text = client.get("/api/ui/wireguard").text
    assert FAKE_PRIVATE_KEY not in text
    assert "172.16.0.2" not in text
    assert "[Interface]" not in text
    assert "[Peer]" not in text


def test_import_route_does_not_echo_upload_content(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/wireguard/import",
        files={"file": ("x.conf", fake_config_text().encode(), "text/plain")},
        data={"name": "noi-dung-rieng"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    text = client.get("/api/ui/wireguard").text
    assert FAKE_PRIVATE_KEY not in text


# ── Settings persistence (bao gồm argv 1 arg/dòng) ────────────────────────


def test_settings_persist_globally_with_argv_per_line(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    res = client.post("/api/ui/wireguard/settings", json={
        "enabled": True,
        "profiles_dir": str(_profiles_dir(tmp_path)),
        "wg_exe": "C:\\tools\\wg.exe",
        "manage_service": True,
        "service_timeout_seconds": 45,
        "lock_timeout_seconds": 9,
        "wgcf_enabled": True,
        "wgcf_executable": "C:\\tools\\wgcf.exe",
        "replace_wgcf_argv": True,
        "wgcf_argv": "register\n--token\nABC 123\n--name \"x y\"",
        "wgcf_output": "gen.conf",
        "wgcf_timeout_seconds": 200,
    })
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    cfg = load_config(db).wireguard
    assert cfg.enabled is True
    assert cfg.manage_service is True
    assert cfg.wg_exe == "C:\\tools\\wg.exe"
    assert cfg.service_timeout_seconds == 45
    assert cfg.lock_timeout_seconds == 9
    assert cfg.wgcf.enabled is True
    assert cfg.wgcf.executable == "C:\\tools\\wgcf.exe"
    # 1 dòng = 1 tham số, không parse shell.
    assert cfg.wgcf.argv == ["register", "--token", "ABC 123", "--name \"x y\""]
    assert cfg.wgcf.output == "gen.conf"
    assert cfg.wgcf.timeout_seconds == 200


def test_settings_checkbox_unticked_disables(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    client.post("/api/ui/wireguard/settings", json={
        "enabled": True, "manage_service": True, "wgcf_enabled": True,
    })
    client.post("/api/ui/wireguard/settings", json={})  # không tick ô nào
    cfg = load_config(db).wireguard
    assert cfg.enabled is False
    assert cfg.manage_service is False
    assert cfg.wgcf.enabled is False


# ── wgcf.argv bảo mật: không lộ token, chỉ thay khi tích replace ──────────

WGCF_TOKEN = "s3cr3t-wgcf-token-9876"


def _set_argv(db, argv):
    wg.write_config(str(db), {"wgcf": {"argv": argv}})


def test_get_page_never_renders_stored_wgcf_argv_token(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    _set_argv(db, ["register", "--token", WGCF_TOKEN])

    data = client.get("/api/ui/wireguard").json()
    config = data["config"]
    # API không lộ giá trị argv (có thể chứa token) — chỉ báo cấu trúc an toàn.
    assert WGCF_TOKEN not in str(config)
    assert config["wgcf_argv_configured"] is True
    assert config["wgcf_argv_count"] == 3  # 3 tham số: register, --token, token value
    assert "wgcf_argv" not in config  # không bao giờ kèm giá trị argv


def test_saving_unrelated_settings_preserves_existing_argv(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    _set_argv(db, ["register", "--token", WGCF_TOKEN])

    # Không tick replace_wgcf_argv → argv giữ nguyên, dù textarea có gửi nội dung.
    res = client.post("/api/ui/wireguard/settings", json={
        "profiles_dir": str(_profiles_dir(tmp_path)),
        "replace_wgcf_argv": False,
        "wgcf_argv": "DO-NOT-APPLY",
    })
    assert res.status_code == 200
    cfg = load_config(db).wireguard
    assert cfg.wgcf.argv == ["register", "--token", WGCF_TOKEN]
    assert cfg.profiles_dir == str(_profiles_dir(tmp_path))


def test_replace_wgcf_argv_explicitly_replaces(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    _set_argv(db, ["old", "value"])

    res = client.post("/api/ui/wireguard/settings", json={
        "replace_wgcf_argv": True,
        "wgcf_argv": "register\n--token\nNEW-VALUE",
    })
    assert res.status_code == 200
    cfg = load_config(db).wireguard
    assert cfg.wgcf.argv == ["register", "--token", "NEW-VALUE"]


def test_replace_wgcf_argv_with_blank_textarea_clears(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    _set_argv(db, ["register", "--token", WGCF_TOKEN])

    res = client.post("/api/ui/wireguard/settings", json={"replace_wgcf_argv": True, "wgcf_argv": ""})
    assert res.status_code == 200
    cfg = load_config(db).wireguard
    assert cfg.wgcf.argv == []


# ── Import: valid / invalid / oversize + dọn tạm ──────────────────────────


def test_import_valid_conf(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    res = client.post(
        "/api/ui/wireguard/import",
        files={"file": ("warp.conf", fake_config_text().encode(), "text/plain")},
        data={"name": "warp"},
    )
    assert res.status_code == 200
    rows = wg.list_profiles(str(db))
    assert len(rows) == 1
    assert rows[0]["filename"].endswith(".conf")
    assert rows[0]["source"] == "manual"
    assert (profiles / rows[0]["filename"]).exists()
    # DB chỉ metadata — không lọt nội dung/private key.
    payload = "".join(str(v) for v in rows[0].values())
    assert FAKE_PRIVATE_KEY not in payload
    assert "[Interface]" not in payload


def test_import_rejects_invalid_config(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    res = client.post(
        "/api/ui/wireguard/import",
        files={"file": ("bad.conf", "not a wireguard config".encode(), "text/plain")},
    )
    assert res.status_code == 400
    assert "không hợp lệ" in res.json()["detail"]
    assert wg.list_profiles(str(db)) == []


def test_import_rejects_oversize_without_leaving_temp(monkeypatch, tmp_path):
    import app.routes.webui as wg_ui_route

    db, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(wg_ui_route, "_WG_MAX_UPLOAD_BYTES", 1024)

    before = {f for f in os.listdir(tempfile.gettempdir()) if f.startswith("n2e-wg-import-")}
    res = client.post(
        "/api/ui/wireguard/import",
        files={"file": ("big.conf", b"x" * 4096, "text/plain")},
    )
    after = {f for f in os.listdir(tempfile.gettempdir()) if f.startswith("n2e-wg-import-")}
    assert res.status_code == 400
    assert "quá lớn" in res.json()["detail"]
    assert after == before  # không để lại file tạm
    assert wg.list_profiles(str(db)) == []


def test_import_cleans_up_temp_file_after_success(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    before = {f for f in os.listdir(tempfile.gettempdir()) if f.startswith("n2e-wg-import-")}
    res = client.post(
        "/api/ui/wireguard/import",
        files={"file": ("ok.conf", fake_config_text().encode(), "text/plain")},
    )
    assert res.status_code == 200
    after = {f for f in os.listdir(tempfile.gettempdir()) if f.startswith("n2e-wg-import-")}
    assert after == before


# ── Discover / Provision (mock domain) ────────────────────────────────────


def test_discover_calls_domain(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    calls = {}

    def fake_discover(db_path, profiles_dir, *, source="discovered"):
        calls["db"] = db_path
        calls["dir"] = str(profiles_dir)
        return []

    monkeypatch.setattr(wg, "discover_profiles", fake_discover)
    res = client.post("/api/ui/wireguard/discover")
    assert res.status_code == 200
    assert res.json() == {"added": 0}
    assert calls["db"] == str(db)
    assert calls["dir"] == str(profiles)


def test_provision_calls_domain_with_label(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    calls = {}

    def fake_provision(db_path, cfg, *, label=""):
        calls["label"] = label
        return {}

    monkeypatch.setattr(wg, "provision_wgcf_profile", fake_provision)
    res = client.post("/api/ui/wireguard/provision", json={"label": "warp.conf"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert calls["label"] == "warp.conf"


def test_rotate_calls_domain(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    calls = {}

    def fake_rotate(db_path, cfg, *, current_id=None):
        calls["db"] = db_path
        return {}

    monkeypatch.setattr(wg, "rotate_profile", fake_rotate)
    res = client.post("/api/ui/wireguard/rotate")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert calls["db"] == str(db)


# ── enable / disable / order ──────────────────────────────────────────────


def test_enable_disable_and_set_order(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    a = _attach_profile(db, profiles, "a")
    b = _attach_profile(db, profiles, "b")

    assert client.post(f"/api/ui/wireguard/{a['id']}/enable").status_code == 200
    assert wg.get_profile(str(db), a["id"])["enabled"] == 1

    assert client.post(f"/api/ui/wireguard/{b['id']}/disable").status_code == 200
    assert wg.get_profile(str(db), b["id"])["enabled"] == 0

    # Đổi thứ tự: b (vị trí 1) lên trước a (vị trí 0).
    assert client.post(f"/api/ui/wireguard/{b['id']}/position", json={"position": -1}).status_code == 200
    rows = wg.list_profiles(str(db))
    positions = {r["id"]: r["position"] for r in rows}
    assert positions[b["id"]] == -1
    assert positions[a["id"]] == 0


def test_unknown_profile_404(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    assert client.post("/api/ui/wireguard/does-not-exist/enable").status_code == 404
    assert client.post("/api/ui/wireguard/does-not-exist/disable").status_code == 404
    assert client.post("/api/ui/wireguard/does-not-exist/position", json={"position": 0}).status_code == 404
    assert client.post("/api/ui/wireguard/does-not-exist/activate").status_code == 404
    assert client.post("/api/ui/wireguard/does-not-exist/delete").status_code == 404


# ── Delete: active conflict 409 + xóa thường ──────────────────────────────


def test_delete_active_profile_conflicts(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    a = _attach_profile(db, profiles)
    wg.set_active(str(db), a["id"])

    res = client.post(f"/api/ui/wireguard/{a['id']}/delete")
    assert res.status_code == 409
    assert "active" in res.json()["detail"]
    # Profile vẫn còn nguyên.
    assert wg.get_profile(str(db), a["id"]) is not None


def test_delete_inactive_profile_removes_row_and_file(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    a = _attach_profile(db, profiles)

    res = client.post(f"/api/ui/wireguard/{a['id']}/delete")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert wg.get_profile(str(db), a["id"]) is None
    assert not (profiles / a["filename"]).exists()


# ── activate / rotate: gọi đúng domain ────────────────────────────────────


def test_activate_calls_domain_with_profile(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    a = _attach_profile(db, profiles)
    wg.set_enabled(str(db), a["id"], True)
    calls = {}

    def fake_activate(db_path, cfg, selector):
        calls["db"] = db_path
        calls["selector"] = selector
        return wg.get_profile(db_path, selector) or {}

    monkeypatch.setattr(wg, "activate_profile", fake_activate)
    res = client.post(f"/api/ui/wireguard/{a['id']}/activate")
    assert res.status_code == 200
    assert calls["db"] == str(db)
    assert calls["selector"] == a["id"]


def test_activate_domain_error_maps_to_400(monkeypatch, tmp_path):
    from novel2epub.wireguard import WireGuardProfileError

    db, client = _client(monkeypatch, tmp_path)
    profiles = _profiles_dir(tmp_path)
    a = _attach_profile(db, profiles)

    def fake_activate(db_path, cfg, selector):
        raise WireGuardProfileError("quản lý tunnel service chưa bật (wireguard.manage_service=true)")

    monkeypatch.setattr(wg, "activate_profile", fake_activate)
    res = client.post(f"/api/ui/wireguard/{a['id']}/activate")
    assert res.status_code == 400
    assert "manage_service" in res.json()["detail"]


def test_rotate_domain_error_maps_to_400(monkeypatch, tmp_path):
    from novel2epub.wireguard import WireGuardProfileError

    db, client = _client(monkeypatch, tmp_path)

    def fake_rotate(db_path, cfg, *, current_id=None):
        raise WireGuardProfileError("không có profile đã bật để rotate")

    monkeypatch.setattr(wg, "rotate_profile", fake_rotate)
    res = client.post("/api/ui/wireguard/rotate")
    assert res.status_code == 400
    assert "profile" in res.json()["detail"]