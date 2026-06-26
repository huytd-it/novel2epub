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


# Dấu kết câu Hán + Latin, dùng để chia câu khi một đoạn vượt giới hạn token.
_SENTENCE_RE = re.compile(r"[^。！？…!?.\n]*[。！？…!?.]+|[^。！？…!?.\n]+")


def _split_into_sentences(line: str) -> list[str]:
    """Chia MỘT dòng (không chứa \\n) thành các câu, giữ dấu kết câu.

    Dùng làm bước fallback cho MoxhiMT khi một đoạn văn quá dài so với giới hạn
    512 token của model. Trả list rỗng nếu dòng chỉ có khoảng trắng.
    """
    return [m.group(0) for m in _SENTENCE_RE.finditer(line) if m.group(0).strip()]


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Cắt cứng theo ký tự khi một câu vẫn dài hơn ngưỡng an toàn của model.

    Tránh để model tự truncate âm thầm (mất nghĩa cuối câu). max_chars luôn
    >= 1 nên hàm này kết thúc.
    """
    step = max(1, max_chars)
    return [text[i:i + step] for i in range(0, len(text), step)]


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


class MoxhiMTTranslator:
    """Dịch Trung→Việt cục bộ bằng model MoxhiMT (CTranslate2 + SentencePiece).

    Khác `CLITranslator` (LLM theo prompt) và `GoogleTranslator` (API mạng),
    đây là model NMT seq2seq chạy offline. Tự tải model từ Hugging Face Hub về
    cache ở lần dùng đầu (lazy), tái sử dụng các lần sau.

    Chia chunk: mặc định `chunk_mode="paragraph"` — gom trọn từng dòng/đoạn của
    bản gốc cho model giữ ngữ cảnh liên câu (cẩn thận nhất). Khi một đoạn vượt
    ngân sách token an toàn của `max_length`, fallback chia câu; câu vẫn quá dài
    thì cắt cứng theo ký tự. Glossary áp dụng bằng string-replace sau dịch
    (model không nhận "instruction" như LLM).
    """

    def __init__(self, cfg: TranslateConfig, log: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.mox = cfg.moxhimt
        self.glossary = load_glossary_dict(cfg)
        self.log = log or (lambda _: None)
        # Kiểm tra package ngay khi khởi tạo (báo lỗi sớm, rõ ràng). Việc tải +
        # load model để lazy tới lần dịch đầu (xem `_ensure_loaded`).
        self._import_ct2()
        self._import_spm()
        self._import_hub()
        self._ct2 = None
        self._sp = None

    # ----- lazy import (tránh ép cài nặng cho người không dùng backend này) -----
    @staticmethod
    def _import_ct2():
        try:
            import ctranslate2
            return ctranslate2
        except ImportError as e:  # pragma: no cover - phụ thuộc môi trường
            raise ImportError(
                "Chưa cài ctranslate2 (cần cho translate.type=moxhimt). "
                "Chạy: pip install ctranslate2 sentencepiece huggingface_hub"
            ) from e

    @staticmethod
    def _import_spm():
        try:
            import sentencepiece
            return sentencepiece
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài sentencepiece (cần cho translate.type=moxhimt). "
                "Chạy: pip install ctranslate2 sentencepiece huggingface_hub"
            ) from e

    @staticmethod
    def _import_hub():
        try:
            import huggingface_hub
            return huggingface_hub
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài huggingface_hub (cần cho translate.type=moxhimt). "
                "Chạy: pip install ctranslate2 sentencepiece huggingface_hub"
            ) from e

    # ----- tải & định vị model -----
    def _download_model(self) -> Path:
        hub = self._import_hub()
        try:
            local = hub.snapshot_download(self.mox.model_id, cache_dir=(self.mox.cache_dir or None))
        except Exception as e:  # noqa: BLE001 - gom mọi lỗi mạng/HTTP thành thông báo rõ
            raise RuntimeError(
                f"Không tải được model {self.mox.model_id!r} từ Hugging Face Hub: {e}. "
                "Kiểm tra kết nối mạng, hoặc đặt biến môi trường HF_HOME / "
                "translate.moxhimt.cache_dir tới thư mục cache hợp lệ."
            ) from e
        return Path(local)

    def _locate_model_files(self, root: Path) -> tuple[Path, Path]:
        """Tìm thư mục model CTranslate2 (chứa model.bin) + file SentencePiece.

        Robust với nhiều layout repo trong họ model (ưu tiên bản INT8 `ct2-int8/`
        cho tốc độ CPU). Raise RuntimeError rõ ràng nếu repo không đúng định dạng
        (vd LoRA adapter — không được backend này hỗ trợ).
        """
        ct2_dirs = [p.parent for p in root.rglob("model.bin")]
        if not ct2_dirs:
            raise RuntimeError(
                f"Không tìm thấy model CTranslate2 (model.bin) trong {root}. "
                f"model_id {self.mox.model_id!r} có thể không phải định dạng CTranslate2 "
                "(backend moxhimt chỉ hỗ trợ model SentencePiece + CTranslate2 Marian, "
                "không hỗ trợ LoRA adapter)."
            )

        def _ct2_rank(p: Path) -> tuple:
            name = p.name.lower()
            return (0 if "int8" in name else 1, 0 if "ct2" in name else 1, len(str(p)))

        ct2_dir = sorted(ct2_dirs, key=_ct2_rank)[0]

        spm_files = [p for p in (*root.rglob("*.spm"), *root.rglob("*.model")) if p.is_file()]
        if not spm_files:
            raise RuntimeError(
                f"Không tìm thấy SentencePiece tokenizer (*.spm/*.model) trong {root}. "
                f"model_id {self.mox.model_id!r} thiếu file tokenizer."
            )

        def _spm_rank(p: Path) -> tuple:
            name = p.name.lower()
            if "source" in name or "src" in name:
                score = 0
            elif "shared" in name or "joint" in name or "spm" in name:
                score = 1
            elif name.endswith(".model"):
                score = 2
            else:
                score = 3
            return (score, len(str(p)))

        spm_path = sorted(spm_files, key=_spm_rank)[0]
        return ct2_dir, spm_path

    def _ensure_loaded(self) -> None:
        if self._ct2 is not None:
            return
        ct2 = self._import_ct2()
        spm = self._import_spm()
        model_dir = self._download_model()
        ct2_dir, spm_path = self._locate_model_files(model_dir)
        self.log(f"  … nạp model MoxhiMT {self.mox.model_id} (ct2={ct2_dir.name}, spm={spm_path.name})")
        try:
            self._ct2 = ct2.Translator(str(ct2_dir), device=self.mox.device)
            self._sp = spm.SentencePieceProcessor(model_file=str(spm_path))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Không nạp được model MoxhiMT từ {model_dir}: {e}."
            ) from e

    # ----- chia chunk + dịch -----
    def _token_budget(self) -> int:
        # Chừa biên cho token đặc biệt + bản dịch VI thường dài hơn nguồn ZH.
        return max(16, int(self.mox.max_length) - 32)

    def _ntokens(self, text: str) -> int:
        return len(self._sp.encode(text, out_type=str))

    def _translate_texts(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        batch = [self._sp.encode(t, out_type=str) for t in texts]
        results = self._ct2.translate_batch(
            batch,
            beam_size=int(self.mox.beam_size),
            max_decoding_length=int(self.mox.max_length),
        )
        return [self._sp.decode(r.hypotheses[0]) for r in results]

    def _translate_line(self, line: str) -> str:
        """Dịch một dòng (đoạn văn). Gom cả đoạn nếu vừa token; nếu không thì
        fallback chia câu, câu quá dài thì cắt cứng theo ký tự."""
        budget = self._token_budget()
        if self.mox.chunk_mode != "sentence" and self._ntokens(line) <= budget:
            return self._translate_texts([line])[0]

        sentences = _split_into_sentences(line) or [line]
        segments: list[str] = []
        for sent in sentences:
            if self._ntokens(sent) <= budget:
                segments.append(sent)
            else:
                segments.extend(_hard_split(sent, budget))
        outs = self._translate_texts(segments)
        return " ".join(o.strip() for o in outs if o.strip())

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
        # Mỗi dòng/đoạn gốc = 1 đơn vị tiến độ; on_chunk được pipeline append với
        # "\n" nên giữ đúng cấu trúc dòng. Glossary áp dụng NGAY trên từng dòng
        # để bản lưu (stream qua on_chunk) cũng có glossary, không chỉ giá trị
        # trả về.
        lines = text.split("\n")
        total = len(lines)
        out_lines: list[str] = []
        for i, line in enumerate(lines):
            if line.strip():
                out = _apply_glossary(self._translate_line(line), self.glossary)
            else:
                out = line  # giữ nguyên dòng trống
            out_lines.append(out)
            if on_chunk is not None:
                on_chunk(i + 1, total, out, i + 1 == total)
        return "\n".join(out_lines)

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        if not text.strip():
            return text, ""
        self._ensure_loaded()
        out = _apply_glossary(self._translate_line(text.strip()), self.glossary)
        return out, ""


def make_translator(cfg: TranslateConfig, log: Callable[[str], None] | None = None) -> Translator:
    kind = (cfg.type or "none").lower()
    if kind == "cli":
        return CLITranslator(cfg, log=log)
    if kind == "google":
        return GoogleTranslator(cfg)
    if kind == "moxhimt":
        return MoxhiMTTranslator(cfg, log=log)
    if kind == "none":
        return NoopTranslator()
    raise ValueError(f"translate.type không hợp lệ: {cfg.type!r} (cli|google|moxhimt|none)")


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
