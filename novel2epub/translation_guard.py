"""Guard bắt buộc cho bản dịch chương: bản không qua guard KHÔNG được lưu DB.

- `strip_prompt_echo`: LLM lặp lại prompt dịch trong phản hồi → tách bỏ phần
  prompt; không tách ra được bản dịch thì raise.
- `check_word_counts`: Trung → Việt thì số từ bản Việt phải >= số từ bản Trung
  (dịch thiếu/cắt cụt), và không bản dịch nào được dài bất thường so với nguồn
  (model lặp, bịa thêm, hoặc dính prompt không tách được).

Không có cấu hình tắt: gọi từ `OpenAITranslator._translate_chunk` và
`pipeline._translate_one`.
"""
from __future__ import annotations

import re
import unicodedata

_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# Một "từ" ngoài chữ Hán: cụm chữ/số liền nhau (âm tiết tiếng Việt, từ Latin, số).
_WORD_RE = re.compile(r"[^\W_㐀-䶿一-鿿豈-﫿]+")

_ZH_SOURCES = ("", "zh", "cn", "zh-cn", "zh-tw")

# Trần "dài bất thường": số từ bản dịch > nguồn × MAX_WORD_RATIO + MAX_WORD_SLACK.
# Bản Việt tử tế thường ~1.1–1.5× số chữ Hán; slack để chương/đoạn rất ngắn
# không bị loại oan.
MAX_WORD_RATIO = 3.0
MAX_WORD_SLACK = 50

# Dòng prompt ngắn hơn ngưỡng này quá dễ trùng ngẫu nhiên với văn bản dịch.
_MIN_ECHO_LINE = 20


class TranslationGuardError(RuntimeError):
    """Bản dịch bị guard từ chối — coi như dịch thất bại, không lưu DB."""


def is_zh_to_vi(source_language: str | None, target_language: str | None) -> bool:
    """`source_language` rỗng là mặc định của hệ thống (truyện Trung)."""
    source = (source_language or "").strip().lower()
    target = (target_language or "vi").strip().lower()
    return source in _ZH_SOURCES and target == "vi"


def count_words(text: str, *, han: bool = True) -> int:
    """Đếm từ: mỗi chữ Hán là một từ, mỗi cụm chữ/số ngoài Hán là một từ.

    `han=False` cho bản dịch tiếng Việt — chữ Hán còn sót là phần CHƯA dịch nên
    không được tính là từ của bản Việt.
    """
    text = unicodedata.normalize("NFC", text or "")
    words = len(_WORD_RE.findall(text))
    return words + len(_HAN_RE.findall(text)) if han else words


def check_word_counts(source: str, translated: str, *, zh_to_vi: bool) -> None:
    """Raise `TranslationGuardError` nếu số từ bản dịch không hợp lệ so với nguồn."""
    source_words = count_words(source)
    translated_words = count_words(translated, han=False)
    if zh_to_vi and translated_words < source_words:
        raise TranslationGuardError(
            f"Bản dịch thiếu: {translated_words} từ tiếng Việt < {source_words} từ "
            "bản Trung (Trung → Việt bắt buộc số từ Việt >= số từ Trung)"
        )
    limit = int(source_words * MAX_WORD_RATIO) + MAX_WORD_SLACK
    if translated_words > limit:
        raise TranslationGuardError(
            f"Bản dịch dài bất thường: {translated_words} từ so với {source_words} từ "
            f"bản gốc (trần {limit})"
        )


def _norm(line: str) -> str:
    return " ".join(line.split())


def _prompt_lines(prompt: str, source_lines: set[str]) -> set[str]:
    """Các dòng chỉ dẫn đủ đặc trưng của prompt.

    Bỏ dòng của chính nội dung cần dịch và dòng dạng `Hán = Việt` (glossary /
    bảng nhân vật) — phần `GLOSSARY:` hợp lệ trong phản hồi có thể lặp lại y
    nguyên một mục đã có trong prompt.
    """
    lines: set[str] = set()
    for raw in prompt.splitlines():
        line = _norm(raw)
        if len(line) >= _MIN_ECHO_LINE and "=" not in line and line not in source_lines:
            lines.add(line)
    return lines


def strip_prompt_echo(output: str, prompt: str, source_text: str) -> str:
    """Tách bỏ phần prompt dịch bị LLM lặp lại trong `output`.

    Bỏ trọn khối từ dòng prompt đầu tiên đến dòng prompt cuối cùng xuất hiện
    trong phản hồi (gồm cả nội dung gốc bị lặp nằm giữa), giữ phần trước và sau
    khối đó. Trả nguyên `output` nếu không dính prompt. Raise
    `TranslationGuardError` khi bỏ prompt xong không còn lại bản dịch nào.
    """
    source_lines = {_norm(line) for line in source_text.splitlines()} - {""}
    prompt_lines = _prompt_lines(prompt, source_lines)
    if not prompt_lines:
        return output
    lines = output.splitlines()
    hits = [i for i, line in enumerate(lines) if _norm(line) in prompt_lines]
    if not hits:
        return output
    tail = lines[hits[-1] + 1:]
    # Prompt kết thúc bằng nội dung cần dịch: model lặp prompt thường lặp luôn
    # phần nguồn ngay sau dòng chỉ dẫn cuối, rồi mới tới bản dịch.
    while tail and (
        not tail[0].strip()
        or (_norm(tail[0]) in source_lines
            and (_HAN_RE.search(tail[0]) or len(_norm(tail[0])) >= _MIN_ECHO_LINE))
    ):
        tail.pop(0)
    result = "\n".join(lines[:hits[0]] + tail).strip()
    if not result:
        raise TranslationGuardError(
            "Phản hồi chứa prompt dịch và không tách ra được bản dịch"
        )
    return result
