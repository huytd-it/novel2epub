"""Các bộ dịch Trung -> Việt (pluggable).

- CLITranslator: gọi một AI CLI bất kỳ (opencode, llm, ollama, claude...).
  Văn bản có thể đưa qua stdin (mặc định) hoặc nối vào cuối lệnh.
- GoogleTranslator: Google Translate miễn phí qua deep-translator (chunk 4500 ký tự).
- NoopTranslator: trả nguyên văn (dùng để test pipeline mà không tốn chi phí).
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

from .config import TranslateConfig

# Một số mẫu "lời mở đầu" mà LLM hay tự thêm dù đã bảo đừng.
_PREAMBLE = re.compile(
    r"^\s*(đây là|sau đây là|dưới đây là|bản dịch).{0,40}:\s*$",
    re.IGNORECASE,
)


def _clean_output(text: str) -> str:
    """Bỏ ```fence``` và dòng mở đầu kiểu 'Đây là bản dịch:' nếu có."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    lines = text.splitlines()
    if lines and _PREAMBLE.match(lines[0]):
        lines = lines[1:]
        if lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip()


def _format_glossary(glossary: dict[str, str]) -> str:
    if not glossary:
        return ""
    lines = "\n".join(f"  {zh} = {vi}" for zh, vi in glossary.items())
    return "Bảng thuật ngữ bắt buộc dùng nhất quán:\n" + lines


def _apply_glossary(text: str, glossary: dict[str, str]) -> str:
    """Thay thế literal sau khi dịch để đảm bảo nhất quán tên riêng."""
    for zh, vi in glossary.items():
        if zh and vi:
            text = text.replace(zh, vi)
    return text


def _merge_glossaries(*parts: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for part in parts:
        for zh, vi in part.items():
            if zh and vi:
                merged[zh] = vi
    return merged


class Translator(Protocol):
    def translate(self, text: str) -> str: ...


class NoopTranslator:
    def translate(self, text: str) -> str:
        return text


class CLITranslator:
    def __init__(self, cfg: TranslateConfig):
        self.cfg = cfg
        self.cli = cfg.cli
        self.glossary = self._load_glossary()
        # posix=True để xử lý đúng dấu nháy. Trên Windows nếu lệnh có đường dẫn
        # chứa "\" thì dùng "/" trong config (Python/CLI đều chấp nhận).
        self._argv = shlex.split(cfg.cli.command, posix=True)
        if not self._argv:
            raise ValueError("translate.cli.command đang trống")
        self._argv[0] = self._resolve_command(self._argv[0])
        if self.cli.model:
            self._argv.extend(["--model", self.cli.model])

    def _load_glossary(self) -> dict[str, str]:
        glossary: dict[str, str] = dict(self.cfg.glossary)
        for path in (self.cfg.glossary_files.names, self.cfg.glossary_files.vietphrase):
            if not path:
                continue
            p = Path(path)
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                zh, vi = line.split("=", 1)
                zh = zh.strip()
                vi = vi.strip()
                if zh and vi:
                    glossary[zh] = vi
        return glossary

    def _resolve_command(self, command: str) -> str:
        resolved = shutil.which(command)
        if resolved:
            return resolved

        npm_dir = Path.home() / "AppData" / "Roaming" / "npm"
        for suffix in (".cmd", ".exe", ".bat"):
            candidate = npm_dir / f"{command}{suffix}"
            if candidate.exists():
                return str(candidate)
        return command

    def _build_prompt(self, text: str) -> str:
        return self.cli.prompt_template.format(
            text=text,
            glossary=_format_glossary(self.glossary),
            tone=self.cfg.style.tone,
            pronoun_policy=self.cfg.style.pronoun_policy,
            keep_paragraphs=self.cfg.style.keep_paragraphs,
            title_mode=self.cfg.style.title_mode,
            han_viet_level=self.cfg.style.han_viet_level,
        )

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        prompt = self._build_prompt(text)

        if self.cli.mode == "arg":
            argv = self._argv + [prompt]
            stdin_data = None
        else:  # stdin
            argv = self._argv
            stdin_data = prompt

        attempts = max(1, int(self.cfg.retry.attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                proc = subprocess.run(
                    argv,
                    input=stdin_data,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.cli.timeout_seconds,
                )
            except FileNotFoundError as e:
                raise RuntimeError(
                    f"Không tìm thấy lệnh CLI: {self._argv[0]!r}. "
                    "Kiểm tra translate.cli.command trong config."
                ) from e
            except subprocess.TimeoutExpired as e:
                last_error = RuntimeError(
                    f"CLI dịch quá thời gian ({self.cli.timeout_seconds}s)."
                )
                if attempt < attempts and self.cfg.retry.delay_seconds > 0:
                    time.sleep(self.cfg.retry.delay_seconds)
                continue

            if proc.returncode == 0:
                out = _clean_output(proc.stdout or "")
                return _apply_glossary(out, self.glossary)

            last_error = RuntimeError(
                f"CLI dịch trả về mã lỗi {proc.returncode}:\n{proc.stderr.strip()}"
            )
            if attempt < attempts and self.cfg.retry.delay_seconds > 0:
                time.sleep(self.cfg.retry.delay_seconds)

        if last_error is not None:
            raise last_error
        raise RuntimeError("CLI dịch thất bại")


class GoogleTranslator:
    MAX_CHARS = 4500

    def __init__(self, cfg: TranslateConfig):
        self.cfg = cfg
        self.glossary = _merge_glossaries(cfg.glossary)
        try:
            from deep_translator import GoogleTranslator as _G
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài deep-translator. Chạy: pip install deep-translator"
            ) from e
        self._engine = _G(source="zh-CN", target="vi")

    def _chunks(self, text: str):
        buf = ""
        for para in text.split("\n"):
            # +1 cho ký tự xuống dòng sẽ nối lại
            if len(buf) + len(para) + 1 > self.MAX_CHARS and buf:
                yield buf
                buf = ""
            buf = f"{buf}\n{para}" if buf else para
        if buf:
            yield buf

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        parts = [self._engine.translate(chunk) or "" for chunk in self._chunks(text)]
        return _apply_glossary("\n".join(parts), self.glossary)


def make_translator(cfg: TranslateConfig) -> Translator:
    kind = (cfg.type or "none").lower()
    if kind == "cli":
        return CLITranslator(cfg)
    if kind == "google":
        return GoogleTranslator(cfg)
    if kind == "none":
        return NoopTranslator()
    raise ValueError(f"translate.type không hợp lệ: {cfg.type!r} (cli|google|none)")


class RateLimited:
    """Bọc một translator để chèn delay giữa các lần gọi."""

    def __init__(self, inner: Translator, delay_seconds: float):
        self.inner = inner
        self.delay = delay_seconds

    def translate(self, text: str) -> str:
        out = self.inner.translate(text)
        if self.delay > 0:
            time.sleep(self.delay)
        return out
