"""Các bộ dịch Trung -> Việt (pluggable).

- OpenAITranslator: gọi AI qua HTTP theo chuẩn OpenAI-Compatible (OpenAI,
  OpenRouter, Ollama, LM Studio, vLLM, llama.cpp server, ...).
- GoogleTranslator: Google Translate miễn phí qua deep-translator (chunk 4500 ký tự).
- NoopTranslator: trả nguyên văn (dùng để test pipeline mà không tốn chi phí).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Protocol

from . import openai_client
from .config import LibreTranslateConfig, TranslateConfig
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

    Dùng chung cho OpenAITranslator (dịch chương) và glossary_ai (gợi ý/rewrite).
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
    # Mỗi translate() chia văn bản thành nhiều chunk; triển khai có thể nhận
    # kwarg tùy chọn `on_chunk(index, total, chunk_text, is_final)` để stream
    # tiến độ (xem `translate-chunk-streaming` spec). Gọi không truyền kwarg
    # vẫn hoạt động như cũ — tương thích ngược hoàn toàn.
    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str: ...
    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]: ...


class NoopTranslator:
    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str:
        if on_chunk is not None:
            on_chunk(1, 1, text, True)
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


class OpenAITranslator:
    # Áp dụng khi translate.chunk.max_chars = 0 (mặc định) — tự chia chương dài
    # để tránh prompt quá tải/timeout request AI.
    DEFAULT_MAX_CHARS = 6000

    def __init__(self, cfg: TranslateConfig, log: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.openai = cfg.openai
        self.glossary = load_glossary_dict(cfg)
        self.log = log or (lambda _: None)

    def _build_prompt(self, text: str) -> str:
        return self.openai.prompt_template.format(
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
        return self.openai.title_prompt_template.format(
            text=text,
            kind=kind,
            glossary=_format_glossary(self.glossary),
        )

    def _run_chat_with_retry(self, prompt: str) -> str:
        attempts = max(1, int(self.cfg.retry.attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return openai_client.run_chat(self.openai, prompt)
            except RuntimeError as e:
                last_error = e

            if attempt < attempts and self.cfg.retry.delay_seconds > 0:
                time.sleep(self.cfg.retry.delay_seconds)

        assert last_error is not None
        raise last_error

    def _translate_chunk(self, chunk_text: str) -> str:
        """Dịch một đoạn và thử lại nếu kết quả còn sót chữ Hán chưa dịch."""
        out = self._run_chat_with_retry(self._build_prompt(chunk_text))
        cleaned = _clean_output(out)
        for _ in range(_RESIDUAL_HAN_RETRIES):
            residual = len(_HAN_RE.findall(cleaned))
            if residual == 0:
                break
            out = self._run_chat_with_retry(self._build_fixup_prompt(chunk_text))
            retried = _clean_output(out)
            if len(_HAN_RE.findall(retried)) < residual:
                cleaned = retried
            else:
                break
        return cleaned

    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str:
        if not text.strip():
            return text
        max_chars = self.cfg.chunk.max_chars or self.DEFAULT_MAX_CHARS
        if len(text) <= max_chars:
            cleaned = self._translate_chunk(text)
            if on_chunk is not None:
                on_chunk(1, 1, cleaned, True)
            return _apply_glossary(cleaned, self.glossary)

        overlap = max(0, self.cfg.chunk.overlap_paragraphs)
        chunks = _split_into_chunks(text, max_chars, overlap)
        self.log(f"  … chia {len(chunks)} đoạn ({len(text)} ký tự, ≤{max_chars}/đoạn, overlap={overlap})")
        total = len(chunks)
        pieces: list[str] = []
        for i, chunk_paragraphs in enumerate(chunks):
            chunk_text = "\n".join(chunk_paragraphs)
            self.log(f"  … đoạn {i+1}/{total} ({len(chunk_text)} ký tự)")
            cleaned = self._translate_chunk(chunk_text)
            if i > 0 and overlap > 0:
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[overlap:]) if len(lines) > overlap else cleaned
            pieces.append(cleaned)
            if on_chunk is not None:
                on_chunk(i + 1, total, cleaned, i + 1 == total)
        return _apply_glossary("\n".join(pieces), self.glossary)

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        if not text.strip():
            return text, ""
        out = self._run_chat_with_retry(self._build_title_prompt(text, kind))
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

    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str:
        if not text.strip():
            return text
        chunks = list(self._chunks(text))
        total = len(chunks)
        parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            part = self._engine.translate(chunk) or ""
            parts.append(part)
            if on_chunk is not None:
                on_chunk(i, total, part, i == total)
        return _apply_glossary("\n".join(parts), self.glossary)

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        return self.translate(text), ""


class HachimiMTTranslator:
    """Dịch Trung→Việt cục bộ bằng NMT (CTranslate2 + SentencePiece).

    Wrapper xung quanh HachimiTranslator từ novel2epub.hachimimt, cung cấp
    giao diện Translator (translate/translate_title/translate_titles) tương
    thích với các backend khác trong novel2epub.

    Glossary áp dụng bằng string-replace sau dịch (model NMT không nhận
    "instruction" như LLM).
    """

    def __init__(self, cfg: TranslateConfig, log: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.hmt = cfg.hachimimt
        self.glossary = load_glossary_dict(cfg)
        self.log = log or (lambda _: None)
        self._inner: HachimiTranslator | None = None

    def _ensure_loaded(self):
        if self._inner is not None:
            return
        from .hachimimt.translator import HachimiTranslator, Backend

        self._inner = HachimiTranslator(profile=None)
        self._inner.load(self.hmt.model_key, backend=Backend.CT2)

    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str:
        if not text.strip():
            if on_chunk is not None:
                on_chunk(1, 1, text, True)
            return text
        self._ensure_loaded()
        assert self._inner is not None
        translated = self._inner.translate_text(text, beam_size=self.hmt.beam_size, chunk_mode=self.hmt.chunk_mode)
        out = _apply_glossary(translated, self.glossary)
        if on_chunk is not None:
            on_chunk(1, 1, out, True)
        return out

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        self._ensure_loaded()
        assert self._inner is not None
        if not text.strip():
            return text, ""
        translated = self._inner.translate_chunk(text.strip(), beam_size=self.hmt.beam_size)
        return _apply_glossary(translated, self.glossary), ""

    def translate_titles(self, titles: list[str]) -> list[str]:
        self._ensure_loaded()
        assert self._inner is not None
        result: list[str] = []
        for t in titles:
            if not t.strip():
                result.append(t)
            else:
                translated = self._inner.translate_chunk(t.strip(), beam_size=self.hmt.beam_size)
                result.append(_apply_glossary(translated, self.glossary))
        return result


class LibreTranslateTranslator:
    """Dịch bằng LibreTranslate API (self-hosted).

    Gọi `POST /translate` của LibreTranslate server. Phù hợp cho dịch metadata
    ngắn (title, author, description) — nhanh, không tốn token LLM.
    """

    def __init__(self, cfg: TranslateConfig):
        self.cfg = cfg
        self.lt = cfg.libretranslate
        self.glossary = _merge_glossaries(cfg.glossary)

    def _translate_text(self, text: str) -> str:
        import requests

        url = f"{self.lt.base_url.rstrip('/')}/translate"
        payload: dict[str, Any] = {
            "q": text,
            "source": self.lt.source_language,
            "target": self.lt.target_language,
            "format": "text",
        }
        headers: dict[str, str] = {}
        if self.lt.api_key:
            headers["Authorization"] = f"Bearer {self.lt.api_key}"

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("translatedText", "")

    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str:
        if not text.strip():
            if on_chunk is not None:
                on_chunk(1, 1, text, True)
            return text
        translated = self._translate_text(text)
        out = _apply_glossary(translated, self.glossary)
        if on_chunk is not None:
            on_chunk(1, 1, out, True)
        return out

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        if not text.strip():
            return text, ""
        translated = self._translate_text(text)
        return _apply_glossary(translated, self.glossary), ""


def make_translator(cfg: TranslateConfig, log: Callable[[str], None] | None = None) -> Translator:
    kind = (cfg.type or "none").lower()
    if kind == "openai":
        return OpenAITranslator(cfg, log=log)
    if kind == "google":
        return GoogleTranslator(cfg)
    if kind in ("hachimimt", "moxhimt"):
        return HachimiMTTranslator(cfg, log=log)
    if kind == "libretranslate":
        return LibreTranslateTranslator(cfg)
    if kind == "none":
        return NoopTranslator()
    raise ValueError(f"translate.type không hợp lệ: {cfg.type!r} (openai|google|hachimimt|none)")


class RateLimited:
    """Bọc một translator để chèn delay giữa các lần gọi."""

    def __init__(self, inner: Translator, delay_seconds: float):
        self.inner = inner
        self.delay = delay_seconds

    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
    ) -> str:
        out = self.inner.translate(text, on_chunk=on_chunk)
        if self.delay > 0:
            time.sleep(self.delay)
        return out

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        out = self.inner.translate_title(text, kind)
        if self.delay > 0:
            time.sleep(self.delay)
        return out

    def translate_titles(self, titles: list[str]) -> list[str]:
        out = self.inner.translate_titles(titles)
        if self.delay > 0 and len(titles) > 0:
            time.sleep(self.delay)
        return out
