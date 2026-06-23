"""Các bộ dịch Trung -> Việt (pluggable).

- CLITranslator: gọi một AI CLI bất kỳ (opencode, llm, ollama, claude...).
  Văn bản có thể đưa qua stdin (mặc định) hoặc nối vào cuối lệnh.
- GoogleTranslator: Google Translate miễn phí qua deep-translator (chunk 4500 ký tự).
- NoopTranslator: trả nguyên văn (dùng để test pipeline mà không tốn chi phí).
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Protocol

from . import cli_runner
from .config import TranslateConfig
from .storage import parse_glossary_line

# Một số mẫu "lời mở đầu" mà LLM hay tự thêm dù đã bảo đừng.
_PREAMBLE = re.compile(
    r"^\s*(đây là|sau đây là|dưới đây là|bản dịch).{0,40}:\s*$",
    re.IGNORECASE,
)

_HAN_RE = re.compile(r"[一-鿿]")

# Số lần thử lại tối đa khi bản dịch còn sót chữ Hán chưa dịch.
_RESIDUAL_HAN_RETRIES = 2


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


_TITLE_LINE = re.compile(r"^\s*TI[ÊE]U\s*Đ[ỀE]\s*:\s*(.*)$", re.IGNORECASE)
_NOTE_LINE = re.compile(r"^\s*GI[ẢA]I\s*TH[ÍI]CH\s*:\s*(.*)$", re.IGNORECASE)


def _parse_title_response(raw: str) -> tuple[str, str]:
    """Tách 'TIÊU ĐỀ: ...' / 'GIẢI THÍCH: ...' từ phản hồi LLM.

    Nếu LLM không theo format yêu cầu, coi cả phản hồi (đã clean) là tiêu đề,
    không có giải thích — tránh làm vỡ pipeline vì LLM lệch format.
    """
    cleaned = _clean_output(raw)
    title = ""
    note = ""
    found_title = False
    for line in cleaned.splitlines():
        m = _TITLE_LINE.match(line)
        if m:
            title = m.group(1).strip()
            found_title = True
            continue
        m = _NOTE_LINE.match(line)
        if m:
            note = m.group(1).strip()
    if not found_title:
        return cleaned.strip(), ""
    return title, note


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


def load_glossary_dict(cfg: TranslateConfig) -> dict[str, str]:
    """Gộp glossary inline trong config + 2 file names/vietphrase đang trỏ tới.

    Dùng chung cho CLITranslator (dịch chương) và glossary_ai (gợi ý/rewrite).
    """
    glossary: dict[str, str] = dict(cfg.glossary)
    for path in (cfg.glossary_files.names, cfg.glossary_files.vietphrase):
        if not path:
            continue
        p = Path(path)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            parsed = parse_glossary_line(line)
            if parsed:
                zh, vi, _note = parsed
                glossary[zh] = vi
    return glossary


class Translator(Protocol):
    def translate(self, text: str) -> str: ...
    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]: ...


class NoopTranslator:
    def translate(self, text: str) -> str:
        return text

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        return text, ""


def _split_into_chunks(text: str, max_chars: int, overlap_paragraphs: int) -> list[list[str]]:
    """Chia text thành các nhóm đoạn văn (paragraph) <= max_chars ký tự.

    Mỗi chunk (trừ chunk đầu) lặp lại `overlap_paragraphs` đoạn cuối của chunk
    trước để LLM có ngữ cảnh nối câu, tránh lệch văn phong/ngôi xưng giữa các
    chunk khi chương quá dài phải tách nhỏ.
    """
    paragraphs = text.split("\n")
    chunks: list[list[str]] = []
    buf: list[str] = []
    buf_len = 0
    for para in paragraphs:
        if buf and buf_len + len(para) + 1 > max_chars:
            chunks.append(buf)
            buf = list(buf[-overlap_paragraphs:]) if overlap_paragraphs > 0 else []
            buf_len = sum(len(p) + 1 for p in buf)
        buf.append(para)
        buf_len += len(para) + 1
    if buf:
        chunks.append(buf)
    return chunks


class CLITranslator:
    # Áp dụng khi translate.chunk.max_chars = 0 (mặc định) — tự chia chương dài
    # để tránh prompt quá tải/timeout CLI dịch.
    DEFAULT_MAX_CHARS = 6000

    def __init__(self, cfg: TranslateConfig, log: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.cli = cfg.cli
        self.glossary = load_glossary_dict(cfg)
        self._argv = cli_runner.build_argv(cfg.cli)
        self.log = log or (lambda _: None)

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

    def _build_fixup_prompt(self, text: str) -> str:
        return self._build_prompt(text) + (
            "\n\nLƯU Ý QUAN TRỌNG: Bản dịch trước đó còn sót chữ Hán chưa được dịch. "
            "Hãy dịch toàn bộ văn bản gốc sang tiếng Việt, không để sót lại bất kỳ chữ Hán nào."
        )

    def _build_title_prompt(self, text: str, kind: str) -> str:
        return self.cli.title_prompt_template.format(
            text=text,
            kind=kind,
            glossary=_format_glossary(self.glossary),
        )

    def _run_cli_with_retry(self, prompt: str) -> str:
        attempts = max(1, int(self.cfg.retry.attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return cli_runner.run_cli(self.cli, prompt, argv=self._argv)
            except FileNotFoundError as e:
                hint = ""
                if "opencode" in self._argv[0]:
                    hint = " Cài đặt: https://opencode.ai/docs/go/ — chạy 'opencode auth' sau khi đăng ký."
                raise RuntimeError(
                    f"Không tìm thấy lệnh CLI: {self._argv[0]!r}."
                    f"{hint}"
                ) from e
            except subprocess.TimeoutExpired:
                last_error = RuntimeError(f"CLI dịch quá thời gian ({self.cli.timeout_seconds}s).")
            except RuntimeError as e:
                last_error = e

            if attempt < attempts and self.cfg.retry.delay_seconds > 0:
                time.sleep(self.cfg.retry.delay_seconds)

        assert last_error is not None
        raise last_error

    def _translate_chunk(self, chunk_text: str) -> str:
        """Dịch một đoạn và thử lại nếu kết quả còn sót chữ Hán chưa dịch."""
        out = self._run_cli_with_retry(self._build_prompt(chunk_text))
        cleaned = _clean_output(out)
        for _ in range(_RESIDUAL_HAN_RETRIES):
            residual = len(_HAN_RE.findall(cleaned))
            if residual == 0:
                break
            out = self._run_cli_with_retry(self._build_fixup_prompt(chunk_text))
            retried = _clean_output(out)
            if len(_HAN_RE.findall(retried)) < residual:
                cleaned = retried
            else:
                break
        return cleaned

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        max_chars = self.cfg.chunk.max_chars or self.DEFAULT_MAX_CHARS
        if len(text) <= max_chars:
            return _apply_glossary(self._translate_chunk(text), self.glossary)

        overlap = max(0, self.cfg.chunk.overlap_paragraphs)
        chunks = _split_into_chunks(text, max_chars, overlap)
        self.log(f"  … chia {len(chunks)} đoạn ({len(text)} ký tự, ≤{max_chars}/đoạn, overlap={overlap})")
        pieces: list[str] = []
        for i, chunk_paragraphs in enumerate(chunks):
            chunk_text = "\n".join(chunk_paragraphs)
            self.log(f"  … đoạn {i+1}/{len(chunks)} ({len(chunk_text)} ký tự)")
            cleaned = self._translate_chunk(chunk_text)
            if i > 0 and overlap > 0:
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[overlap:]) if len(lines) > overlap else cleaned
            pieces.append(cleaned)
        return _apply_glossary("\n".join(pieces), self.glossary)

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        if not text.strip():
            return text, ""
        out = self._run_cli_with_retry(self._build_title_prompt(text, kind))
        title, note = _parse_title_response(out)
        return _apply_glossary(title, self.glossary), note


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

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        return self.translate(text), ""


def make_translator(cfg: TranslateConfig, log: Callable[[str], None] | None = None) -> Translator:
    kind = (cfg.type or "none").lower()
    if kind == "cli":
        return CLITranslator(cfg, log=log)
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

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        out = self.inner.translate_title(text, kind)
        if self.delay > 0:
            time.sleep(self.delay)
        return out
