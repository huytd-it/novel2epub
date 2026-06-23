"""Gọi CLI AI bất kỳ (opencode, claude, llm, ollama...) — dùng chung cho
translator.CLITranslator (dịch chương) và glossary_ai (gợi ý/rewrite), tránh
lệch hành vi resolve-command/subprocess giữa 2 nơi.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from .config import CliTranslatorConfig


def resolve_command(command: str) -> str:
    """Tìm đường dẫn đầy đủ của lệnh CLI; thử thêm thư mục npm global trên Windows."""
    resolved = shutil.which(command)
    if resolved:
        return resolved
    npm_dir = Path.home() / "AppData" / "Roaming" / "npm"
    for suffix in (".cmd", ".exe", ".bat"):
        candidate = npm_dir / f"{command}{suffix}"
        if candidate.exists():
            return str(candidate)
    return command


def build_argv(cli: CliTranslatorConfig) -> list[str]:
    # posix=True để xử lý đúng dấu nháy. Trên Windows nếu lệnh có đường dẫn
    # chứa "\" thì dùng "/" trong config (Python/CLI đều chấp nhận).
    argv = shlex.split(cli.command, posix=True)
    if not argv:
        raise ValueError("translate.cli.command đang trống")
    argv[0] = resolve_command(argv[0])
    if cli.model:
        argv.extend(["--model", cli.model])
    return argv


def run_cli(cli: CliTranslatorConfig, prompt: str, argv: list[str] | None = None) -> str:
    """Chạy CLI đúng 1 lần (không retry), trả raw stdout.

    Raise FileNotFoundError nếu không tìm thấy lệnh, subprocess.TimeoutExpired
    nếu quá giờ, RuntimeError nếu CLI trả mã lỗi khác 0.
    """
    argv = argv if argv is not None else build_argv(cli)
    if cli.mode == "arg":
        full_argv = argv + [prompt]
        stdin_data = None
    else:  # stdin
        full_argv = argv
        stdin_data = prompt

    proc = subprocess.run(
        full_argv,
        input=stdin_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=cli.timeout_seconds,
    )
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0:
        # Nhiều AI CLI (vd `claude -p`) in thông báo lỗi ra stdout chứ không phải
        # stderr. Gộp cả hai để không nuốt mất nguyên nhân thật.
        parts = [p for p in (stderr, stdout) if p]
        detail = "\n".join(parts) or "(không có stderr/stdout)"
        raise RuntimeError(f"CLI trả về mã lỗi {proc.returncode}:\n{detail}")

    out = proc.stdout or ""
    # Nhiều AI CLI vẫn thoát mã 0 dù gặp lỗi (auth/rate-limit/sai model) rồi in
    # lỗi ra stderr và không trả gì ở stdout. Coi output rỗng là thất bại để báo
    # lỗi thay vì âm thầm ghi bản dịch trống.
    if not out.strip():
        detail = stderr or "Không có stderr — kiểm tra command/model/prompt trong config."
        raise RuntimeError(f"CLI thoát mã 0 nhưng không trả về nội dung:\n{detail}")
    return out
