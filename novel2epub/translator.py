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
from typing import Any, Callable, Protocol

from . import characters as characters_mod
from . import genre as genre_mod
from . import idioms as idioms_mod
from . import openai_client
from .config import LibreTranslateConfig, TranslateConfig
from .idioms import Idiom
from .storage import Storage, normalize_glossary_pending, parse_glossary_line

# Một số mẫu "lời mở đầu" mà LLM hay tự thêm dù đã bảo đừng.
_PREAMBLE = re.compile(
    r"^\s*(đây là|sau đây là|dưới đây là|bản dịch).{0,40}:\s*$",
    re.IGNORECASE,
)

# Marker để AI đánh dấu phần glossary trong response dịch.
# Hỗ trợ cả `## GLOSSARY` (format mới, đồng bộ với bulk_transfer) và
# `===GLOSSARY===` (cũ, tương thích ngược).
_GLOSSARY_MARKER = re.compile(r"^(?:#{1,6}\s+)?GLOSSARY\s*$|^===GLOSSARY===\s*$", re.MULTILINE | re.IGNORECASE)
# Bullet `- `/`* `/`+ ` AI hay tự thêm trước mỗi dòng glossary.
_GLOSSARY_BULLET_RE = re.compile(r"^[-*+]\s+")

# Block hướng dẫn auto-glossary — được nhét vào prompt_template qua placeholder
# {auto_glossary_block} khi cfg.auto_glossary bật. Nếu template cũ (pin từ autosave)
# không chứa placeholder, fallback: append sau format (xem _build_prompt).
# Dùng `## GLOSSARY` để đồng bộ với format trong bulk_transfer._GLOSSARY_OUTPUT_RULE.
_AUTO_GLOSSARY_BLOCK = (
    "\n\nỞ CUỐI bản dịch, thêm một mục `## GLOSSARY` để liệt kê "
    "các mục glossary MỚI, mỗi mục MỘT DÒNG theo đúng dạng:\n"
    "- <Hán> = <Việt>\n"
    "Glossary là bảng ĐỒNG BỘ cách dịch xuyên suốt truyện, KHÔNG phải "
    "từ điển — thà bỏ sót còn hơn đưa nhầm từ thông thường.\n"
    "CHỈ đưa vào: tên riêng (nhân vật, địa danh, môn phái/tổ chức, "
    "chức danh) và thuật ngữ ĐẶC THÙ lặp lại nhiều lần (công pháp, "
    "chiêu thức, cảnh giới, pháp bảo, đan dược, chủng tộc, hệ thống "
    "sức mạnh, biệt danh cố định).\n"
    "Tên người nước ngoài ghi dạng chữ Latin gốc (夏洛克 → Sherlock), "
    "không ghi Hán Việt.\n"
    "TUYỆT ĐỐI KHÔNG đưa vào: từ đời thường (đồ ăn, mua sắm, động tác, "
    "cảm xúc, nghề nghiệp, vật dụng phổ thông); thành ngữ/khẩu ngữ/tiếng "
    "lóng dịch thoát ý; từ hiện đại phổ thông; từ độc giả Việt hiểu ngay "
    "hoặc chỉ xuất hiện một lần.\n"
    "Không giải thích, không đánh số, không JSON. Nếu không có mục nào "
    "đạt tiêu chí, để mục `## GLOSSARY` trống (chỉ ghi tiêu đề, không kèm mục con)."
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

    Nguyên tắc so khớp:
    - zh (chữ Hán) trong zh_text (văn bản Hán): substring — không có ranh giới từ
      trong text Hán ngữ, multi-char term đã đủ chính xác.
    - vi (tiếng Việt) trong vi_text (văn bản dịch): dùng regex \\b word boundary
      để tránh false positive kiểu "đi" khớp trong "điện thoại".
    """
    import re
    result: dict[str, str] = {}
    for zh, vi in glossary.items():
        if zh_text and zh and zh in zh_text:
            result[zh] = vi
        elif vi_text and vi and _is_vi_word_in_text(vi, vi_text):
            result[zh] = vi
    return result


def _is_vi_word_in_text(word: str, text: str) -> bool:
    """Kiểm tra `word` xuất hiện như một từ độc lập trong `text` (\\b boundary).

    Lưu ý: `word` có thể chứa ký tự có dấu tiếng Việt (ổ, ế, ợ...) —
    `\\w` trong Python regex bao gồm cả ký tự Unicode có dấu nên \\b hoạt động
    chính xác cho tiếng Việt.
    """
    try:
        return bool(re.search(rf'\b{re.escape(word)}\b', text, re.IGNORECASE))
    except re.error:
        return word in text


def _apply_glossary(text: str, glossary: dict[str, str]) -> str:
    """Thay thế literal sau khi dịch để đảm bảo nhất quán tên riêng.

    Áp source dài trước source ngắn (longest-match): tránh trường hợp glossary
    có cả `韩=Hàn` và `韩溯=Hàn Tố` mà `韩` được áp trước biến `韩溯` thành
    `Hàn溯`, hỏng tên dài. Mọi source là Hán, target là Việt nên không có
    nhiễm chéo Việt→Trung — chỉ cần đúng thứ tự độ dài."""
    for zh, vi in sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True):
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
    """Load glossary for prompts from SQLite only.

    `names.txt`/`vietphrase.txt`, external glossary files, inline config glossary,
    and pending AI suggestions are not prompt sources. Pending suggestions become
    prompt-visible only after approval writes them into SQLite `names.txt`.
    """
    if storage is None:
        return {}
    try:
        entries = storage.read_glossary_entries("names.txt")
    except Exception:
        return {}
    return {source: target for source, target, _note in entries if source and target}


def load_idioms_list(cfg: TranslateConfig, storage: "Storage | None") -> list[Idiom]:
    """Đọc kho idiom global từ DB nếu `translate.use_idioms` bật và có storage.

    Idiom là kho DÙNG CHUNG mọi ebook (bảng `idioms`, không gắn slug) — bất kỳ
    Storage nào cũng đọc được cùng một kho. Không có storage (đường backward-
    compat/test) → trả rỗng, tính năng idiom tắt an toàn."""
    if not getattr(cfg, "use_idioms", False) or storage is None:
        return []
    try:
        rows = storage.read_idiom_entries()
    except Exception:
        return []
    return idioms_mod.idioms_from_rows(rows)


def load_characters(cfg: TranslateConfig, storage: "Storage | None") -> list:
    """Đọc bảng nhân vật của ebook. Trả [] khi chưa có storage."""
    if storage is None:
        return []
    return characters_mod.characters_from_rows(storage.read_character_entries())


def load_relations(cfg: TranslateConfig, storage: "Storage | None") -> list:
    """Đọc bảng quan hệ của ebook. Trả [] khi chưa có storage."""
    if storage is None:
        return []
    return characters_mod.relations_from_rows(storage.read_relation_entries())


class Translator(Protocol):
    # Mỗi translate() chia văn bản thành nhiều chunk; triển khai có thể nhận
    # kwarg tùy chọn `on_chunk(index, total, chunk_text, is_final)` để stream
    # tiến độ (xem `translate-chunk-streaming` spec), và `chapter_idx` để chọn
    # đúng mốc quan hệ nhân vật (xem `characters.resolve_relations`). Gọi
    # không truyền kwarg vẫn hoạt động như cũ — tương thích ngược hoàn toàn.
    def translate(
        self,
        text: str,
        *,
        chapter_idx: int | None = None,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str: ...
    def translate_title(self, text: str, kind: str = "tên chương") -> tuple[str, str]: ...


class NoopTranslator:
    def translate(
        self,
        text: str,
        *,
        chapter_idx: int | None = None,
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
        self.storage = storage
        self.glossary = load_glossary_dict(cfg, storage)
        self.idioms = load_idioms_list(cfg, storage)
        self.characters = load_characters(cfg, storage)
        self.relations = load_relations(cfg, storage)
        self.log = log or (lambda _: None)
        self._glossary_lock = threading.Lock()
        self._last_chapter_meta: dict[str, Any] = {}

    def extend_glossary(
        self,
        new_entries: dict[str, str],
        storage: "Storage",
        chapter_index: int = 0,
    ) -> dict:
        """Merge new_entries vào glossary + ghi HÀNG CHỜ DUYỆT. Thread-safe.

        - Source MỚI (chưa có trong glossary): thêm NGAY vào `names.txt` (note
          rỗng) + cập nhật in-memory — prompt các chương sau thấy ngay.
        - Source đã có CÙNG giá trị: bỏ qua.
        - Source đã có KHÁC giá trị (đổi cách dịch): KHÔNG tự sửa — persist vào
          extra json `glossary_pending` (first-wins theo source, atomic qua
          `update_extra_json`) để người dùng preview/duyệt trên trang Glossary.

        Trả {'added': [(source, target), ...],
        'changed': [{source, existing_target, target, chapter_index}, ...]}.
        """
        added, changed = [], []
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
                    changed.append(
                        {
                            "source": source,
                            "existing_target": existing,
                            "target": new_target,
                            "chapter_index": chapter_index,
                        }
                    )
            if changed:
                preexisting = {
                    p["source"] for p in normalize_glossary_pending(storage.read_extra_json("glossary_pending"))
                }

                def _merge_pending(current):
                    pending = normalize_glossary_pending(current)
                    seen = {p["source"] for p in pending}
                    out = list(pending)
                    for c in normalize_glossary_pending(changed):
                        if c["source"] not in seen:
                            out.append(c)
                            seen.add(c["source"])
                    return out

                storage.update_extra_json("glossary_pending", _merge_pending)
                # `changed` trả về chỉ gồm những source THỰC SỰ được thêm mới
                # vào hàng chờ lần này (first-wins: source đã chờ từ trước → bỏ).
                changed = [
                    c
                    for c in normalize_glossary_pending(changed)
                    if c["source"] not in preexisting
                ]
        return {"added": added, "changed": changed}

    def _glossary_for_prompt(self, zh_text: str, vi_text: str = "") -> dict[str, str]:
        """Bản glossary để nhét vào prompt: reload SQLite để job đang chạy thấy
        CRUD mới nhất, rồi snapshot dưới lock. Không dùng TXT/pending/config."""
        with self._glossary_lock:
            if self.storage is not None:
                self.glossary = load_glossary_dict(self.cfg, self.storage)
            snapshot = dict(self.glossary)
        if not self.cfg.glossary_filter:
            return snapshot
        return _filter_glossary(snapshot, zh_text=zh_text, vi_text=vi_text)

    def _build_prompt(self, text: str, chapter_idx: int | None = None) -> str:
        tpl = self.openai.prompt_template
        auto_block = _AUTO_GLOSSARY_BLOCK if self.cfg.auto_glossary else ""
        # Use .replace() instead of .format() so that {auto_glossary_block}
        # stays as literal text in the template visible in the settings textarea
        # (autosave pins whatever the textarea contains).
        idiom_block = idioms_mod.format_llm_block(
            idioms_mod.filter_for_text(self.idioms, text)
        )
        chars = characters_mod.filter_for_text(
            self.characters, text, source_language=self.cfg.source_language
        )
        rels = characters_mod.resolve_relations(self.relations, chapter_idx)
        char_block = characters_mod.format_llm_block(chars, rels)
        style = self.cfg.style
        prompt = (
            tpl
            .replace("{text}", text)
            .replace("{glossary}", _format_glossary(self._glossary_for_prompt(text)))
            .replace("{idioms}", idiom_block)
            .replace("{characters}", char_block)
            .replace("{tone}", style.tone)
            .replace("{pronoun_policy}", genre_mod.format_pronoun_rules(
                self.cfg.genre, style.pronoun_policy))
            .replace("{keep_paragraphs}", str(style.keep_paragraphs))
            .replace("{title_mode}", genre_mod.format_style_value("title_mode", style.title_mode))
            .replace("{han_viet_level}", genre_mod.format_style_value(
                "han_viet_level", style.han_viet_level))
        )
        # Back-compat: template pin cũ không có {characters} → chèn ngay trước
        # nội dung (đúng chỗ mong muốn về mặt recency) thay vì im lặng bỏ qua.
        if char_block and "{characters}" not in tpl:
            prompt = prompt.replace(text, f"{char_block}\n\n{text}", 1)
        # Back-compat: old pinned templates without the placeholder → append.
        if "{auto_glossary_block}" in tpl:
            prompt = prompt.replace("{auto_glossary_block}", auto_block)
        elif auto_block:
            prompt += auto_block
        # Back-compat: strip the removed {fixup_warning} placeholder from old
        # pinned templates so it doesn't leak into the prompt literally.
        prompt = prompt.replace("{fixup_warning}", "")
        # Dòng ghim nối bằng code (không qua placeholder) nên chạy được với MỌI
        # template, kể cả prompt người dùng đã pin từ trước.
        pin = characters_mod.format_pin_line(
            chars,
            genre_mod.forbid_words(self.cfg.genre),
            genre_mod.RUNTIME_PRONOUN_PIN,
        )
        if pin:
            prompt = f"{prompt}\n\n{pin}"
        return prompt

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
        chapter_idx: int | None = None,
    ) -> str:
        """Dịch một đoạn.
        Nếu glossary_accumulator được truyền, các entry glossary trích từ response
        AI được append vào đó. Nếu meta_accumulator được truyền, cost/tokens/latency
        từ response (OmniRoute) được cộng dồn vào đó."""
        out, meta = self._run_chat_with_retry_meta(
            self._build_prompt(chunk_text, chapter_idx)
        )
        if meta_accumulator is not None:
            self._merge_meta(meta_accumulator, meta)
        translation_text, glossary_entries = self._split_response(out)
        cleaned = _clean_output(translation_text)
        if glossary_entries and glossary_accumulator is not None:
            glossary_accumulator.extend(glossary_entries)
        return cleaned

    # Sàn tối thiểu cho budget nội dung mỗi chunk khi prompt_max_chars quá
    # chật so với overhead (template + glossary) — tránh chia chương thành
    # hàng nghìn chunk tí hon hoặc lặp vô hạn.
    MIN_CHUNK_BUDGET = 200

    def _clamp_to_prompt_budget(
        self, max_chars: int, text: str, chapter_idx: int | None = None
    ) -> int:
        """Thu nhỏ budget nội dung mỗi chunk để TỔNG prompt (template + glossary
        + idiom + bảng nhân vật + nội dung) không vượt cfg.prompt_max_chars.

        Overhead đo bằng prompt build từ chính `text` (glossary/idiom/bảng nhân
        vật lọc theo toàn văn bản — superset của mọi chunk con, nên là cận trên
        an toàn). prompt_max_chars <= 0 → không giới hạn, trả nguyên max_chars.
        """
        budget = self.cfg.prompt_max_chars
        if budget <= 0:
            return max_chars
        overhead = len(self._build_prompt(text, chapter_idx)) - len(text)
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
        chapter_idx: int | None = None,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str:
        if not text.strip():
            return text
        max_chars = self.cfg.chunk.max_chars or self.DEFAULT_MAX_CHARS
        max_chars = self._clamp_to_prompt_budget(max_chars, text, chapter_idx)
        glossary_accum: list[dict] = []
        meta_accum: dict[str, Any] = {}
        if len(text) <= max_chars:
            cleaned = self._translate_chunk(text, glossary_accum, meta_accum, chapter_idx)
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
            cleaned = self._translate_chunk(chunk_text, glossary_accum, meta_accum, chapter_idx)
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
        chapter_idx: int | None = None,
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
        self.idioms = load_idioms_list(cfg, storage)
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
        chapter_idx: int | None = None,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str:
        if not text.strip():
            if on_chunk is not None:
                on_chunk(1, 1, text, True)
            return text
        self._ensure_loaded()
        assert self._inner is not None
        # Idiom protect: thay idiom `@protect` bằng placeholder TRƯỚC khi MT dịch
        # (idiom thường để MT dịch bình thường rồi chuẩn hoá literal ở hậu xử lý).
        protected_text, restore_map = idioms_mod.protect_source(text, self.idioms)
        translated = self._inner.translate_text(protected_text, beam_size=self.hmt.beam_size, chunk_mode=self.hmt.chunk_mode)
        out = _apply_glossary(translated, self.glossary)
        # Khôi phục placeholder → natural, rồi chuẩn hoá literal → natural.
        out = idioms_mod.apply_mt_post(out, self.idioms, restore_map)
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
        chapter_idx: int | None = None,
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
    # Nguồn đã là tiếng Việt (truyện VN crawl về) — không cần dịch, giữ nguyên
    # bản gốc bất kể type là gì (không load model/gọi API).
    if (cfg.source_language or "").strip().lower() == "vi":
        return NoopTranslator()
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
        chapter_idx: int | None = None,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str:
        out = self.inner.translate(
            text, chapter_idx=chapter_idx, on_chunk=on_chunk, on_glossary=on_glossary
        )
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

    def extend_glossary(self, new_entries: dict[str, str], storage, chapter_index: int = 0) -> dict:
        return self.inner.extend_glossary(new_entries, storage, chapter_index)

    def drain_last_meta(self) -> dict:
        return self.inner.drain_last_meta() if hasattr(self.inner, "drain_last_meta") else {}
