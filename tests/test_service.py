"""Tests novel2epub/service.py: sinh launcher/systemd unit/lệnh đăng ký (thuần),
và service_main gọi đúng lệnh theo OS (mock subprocess)."""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from novel2epub.service import (
    TASK_NAME,
    render_cmd_launcher,
    render_systemd_unit,
    schtasks_args,
    systemctl_args,
)


def test_render_cmd_launcher():
    out = render_cmd_launcher(Path(r"D:\Projects\novel2epub"), r"D:\v\python.exe", "127.0.0.1", 8010)
    assert 'cd /d "D:\\Projects\\novel2epub"' in out
    assert '"D:\\v\\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8010' in out


def test_render_systemd_unit():
    # PurePosixPath: trên Linux thật project_dir là PosixPath; Path("/opt/...")
    # trên máy dev Windows sẽ thành WindowsPath in ra "\opt\..." — sai bản chất
    out = render_systemd_unit(PurePosixPath("/opt/n2e"), "/opt/n2e/.venv/bin/python", "0.0.0.0", 9000)
    assert "WorkingDirectory=/opt/n2e" in out
    assert "ExecStart=/opt/n2e/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 9000" in out
    assert "Restart=on-failure" in out
    assert "WantedBy=default.target" in out


def test_schtasks_args():
    launcher = Path(r"D:\Projects\novel2epub\start_server.cmd")
    assert schtasks_args("install", launcher) == [
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
        "/TR", f'"{launcher}"', "/F",
    ]
    assert schtasks_args("status") == ["schtasks", "/Query", "/TN", TASK_NAME]
    assert schtasks_args("uninstall") == ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def test_systemctl_args():
    assert systemctl_args("install") == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", TASK_NAME],
    ]
    assert systemctl_args("status") == [["systemctl", "--user", "status", TASK_NAME, "--no-pager"]]
    assert systemctl_args("uninstall") == [
        ["systemctl", "--user", "disable", "--now", TASK_NAME],
        ["systemctl", "--user", "daemon-reload"],
    ]


# ---------- service_main ----------

import types  # noqa: E402

from novel2epub import service  # noqa: E402


def _fake_run(calls, returncode=0):
    def run(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr="")

    return run


def test_service_install_windows_writes_launcher_and_registers(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))

    rc = service.service_main("install", host="127.0.0.1", port=8010)
    assert rc == 0
    launcher = tmp_path / "start_server.cmd"
    assert launcher.exists()
    assert "-m uvicorn app.main:app --host 127.0.0.1 --port 8010" in launcher.read_text(encoding="utf-8")
    assert calls == [service.schtasks_args("install", launcher)]


def test_service_uninstall_windows_removes_launcher(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))
    (tmp_path / "start_server.cmd").write_text("x", encoding="utf-8")

    rc = service.service_main("uninstall")
    assert rc == 0
    assert not (tmp_path / "start_server.cmd").exists()
    assert calls == [service.schtasks_args("uninstall")]


def test_service_install_linux_writes_unit_and_enables(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))

    rc = service.service_main("install", host="0.0.0.0", port=9000)
    assert rc == 0
    unit = tmp_path / ".config" / "systemd" / "user" / "novel2epub.service"
    assert unit.exists()
    assert "--host 0.0.0.0 --port 9000" in unit.read_text(encoding="utf-8")
    assert calls == service.systemctl_args("install")


def test_service_uninstall_linux_removes_unit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))
    unit = tmp_path / ".config" / "systemd" / "user" / "novel2epub.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("x", encoding="utf-8")

    rc = service.service_main("uninstall")
    assert rc == 0
    assert not unit.exists()
    assert calls == service.systemctl_args("uninstall")


def test_service_unsupported_platform(monkeypatch, capsys):
    monkeypatch.setattr(service.sys, "platform", "darwin")
    rc = service.service_main("install")
    assert rc == 1
    assert "Chưa hỗ trợ" in capsys.readouterr().err


def test_service_status_passes_returncode_through(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls, returncode=1))
    assert service.service_main("status") == 1
