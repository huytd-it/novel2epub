"""AI trích bảng NHÂN VẬT & quan hệ từ chương raw — tách khỏi `glossary_ai.py`
vì prompt và cấu trúc đầu ra khác hẳn.

Quyết định nền: GOM NHÓM chương, không chạy từng chương như
`batch/suggest-glossary`. Mốc đổi xưng hô chỉ tồn tại khi so sánh được hai thời
điểm — chạy rời rạc thì chương 2 và chương 120 là hai lời gọi không biết gì về
nhau, và AI không có cơ sở nhận ra quan hệ đã chuyển giai đoạn.

Ràng buộc trung tâm: chữ Hán gốc KHÁC bản Việt hoá. `师父`/`弟子` có thật trong
văn bản; "sư phụ"/"đồ nhi" là lựa chọn dịch. Mỗi xưng hô lưu hai phần (`*_raw`,
`*_vi`) để người duyệt biết AI dựa vào chữ nào, và để map lại hàng loạt khi đổi
phong cách dịch. `raw` không bao giờ vào prompt dịch.

Mọi thứ ở đây là logic thuần TRỪ `extract_characters` — hàm duy nhất gọi mạng.
"""
from __future__ import annotations

import json
import re

from . import openai_client

# Bằng chứng dài hơn mức này bị cắt — hàng chờ nằm trong một ô JSON, để nguyên
# câu dài sẽ phình vô ích.
MAX_EVIDENCE = 200

_CONFIDENCE = ("high", "medium", "low")
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


EXTRACT_PROMPT = """Bạn là trợ lý phân tích truyện Trung Quốc để dựng BẢNG NHÂN VẬT & NGÔI XƯNG phục vụ dịch sang tiếng Việt.

Nhiệm vụ: đọc các chương dưới đây (mỗi chương có nhãn `## Chương N`) và trả về danh sách nhân vật cùng quan hệ xưng hô giữa họ.

PHÂN BIỆT BẮT BUỘC — chữ Hán gốc KHÁC bản dịch tiếng Việt:
- Trong bản gốc có sẵn các dạng xưng hô như 师父, 师尊, 弟子, 徒儿, 为师, 姑娘, 公子, 师兄, 师妹, 在下, 晚辈, 前辈, 本座, 朕, 臣, 妾身, 奴家, 本王, 老朽, 小生...
- "sư phụ", "đồ nhi", "cô nương", "tại hạ" KHÔNG có trong bản gốc — đó là bản Việt hoá do bạn chọn.
- Vì vậy mỗi xưng hô phải trả về CẢ HAI: `*_raw` (chuỗi Hán có thật trong văn bản) và `*_vi` (bản Việt bạn đề xuất).
- Không tìm thấy chuỗi Hán tương ứng thì `*_raw` để null, KHÔNG được bịa.

LUẬT:
1. KHÔNG bịa khi thiếu căn cứ. Đoạn chỉ có 他说："你好。" thì không đủ cơ sở kết luận xưng hô nào — trả `a_calls_b_vi: null`, `a_self_vi: null`, `confidence: "low"`. Đừng đoán bừa theo thể loại.
2. Phân biệt CHỨNG CỨ TRỰC TIẾP với SUY LUẬN. Trích được câu thoại có xưng hô → `inferred: false`, `confidence: "high"`. Suy ra từ thái độ, bối cảnh, cách người khác gọi → `inferred: true`, `confidence: "medium"` hoặc thấp hơn. Luôn điền `evidence` là câu Hán ngắn làm căn cứ.
3. Ưu tiên xưng hô ĐẶC THÙ hơn đại từ chung: 朕 → "trẫm" (không phải "ta"), 为师 → "vi sư", 本座 → "bổn tọa", 妾身 → "thiếp". Chỉ lùi về đại từ chung khi bản gốc thật sự chỉ có 我/你/他/她.
4. Một cặp nhân vật có thể có NHIỀU mốc xưng hô. Nếu thấy quan hệ đổi giữa các chương (xa lạ → thân mật), trả về NHIỀU mục cho cùng cặp đó với `from_chapter` khác nhau. KHÔNG gộp cứng thành một dòng.
5. KHÔNG đề xuất lại nhân vật đã có trong danh sách bên dưới. Ngoại lệ duy nhất: phát hiện ALIAS MỚI của họ thì trả mục dạng `{{"source": "...", "update_only": true, "new_aliases_raw": [...], "new_aliases_vi": [...]}}`.
6. `to_chapter` mặc định null (còn hiệu lực tới mốc kế tiếp). CHỈ điền khi quan hệ chấm dứt dứt khoát mà không có mốc sau — nhân vật chết, đoạn tuyệt, rời truyện.

Nhân vật đã có (KHÔNG đề xuất lại, xem luật 5):
{existing}

Glossary hiện có (dùng đúng các tên này khi dịch tên riêng):
{glossary}

Thể loại truyện: {genre}

{chapters}

Chỉ trả về JSON, không kèm giải thích, không dùng code fence:
{{"characters": [
   {{"source": "<Hán>", "target": "<tên Việt>", "aliases_raw": [], "aliases_vi": [],
    "gender": "nam|nu|", "self_pronoun": "<tự xưng, tiếng Việt>",
    "narrator_ref": "<lời kể gọi, tiếng Việt>", "role_note": "<vai trò, 1 dòng>",
    "importance": "main|side", "reason": "<lý do ngắn>", "confidence": "high|medium|low"}}
 ],
 "relations": [
   {{"a_source": "<Hán>", "b_source": "<Hán>", "from_chapter": <số>, "to_chapter": null,
    "a_calls_b_raw": "<Hán hoặc null>", "a_calls_b_vi": "<Việt hoặc null>",
    "a_self_raw": "<Hán hoặc null>", "a_self_vi": "<Việt hoặc null>",
    "evidence": "<câu Hán ngắn>", "inferred": true|false,
    "confidence": "high|medium|low", "reason": "<lý do ngắn>"}}
 ]}}
Không có gì để đề xuất thì trả {{"characters": [], "relations": []}}.
"""


