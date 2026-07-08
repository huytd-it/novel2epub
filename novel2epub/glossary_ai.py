"""AI hỗ trợ quản lý glossary và "edit hay" bản dịch — tách riêng khỏi luồng
dịch chương chính (translator.py) vì dùng prompt khác hẳn (phân tích/biên tập,
không phải dịch từ đầu).
"""
from __future__ import annotations

import json
import re

from . import openai_client
from .config import OpenAIConfig
from .translator import (
    _apply_glossary,
    _clean_output,
    _filter_glossary,
    _format_glossary,
    load_glossary_dict,
)

SUGGEST_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt, chuyên xây dựng glossary nhất quán.

Nhiệm vụ: đọc bản gốc tiếng Trung và bản dịch tiếng Việt hiện tại dưới đây, đề xuất các mục glossary mới. Glossary là bảng để ĐỒNG BỘ cách dịch xuyên suốt truyện, KHÔNG phải từ điển — thà bỏ sót còn hơn đề xuất nhầm từ thông thường.

CHỈ đề xuất khi thỏa mãn (đưa vào target_file tương ứng):
1. names.txt — tên riêng: nhân vật, địa danh, môn phái/tổ chức, chức danh/tước vị.
2. vietphrase.txt — thuật ngữ ĐẶC THÙ của thế giới truyện, lặp lại nhiều lần: công pháp, chiêu thức, cảnh giới tu luyện, linh thú, pháp bảo, đan dược, chủng tộc, hệ thống sức mạnh, biệt danh/xưng hiệu cố định.

TUYỆT ĐỐI KHÔNG đề xuất (đây là lỗi làm bẩn glossary):
- Từ ngữ đời thường: đồ ăn thức uống, mua sắm, động tác, cảm xúc, nghề nghiệp thông thường, vật dụng phổ thông (vd: kệ hàng, cơm thừa canh cặn, chạy việc vặt, gà thả vườn, thu dọn...).
- Thành ngữ/tục ngữ/khẩu ngữ/tiếng lóng dịch thoát ý (vd: khó đỡ, yêu nhau giết nhau, phát điên...).
- Từ hiện đại phổ thông (vd: ứng dụng đặt xe, khu du lịch sinh thái, tên lửa đẩy...) — trừ khi là khái niệm đặc thù, lặp lại nhiều lần cần dịch thống nhất.
- Bất kỳ từ nào độc giả Việt đọc hiểu ngay, hoặc chỉ xuất hiện một lần.

Ràng buộc chung:
- Không đề xuất lại mục đã có sẵn trong glossary hiện tại (xem danh sách dưới).
- Không bịa thêm tên/thuật ngữ không xuất hiện trong văn bản.
- Không spoil, không thêm bình luận ngoài truyện.

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
    ai_cfg: OpenAIConfig,
    chapters: list[tuple[str, str]],
    existing_glossary: dict[str, str],
    *,
    filter_glossary: bool = True,
) -> list[dict]:
    """Gọi AI phân tích raw+translated của các chương đã chọn, trả list suggestion.

    Lỗi gọi CLI hoặc parse JSON không raise — trả [] để không sập UI, lỗi cụ thể
    do caller tự log nếu cần (xem ngoại lệ bị nuốt có chủ đích ở đây).
    """
    raw_combined = "\n\n".join(raw for raw, _ in chapters if raw.strip())
    translated_combined = "\n\n".join(t for _, t in chapters if t.strip())
    if not raw_combined.strip() and not translated_combined.strip():
        return []

    prompt_glossary = existing_glossary
    if filter_glossary:
        # Khối {existing} chỉ để AI tránh gợi ý trùng; mục hợp lệ bắt buộc phải
        # xuất hiện trong text nên lọc theo text không làm mất thông tin. Dedup
        # Python bên dưới vẫn dùng FULL existing_glossary.
        prompt_glossary = _filter_glossary(
            existing_glossary, zh_text=raw_combined, vi_text=translated_combined
        )
    existing_text = _format_glossary(prompt_glossary) or "(chưa có mục nào)"
    prompt = SUGGEST_PROMPT.format(existing=existing_text, raw=raw_combined, translated=translated_combined)
    try:
        output = openai_client.run_chat(ai_cfg, prompt)
    except Exception:
        return []

    suggestions = _parse_suggestions(output)
    return [s for s in suggestions if existing_glossary.get(s["source"]) != s["suggested"]]


# Alias công khai — glossary_ai dùng lại đúng logic gộp glossary của translator
# để tránh 2 nơi đọc file names.txt/vietphrase.txt theo 2 cách khác nhau.
load_glossary = load_glossary_dict


def rewrite_chapter(
    ai_cfg: OpenAIConfig,
    raw: str,
    current_translation: str,
    glossary: dict[str, str],
    *,
    filter_glossary: bool = True,
) -> str:
    """Biên tập lại 1 chương đã dịch theo glossary + nguyên tắc 'edit hay'."""
    if not current_translation.strip():
        return current_translation
    prompt_glossary = (
        _filter_glossary(glossary, zh_text=raw, vi_text=current_translation)
        if filter_glossary
        else glossary
    )
    prompt = REWRITE_PROMPT.format(
        guidelines=EDIT_HAY_GUIDELINES,
        glossary=_format_glossary(prompt_glossary),
        raw=raw,
        translated=current_translation,
    )
    output = openai_client.run_chat(ai_cfg, prompt)
    return _apply_glossary(_clean_output(output), glossary)


