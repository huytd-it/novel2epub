"""Read-only translation previews for extracted terms and their raw contexts."""
from __future__ import annotations

from copy import deepcopy
import re

from .config import DEFAULT_PROMPT
from .translator import make_translator

_LINE = re.compile(r"^\[\[G(\d+)_(TERM|CONTEXT)\]\]\s*(.+)$")
_FORMAT = """
QUY TẮC DỊCH NHIỀU DÒNG:
Mỗi dòng đầu vào có mã [[G<number>_TERM]] hoặc [[G<number>_CONTEXT]].
Dịch phần văn bản sau mã sang tiếng Việt, giữ nguyên từng mã và đúng một dòng
cho mỗi mã. TERM là thuật ngữ, CONTEXT là ngữ cảnh của cùng thuật ngữ đó;
dùng ngữ cảnh để chọn nghĩa và tên nhất quán. Không thêm, bỏ, gộp dòng hay mã.
Chỉ trả các dòng có mã và bản dịch, không thêm giải thích hoặc markdown.
"""


def translate_extracted_rows(cfg, storage, entries: list[dict], engine: str, *, log=lambda message: None,
                             should_cancel=lambda: False) -> list[dict]:
    """Local MT: one term at a time. LLM: labelled, budgeted batches of rows.

    Never writes glossary/pending/config. A malformed LLM batch is rejected as a
    whole instead of associating translations with the wrong source terms.
    """
    options = deepcopy(cfg.translate)
    options.type = "localmt" if engine == "localmt" else "openai"
    # This endpoint receives Han terms even when an ebook's default is passthrough.
    options.source_language = "zh"
    options.auto_glossary = False
    options.ai_glossary_analysis = False
    if engine == "openai":
        options.openai.prompt_template = DEFAULT_PROMPT
    rows = [dict(source=e["source"], target="", context_target="", error="", engine=engine)
            for e in entries]
    if not rows:
        return rows
    if should_cancel():
        return []
    try:
        translator = make_translator(options, storage=storage)
    except Exception:
        for row in rows:
            row["error"] = "Không tải được engine dịch. Kiểm tra cấu hình/model."
        return rows

    if engine == "localmt":
        for index, (entry, row) in enumerate(zip(entries, rows), 1):
            for key, output in (("source", "target"), ("context", "context_target")):
                if should_cancel():
                    log("[glossary-preview] Đã hủy.")
                    return []
                if not entry.get(key):
                    continue
                try:
                    value = translator.translate(entry[key]).strip()
                    if not value:
                        raise ValueError("empty translation")
                    row[output] = value
                except Exception:
                    row["error"] = "Không dịch được thuật ngữ hoặc ngữ cảnh; có thể thử lại."
            log(f"[glossary-preview] Local MT {index}/{len(rows)} dòng.")
        return rows

    def source_lines(index):
        entry = entries[index]
        return "\n".join(
            f"[[G{index}_{label}]] {' '.join(entry[key].splitlines())}"
            for key, label in (("source", "TERM"), ("context", "CONTEXT")) if entry.get(key)
        )

    # Build the actual DEFAULT_PROMPT first so its overhead counts towards the cap.
    budget = options.prompt_max_chars or 20000
    start = 0
    while start < len(rows):
        if should_cancel():
            log("[glossary-preview] Đã hủy.")
            return []
        batch: list[int] = []
        prompt = ""
        for index in range(start, min(start + 20, len(rows))):
            indices = batch + [index]
            text = "\n".join(source_lines(i) for i in indices)
            candidate = translator._build_prompt(text) + "\n" + _FORMAT
            if len(candidate) > budget:
                break
            batch, prompt = indices, candidate
        if not batch:
            rows[start]["error"] = "Prompt vượt giới hạn prompt_max_chars; tăng giới hạn rồi thử lại."
            start += 1
            continue
        expected = {(i, label) for i in batch for key, label in (("source", "TERM"), ("context", "CONTEXT"))
                    if entries[i].get(key)}
        try:
            response = translator._run_chat_with_retry(prompt)
            values = {}
            for line in response.strip().splitlines():
                if not line.strip():
                    continue
                match = _LINE.fullmatch(line.strip())
                if not match:
                    raise ValueError("unlabelled line")
                key = (int(match[1]), match[2])
                if key not in expected or key in values:
                    raise ValueError("unknown or duplicate id")
                value = match[3].strip()
                if not value:
                    raise ValueError("empty translation")
                values[key] = value
            if set(values) != expected:
                raise ValueError("missing lines")
            for i in batch:
                rows[i]["target"] = values[i, "TERM"]
                rows[i]["context_target"] = values.get((i, "CONTEXT"), "")
        except Exception:
            for i in batch:
                rows[i]["error"] = "LLM lỗi hoặc trả thiếu/sai mã dòng; không ghép bản dịch. Hãy thử lại."
        start += len(batch)
        log(f"[glossary-preview] LLM {start}/{len(rows)} dòng.")
    return rows