def group_chapters(
    chapters: list[tuple[int, str, str]], max_chars: int
) -> list[list[tuple[int, str, str]]]:
    """Chia chương thành nhóm sao cho mỗi nhóm vừa `max_chars`.

    Chương dài hơn cả ngân sách vẫn thành nhóm RIÊNG chứ không bị bỏ — thà một
    lời gọi quá khổ còn hơn mất hẳn chương đó khỏi phân tích.
    """
    groups: list[list[tuple[int, str, str]]] = []
    current: list[tuple[int, str, str]] = []
    size = 0
    for ch in chapters:
        length = len(ch[1]) + len(ch[2])
        if current and size + length > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(ch)
        size += length
    if current:
        groups.append(current)
    return groups


def format_chapters_block(group: list[tuple[int, str, str]]) -> str:
    """Render một nhóm chương cho prompt. Nhãn `## Chương N` là thứ cho phép AI
    gắn mốc `from_chapter` — bỏ nhãn là mất khả năng phát hiện quan hệ đổi."""
    parts: list[str] = []
    for index, raw, translated in group:
        block = f"## Chương {index}\n{raw.strip()}"
        if translated.strip():
            block += f"\n\n[Bản dịch hiện có]\n{translated.strip()}"
        parts.append(block)
    return "\n\n".join(parts)


