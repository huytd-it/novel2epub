"""Đăng ký web server chạy nền khi khởi động máy — Windows Task Scheduler /
Linux systemd user service (xem spec cron-schedule). Phần sinh nội dung là
hàm thuần (test không đụng OS); phần thực thi subprocess nằm ở service_main."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "novel2epub"


def project_dir() -> Path:
    """Gốc repo (chứa app/ + novel2epub/)."""
    return Path(__file__).resolve().parent.parent


def render_cmd_launcher(project_dir: Path, python_exe: str, host: str, port: int) -> str:
    """Nội dung start_server.cmd — Task Scheduler không set được cwd nên
    launcher tự cd vào project trước khi chạy uvicorn."""
    return (
        "@echo off\r\n"
        f'cd /d "{project_dir}"\r\n'
        f'"{python_exe}" -m uvicorn app.main:app --host {host} --port {port}\r\n'
    )


def render_systemd_unit(project_dir: Path, python_exe: str, host: str, port: int) -> str:
    return f"""[Unit]
Description=novel2epub web server

[Service]
WorkingDirectory={project_dir}
ExecStart={python_exe} -m uvicorn app.main:app --host {host} --port {port}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def schtasks_args(action: str, launcher_path: Path | None = None) -> list[str]:
    if action == "install":
        return ["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", f'"{launcher_path}"', "/F"]
    if action == "status":
        return ["schtasks", "/Query", "/TN", TASK_NAME]
    if action == "uninstall":
        return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    raise ValueError(f"action không hợp lệ: {action!r}")


def systemctl_args(action: str) -> list[list[str]]:
    if action == "install":
        return [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", TASK_NAME],
        ]
    if action == "status":
        return [["systemctl", "--user", "status", TASK_NAME, "--no-pager"]]
    if action == "uninstall":
        return [
            ["systemctl", "--user", "disable", "--now", TASK_NAME],
            ["systemctl", "--user", "daemon-reload"],
        ]
    raise ValueError(f"action không hợp lệ: {action!r}")


def _run(args: list[str]) -> int:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def service_main(action: str, host: str = "127.0.0.1", port: int = 8010) -> int:
    """install/uninstall/status server nền theo OS. Trả exit code."""
    proj = project_dir()
    python_exe = sys.executable
    if sys.platform == "win32":
        launcher = proj / "start_server.cmd"
        if action == "install":
            launcher.write_text(render_cmd_launcher(proj, python_exe, host, port), encoding="utf-8")
            rc = _run(schtasks_args("install", launcher))
            if rc == 0:
                print(f"Đã đăng ký Task Scheduler '{TASK_NAME}' (chạy khi đăng nhập) → {launcher}")
            return rc
        if action == "uninstall":
            rc = _run(schtasks_args("uninstall"))
            launcher.unlink(missing_ok=True)
            return rc
        return _run(schtasks_args("status"))
    if sys.platform.startswith("linux"):
        unit_path = Path.home() / ".config" / "systemd" / "user" / f"{TASK_NAME}.service"
        if action == "install":
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(render_systemd_unit(proj, python_exe, host, port), encoding="utf-8")
            for args in systemctl_args("install"):
                rc = _run(args)
                if rc != 0:
                    return rc
            print(f"Đã bật systemd user service '{TASK_NAME}' → {unit_path}")
            print("Gợi ý: chạy khi chưa đăng nhập cần `loginctl enable-linger $USER`.")
            return 0
        if action == "uninstall":
            cmds = systemctl_args("uninstall")
            rc = _run(cmds[0])
            unit_path.unlink(missing_ok=True)
            rc2 = _run(cmds[1])
            return rc or rc2
        return _run(systemctl_args("status")[0])
    print(f"Chưa hỗ trợ cài service trên {sys.platform} (mới có Windows/Linux).", file=sys.stderr)
    return 1
