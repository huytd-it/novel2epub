"""AI hỗ trợ quản lý glossary và "edit hay" bản dịch — tách riêng khỏi luồng
dịch chương chính (translator.py) vì dùng prompt khác hẳn (phân tích/biên tập,
không phải dịch từ đầu).
"""
from __future__ import annotations

import json
import re

from . import openai_client
from .config import TranslateConfig
from .translator import _apply_glossary, _clean_output, _format_glossary, load_glossary_dict

SUGGEST_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt, chuyên xây dựng glossary nhất quán.

Nhiệm vụ: đọc bản gốc tiếng Trung và bản dịch tiếng Việt hiện tại dưới đây, đề xuất các mục glossary mới.

Nguyên tắc:
1. Tên riêng (nhân vật), địa danh, công pháp, chiêu thức, linh thú, pháp bảo: giữ Hán Việt, đề xuất nếu chưa có trong glossary hiện tại.
2. Cụm từ xuất hiện nhiều lần cần thống nhất cách dịch.
3. Không đề xuất lại mục đã có sẵn trong glossary hiện tại (xem danh sách dưới).
4. Không bịa thêm tên/thuật ngữ không xuất hiện trong văn bản.
5. Không spoil, không thêm bình luận ngoài truyện.

Glossary hiện tại (không đề xuất lại các mục này):
{existing}

--- Bản gốc (Trung) ---
{raw}

--- Bản dịch hiện tại (Việt) ---
{translated}

Chỉ trả về JSON array, không kèm giải thích, không dùng code fence. Mỗi phần tử có dạng:
{{"source": "<Hán>", "suggested": "<Việt>", "type": "name|place|skill|item|term|phrase", "reason": "<lý do ngắn>", "target_file": "names.txt|vietphrase.txt"}}
Nếu không có gì để đề xuất, trả về [].
"""

EDIT_HAY_GUIDELINES = """Nguyên tắc "edit hay" (biên tập lại bản dịch máy/dịch thô cho mượt):
1. Dùng từ đồng nghĩa linh hoạt theo sắc thái nhân vật và bối cảnh; tránh từ quá thô/hài/lố nếu cảnh đang trang trọng hoặc là chính truyện.
2. Không bê nguyên trật tự câu tiếng Trung; viết lại theo ngữ pháp Việt tự nhiên (chủ ngữ + động từ + vị ngữ, trạng ngữ lên đầu câu khi hợp lý).
3. Ngôi xưng phải theo quan hệ và ngữ cảnh, không lạm dụng ta/ngươi.
4. Câu rõ nghĩa nhưng khô/máy móc cần viết lại tự nhiên hơn, không đổi nghĩa gốc.
5. Thành ngữ, tục ngữ, thơ từ, điển tích nên dịch thoát ý hoặc dùng bản dịch quen thuộc nếu có, không dịch từng chữ.
6. Tên chương cần chuyển ngữ hay, có ý vị, không giữ nguyên Hán Việt khô khó hiểu.
7. Không spoil, không chèn bình luận/nhận xét ngoài truyện, không thêm/bớt nội dung so với bản gốc.
"""

REWRITE_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt. Nhiệm vụ của bạn là BIÊN TẬP LẠI bản dịch hiện tại cho hay hơn, KHÔNG dịch lại từ đầu.

{guidelines}
{glossary}

--- Bản gốc (Trung), dùng để đối chiếu khi cần ---
{raw}

--- Bản dịch hiện tại (Việt), cần biên tập lại ---
{translated}

Chỉ trả về toàn văn bản đã biên tập lại (giữ nguyên cách chia đoạn). KHÔNG thêm lời mở đầu, ghi chú, giải thích, hay code fence.
"""

EVALUATE_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt, nhiệm vụ là ĐÁNH GIÁ (review) chứ KHÔNG sửa.

