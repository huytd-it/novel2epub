"""Tests cho novel2epub/wireguard.py — phiên bản AN TOÀN.

Tách làm nhiều nhóm: cấu hình/schema, parsing không lộ key, registry + tuyển
chọn, nhập/discovery/xóa, khóa liên tiến trình, subprocess (mock), activation
+ scope, cung cấp wgcf (argv + an toàn đường dẫn + dọn artifact), CLI.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from novel2epub.config import load_config, WireGuardConfig, WgcfConfig
from novel2epub import wireguard
from novel2epub.wireguard import (
    CrossProcessLock,
    WireGuardProfileError,
    build_config,
    discover_profiles,
    get_active_id,
    import_profile,
    install_tunnel_service,
    list_profiles,
    nested_update,
    parse_wireguard_config,
    provision_wgcf_profile,
    remove_profile,
    rotate_profile_id,
    run_tool,
    select_profile_id,
    service_install_args,
    service_uninstall_args,
    set_active,
    set_enabled,
    set_status,
    uninstall_tunnel_service,
    validate_config_file,
    wireguard_network_scope,
    write_config,
    activate_profile,
    rotate_profile,
)
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


def _db(tmp_path: Path, *, wireguard_cfg: dict | None = None) -> str:
    defaults = {"wireguard": wireguard_cfg or {}}
    path = tmp_path / "novel2epub.db"
    return str(write_db_config(path, defaults=defaults, ebooks={"demo": {"novel": {"slug": "demo"}}}))


def _profiles_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wireguard"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Cấu hình (load/set, default profiles_dir) ────────────────────────────


def test_load_config_reads_wireguard_defaults(tmp_path):
    db = _db(tmp_path, wireguard_cfg={"enabled": True, "wgcf": {"output": "x.conf", "enabled": True}})
    cfg = load_config(db)
    assert cfg.wireguard.enabled is True
    assert cfg.wireguard.wgcf.output == "x.conf"
    assert cfg.wireguard.wgcf.enabled is True
    # profiles_dir mặc định = <db_dir>/wireguard
    assert cfg.wireguard.profiles_dir == str(tmp_path / "wireguard")


def test_write_config_roundtrip_and_default(tmp_path):
    db = _db(tmp_path)
    write_config(db, nested_update("enabled", True))
    write_config(db, nested_update("wgcf.output", "profile.conf"))
    cfg = load_config(db).wireguard
    assert cfg.enabled is True
    assert cfg.wgcf.output == "profile.conf"
    assert cfg.wgcf.argv == []  # không tự bịa cờ wgcf


def test_nested_update():
    assert nested_update("wgcf.output", "x") == {"wgcf": {"output": "x"}}
    assert nested_update("enabled", True) == {"enabled": True}
    assert nested_update("wgcf.argv", ["a", "b"]) == {"wgcf": {"argv": ["a", "b"]}}


# ── Parsing / validation — không lộ key ───────────────────────────────────


def test_parse_valid_config_keeps_only_key_names():
    parsed = parse_wireguard_config(fake_config_text())
    assert "PrivateKey" in parsed.interface_keys
    assert "Address" in parsed.interface_keys
    assert "Endpoint" in parsed.peers_keys[0]
    # KHÔNG có giá trị nào của key (đặc biệt private key) lọt vào object.
    assert FAKE_PRIVATE_KEY not in repr(parsed)


def test_parse_missing_peer_rejected():
    secret = "SUPERSECRETVALUE12345"
    # Interface đủ key nhưng KHÔNG có [Peer] => không hợp lệ.
    with pytest.raises(WireGuardProfileError) as exc:
        parse_wireguard_config(build_config({"PrivateKey": secret, "Address": "a"}, []))
    assert "Peer" in str(exc.value)
    # Không giá trị nào của config lọt ra ngoài (construct + nhé không lộ secret).
    assert secret not in str(exc.value)


def test_import_never_writes_config_text_to_db(tmp_path):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    src = tmp_path / "src.conf"
    src.write_text(fake_config_text(), encoding="utf-8")

    prof = import_profile(db, profiles, src, source="manual")
    # file ngoài giữ nội dung cấu hình
    assert (profiles / prof["filename"]).exists()
    # DB chỉ có metadata — không có text cấu hình / private key
    row = list_profiles(db)[0]
    rows_payload = "".join(str(v) for v in row.values())
    assert FAKE_PRIVATE_KEY not in rows_payload
    assert "[Interface]" not in rows_payload


# ── Registry + tuyển chọn round-robin xác định ───────────────────────────


def test_select_and_rotate_deterministic(tmp_path):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    p1 = tmp_path / "a.conf"; p1.write_text(fake_config_text(), encoding="utf-8")
    p2 = tmp_path / "b.conf"; p2.write_text(fake_config_text(), encoding="utf-8")
    a = import_profile(db, profiles, p1, name="a")
    b = import_profile(db, profiles, p2, name="b")
    set_enabled(db, a["id"], True)
    set_enabled(db, b["id"], True)

    first = select_profile_id(db)
    assert first == a["id"]  # position nhỏ nhất trước
    assert select_profile_id(db) == first  # xác định — lặp cho cùng kết quả
    assert rotate_profile_id(db, current_id=a["id"]) == b["id"]  # vòng kế
    assert rotate_profile_id(db, current_id=b["id"]) == a["id"]  # vòng lặp đầy


def test_exclude_error_and_disabled(tmp_path):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    s1 = tmp_path / "s1.conf"; s1.write_text(fake_config_text(), encoding="utf-8")
    s2 = tmp_path / "s2.conf"; s2.write_text(fake_config_text(), encoding="utf-8")
    a = import_profile(db, profiles, s1, name="s1")
    b = import_profile(db, profiles, s2, name="s2")
    set_status(db, a["id"], status="error", error="test")  # a bị lỗi -> bỏ
    set_enabled(db, b["id"], False)  # b tắt -> bỏ
    assert select_profile_id(db) is None


# ── Khóa liên tiến trình ──────────────────────────────────────────────────


def test_exclusive_lock_acquire_release(tmp_path):
    lock = CrossProcessLock(tmp_path / "wg.lock", backend="exclusive")
    lock.acquire()
    with pytest.raises(WireGuardProfileError):
        CrossProcessLock(tmp_path / "wg.lock", backend="exclusive", timeout=0.2).acquire()
    lock.release()
    lock2 = CrossProcessLock(tmp_path / "wg.lock", backend="exclusive", timeout=0.2)
    lock2.acquire()
    lock2.release()


# ── Subprocess (mocked) + tunnel service args ──────────────────────────────


def test_service_args():
    assert service_install_args(Path("wg-a.conf")) == ["/installtunnelservice", "wg-a.conf"]
    assert service_uninstall_args("wg-a") == ["/uninstalltunnelservice", "wg-a"]


def test_run_tool_shell_false_timeout(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd, cwd=None, shell=False, capture_output=True, text=True, timeout=None):
        calls["cmd"] = cmd
        calls["shell"] = shell
        calls["timeout"] = timeout
        calls["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(wireguard.subprocess, "run", fake_run)
    run_tool("wg.exe", ["arg1"], cwd=str(tmp_path), timeout=12.0)
    assert calls["shell"] is False
    assert calls["timeout"] == 12.0
    assert calls["cwd"] == str(tmp_path)
    assert calls["cmd"] == ["wg.exe", "arg1"]


def test_run_tool_error_does_not_expose_stderr(monkeypatch):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(["wg.exe"], 1, stdout="", stderr=FAKE_PRIVATE_KEY)

    monkeypatch.setattr(wireguard.subprocess, "run", fake_run)
    with pytest.raises(WireGuardProfileError) as exc:
        install_tunnel_service(WireGuardConfig(wg_exe="wg.exe", manage_service=True), Path("wg.conf"))
    # Message lỗi làm sạch: KHÔNG chứa stderr (có thể là key).
    assert FAKE_PRIVATE_KEY not in str(exc.value)


def test_install_service_requires_manage_flag():
    with pytest.raises(WireGuardProfileError):
        install_tunnel_service(WireGuardConfig(), Path("wg.conf"))


# ── Provision w / an toàn tuyệt đường + dọn artifact ─────────────────────


def test_validate_relative_output_train_and_reject():
    with pytest.raises(WireGuardProfileError):
        wireguard._validate_relative_output("../escape.conf")
    with pytest.raises(WireGuardProfileError):
        wireguard._validate_relative_output("/abs/x.conf")
    with pytest.raises(WireGuardProfileError):
        wireguard._validate_relative_output("dir/x.conf")
    assert wireguard._validate_relative_output("ok.conf") == "ok.conf"


def test_provision_calls_wgcf_with_argv_and_cleanup(monkeypatch, tmp_path):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    outname = "gen.conf"
    calls = {}

    def fake_run(cmd, cwd=None, shell=False, capture_output=True, text=True, timeout=None):
        calls["exe"] = cmd[0]
        calls["argv"] = cmd[1:]
        calls["cwd"] = cwd
        (Path(cwd) / outname).write_text(fake_config_text(), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(wireguard.subprocess, "run", fake_run)
    cfg = WireGuardConfig(
        enabled=True,
        profiles_dir=str(profiles),
        wgcf=WgcfConfig(enabled=True, executable="wgcf.exe", argv=["register", "--token", "T"], output=outname),
    )
    prof = provision_wgcf_profile(db, cfg, label="warp")
    assert calls["exe"] == "wgcf.exe"
    assert calls["argv"] == ["register", "--token", "T"]  # argv tường minh, không tự thêm cờ
    assert calls["cwd"] != "" and Path(calls["cwd"]).is_absolute()
    # profile sinh ra đã nhập vào profiles_dir
    assert (profiles / prof["filename"]).exists()
    assert prof["source"] == "wgcf"


def test_provision_rejects_bad_output():
    cfg = WireGuardConfig(wgcf=WgcfConfig(enabled=True, executable="wgcf", output="../../x"))
    with pytest.raises(WireGuardProfileError):
        provision_wgcf_profile("fake.db", cfg)


# ── Activation (tunnel service THẬT) + rollback + scope ──────────────────


def _make_subprocess(monkeypatch, *, fail_stem: str | None = None, leak: str = ""):
    """Giả subprocess.run cho run_tool để test vòng đời service thật.
    `fail_stem`: stem của file gọi /installtunnelservice sẽ trả exit != 0.
    `leak`: chuỗi (vd private key) nhét vào stderr để kiểm tra không lọt ra ngoài."""
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, shell=False, capture_output=True, text=True, timeout=None):
        calls.append(list(cmd))
        op = cmd[1] if len(cmd) > 1 else ""
        fail = op == "/installtunnelservice" and fail_stem and Path(cmd[2]).stem == fail_stem
        stderr = leak if fail else ""
        rc = 1 if fail else 0
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=stderr)

    monkeypatch.setattr(wireguard.subprocess, "run", fake_run)
    return calls


def _attach_profiles(db, profiles) -> tuple[dict, dict]:
    a = import_profile(db, profiles, _fresh_src(profiles, "v1"), name="v1")
    b = import_profile(db, profiles, _fresh_src(profiles, "v2"), name="v2")
    set_enabled(db, a["id"], True)
    set_enabled(db, b["id"], True)
    return a, b


def _fresh_src(profiles: Path, stem: str) -> Path:
    src = profiles / f"{stem}-src.conf"
    src.write_text(fake_config_text(), encoding="utf-8")
    return src


def test_activate_refuses_when_manage_service_false(tmp_path):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, _ = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(manage_service=False, profiles_dir=str(profiles))
    with pytest.raises(WireGuardProfileError) as exc:
        activate_profile(db, cfg, a["id"])
    assert "manage_service=false" in str(exc.value)
    # Không lén ghi active khi refuse
    assert get_active_id(db) is None


def test_activate_installs_real_service_and_records(tmp_path, monkeypatch):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, _ = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(manage_service=True, wg_exe="wg.exe", profiles_dir=str(profiles))
    calls = _make_subprocess(monkeypatch)

    out = activate_profile(db, cfg, a["id"])
    assert out["id"] == a["id"]
    # cài tunnel service target bằng lệnh WireGuard for Windows chuẩn
    assert calls and calls[0][0:2] == ["wg.exe", "/installtunnelservice"]
    assert Path(calls[0][2]).name == a["filename"]
    # DB active chỉ cập nhật SAU khi cài thành công
    assert get_active_id(db) == a["id"]


def test_activate_preserves_disabled_target(tmp_path, monkeypatch):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, _ = _attach_profiles(db, profiles)
    set_enabled(db, a["id"], False)
    cfg = WireGuardConfig(manage_service=True, wg_exe="wg.exe", profiles_dir=str(profiles))
    with pytest.raises(WireGuardProfileError) as exc:
        activate_profile(db, cfg, a["id"])
    assert "đã tắt" in str(exc.value)
    assert get_active_id(db) is None


def test_rotate_uninstalls_previous_then_installs_target(tmp_path, monkeypatch):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, b = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(manage_service=True, wg_exe="wg.exe", profiles_dir=str(profiles))
    calls = _make_subprocess(monkeypatch)

    activate_profile(db, cfg, a["id"])
    out = rotate_profile(db, cfg)
    assert out["id"] == b["id"]
    # uninstall service profile cũ (sở hữu qua registry) rồi cài target mới
    uninstalls = [c for c in calls if c[1] == "/uninstalltunnelservice"]
    installs = [c for c in calls if c[1] == "/installtunnelservice"]
    assert [c[2] for c in uninstalls] == [Path(a["filename"]).stem]
    assert [Path(c[2]).name for c in installs] == [a["filename"], b["filename"]]
    assert get_active_id(db) == b["id"]
    # KHÔNG bao giờ uninstall tunnel ngoài registry
    for c in uninstalls:
        assert c[2] in {Path(a["filename"]).stem, Path(b["filename"]).stem}


def test_activate_rolls_back_previous_on_target_failure(tmp_path, monkeypatch):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, b = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(manage_service=True, wg_exe="wg.exe", profiles_dir=str(profiles))
    calls = _make_subprocess(monkeypatch, fail_stem=Path(b["filename"]).stem)

    activate_profile(db, cfg, a["id"])
    with pytest.raises(WireGuardProfileError):
        rotate_profile(db, cfg)
    # rollback: cài LẠI profile trước
    installs = [c for c in calls if c[1] == "/installtunnelservice"]
    assert Path(installs[-1][2]).name == a["filename"]
    # active được khôi phục về a; b bị đánh dấu lỗi (không lọt key vào DB)
    assert get_active_id(db) == a["id"]
    target = wireguard.get_profile(db, b["id"])
    assert target["status"] == "error"
    assert FAKE_PRIVATE_KEY not in "".join(str(v) for v in target.values())
    assert FAKE_PRIVATE_KEY not in str(target)


def test_activate_failure_does_not_leak_secret(tmp_path, monkeypatch):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, _ = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(manage_service=True, wg_exe="wg.exe", profiles_dir=str(profiles))
    _ = _make_subprocess(monkeypatch, fail_stem=Path(a["filename"]).stem, leak=FAKE_PRIVATE_KEY)
    with pytest.raises(WireGuardProfileError) as exc:
        activate_profile(db, cfg, a["id"])
    assert FAKE_PRIVATE_KEY not in str(exc.value)
    assert get_active_id(db) is None


def test_remove_active_profile_rejected(tmp_path):
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    a, _ = _attach_profiles(db, profiles)
    set_active(db, a["id"])
    with pytest.raises(WireGuardProfileError):
        remove_profile(db, profiles, a["id"])


# ── Scope metadata-free: chỉ chọn, KHÔNG ghi active ──────────────────────


def test_scope_selects_but_never_touches_active(tmp_path):
    db = _db(tmp_path, wireguard_cfg={"enabled": True})
    profiles = _profiles_dir(tmp_path)
    a, b = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(enabled=True, profiles_dir=str(profiles))

    with wireguard_network_scope(cfg, db) as pid:
        assert pid == a["id"]
        # metadata-free: DB active không bị ghi (scope không commit activation)
        assert get_active_id(db) is None

    assert set_active is not None  # vẫn còn hàm này (dùng nội bộ domain)
    with wireguard_network_scope(cfg, db) as pid:
        assert pid == a["id"]
    assert get_active_id(db) is None


def test_scope_returns_same_deterministic_profile_each_run(tmp_path):
    db = _db(tmp_path, wireguard_cfg={"enabled": True})
    profiles = _profiles_dir(tmp_path)
    a, b = _attach_profiles(db, profiles)
    cfg = WireGuardConfig(enabled=True, profiles_dir=str(profiles))

    picks = set()
    for _ in range(3):
        with wireguard_network_scope(cfg, db) as pid:
            picks.add(pid)
    assert picks == {a["id"]}


# ── CLI surface ──────────────────────────────────────────────────────────


def test_cli_wireguard_list_and_status_without_ebook(capsys, tmp_path, monkeypatch):
    from novel2epub.cli import main
    db = _db(tmp_path)
    profiles = _profiles_dir(tmp_path)
    src = tmp_path / "cli-src.conf"
    src.write_text(fake_config_text(), encoding="utf-8")
    import_profile(db, profiles, src, name="cli")

    rc = main(["-c", db, "wireguard", "list"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "cli.conf" in captured.out
    assert FAKE_PRIVATE_KEY not in captured.out

    rc = main(["-c", db, "wireguard", "status"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "cli.conf" in captured.out
    assert FAKE_PRIVATE_KEY not in captured.out