FIX_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt. Người đọc đã đánh dấu các chỗ dịch có vấn đề kèm ghi chú. Nhiệm vụ của bạn: đề xuất bản sửa cho TỪNG chỗ được đánh dấu.

{guidelines}
{glossary}

--- Bản gốc (Trung), dùng để đối chiếu ---
{raw}

--- Bản dịch hiện tại (Việt) ---
{translated}

--- Các ghi chú lỗi cần sửa ---
{notes}

Yêu cầu:
1. Với mỗi ghi chú, `fixed_text` là đoạn văn bản THAY THẾ đúng phần được đánh dấu «...» — KHÔNG viết lại cả đoạn, không thêm/bớt nội dung ngoài phạm vi được đánh dấu.
2. Sửa theo ghi chú của người đọc, đối chiếu bản gốc Trung và tuân thủ glossary.
3. Nếu chỗ đánh dấu thực ra đã ổn, vẫn trả về mục đó với fixed_text giữ nguyên và giải thích lý do.

Chỉ trả về JSON array, không kèm giải thích ngoài JSON, không dùng code fence. Mỗi phần tử có dạng:
{{"id": "<id ghi chú>", "fixed_text": "<đoạn thay thế>", "explanation": "<giải thích ngắn>"}}
"""


def _format_fix_notes(notes: list[dict]) -> str:
    """Định dạng danh sách ghi chú cho FIX_PROMPT: id + đoạn + text được chọn + ghi chú."""
    blocks = []
    for n in notes:
        blocks.append(
            f"[{n.get('id', '')}] Đoạn {n.get('para_index', '?')}: «{n.get('selected_text', '')}»\n"
            f"Ngữ cảnh đoạn: {n.get('para_text', '')}\n"
            f"Ghi chú: {n.get('note', '')}"
        )
    return "\n\n".join(blocks)


def _parse_fixes(text: str, valid_ids: set[str]) -> list[dict]:
    """Parse JSON array đề xuất sửa. Loại mục có id lạ hoặc fixed_text rỗng."""
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

    fixes = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        fix_id = str(item.get("id", "")).strip()
        fixed_text = str(item.get("fixed_text", "")).strip()
        if fix_id not in valid_ids or fix_id in seen or not fixed_text:
            continue
        seen.add(fix_id)
        fixes.append(
            {
                "id": fix_id,
                "fixed_text": fixed_text,
                "explanation": str(item.get("explanation", "")).strip(),
            }
        )
    return fixes


def fix_passages(
    ai_cfg: OpenAIConfig,
    raw: str,
    translated: str,
    notes: list[dict],
    glossary: dict[str, str],
    *,
    filter_glossary: bool = True,
) -> list[dict]:
    """Gọi AI sửa các chỗ dịch được người đọc đánh dấu kèm ghi chú.

    Trả list {id, fixed_text, explanation}. KHÁC suggest_glossary: RuntimeError
    từ openai_client được cho lan ra để route trả 502 kèm thông báo thật —
    luồng tương tác (người dùng bấm nút chờ kết quả) cần thấy lỗi cụ thể.
    """
    if not notes:
        return []
    prompt_glossary = (
        _filter_glossary(glossary, zh_text=raw or "", vi_text=translated)
        if filter_glossary
        else glossary
    )
    prompt = FIX_PROMPT.format(
        guidelines=EDIT_HAY_GUIDELINES,
        glossary=_format_glossary(prompt_glossary),
        raw=raw or "(chưa có bản gốc)",
        translated=translated,
        notes=_format_fix_notes(notes),
    )
    output = openai_client.run_chat(ai_cfg, prompt)
    return _parse_fixes(output, {str(n.get("id", "")) for n in notes})


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
    ai_cfg: OpenAIConfig,
    chapters: list[tuple[str, str]],
    glossary: dict[str, str],
) -> dict:
    """Gọi AI đánh giá glossary + bản dịch của các chương đã chọn, trả report.

    Read-only: không sửa file, không áp dụng gì. Lỗi gọi CLI hoặc parse JSON
    không raise — trả report rỗng để không sập UI. Luôn dùng TOÀN BỘ glossary
    (không lọc theo translate.glossary_filter) vì mục đích là audit cả bảng
    glossary (tìm mục thừa/trùng/mâu thuẫn), không chỉ mục xuất hiện trong đoạn.
    """
    raw_combined = "\n\n".join(raw for raw, _ in chapters if raw.strip())
    translated_combined = "\n\n".join(t for _, t in chapters if t.strip())
    if not raw_combined.strip() and not translated_combined.strip():
        return dict(_EMPTY_REPORT)

    glossary_text = _format_glossary(glossary) or "(chưa có mục nào)"
    prompt = EVALUATE_PROMPT.format(glossary=glossary_text, raw=raw_combined, translated=translated_combined)
    try:
        output = openai_client.run_chat(ai_cfg, prompt)
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