Hãy đọc glossary hiện tại + các cặp bản gốc/bản dịch dưới đây rồi đánh giá:
1. Chất lượng & tính nhất quán của GLOSSARY: mục trùng lặp, mâu thuẫn (một Hán -> nhiều cách dịch khác nhau), Hán-Việt sai hoặc khó hiểu, mục nên có nhưng còn thiếu.
2. Chất lượng BẢN DỊCH: trung thành với bản gốc, văn phong mượt/tự nhiên, ngôi xưng hợp ngữ cảnh, câu không khô/máy móc.
3. ĐỐI CHIẾU CHÉO glossary <-> bản dịch: chương có dùng đúng cách dịch trong glossary không; thuật ngữ/tên riêng nào trong chương đang dịch lệch so với bảng.

Nguyên tắc:
- Chỉ nêu vấn đề có thật, dẫn được chỗ cụ thể; không bịa, không spoil.
- Với mỗi vấn đề, đề xuất cách sửa ngắn gọn nhưng KHÔNG tự viết lại cả chương.

Glossary hiện tại:
{glossary}

--- Bản gốc (Trung) ---
{raw}

--- Bản dịch hiện tại (Việt) ---
{translated}

Chỉ trả về JSON object, không kèm giải thích, không dùng code fence. Dạng:
{{"summary": "<nhận xét tổng quan ngắn>", "score": <số 0-10 hoặc null>, "issues": [
  {{"category": "glossary|consistency|mistranslation|hanviet|fluency|other", "severity": "high|medium|low", "chapter": "<số chương/tên hoặc rỗng>", "source": "<Hán liên quan hoặc rỗng>", "current": "<chỗ dịch có vấn đề>", "suggestion": "<đề xuất sửa>", "reason": "<lý do ngắn>"}}
]}}
Nếu không có vấn đề, trả về "issues": [].
"""


_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _parse_suggestions(text: str) -> list[dict]:
    text = _clean_output(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_ARRAY.search(text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []

    valid_types = {"name", "place", "skill", "item", "term", "phrase"}
    valid_files = {"names.txt", "vietphrase.txt"}
    suggestions = []
    for item in data:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        suggested = str(item.get("suggested", "")).strip()
        if not source or not suggested:
            continue
        suggestions.append(
            {
                "source": source,
                "suggested": suggested,
                "type": item.get("type") if item.get("type") in valid_types else "term",
                "reason": str(item.get("reason", "")).strip(),
                "target_file": item.get("target_file") if item.get("target_file") in valid_files else "vietphrase.txt",
            }
        )
    return suggestions


def suggest_glossary(
    cfg: TranslateConfig,
    chapters: list[tuple[str, str]],
    existing_glossary: dict[str, str],
) -> list[dict]:
    """Gọi AI phân tích raw+translated của các chương đã chọn, trả list suggestion.

    Lỗi gọi CLI hoặc parse JSON không raise — trả [] để không sập UI, lỗi cụ thể
    do caller tự log nếu cần (xem ngoại lệ bị nuốt có chủ đích ở đây).
    """
    raw_combined = "\n\n".join(raw for raw, _ in chapters if raw.strip())
    translated_combined = "\n\n".join(t for _, t in chapters if t.strip())
    if not raw_combined.strip() and not translated_combined.strip():
        return []

    existing_text = _format_glossary(existing_glossary) or "(chưa có mục nào)"
    prompt = SUGGEST_PROMPT.format(existing=existing_text, raw=raw_combined, translated=translated_combined)
    try:
        output = openai_client.run_chat(cfg.openai, prompt)
    except Exception:
        return []

    suggestions = _parse_suggestions(output)
    return [s for s in suggestions if existing_glossary.get(s["source"]) != s["suggested"]]


# Alias công khai — glossary_ai dùng lại đúng logic gộp glossary của translator
# để tránh 2 nơi đọc file names.txt/vietphrase.txt theo 2 cách khác nhau.
load_glossary = load_glossary_dict


def rewrite_chapter(cfg: TranslateConfig, raw: str, current_translation: str, glossary: dict[str, str]) -> str:
    """Biên tập lại 1 chương đã dịch theo glossary + nguyên tắc 'edit hay'."""
    if not current_translation.strip():
        return current_translation
    prompt = REWRITE_PROMPT.format(
        guidelines=EDIT_HAY_GUIDELINES,
        glossary=_format_glossary(glossary),
        raw=raw,
        translated=current_translation,
    )
    output = openai_client.run_chat(cfg.openai, prompt)
    return _apply_glossary(_clean_output(output), glossary)


_EMPTY_REPORT = {"summary": "", "score": None, "issues": []}


def _parse_evaluation(text: str) -> dict:
    """Parse JSON object báo cáo đánh giá. Lỗi parse -> report rỗng (không raise)."""
    text = _clean_output(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(text)
        if not match:
            return dict(_EMPTY_REPORT)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return dict(_EMPTY_REPORT)
    if not isinstance(data, dict):
        return dict(_EMPTY_REPORT)

    valid_categories = {"glossary", "consistency", "mistranslation", "hanviet", "fluency", "other"}
    valid_severities = {"high", "medium", "low"}
    issues = []
    for item in data.get("issues", []) if isinstance(data.get("issues"), list) else []:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        severity = item.get("severity")
        issues.append(
            {
                "category": category if category in valid_categories else "other",
                "severity": severity if severity in valid_severities else "low",
                "chapter": str(item.get("chapter", "")).strip(),
                "source": str(item.get("source", "")).strip(),
                "current": str(item.get("current", "")).strip(),
                "suggestion": str(item.get("suggestion", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
            }
        )

    score = data.get("score")
    try:
        score = int(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {"summary": str(data.get("summary", "")).strip(), "score": score, "issues": issues}


def evaluate_translation(
    cfg: TranslateConfig,
    chapters: list[tuple[str, str]],
    glossary: dict[str, str],
) -> dict:
    """Gọi AI đánh giá glossary + bản dịch của các chương đã chọn, trả report.

    Read-only: không sửa file, không áp dụng gì. Lỗi gọi CLI hoặc parse JSON
    không raise — trả report rỗng để không sập UI.
    """
    raw_combined = "\n\n".join(raw for raw, _ in chapters if raw.strip())
    translated_combined = "\n\n".join(t for _, t in chapters if t.strip())
    if not raw_combined.strip() and not translated_combined.strip():
        return dict(_EMPTY_REPORT)

    glossary_text = _format_glossary(glossary) or "(chưa có mục nào)"
    prompt = EVALUATE_PROMPT.format(glossary=glossary_text, raw=raw_combined, translated=translated_combined)
    try:
        output = openai_client.run_chat(cfg.openai, prompt)
    except Exception:
        return dict(_EMPTY_REPORT)

    return _parse_evaluation(output)


def format_evaluation_text(report: dict) -> str:
    """Định dạng report thành plain-text cho CLI / log."""
    lines: list[str] = []
    summary = report.get("summary", "")
    score = report.get("score")
    if score is not None:
        lines.append(f"Điểm: {score}/10")
    if summary:
        lines.append(f"Nhận xét: {summary}")
    issues = report.get("issues", [])
    if not issues:
        lines.append("Không phát hiện vấn đề nào.")
        return "\n".join(lines)
    lines.append(f"Vấn đề ({len(issues)}):")
    for i, it in enumerate(issues, 1):
        head = f"  {i}. [{it.get('severity', '')}/{it.get('category', '')}]"
        chapter = it.get("chapter", "")
        if chapter:
            head += f" chương {chapter}"
        source = it.get("source", "")
        if source:
            head += f" — {source}"
        lines.append(head)
        current = it.get("current", "")
        suggestion = it.get("suggestion", "")
        if current or suggestion:
            lines.append(f"     {current} -> {suggestion}")
        reason = it.get("reason", "")
        if reason:
            lines.append(f"     Lý do: {reason}")
    return "\n".join(lines)
