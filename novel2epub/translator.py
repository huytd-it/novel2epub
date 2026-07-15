"""Các bộ dịch Trung -> Việt (pluggable).

- OpenAITranslator: gọi AI qua HTTP theo chuẩn OpenAI-Compatible (OpenAI,
  OpenRouter, Ollama, LM Studio, vLLM, llama.cpp server, ...).
- GoogleTranslator: Google Translate miễn phí qua deep-translator (chunk 4500 ký tự).
- NoopTranslator: trả nguyên văn (dùng để test pipeline mà không tốn chi phí).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from . import openai_client
from .config import LibreTranslateConfig, TranslateConfig
from .storage import Storage, parse_glossary_line

# Một số mẫu "lời mở đầu" mà LLM hay tự thêm dù đã bảo đừng.
_PREAMBLE = re.compile(
    r"^\s*(đây là|sau đây là|dưới đây là|bản dịch).{0,40}:\s*$",
    re.IGNORECASE,
)

_HAN_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")

# Số lần thử lại tối đa khi bản dịch còn sót chữ Hán chưa dịch.
_RESIDUAL_HAN_RETRIES = 2

# Marker để AI đánh dấu phần glossary trong response dịch.
_GLOSSARY_MARKER = re.compile(r"^===GLOSSARY===\s*$", re.MULTILINE)
# Bullet `- `/`* `/`+ ` AI hay tự thêm trước mỗi dòng glossary.
_GLOSSARY_BULLET_RE = re.compile(r"^[-*+]\s+")


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


_TITLES_BATCH_LINE = re.compile(r"^\s*(\d+)\s*[.\):]\s*(.+?)\s*$")


def _parse_titles_batch_response(raw: str, count: int) -> dict[int, str]:
    """Tách các dòng '<số>. <bản dịch>' từ phản hồi dịch hàng loạt tiêu đề.

    Trả dict {1-based index: title}. Bỏ qua dòng không khớp định dạng hoặc
    số thứ tự ngoài phạm vi — caller tự fallback dịch riêng lẻ cho các
    tiêu đề bị thiếu.
    """
    cleaned = _clean_output(raw)
    result: dict[int, str] = {}
    for line in cleaned.splitlines():
        m = _TITLES_BATCH_LINE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        if 1 <= idx <= count:
            result[idx] = m.group(2).strip()
    return result


def _format_glossary(glossary: dict[str, str]) -> str:
    if not glossary:
        return ""
    lines = "\n".join(f"{zh} = {vi}" for zh, vi in glossary.items())
    return "Bảng thuật ngữ bắt buộc dùng nhất quán:\n" + lines


def _filter_glossary(
    glossary: dict[str, str], zh_text: str = "", vi_text: str = ""
) -> dict[str, str]:
    """Trả dict MỚI chỉ gồm entry có zh xuất hiện trong zh_text hoặc vi trong vi_text.

    Dùng để rút gọn khối glossary nhét vào prompt AI theo đúng đoạn đang xử lý
    (tiết kiệm token); KHÔNG dùng cho _apply_glossary hậu xử lý — bước đó luôn
    chạy trên toàn bộ glossary.
    """
    return {
        zh: vi
        for zh, vi in glossary.items()
        if (zh_text and zh and zh in zh_text) or (vi_text and vi and vi in vi_text)
    }


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


def load_glossary_dict(cfg: TranslateConfig, storage: "Storage | None" = None) -> dict[str, str]:
    """Gộp glossary inline trong config + 2 list names/vietphrase.

    Dùng chung cho OpenAITranslator (dịch chương) và glossary_ai (gợi ý/rewrite).

    Khi caller có sẵn `storage` (pipeline/web routes) thì ĐỌC TRỰC TIẾP 2 list
    chuẩn từ DB — nguồn mà auto-glossary + trang Glossary đang ghi. Path trong
    `cfg.glossary_files` chỉ còn dùng cho file NGOÀI user tự trỏ (tồn tại thật
    trên đĩa). Thứ tự merge: inline cfg.glossary < file ngoài < DB (DB thắng —
    tránh file legacy thời trước migration SQLite che mất entry mới trong DB).
    Khi trùng source giữa 2 list, `names.txt` (list chuẩn duy nhất sau khi bỏ
    phân loại) thắng `vietphrase.txt` (dữ liệu cũ chưa consolidate).

    Khi không có `storage` (backward-compat): giữ hành vi cũ — đọc file nếu
    tồn tại, ngược lại suy ngược data_dir/slug từ quy ước path
    `data_dir/<slug>/glossary/<name>.txt` để đọc DB.
    """
    glossary: dict[str, str] = dict(cfg.glossary)
    # vietphrase đọc TRƯỚC, names đọc SAU → names.txt thắng khi trùng source.
    for path in (cfg.glossary_files.vietphrase, cfg.glossary_files.names):
        if not path:
            continue
        p = Path(path)
        if p.exists():
            # File thật trên đĩa: file ngoài user tự trỏ, hoặc file legacy
            # thời trước migration SQLite. Đọc trực tiếp; entry DB (đọc bên
            # dưới khi có storage) sẽ ghi đè nếu trùng source.
            lines = p.read_text(encoding="utf-8").splitlines()
        elif storage is None:
            # Đường dẫn mặc định do config.py suy ra (data_dir/<slug>/glossary/
            # <name>.txt) — glossary nay sống trong DB qua Storage, không còn
            # file thật ở đây. Suy ngược slug/data_dir từ đúng quy ước đó.
            try:
                data_dir = p.parent.parent.parent
                slug = p.parent.parent.name
                entries = Storage(data_dir, slug).read_glossary_entries(p.name)
            except Exception:
                continue
            lines = [f"{s} = {t}" + (f" | {n}" if n else "") for s, t, n in entries]
        else:
            continue  # có storage: DB đọc tập trung bên dưới, không suy path
        for line in lines:
            parsed = parse_glossary_line(line)
            if parsed:
                zh, vi, _note = parsed
                glossary[zh] = vi
    if storage is not None:
        for list_name in ("vietphrase.txt", "names.txt"):
            try:
                entries = storage.read_glossary_entries(list_name)
            except Exception:
                continue
            for source, target, _note in entries:
                if source and target:
                    glossary[source] = target
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
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str: ...
    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]: ...


class NoopTranslator:
    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
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


def _fire_glossary(
    on_glossary: Callable[[list[dict]], None] | None,
    glossary_accum: list[dict],
) -> None:
    """Deduplicate theo source rồi gọi callback glossary nếu có entry."""
    if not on_glossary or not glossary_accum:
        return
    merged: dict[str, dict] = {}
    for entry in glossary_accum:
        merged[entry["source"]] = entry
    on_glossary(list(merged.values()))


class OpenAITranslator:
    # Áp dụng khi translate.chunk.max_chars = 0 (mặc định) — tự chia chương dài
    # để tránh prompt quá tải/timeout request AI.
    DEFAULT_MAX_CHARS = 6000

    # Số tiêu đề tối đa gộp vào 1 lần gọi khi dịch hàng loạt (translate_titles).
    # Tiêu đề ngắn nên gộp được nhiều, nhưng vẫn giới hạn để tránh prompt/response
    # quá dài (timeout, model cắt bớt output) — chia thành nhiều batch nếu cần.
    TITLES_BATCH_SIZE = 50

    def __init__(self, cfg: TranslateConfig, log: Callable[[str], None] | None = None, storage: "Storage | None" = None):
        self.cfg = cfg
        self.openai = cfg.openai
        self.glossary = load_glossary_dict(cfg, storage)
        self.log = log or (lambda _: None)
        self._glossary_lock = threading.Lock()
        self._auto_glossary_conflicts: list[dict] = []
        self._last_chapter_meta: dict[str, Any] = {}

    def extend_glossary(
        self,
        new_entries: dict[str, str],
        storage: "Storage",
    ) -> dict:
        """Merge new_entries vào in-memory glossary + ghi DB. Thread-safe.

        Không còn phân loại names/vietphrase — mọi entry mới ghi vào list
        chuẩn duy nhất `names.txt`. Trả {'added': [(source, target), ...],
        'conflicts': [{source, existing, new}, ...]}. Existing wins khi conflict.
        """
        added, conflicts = [], []
        with self._glossary_lock:
            for source, new_target in new_entries.items():
                if not source or not new_target:
                    continue
                existing = self.glossary.get(source)
                if existing is None:
                    self.glossary[source] = new_target
                    storage.append_glossary_line("names.txt", f"{source} = {new_target}")
                    added.append((source, new_target))
                elif existing == new_target:
                    continue
                else:
                    c = {
                        "source": source,
                        "existing": existing,
                        "new": new_target,
                    }
                    conflicts.append(c)
                    self._auto_glossary_conflicts.append(c)
        return {"added": added, "conflicts": conflicts}

    def drain_conflicts(self) -> list[dict]:
        with self._glossary_lock:
            out = list(self._auto_glossary_conflicts)
            self._auto_glossary_conflicts.clear()
            return out

    def _glossary_for_prompt(self, zh_text: str, vi_text: str = "") -> dict[str, str]:
        """Bản glossary để nhét vào prompt: snapshot dưới lock (an toàn với
        extend_glossary chạy song song), lọc theo text đang xử lý nếu
        cfg.glossary_filter bật. Không bao giờ mutate self.glossary."""
        with self._glossary_lock:
            snapshot = dict(self.glossary)
        if not self.cfg.glossary_filter:
            return snapshot
        return _filter_glossary(snapshot, zh_text=zh_text, vi_text=vi_text)

    def _build_prompt(self, text: str) -> str:
        prompt = self.openai.prompt_template.format(
            text=text,
            glossary=_format_glossary(self._glossary_for_prompt(text)),
            tone=self.cfg.style.tone,
            pronoun_policy=self.cfg.style.pronoun_policy,
            keep_paragraphs=self.cfg.style.keep_paragraphs,
            title_mode=self.cfg.style.title_mode,
            han_viet_level=self.cfg.style.han_viet_level,
        )
        if self.cfg.auto_glossary:
            prompt += (
                "\n\nSAU KHI DỊCH XONG, thêm một dòng ===GLOSSARY=== rồi liệt kê "
                "các mục glossary MỚI, mỗi mục MỘT DÒNG theo đúng dạng:\n"
                "<Hán> = <Việt>\n"
                "Glossary là bảng ĐỒNG BỘ cách dịch xuyên suốt truyện, KHÔNG phải "
                "từ điển — thà bỏ sót còn hơn đưa nhầm từ thông thường.\n"
                "CHỈ đưa vào: tên riêng (nhân vật, địa danh, môn phái/tổ chức, "
                "chức danh) và thuật ngữ ĐẶC THÙ lặp lại nhiều lần (công pháp, "
                "chiêu thức, cảnh giới, pháp bảo, đan dược, chủng tộc, hệ thống "
                "sức mạnh, biệt danh cố định).\n"
                "TUYỆT ĐỐI KHÔNG đưa vào: từ đời thường (đồ ăn, mua sắm, động tác, "
                "cảm xúc, nghề nghiệp, vật dụng phổ thông); thành ngữ/khẩu ngữ/tiếng "
                "lóng dịch thoát ý; từ hiện đại phổ thông; từ độc giả Việt hiểu ngay "
                "hoặc chỉ xuất hiện một lần.\n"
                "Không giải thích, không đánh số, không JSON. Nếu không có mục nào "
                "đạt tiêu chí: chỉ in đúng dòng ===GLOSSARY=== và không thêm gì sau đó."
            )
        return prompt

    def _build_fixup_prompt(self, text: str) -> str:
        return self._build_prompt(text) + (
            "\n\nCẢNH BÁO NGHIÊM TRỌNG: Bản dịch trước đó còn chứa chữ Hán chưa được dịch. "
            "Đây là lỗi KHÔNG THỂ CHẤP NHẬN. "
            "Hãy dịch TOÀN BỘ văn bản gốc sang tiếng Việt thuần túy. "
            "KHÔNG được giữ lại bất kỳ ký tự Trung Quốc nào. "
            "KHÔNG được dùng định dạng 'từ gốc (dịch nghĩa)' — "
            "chỉ trả về tiếng Việt 100%."
        )

    def _split_response(self, raw: str) -> tuple[str, list[dict] | None]:
        """Tách phần dịch và glossary sau ===GLOSSARY===.

        Format chuẩn: mỗi dòng `Hán = Việt` (parse bằng parse_glossary_line,
        chấp nhận bullet `- `/`* ` đầu dòng, bỏ dòng prose/placeholder).
        Back-compat: nếu phần glossary bắt đầu bằng `[`/`{` (prompt cũ dạng
        JSON còn pin trong config user) → parse JSON như trước.
        """
        parts = _GLOSSARY_MARKER.split(raw, maxsplit=1)
        if len(parts) < 2:
            return raw, None
        translation = parts[0].strip()
        glossary_text = parts[1].strip()
        if not glossary_text:
            return translation, None
        if glossary_text[0] in "[{":
            try:
                data = json.loads(glossary_text)
                if isinstance(data, list):
                    valid = [
                        e for e in data
                        if isinstance(e, dict) and e.get("source") and e.get("suggested")
                    ]
                    return translation, valid if valid else None
            except (json.JSONDecodeError, ValueError):
                pass
            return translation, None
        entries: list[dict] = []
        for line in glossary_text.splitlines():
            line = _GLOSSARY_BULLET_RE.sub("", line.strip())
            parsed = parse_glossary_line(line)
            if not parsed:
                continue  # dòng prose/heading — bỏ qua
            source, target, _note = parsed
            if "<" in source or ">" in source or "<" in target or ">" in target:
                continue  # placeholder `<Hán> = <Việt>` bị AI echo lại
            entries.append({"source": source, "suggested": target})
        return translation, entries if entries else None

    def _build_title_prompt(self, text: str, kind: str) -> str:
        return self.openai.title_prompt_template.format(
            text=text,
            kind=kind,
            glossary=_format_glossary(self._glossary_for_prompt(text)),
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

    def _run_chat_with_retry_meta(
        self, prompt: str
    ) -> tuple[str, dict[str, Any]]:
        """Giống `_run_chat_with_retry` nhưng trả `(content, meta)` để capture
        OmniRoute cost/tokens/latency headers. Vẫn raise sau khi hết retry.

        Backward compat: nếu `openai_client.run_chat` được mock nhưng
        `run_chat_with_meta` thì không (test cũ), nhận về str → wrap thành
        (str, {}). Ngược lại, nếu cả 2 đều mock thì dùng `run_chat_with_meta`.
        """
        attempts = max(1, int(self.cfg.retry.attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = openai_client.run_chat_with_meta(self.openai, prompt)
                if isinstance(result, tuple) and len(result) == 2:
                    return result  # type: ignore[return-value]
                # Mock chỉ trả str (tương thích test cũ) → wrap meta rỗng
                return result, {}  # type: ignore[return-value]
            except RuntimeError as e:
                last_error = e

            if attempt < attempts and self.cfg.retry.delay_seconds > 0:
                time.sleep(self.cfg.retry.delay_seconds)

        assert last_error is not None
        raise last_error

    def _merge_meta(self, target: dict[str, Any], src: dict[str, Any]) -> None:
        """Cộng dồn cost/tokens/latency từ `src` vào `target` (in-place)."""
        if not src:
            return
        for k in ("cost_usd", "cost_saved_usd", "tokens_in", "tokens_out", "latency_ms"):
            if k in src:
                target[k] = target.get(k, 0) + src[k]
        for k in ("version", "actual_model", "provider", "request_id"):
            if k in src:
                target.setdefault(k, src[k])
        if src.get("cache_hit"):
            target["cache_hits"] = target.get("cache_hits", 0) + 1

    def drain_last_meta(self) -> dict[str, Any]:
        """Lấy và reset cost/latency metadata của chapter vừa dịch (gọi 1 lần
        cuối job hoặc sau mỗi chương). Trả dict trống nếu response không từ
        OmniRoute hoặc chapter rỗng."""
        with self._glossary_lock:
            out = self._last_chapter_meta
            self._last_chapter_meta = {}
            return dict(out)

    def _translate_chunk(
        self,
        chunk_text: str,
        glossary_accumulator: list[dict] | None = None,
        meta_accumulator: dict[str, Any] | None = None,
    ) -> str:
        """Dịch một đoạn và thử lại nếu kết quả còn sót chữ Hán chưa dịch.
        Nếu glossary_accumulator được truyền, các entry glossary trích từ response
        AI được append vào đó. Nếu meta_accumulator được truyền, cost/tokens/latency
        từ response (OmniRoute) được cộng dồn vào đó."""
        out, meta = self._run_chat_with_retry_meta(self._build_prompt(chunk_text))
        if meta_accumulator is not None:
            self._merge_meta(meta_accumulator, meta)
        translation_text, glossary_entries = self._split_response(out)
        cleaned = _clean_output(translation_text)
        for _ in range(_RESIDUAL_HAN_RETRIES):
            residual = len(_HAN_RE.findall(cleaned))
            if residual == 0:
                break
            out, fixup_meta = self._run_chat_with_retry_meta(
                self._build_fixup_prompt(chunk_text)
            )
            if meta_accumulator is not None:
                self._merge_meta(meta_accumulator, fixup_meta)
            fixup_text, fixup_glossary = self._split_response(out)
            retried = _clean_output(fixup_text)
            if len(_HAN_RE.findall(retried)) < residual:
                cleaned = retried
                glossary_entries = fixup_glossary or glossary_entries
            else:
                break
        if glossary_entries and glossary_accumulator is not None:
            glossary_accumulator.extend(glossary_entries)
        return cleaned

    # Sàn tối thiểu cho budget nội dung mỗi chunk khi prompt_max_chars quá
    # chật so với overhead (template + glossary) — tránh chia chương thành
    # hàng nghìn chunk tí hon hoặc lặp vô hạn.
    MIN_CHUNK_BUDGET = 200

    def _clamp_to_prompt_budget(self, max_chars: int, text: str) -> int:
        """Thu nhỏ budget nội dung mỗi chunk để TỔNG prompt (template + glossary
        + nội dung) không vượt cfg.prompt_max_chars.

        Overhead đo bằng prompt build từ chính `text` (glossary lọc theo toàn
        văn bản — superset của glossary mọi chunk con, nên là cận trên an toàn).
        prompt_max_chars <= 0 → không giới hạn, trả nguyên max_chars.
        """
        budget = self.cfg.prompt_max_chars
        if budget <= 0:
            return max_chars
        overhead = len(self._build_prompt(text)) - len(text)
        allowed = budget - overhead
        if allowed >= max_chars:
            return max_chars
        if allowed < self.MIN_CHUNK_BUDGET:
            self.log(
                f"  ⚠ prompt_max_chars={budget} quá nhỏ so với overhead prompt "
                f"({overhead} ký tự template+glossary) — dùng sàn {self.MIN_CHUNK_BUDGET} ký tự/đoạn."
            )
            return self.MIN_CHUNK_BUDGET
        self.log(
            f"  … prompt_max_chars={budget}: thu budget mỗi đoạn "
            f"{max_chars} → {allowed} ký tự (overhead prompt {overhead})."
        )
        return allowed

    def translate(
        self,
        text: str,
        *,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str:
        if not text.strip():
            return text
        max_chars = self.cfg.chunk.max_chars or self.DEFAULT_MAX_CHARS
        max_chars = self._clamp_to_prompt_budget(max_chars, text)
        glossary_accum: list[dict] = []
        meta_accum: dict[str, Any] = {}
        if len(text) <= max_chars:
            cleaned = self._translate_chunk(text, glossary_accum, meta_accum)
            if on_chunk is not None:
                on_chunk(1, 1, cleaned, True)
            _fire_glossary(on_glossary, glossary_accum)
            with self._glossary_lock:
                self._last_chapter_meta = meta_accum
            return _apply_glossary(cleaned, self.glossary)

        overlap = max(0, self.cfg.chunk.overlap_paragraphs)
        chunks = _split_into_chunks(text, max_chars, overlap)
        self.log(f"  … chia {len(chunks)} đoạn ({len(text)} ký tự, ≤{max_chars}/đoạn, overlap={overlap})")
        total = len(chunks)
        pieces: list[str] = []
        for i, chunk_paragraphs in enumerate(chunks):
            chunk_text = "\n".join(chunk_paragraphs)
            self.log(f"  … đoạn {i+1}/{total} ({len(chunk_text)} ký tự)")
            cleaned = self._translate_chunk(chunk_text, glossary_accum, meta_accum)
            if i > 0 and overlap > 0:
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[overlap:]) if len(lines) > overlap else cleaned
            pieces.append(cleaned)
            if on_chunk is not None:
                on_chunk(i + 1, total, cleaned, i + 1 == total)
        _fire_glossary(on_glossary, glossary_accum)
        with self._glossary_lock:
            self._last_chapter_meta = meta_accum
        return _apply_glossary("\n".join(pieces), self.glossary)

    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]:
        if not text.strip():
            return text, ""
        out = self._run_chat_with_retry(self._build_title_prompt(text, kind))
        title, note = _parse_title_response(out)
        return _apply_glossary(title, self.glossary), note

    def _build_titles_batch_prompt(self, titles: list[str]) -> str:
        numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, start=1))
        glossary = _format_glossary(self._glossary_for_prompt("\n".join(titles)))
        glossary_block = f"{glossary}\n\n" if glossary else ""
        return (
            f"Bạn là biên tập tiêu đề cho truyện dịch Trung-Việt. Nhiệm vụ: chuyển ngữ "
            f"{len(titles)} tiêu đề chương sau sang tiếng Việt thật HAY, có hồn, "
            "KHÔNG dịch sát nghĩa kiểu máy/Quick Translate.\n\n"
            "Nguyên tắc bắt buộc:\n"
            "1. Không bê nguyên âm Hán Việt nếu người đọc Việt không hiểu nghĩa.\n"
            "2. Có thể đảo cấu trúc, dùng hình ảnh/ẩn dụ tương đương trong tiếng Việt, "
            "miễn giữ đúng tinh thần và nội dung cốt lõi.\n\n"
            f"{glossary_block}"
            f"Trả lời ĐÚNG {len(titles)} dòng, mỗi dòng một tiêu đề đã dịch, giữ NGUYÊN "
            "thứ tự và số thứ tự như danh sách gốc, theo định dạng:\n"
            "<số thứ tự>. <bản dịch tiếng Việt>\n"
            "Không thêm giải thích, không gộp/bỏ dòng nào, không đánh số lại.\n\n"
            "--- Danh sách tiêu đề cần dịch ---\n"
            f"{numbered}"
        )

    def translate_titles(self, titles: list[str]) -> list[str]:
        if not titles:
            return []
        result: list[str] = []
        for start in range(0, len(titles), self.TITLES_BATCH_SIZE):
            batch = titles[start : start + self.TITLES_BATCH_SIZE]
            out = self._run_chat_with_retry(self._build_titles_batch_prompt(batch))
            parsed = _parse_titles_batch_response(out, len(batch))
            for i, t in enumerate(batch, start=1):
                if i in parsed and parsed[i]:
                    result.append(_apply_glossary(parsed[i], self.glossary))
                else:
                    # Model bỏ sót dòng này trong response hàng loạt → fallback dịch riêng.
                    title, _note = self.translate_title(t)
                    result.append(title)
        return result


class GoogleTranslator:
    MAX_CHARS = 4500

    def __init__(self, cfg: TranslateConfig, storage: "Storage | None" = None):
        self.cfg = cfg
        self.glossary = load_glossary_dict(cfg, storage) if storage is not None else _merge_glossaries(cfg.glossary)
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
        on_glossary: Callable[[list[dict]], None] | None = None,
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

    def __init__(self, cfg: TranslateConfig, log: Callable[[str], None] | None = None, storage: "Storage | None" = None):
        self.cfg = cfg
        self.hmt = cfg.hachimimt
        self.glossary = load_glossary_dict(cfg, storage)
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
        on_glossary: Callable[[list[dict]], None] | None = None,
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

    def __init__(self, cfg: TranslateConfig, storage: "Storage | None" = None):
        self.cfg = cfg
        self.lt = cfg.libretranslate
        self.glossary = load_glossary_dict(cfg, storage) if storage is not None else _merge_glossaries(cfg.glossary)

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
        on_glossary: Callable[[list[dict]], None] | None = None,
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


def make_translator(cfg: TranslateConfig, log: Callable[[str], None] | None = None, storage: "Storage | None" = None) -> Translator:
    """`storage` (tùy chọn): Storage của ebook đang dịch — khi truyền vào,
    glossary được đọc thẳng từ DB (nguồn auto-glossary/trang Glossary ghi)
    thay vì suy path, xem load_glossary_dict."""
    kind = (cfg.type or "none").lower()
    if kind == "openai":
        return OpenAITranslator(cfg, log=log, storage=storage)
    if kind == "google":
        return GoogleTranslator(cfg, storage=storage)
    if kind in ("hachimimt", "moxhimt"):
        return HachimiMTTranslator(cfg, log=log, storage=storage)
    if kind == "libretranslate":
        return LibreTranslateTranslator(cfg, storage=storage)
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
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str:
        out = self.inner.translate(text, on_chunk=on_chunk, on_glossary=on_glossary)
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

    def extend_glossary(self, new_entries: dict[str, str], storage) -> dict:
        return self.inner.extend_glossary(new_entries, storage)

    def drain_conflicts(self) -> list[dict]:
        return self.inner.drain_conflicts() if hasattr(self.inner, "drain_conflicts") else []

    def drain_last_meta(self) -> dict:
        return self.inner.drain_last_meta() if hasattr(self.inner, "drain_last_meta") else {}