def _clean_json_text(text: str) -> str:
    """Bỏ code fence quanh JSON nếu có."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _confidence(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in _CONFIDENCE else "low"


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _opt_str(value) -> str:
    """None/null → chuỗi rỗng; còn lại trim."""
    if value is None:
        return ""
    return str(value).strip()


def _parse_character(item: dict) -> dict | None:
    source = _opt_str(item.get("source"))
    if not source:
        return None
    if item.get("update_only"):
        # Mục chỉ bổ sung alias cho nhân vật đã có — không mang trường nào khác.
        return {
            "source": source,
            "update_only": True,
            "new_aliases_raw": _str_list(item.get("new_aliases_raw")),
            "new_aliases_vi": _str_list(item.get("new_aliases_vi")),
            "reason": _opt_str(item.get("reason")),
        }
    return {
        "source": source,
        "target": _opt_str(item.get("target")),
        "aliases_raw": _str_list(item.get("aliases_raw")),
        "aliases_vi": _str_list(item.get("aliases_vi")),
        "gender": _opt_str(item.get("gender")),
        "self_pronoun": _opt_str(item.get("self_pronoun")),
        "narrator_ref": _opt_str(item.get("narrator_ref")),
        "role_note": _opt_str(item.get("role_note")),
        "importance": _opt_str(item.get("importance")) or "side",
        "reason": _opt_str(item.get("reason")),
        "confidence": _confidence(item.get("confidence")),
        "update_only": False,
    }


def _parse_int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_relation(item: dict) -> dict | None:
    a = _opt_str(item.get("a_source"))
    b = _opt_str(item.get("b_source"))
    if not a or not b:
        return None
    calls_vi = _opt_str(item.get("a_calls_b_vi"))
    self_vi = _opt_str(item.get("a_self_vi"))
    # Luật 2: không có cả hai giá trị Việt thì mục này vô dụng cho prompt và chỉ
    # làm nhiễu bảng duyệt.
    if not calls_vi and not self_vi:
        return None
    evidence = _opt_str(item.get("evidence"))[:MAX_EVIDENCE]
    from_chapter = _parse_int_or_none(item.get("from_chapter"))
    return {
        "a_source": a,
        "b_source": b,
        "from_chapter": 0 if from_chapter is None else from_chapter,
        "to_chapter": _parse_int_or_none(item.get("to_chapter")),
        "a_calls_b_raw": _opt_str(item.get("a_calls_b_raw")),
        "a_calls_b_vi": calls_vi,
        "a_self_raw": _opt_str(item.get("a_self_raw")),
        "a_self_vi": self_vi,
        "evidence": evidence,
        "inferred": bool(item.get("inferred", False)),
        "confidence": _confidence(item.get("confidence")),
        "reason": _opt_str(item.get("reason")),
    }


def parse_extraction(text: str) -> dict:
    """Parse phản hồi AI thành `{"characters": [...], "relations": [...]}`.

    Khoan dung: chấp nhận code fence và JSON lẫn trong prose. Lỗi parse trả về
    dict rỗng chứ không raise — một nhóm hỏng không được giết cả job.
    """
    empty = {"characters": [], "relations": []}
    cleaned = _clean_json_text(text)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        match = _JSON_OBJECT.search(cleaned)
        if not match:
            return empty
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return empty
    if not isinstance(data, dict):
        return empty

    characters = []
    for item in data.get("characters") or []:
        if isinstance(item, dict):
            parsed = _parse_character(item)
            if parsed:
                characters.append(parsed)
    relations = []
    for item in data.get("relations") or []:
        if isinstance(item, dict):
            parsed = _parse_relation(item)
            if parsed:
                relations.append(parsed)
    return {"characters": characters, "relations": relations}


def _has_raw(rel: dict) -> bool:
    return bool(rel.get("a_calls_b_raw") or rel.get("a_self_raw"))


def _better_relation(new: dict, old: dict) -> bool:
    """True nếu `new` nên thay `old` theo luật xung đột (§8 của spec).

    Thứ tự: confidence cao hơn → có trích dẫn Hán trực tiếp → evidence dài hơn.
    Hết cả ba mà vẫn ngang thì giữ bản cũ và caller đánh dấu conflict.
    """
    new_rank = _CONFIDENCE_RANK.get(new.get("confidence", "low"), 1)
    old_rank = _CONFIDENCE_RANK.get(old.get("confidence", "low"), 1)
    if new_rank != old_rank:
        return new_rank > old_rank
    if _has_raw(new) != _has_raw(old):
        return _has_raw(new)
    return len(new.get("evidence", "")) > len(old.get("evidence", ""))


def _same_content(a: dict, b: dict) -> bool:
    keys = ("a_calls_b_vi", "a_self_vi", "a_calls_b_raw", "a_self_raw", "to_chapter")
    return all(a.get(k) == b.get(k) for k in keys)


def merge_extractions(results: list[dict]) -> dict:
    """Gộp kết quả nhiều nhóm chương thành một bộ đề xuất.

    Nhân vật: cùng `source` thì hợp nhất alias (giữ thứ tự, bỏ trùng) và lấy giá
    trị non-empty ĐẦU TIÊN cho mỗi trường vô hướng.

    Quan hệ: khoá theo `(a, b, from_chapter)` — nên hai mốc khác chương của cùng
    một cặp luôn được giữ cả hai (đây là giá trị chính của tính năng). Trùng
    khoá thì áp luật ưu tiên; không phân định được thì giữ bản đầu và đánh dấu
    `conflict` kèm bản bị loại, để UI hiện cả hai cho người dùng chọn.
    """
    chars: dict[str, dict] = {}
    for result in results:
        for item in result.get("characters", []):
            source = item["source"]
            existing = chars.get(source)
            if existing is None:
                chars[source] = dict(item)
                continue
            if existing.get("update_only") != item.get("update_only"):
                # Mục đầy đủ luôn thắng mục update_only cho cùng một nhân vật.
                if existing.get("update_only"):
                    merged = dict(item)
                    merged["new_aliases_raw"] = existing.get("new_aliases_raw", [])
                    merged["new_aliases_vi"] = existing.get("new_aliases_vi", [])
                    chars[source] = merged
                continue
            for key, value in item.items():
                if isinstance(value, list):
                    combined = list(existing.get(key) or [])
                    for v in value:
                        if v not in combined:
                            combined.append(v)
                    existing[key] = combined
                elif not existing.get(key) and value:
                    existing[key] = value

    rels: dict[tuple[str, str, int], dict] = {}
    for result in results:
        for item in result.get("relations", []):
            key = (item["a_source"], item["b_source"], item["from_chapter"])
            existing = rels.get(key)
            if existing is None:
                rels[key] = dict(item)
                continue
            if _same_content(existing, item):
                continue
            if _better_relation(item, existing):
                loser = existing
                winner = dict(item)
            elif _better_relation(existing, item):
                loser = item
                winner = existing
            else:
                # Không phân định được — giữ bản đầu, phơi bản kia ra UI thay vì
                # âm thầm chọn.
                winner = existing
                winner["conflict"] = True
                winner["conflict_with"] = dict(item)
                rels[key] = winner
                continue
            winner.pop("conflict", None)
            winner.pop("conflict_with", None)
            _ = loser
            rels[key] = winner

    return {"characters": list(chars.values()), "relations": list(rels.values())}


def _format_existing(existing_chars: dict[str, str]) -> str:
    if not existing_chars:
        return "(chưa có nhân vật nào)"
    return "\n".join(f"{src} = {tgt}" for src, tgt in existing_chars.items())


def _format_glossary(glossary: dict[str, str]) -> str:
    if not glossary:
        return "(chưa có mục nào)"
    return "\n".join(f"{src} = {tgt}" for src, tgt in glossary.items())


def extract_characters(
    ai_cfg,
    chapters: list[tuple[int, str, str]],
    existing_chars: dict[str, str],
    glossary: dict[str, str],
    *,
    genre: str = "auto",
    max_chars: int = 20000,
    log=None,
) -> dict:
    """Chạy AI trích nhân vật trên các chương đã chọn, trả bộ đề xuất đã gộp.

    Hàm DUY NHẤT trong module này chạm mạng. Một nhóm lỗi (mạng hỏng hoặc JSON
    rác) chỉ mất nhóm đó — các nhóm còn lại vẫn về đích, vì phân tích 20 chương
    mà hỏng cả job chỉ vì một lần gọi lỗi là quá đắt.
    """
    log = log or (lambda _msg: None)
    groups = group_chapters(chapters, max_chars)
    results: list[dict] = []
    for i, group in enumerate(groups, start=1):
        indexes = [c[0] for c in group]
        log(f"[trích-nhân-vật] nhóm {i}/{len(groups)}: chương {indexes}")
        prompt = EXTRACT_PROMPT.format(
            existing=_format_existing(existing_chars),
            glossary=_format_glossary(glossary),
            genre=genre or "auto",
            chapters=format_chapters_block(group),
        )
        try:
            output = openai_client.run_chat(ai_cfg, prompt)
        except Exception as exc:  # noqa: BLE001 - một nhóm hỏng không giết cả job
            log(f"[trích-nhân-vật] nhóm {i} lỗi gọi AI: {exc}")
            continue
        parsed = parse_extraction(output)
        log(f"[trích-nhân-vật] nhóm {i}: {len(parsed['characters'])} nhân vật, "
            f"{len(parsed['relations'])} quan hệ")
        results.append(parsed)
    return merge_extractions(results)
