# AI trích nhân vật & quan hệ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Để AI đọc các chương đã chọn và đề xuất sẵn bảng nhân vật + quan hệ
kèm mốc chương, người dùng chỉ việc duyệt thay vì gõ tay 40 nhân vật.

**Architecture:** Một module logic thuần (`characters_ai.py`) lo prompt, chia
nhóm chương, parse JSON và gộp kết quả; một hàm duy nhất gọi mạng; hàng chờ
duyệt nằm trong `ebook_extra_json` như `glossary_pending`; schema lên v6 để chứa
chữ Hán gốc, bằng chứng và độ tin cậy.

**Tech Stack:** Python 3.10+, SQLite, FastAPI + Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-07-31-characters-ai-extract-design.md`

## Global Constraints

- `novel2epub/characters_ai.py` là logic thuần TRỪ đúng một hàm gọi mạng
  (`extract_characters`). Mọi thứ khác test được không cần mạng, đúng khuôn
  `novel2epub/glossary_ai.py`.
- Không import gì từ `novel2epub.hachimimt` trong bất kỳ module mới nào —
  package đó kéo theo `sentencepiece` + `huggingface_hub` (dep TÙY CHỌN) ngay ở
  `__init__`, sẽ biến chúng thành bắt buộc trên đường dịch mặc định.
- **Chữ Hán gốc ≠ bản Việt hoá.** `*_raw` là chuỗi có thật trong bản gốc;
  `*_vi` là lựa chọn dịch. `raw` KHÔNG BAO GIỜ được chèn vào prompt dịch — nó
  chỉ phục vụ người duyệt và việc map lại về sau.
- Cột DB mới phải khai ở **HAI** nơi trong `novel2epub/db.py`: trong
  `CREATE TABLE` (cho DB tạo mới) VÀ trong `_ADDED_COLUMNS` (`db.py:234`, nơi
  `_ensure_columns` vá bằng `ALTER TABLE` cho DB đã tồn tại). Sub-project A đã
  merge nên DB của người dùng đang ở v5 và ĐÃ có hai bảng này — bỏ sót nửa sau
  thì máy họ thiếu cột và vỡ khi đọc, trong khi máy cài mới vẫn chạy tốt.
- Comment và docstring tiếng Việt.
- Chạy test: `pytest tests/ -q`. Có MỘT test đỏ chập chờn có sẵn,
  `tests/test_crawl_throttle.py::test_rate_limiter_spaces_out_calls` — flake về
  thời gian, đỏ cả trên `master`. Bỏ qua đúng test đó, mọi test đỏ khác là do
  thay đổi của bạn.
- Mỗi task kết thúc bằng một commit.

---

### Task 1: `characters_ai.py` — prompt, chia nhóm, parse, gộp

**Files:**
- Create: `novel2epub/characters_ai.py`
- Test: `tests/test_characters_ai.py`

**Interfaces:**
- Consumes: không có (thuần).
- Produces: `EXTRACT_PROMPT`, `group_chapters(chapters, max_chars) -> list[list[tuple[int, str, str]]]`,
  `format_chapters_block(group) -> str`, `parse_extraction(text) -> dict`,
  `merge_extractions(results) -> dict`. `chapters` là list
  `(index, raw, translated)`. Kết quả parse/merge là dict
  `{"characters": [...], "relations": [...]}` đúng shape hàng chờ ở §10 của spec.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_characters_ai.py`:

```python
"""Tests cho AI trích nhân vật & quan hệ (logic thuần, không gọi mạng)."""
from novel2epub import characters_ai as A


# ---------- chia nhóm chương ----------

def test_group_chapters_respects_budget():
    chapters = [(1, "a" * 400, ""), (2, "b" * 400, ""), (3, "c" * 400, "")]
    groups = A.group_chapters(chapters, max_chars=900)
    assert [[c[0] for c in g] for g in groups] == [[1, 2], [3]]


def test_group_chapters_keeps_oversized_chapter_as_own_group():
    # Chương dài hơn cả ngân sách vẫn phải được xử lý, không được bỏ rơi.
    chapters = [(1, "a" * 50, ""), (2, "b" * 5000, ""), (3, "c" * 50, "")]
    groups = A.group_chapters(chapters, max_chars=200)
    assert [c[0] for c in groups[1]] == [2]
    assert [c[0] for g in groups for c in g] == [1, 2, 3]


def test_group_chapters_empty():
    assert A.group_chapters([], max_chars=100) == []


def test_format_chapters_block_labels_chapter_numbers():
    out = A.format_chapters_block([(7, "原文七", "Bản dịch bảy")])
    assert "## Chương 7" in out
    assert "原文七" in out
    assert "Bản dịch bảy" in out


# ---------- parse ----------

_GOOD = """```json
{"characters": [{"source": "林凡", "target": "Lâm Phàm",
                 "aliases_raw": ["凡儿"], "aliases_vi": ["Phàm nhi"],
                 "gender": "nam", "self_pronoun": "ta", "narrator_ref": "hắn",
                 "importance": "main", "confidence": "high"}],
 "relations": [{"a_source": "林凡", "b_source": "玄尘子", "from_chapter": 1,
                "a_calls_b_raw": "师父", "a_calls_b_vi": "sư phụ",
                "a_self_raw": "弟子", "a_self_vi": "đồ nhi",
                "evidence": "师父，弟子回来了。", "inferred": false,
                "confidence": "high"}]}
```"""


def test_parse_extraction_handles_code_fence():
    out = A.parse_extraction(_GOOD)
    assert out["characters"][0]["source"] == "林凡"
    assert out["relations"][0]["a_calls_b_vi"] == "sư phụ"
    assert out["relations"][0]["inferred"] is False


def test_parse_extraction_finds_json_amid_prose():
    text = 'Đây là kết quả:\n{"characters": [], "relations": []}\nHết.'
    assert A.parse_extraction(text) == {"characters": [], "relations": []}


def test_parse_extraction_garbage_returns_empty():
    assert A.parse_extraction("không phải json") == {"characters": [], "relations": []}


def test_parse_extraction_drops_relation_with_no_vi_values():
    # Luật 2: quan hệ không có cả a_calls_b_vi lẫn a_self_vi thì vô dụng cho
    # prompt, chỉ làm nhiễu bảng duyệt.
    text = ('{"characters": [], "relations": [{"a_source":"A","b_source":"B",'
            '"a_calls_b_vi": null, "a_self_vi": null, "confidence":"low"}]}')
    assert A.parse_extraction(text)["relations"] == []


def test_parse_extraction_truncates_long_evidence():
    long_ev = "字" * 500
    text = ('{"characters": [], "relations": [{"a_source":"A","b_source":"B",'
            f'"a_self_vi":"ta","evidence":"{long_ev}"}}]}}')
    assert len(A.parse_extraction(text)["relations"][0]["evidence"]) == A.MAX_EVIDENCE


def test_parse_extraction_defaults_missing_flags():
    text = ('{"characters": [], "relations": [{"a_source":"A","b_source":"B",'
            '"a_self_vi":"ta"}]}')
    rel = A.parse_extraction(text)["relations"][0]
    assert rel["inferred"] is False
    assert rel["confidence"] == "low"      # thiếu thì coi là kém tin cậy nhất
    assert rel["from_chapter"] == 0
    assert rel["to_chapter"] is None


def test_parse_extraction_drops_character_without_source():
    text = '{"characters": [{"target": "X"}], "relations": []}'
    assert A.parse_extraction(text)["characters"] == []


# ---------- gộp nhóm ----------

def _rel(**kw):
    base = {"a_source": "林凡", "b_source": "苏清雪", "from_chapter": 2,
            "to_chapter": None, "a_calls_b_raw": "", "a_calls_b_vi": "cô nương",
            "a_self_raw": "", "a_self_vi": "tại hạ", "evidence": "",
            "inferred": True, "confidence": "medium", "reason": ""}
    base.update(kw)
    return base


def test_merge_unions_aliases_across_groups():
    g1 = {"characters": [{"source": "林凡", "target": "Lâm Phàm",
                          "aliases_raw": ["凡儿"], "aliases_vi": ["Phàm nhi"]}],
          "relations": []}
    g2 = {"characters": [{"source": "林凡", "target": "",
                          "aliases_raw": ["林公子"], "aliases_vi": ["Lâm công tử"]}],
          "relations": []}
    out = A.merge_extractions([g1, g2])
    assert len(out["characters"]) == 1
    assert out["characters"][0]["aliases_raw"] == ["凡儿", "林公子"]
    assert out["characters"][0]["target"] == "Lâm Phàm"   # non-empty đầu tiên thắng


def test_merge_keeps_distinct_milestones_of_same_pair():
    out = A.merge_extractions([
        {"characters": [], "relations": [_rel(from_chapter=2)]},
        {"characters": [], "relations": [_rel(from_chapter=120, a_calls_b_vi="nàng")]},
    ])
    assert sorted(r["from_chapter"] for r in out["relations"]) == [2, 120]


def test_merge_conflict_higher_confidence_wins():
    lo = _rel(confidence="low", a_calls_b_vi="X")
    hi = _rel(confidence="high", a_calls_b_vi="Y")
    out = A.merge_extractions([{"characters": [], "relations": [lo]},
                               {"characters": [], "relations": [hi]}])
    assert len(out["relations"]) == 1
    assert out["relations"][0]["a_calls_b_vi"] == "Y"


def test_merge_conflict_raw_beats_no_raw_at_equal_confidence():
    no_raw = _rel(a_calls_b_vi="X")
    with_raw = _rel(a_calls_b_vi="Y", a_calls_b_raw="姑娘")
    out = A.merge_extractions([{"characters": [], "relations": [no_raw]},
                               {"characters": [], "relations": [with_raw]}])
    assert out["relations"][0]["a_calls_b_vi"] == "Y"


def test_merge_conflict_longer_evidence_wins_at_equal_rank():
    short = _rel(a_calls_b_vi="X", evidence="短")
    long = _rel(a_calls_b_vi="Y", evidence="长长长长长")
    out = A.merge_extractions([{"characters": [], "relations": [short]},
                               {"characters": [], "relations": [long]}])
    assert out["relations"][0]["a_calls_b_vi"] == "Y"


def test_merge_unresolvable_conflict_is_flagged_not_silently_dropped():
    a = _rel(a_calls_b_vi="X")
    b = _rel(a_calls_b_vi="Y")
    out = A.merge_extractions([{"characters": [], "relations": [a]},
                               {"characters": [], "relations": [b]}])
    kept = out["relations"][0]
    assert kept["a_calls_b_vi"] == "X"          # bản đầu được giữ
    assert kept["conflict"] is True
    assert kept["conflict_with"]["a_calls_b_vi"] == "Y"


def test_merge_update_only_carries_aliases_only():
    g = {"characters": [{"source": "林凡", "update_only": True,
                         "new_aliases_raw": ["凡儿"], "new_aliases_vi": ["Phàm nhi"]}],
         "relations": []}
    out = A.merge_extractions([g])
    ch = out["characters"][0]
    assert ch["update_only"] is True
    assert ch["new_aliases_raw"] == ["凡儿"]
    assert ch.get("gender", "") == ""
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_characters_ai.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novel2epub.characters_ai'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `novel2epub/characters_ai.py`:

```python
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

Mọi thứ ở đây là logic thuần TRỪ `extract_characters` (Task 3) — hàm duy nhất
gọi mạng.
"""
from __future__ import annotations

import json
import re

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
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_characters_ai.py -v`
Expected: PASS — 17 test.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/characters_ai.py tests/test_characters_ai.py
git commit -m "feat: prompt + chia nhóm + parse + gộp cho AI trích nhân vật"
```

---

### Task 2: Schema v6, `to_chapter`, và Storage

**Files:**
- Modify: `novel2epub/db.py` (`CREATE TABLE` + `_ADDED_COLUMNS`, `SCHEMA_VERSION` 5 → 6)
- Modify: `novel2epub/characters.py` (`Relation` thêm trường, `relations_from_rows`, `resolve_relations`)
- Modify: `novel2epub/storage.py` (`read_relation_entries`, `upsert_relation`, `read_character_entries`, `upsert_character`)
- Test: `tests/test_characters.py`, `tests/test_storage_characters.py`, `tests/test_db_schema.py` (bổ sung cả ba)

**Interfaces:**
- Consumes: `Relation`, `relations_from_rows`, `resolve_relations` từ sub-project A.
- Produces: `Relation` có thêm `to_chapter: int | None = None`, `a_calls_b_raw: str = ""`,
  `a_self_raw: str = ""`, `evidence: str = ""`, `inferred: bool = False`,
  `confidence: str = ""`. Row tuple của `read_relation_entries` là 12 phần tử,
  6 phần tử cũ GIỮ NGUYÊN THỨ TỰ, 6 phần tử mới NỐI VÀO CUỐI. Row tuple của
  `read_character_entries` là 9 phần tử, `aliases_vi` nối vào cuối.

**Vì sao nối vào cuối:** `relations_from_rows` và `characters_from_rows` đọc
theo VỊ TRÍ và đã có guard `len(row) > N`. Nối vào cuối giữ mọi test và mọi
caller của A chạy nguyên vẹn; chèn vào giữa sẽ làm lệch dữ liệu một cách IM
LẶNG — đúng hình dạng, sai nội dung, không exception.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_characters.py`:

```python
# ---------- to_chapter (sub-project B) ----------

def test_resolve_relations_without_to_chapter_unchanged():
    # Chống hồi quy cho sub-project A: to_chapter rỗng thì hành vi y hệt trước.
    r0 = Relation("A", "B", 0, "nàng", "ta")
    r120 = Relation("A", "B", 120, "em", "anh")
    assert C.resolve_relations([r0, r120], 200) == [r120]
    assert C.resolve_relations([r0, r120], 50) == [r0]


def test_resolve_relations_respects_to_chapter_end():
    # Quan hệ chấm dứt ở ch.99 và KHÔNG có mốc kế tiếp → sau đó không áp dụng.
    ended = Relation("A", "B", 0, "sư phụ", "đồ nhi", to_chapter=99)
    assert C.resolve_relations([ended], 50) == [ended]
    assert C.resolve_relations([ended], 100) == []


def test_resolve_relations_to_chapter_alongside_later_milestone():
    ended = Relation("A", "B", 0, "cô nương", "tại hạ", to_chapter=99)
    later = Relation("A", "B", 120, "nàng", "ta")
    assert C.resolve_relations([ended, later], 50) == [ended]
    assert C.resolve_relations([ended, later], 110) == []      # khe hở 100-119
    assert C.resolve_relations([ended, later], 200) == [later]


def test_relations_from_rows_accepts_legacy_six_tuple():
    # Row cũ 6 phần tử vẫn dựng được, trường mới nhận mặc định.
    out = C.relations_from_rows([("A", "B", 5, "x", "y", "")])
    assert out[0].to_chapter is None
    assert out[0].a_calls_b_raw == ""
    assert out[0].inferred is False


def test_relations_from_rows_reads_new_columns():
    row = ("A", "B", 5, "sư phụ", "đồ nhi", "", 99, "师父", "弟子", "证据", 1, "high")
    rel = C.relations_from_rows([row])[0]
    assert rel.to_chapter == 99
    assert rel.a_calls_b_raw == "师父"
    assert rel.a_self_raw == "弟子"
    assert rel.evidence == "证据"
    assert rel.inferred is True
    assert rel.confidence == "high"


def test_characters_from_rows_reads_aliases_vi():
    row = ("林凡", "Lâm Phàm", "凡儿", "nam", "ta", "hắn", "", "main", "Phàm nhi")
    ch = C.characters_from_rows([row])[0]
    assert ch.aliases == ("凡儿",)
    assert ch.aliases_vi == ("Phàm nhi",)
```

Thêm vào `tests/test_storage_characters.py`:

```python
def test_relation_roundtrip_new_columns(storage):
    storage.upsert_relation("林凡", "苏清雪", 2, "cô nương", "tại hạ",
                            to_chapter=119, a_calls_b_raw="姑娘",
                            a_self_raw="在下", evidence="林公子，请自重。",
                            inferred=True, confidence="medium")
    row = storage.read_relation_entries()[0]
    assert row[2] == 2            # from_chapter
    assert row[6] == 119          # to_chapter
    assert row[7] == "姑娘"
    assert row[8] == "在下"
    assert row[9] == "林公子，请自重。"
    assert row[10] == 1           # inferred
    assert row[11] == "medium"


def test_relation_to_chapter_defaults_null(storage):
    storage.upsert_relation("A", "B", 0, "x", "y")
    assert storage.read_relation_entries()[0][6] is None


def test_character_aliases_vi_roundtrip(storage):
    storage.upsert_character("林凡", "Lâm Phàm", "凡儿", aliases_vi="Phàm nhi")
    row = storage.read_character_entries()[0]
    assert row[2] == "凡儿"
    assert row[8] == "Phàm nhi"
```

Thêm vào `tests/test_db_schema.py` (đọc file trước, dùng đúng style sẵn có ở đó):

```python
def test_schema_v6_columns_present():
    from novel2epub import db
    conn = db.get_connection(":memory:")
    db.init_schema(conn)
    rel_cols = {r[1] for r in conn.execute("PRAGMA table_info(character_relations)")}
    for col in ("to_chapter", "a_calls_b_raw", "a_self_raw", "evidence",
                "inferred", "confidence"):
        assert col in rel_cols
    char_cols = {r[1] for r in conn.execute("PRAGMA table_info(characters)")}
    assert "aliases_vi" in char_cols
    assert db.SCHEMA_VERSION == 6


def test_v5_database_gets_new_columns_without_data_loss():
    """DB đã tồn tại ở v5 (bảng có sẵn, thiếu cột mới) phải được ALTER TABLE vá.

    Đây là ca THẬT của người dùng: sub-project A đã merge nên DB của họ có hai
    bảng này rồi, và CREATE TABLE IF NOT EXISTS sẽ không thêm cột.
    """
    from novel2epub import db
    conn = db.get_connection(":memory:")
    conn.execute("CREATE TABLE ebooks (slug TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO ebooks (slug) VALUES ('t')")
    conn.execute(
        "CREATE TABLE character_relations (ebook_slug TEXT NOT NULL, "
        "a_source TEXT NOT NULL, b_source TEXT NOT NULL, "
        "from_chapter INTEGER NOT NULL DEFAULT 0, a_calls_b TEXT NOT NULL DEFAULT '', "
        "a_self TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (ebook_slug, a_source, b_source, from_chapter))"
    )
    conn.execute(
        "INSERT INTO character_relations (ebook_slug, a_source, b_source, "
        "from_chapter, a_calls_b, a_self) VALUES ('t','A','B',5,'sư phụ','đồ nhi')"
    )
    conn.commit()

    db.init_schema(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(character_relations)")}
    assert "to_chapter" in cols and "confidence" in cols
    row = conn.execute(
        "SELECT a_calls_b, a_self, to_chapter FROM character_relations"
    ).fetchone()
    assert row[0] == "sư phụ" and row[1] == "đồ nhi" and row[2] is None
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_characters.py tests/test_storage_characters.py tests/test_db_schema.py -v`
Expected: FAIL — `TypeError: Relation.__init__() got an unexpected keyword argument 'to_chapter'` và `assert db.SCHEMA_VERSION == 6`.

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `novel2epub/db.py`: đổi `SCHEMA_VERSION = 5` thành `SCHEMA_VERSION = 6`.

Thêm cột vào `CREATE TABLE characters` (sau `importance`):

```sql
        aliases_vi   TEXT NOT NULL DEFAULT '',
```

Thêm cột vào `CREATE TABLE character_relations` (sau `note`):

```sql
        to_chapter    INTEGER,
        a_calls_b_raw TEXT NOT NULL DEFAULT '',
        a_self_raw    TEXT NOT NULL DEFAULT '',
        evidence      TEXT NOT NULL DEFAULT '',
        inferred      INTEGER NOT NULL DEFAULT 0,
        confidence    TEXT NOT NULL DEFAULT '',
```

Và — BẮT BUỘC, đây là nửa mà DB v5 hiện có của người dùng phụ thuộc vào — thêm
vào cuối `_ADDED_COLUMNS`:

```python
    # v6: AI trích nhân vật — chữ Hán gốc, bằng chứng, độ tin cậy, mốc kết thúc
    ("characters", "aliases_vi", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "to_chapter", "INTEGER"),
    ("character_relations", "a_calls_b_raw", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "a_self_raw", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "evidence", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "inferred", "INTEGER NOT NULL DEFAULT 0"),
    ("character_relations", "confidence", "TEXT NOT NULL DEFAULT ''"),
```

Trong `novel2epub/characters.py`, `Character` thêm một trường (nối CUỐI):

```python
    aliases_vi: tuple[str, ...] = ()
```

`Relation` thêm sáu trường (nối CUỐI):

```python
    to_chapter: int | None = None
    a_calls_b_raw: str = ""
    a_self_raw: str = ""
    evidence: str = ""
    inferred: bool = False
    confidence: str = ""
```

`characters_from_rows` đọc thêm cột 8:

```python
                aliases_vi=_split_aliases(row[8] if len(row) > 8 else ""),
```

`relations_from_rows` đọc thêm cột 6..11 (thêm vào lời gọi `Relation(...)`):

```python
                to_chapter=(
                    int(row[6]) if len(row) > 6 and row[6] is not None else None
                ),
                a_calls_b_raw=(row[7] or "").strip() if len(row) > 7 else "",
                a_self_raw=(row[8] or "").strip() if len(row) > 8 else "",
                evidence=(row[9] or "").strip() if len(row) > 9 else "",
                inferred=bool(row[10]) if len(row) > 10 else False,
                confidence=(row[11] or "").strip() if len(row) > 11 else "",
```

`resolve_relations` — thêm ĐÚNG một điều kiện, giữ nguyên phần còn lại:

```python
    for rel in relations:
        if rel.from_chapter > limit:
            continue
        # to_chapter rỗng = còn hiệu lực tới mốc kế tiếp (hoặc mãi mãi). Chỉ khi
        # được điền tường minh thì quan hệ mới hết hiệu lực sau chương đó — ca
        # nhân vật chết / đoạn tuyệt, nơi không có mốc kế tiếp nào thay thế.
        if rel.to_chapter is not None and limit > rel.to_chapter:
            continue
```

Cập nhật docstring của `resolve_relations` để nói về `to_chapter`.

Trong `novel2epub/storage.py`:

`read_character_entries` — thêm `aliases_vi` vào SELECT và vào tuple trả về (vị
trí CUỐI, thành 9 phần tử).

`upsert_character` — thêm kwarg `aliases_vi: str = ""` (đặt CUỐI danh sách tham
số để lời gọi theo vị trí sẵn có không vỡ), thêm cột vào INSERT và vào
`ON CONFLICT DO UPDATE SET`.

`read_relation_entries` — SELECT thêm sáu cột, trả tuple 12 phần tử theo đúng
thứ tự: `(a_source, b_source, from_chapter, a_calls_b, a_self, note, to_chapter,
a_calls_b_raw, a_self_raw, evidence, inferred, confidence)`.

`upsert_relation` — thêm sáu kwarg (đặt CUỐI): `to_chapter: int | None = None`,
`a_calls_b_raw: str = ""`, `a_self_raw: str = ""`, `evidence: str = ""`,
`inferred: bool = False`, `confidence: str = ""`. Thêm vào INSERT và
`ON CONFLICT DO UPDATE SET`. `to_chapter` giữ `None` thành SQL NULL, KHÔNG ép về 0.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_characters.py tests/test_storage_characters.py tests/test_db_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `pytest tests/ -q`
Expected: chỉ còn flake `test_rate_limiter_spaces_out_calls`. Đặc biệt chú ý các
test của sub-project A gọi `upsert_relation`/`read_relation_entries` theo vị trí.

- [ ] **Step 6: Commit**

```bash
git add novel2epub/db.py novel2epub/characters.py novel2epub/storage.py tests/test_characters.py tests/test_storage_characters.py tests/test_db_schema.py
git commit -m "feat: schema v6 — chữ Hán gốc, bằng chứng, to_chapter cho quan hệ"
```

---

### Task 3: `extract_characters` + route + JobQueue

**Files:**
- Modify: `novel2epub/characters_ai.py` (thêm hàm gọi mạng)
- Modify: `app/routes/characters.py` (ba route hàng chờ)
- Modify: `app/routes/chapters.py` (route chạy job)
- Test: `tests/test_characters_ai.py`, `tests/test_routes_characters.py` (bổ sung)

**Interfaces:**
- Consumes: `group_chapters`, `format_chapters_block`, `parse_extraction`,
  `merge_extractions` (Task 1); `Storage.upsert_character`/`upsert_relation`
  với kwarg mới (Task 2); `novel2epub.openai_client.run_chat`;
  `Storage.read_extra_json`/`write_extra_json`.
- Produces: `extract_characters(ai_cfg, chapters, existing_chars, glossary, *, genre, max_chars, log=None) -> dict`;
  ba route `GET/POST /api/ebooks/{slug}/characters/pending[/approve|/clear]`;
  `POST /api/ebooks/{slug}/batch/extract-characters`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_characters_ai.py`:

```python
def test_extract_characters_merges_groups_and_survives_bad_json(monkeypatch):
    """Một nhóm trả rác không được giết cả lần chạy — nhóm còn lại vẫn về đích."""
    calls = []

    def fake_run_chat(cfg, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "hoàn toàn không phải JSON"
        return ('{"characters": [{"source":"林凡","target":"Lâm Phàm"}],'
                ' "relations": []}')

    monkeypatch.setattr(A.openai_client, "run_chat", fake_run_chat)
    out = A.extract_characters(
        object(), [(1, "x" * 300, ""), (2, "y" * 300, "")], {}, {},
        genre="xianxia", max_chars=400,
    )
    assert len(calls) == 2
    assert [c["source"] for c in out["characters"]] == ["林凡"]


def test_extract_characters_prompt_carries_chapter_labels(monkeypatch):
    seen = {}

    def fake_run_chat(cfg, prompt):
        seen["prompt"] = prompt
        return '{"characters": [], "relations": []}'

    monkeypatch.setattr(A.openai_client, "run_chat", fake_run_chat)
    A.extract_characters(object(), [(42, "原文", "")], {"林凡": "Lâm Phàm"},
                         {}, genre="urban", max_chars=10000)
    assert "## Chương 42" in seen["prompt"]
    assert "林凡" in seen["prompt"]        # glossary được nhét vào
```

Thêm vào `tests/test_routes_characters.py` (dùng đúng fixture `_cfg`/`_client`
sẵn có trong file — đọc file trước):

```python
def test_pending_roundtrip_and_approve_order(client, slug, storage):
    storage.write_extra_json("characters_pending", {
        "characters": [
            {"source": "林凡", "target": "Lâm Phàm", "aliases_raw": ["凡儿"],
             "aliases_vi": ["Phàm nhi"], "importance": "main"},
            {"source": "苏清雪", "target": "Tô Thanh Tuyết"},
        ],
        "relations": [
            {"a_source": "林凡", "b_source": "苏清雪", "from_chapter": 2,
             "a_calls_b_vi": "cô nương", "a_self_vi": "tại hạ",
             "evidence": "林公子，请自重。", "inferred": True,
             "confidence": "medium"},
        ],
    })
    data = client.get(f"/api/ebooks/{slug}/characters/pending").json()
    assert data["counts"] == {"characters": 2, "relations": 1}

    resp = client.post(f"/api/ebooks/{slug}/characters/pending/approve", json={
        "characters": [{"source": "林凡"}, {"source": "苏清雪"}],
        "relations": [{"a_source": "林凡", "b_source": "苏清雪", "from_chapter": 2}],
    })
    assert resp.status_code == 200
    assert resp.json()["blocked"] == []
    assert {r[0] for r in storage.read_character_entries()} == {"林凡", "苏清雪"}
    rel = storage.read_relation_entries()[0]
    assert rel[3] == "cô nương" and rel[11] == "medium"


def test_approve_relation_missing_endpoint_is_blocked_with_name(client, slug, storage):
    storage.write_extra_json("characters_pending", {
        "characters": [{"source": "林凡", "target": "Lâm Phàm"},
                       {"source": "苏清雪", "target": "Tô Thanh Tuyết"}],
        "relations": [{"a_source": "林凡", "b_source": "苏清雪", "from_chapter": 2,
                       "a_calls_b_vi": "cô nương"}],
    })
    # Duyệt quan hệ nhưng KHÔNG tick 苏清雪 → phải bị chặn, nêu đích danh.
    resp = client.post(f"/api/ebooks/{slug}/characters/pending/approve", json={
        "characters": [{"source": "林凡"}],
        "relations": [{"a_source": "林凡", "b_source": "苏清雪", "from_chapter": 2}],
    })
    assert resp.status_code == 200
    blocked = resp.json()["blocked"]
    assert len(blocked) == 1
    assert "苏清雪" in blocked[0]
    assert "Tô Thanh Tuyết" in blocked[0]
    assert storage.read_relation_entries() == []          # không tạo mồ côi
    assert [r[0] for r in storage.read_character_entries()] == ["林凡"]  # vẫn lưu


def test_approve_update_only_appends_aliases(client, slug, storage):
    storage.upsert_character("林凡", "Lâm Phàm", "凡儿")
    storage.write_extra_json("characters_pending", {
        "characters": [{"source": "林凡", "update_only": True,
                        "new_aliases_raw": ["林公子"],
                        "new_aliases_vi": ["Lâm công tử"]}],
        "relations": [],
    })
    client.post(f"/api/ebooks/{slug}/characters/pending/approve", json={
        "characters": [{"source": "林凡"}], "relations": [],
    })
    row = storage.read_character_entries()[0]
    assert row[1] == "Lâm Phàm"           # KHÔNG bị ghi đè
    assert row[2] == "凡儿|林公子"          # alias được NỐI THÊM
    assert row[8] == "Lâm công tử"


def test_pending_clear_all(client, slug, storage):
    storage.write_extra_json("characters_pending",
                             {"characters": [{"source": "X"}], "relations": []})
    resp = client.post(f"/api/ebooks/{slug}/characters/pending/clear",
                       json={"all": True})
    assert resp.status_code == 200
    assert storage.read_extra_json("characters_pending") in (None, {}, {"characters": [], "relations": []})
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_characters_ai.py tests/test_routes_characters.py -v`
Expected: FAIL — `AttributeError: module 'novel2epub.characters_ai' has no attribute 'extract_characters'` và 404 trên các route pending.

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `novel2epub/characters_ai.py`, thêm import ở đầu file:

```python
from . import openai_client
```

và hàm gọi mạng ở cuối file:

```python
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
```

Trong `app/routes/characters.py`, thêm ba route (đặt sau các route CRUD sẵn có):

```python
_PENDING_KEY = "characters_pending"


def _read_pending(storage: Storage) -> dict:
    """Hàng chờ đề xuất AI. Trả về dict hai mảng, chịu được dữ liệu cũ/hỏng."""
    raw = storage.read_extra_json(_PENDING_KEY)
    if not isinstance(raw, dict):
        return {"characters": [], "relations": []}
    chars = raw.get("characters")
    rels = raw.get("relations")
    return {
        "characters": chars if isinstance(chars, list) else [],
        "relations": rels if isinstance(rels, list) else [],
    }


@router.get("/api/ebooks/{slug}/characters/pending")
def characters_pending(slug: str):
    pending = _read_pending(_storage(slug))
    return JSONResponse({
        "characters": pending["characters"],
        "relations": pending["relations"],
        "counts": {"characters": len(pending["characters"]),
                   "relations": len(pending["relations"])},
    })


def _rel_key(item: dict) -> tuple:
    try:
        chapter = int(item.get("from_chapter") or 0)
    except (TypeError, ValueError):
        chapter = 0
    return (str(item.get("a_source", "")), str(item.get("b_source", "")), chapter)


@router.post("/api/ebooks/{slug}/characters/pending/approve")
def characters_pending_approve(slug: str, payload: dict = Body(...)):
    """Duyệt đề xuất: NHÂN VẬT TRƯỚC, QUAN HỆ SAU.

    Thứ tự đó là bắt buộc — duyệt quan hệ trước thì hai đầu chưa tồn tại. Quan
    hệ có đầu vừa không được chọn vừa chưa có trong bảng sẽ bị CHẶN kèm thông
    báo nêu đích danh, không tạo quan hệ mồ côi và không im lặng bỏ qua. Nhân
    vật hợp lệ vẫn được lưu bình thường.
    """
    storage = _storage(slug)
    pending = _read_pending(storage)
    by_source = {c.get("source"): c for c in pending["characters"]}
    by_rel = {_rel_key(r): r for r in pending["relations"]}

    picked_chars = [str(c.get("source", "")).strip()
                    for c in payload.get("characters", []) if isinstance(c, dict)]
    picked_rels = [_rel_key(r) for r in payload.get("relations", [])
                   if isinstance(r, dict)]

    # --- nhân vật trước ---
    approved_chars: list[str] = []
    for source in picked_chars:
        item = by_source.get(source)
        if not item:
            continue
        if item.get("update_only"):
            existing = {r[0]: r for r in storage.read_character_entries()}.get(source)
            if existing is None:
                continue
            old_raw = [a for a in (existing[2] or "").split("|") if a]
            old_vi = [a for a in (existing[8] or "").split("|") if a]
            for a in item.get("new_aliases_raw", []):
                if a not in old_raw:
                    old_raw.append(a)
            for a in item.get("new_aliases_vi", []):
                if a not in old_vi:
                    old_vi.append(a)
            storage.upsert_character(
                source, existing[1], "|".join(old_raw), existing[3], existing[4],
                existing[5], existing[6], existing[7], aliases_vi="|".join(old_vi),
            )
        else:
            storage.upsert_character(
                source,
                item.get("target", ""),
                "|".join(item.get("aliases_raw", [])),
                item.get("gender", ""),
                item.get("self_pronoun", ""),
                item.get("narrator_ref", ""),
                item.get("role_note", ""),
                item.get("importance", "side"),
                aliases_vi="|".join(item.get("aliases_vi", [])),
            )
        approved_chars.append(source)

    # --- quan hệ sau ---
    known = {r[0] for r in storage.read_character_entries()}
    names = {c.get("source"): c.get("target", "") for c in pending["characters"]}
    # Chỉ quan hệ LƯU ĐƯỢC mới bị gỡ khỏi hàng chờ; quan hệ bị chặn phải ở lại
    # để người dùng duyệt nhân vật thiếu rồi thử lại.
    approved_rel_keys: set[tuple] = set()
    blocked: list[str] = []
    for key in picked_rels:
        item = by_rel.get(key)
        if not item:
            continue
        missing = [s for s in (item["a_source"], item["b_source"]) if s not in known]
        if missing:
            for s in missing:
                label = f"{s} ({names.get(s)})" if names.get(s) else s
                blocked.append(
                    f'Quan hệ "{item["a_source"]} → {item["b_source"]}" không lưu '
                    f"được: nhân vật {label} chưa có trong bảng và không được "
                    f"chọn duyệt."
                )
            continue
        storage.upsert_relation(
            item["a_source"], item["b_source"], key[2],
            item.get("a_calls_b_vi", ""), item.get("a_self_vi", ""),
            item.get("reason", ""),
            to_chapter=item.get("to_chapter"),
            a_calls_b_raw=item.get("a_calls_b_raw", ""),
            a_self_raw=item.get("a_self_raw", ""),
            evidence=item.get("evidence", ""),
            inferred=bool(item.get("inferred")),
            confidence=item.get("confidence", ""),
        )
        approved_rel_keys.add(key)

    approved_char_keys = set(approved_chars)
    remaining = {
        "characters": [c for c in pending["characters"]
                       if c.get("source") not in approved_char_keys],
        "relations": [r for r in pending["relations"]
                      if _rel_key(r) not in approved_rel_keys],
    }
    storage.write_extra_json(_PENDING_KEY, remaining)
    return JSONResponse({
        "approved_characters": len(approved_chars),
        "approved_relations": len(approved_rel_keys),
        "blocked": blocked,
        "remaining": {"characters": len(remaining["characters"]),
                      "relations": len(remaining["relations"])},
    })


@router.post("/api/ebooks/{slug}/characters/pending/clear")
def characters_pending_clear(slug: str, payload: dict = Body(...)):
    """Bỏ đề xuất khỏi hàng chờ mà KHÔNG đưa vào bảng."""
    storage = _storage(slug)
    pending = _read_pending(storage)
    if payload.get("all"):
        total = len(pending["characters"]) + len(pending["relations"])
        storage.write_extra_json(_PENDING_KEY, {"characters": [], "relations": []})
        return JSONResponse({"cleared": total})
    sources = {str(s).strip() for s in payload.get("characters", []) if str(s).strip()}
    rel_keys = {_rel_key(r) for r in payload.get("relations", []) if isinstance(r, dict)}
    remaining = {
        "characters": [c for c in pending["characters"] if c.get("source") not in sources],
        "relations": [r for r in pending["relations"] if _rel_key(r) not in rel_keys],
    }
    cleared = (len(pending["characters"]) + len(pending["relations"])
               - len(remaining["characters"]) - len(remaining["relations"]))
    storage.write_extra_json(_PENDING_KEY, remaining)
    return JSONResponse({"cleared": cleared})
```

Thêm `Body` vào dòng import `fastapi` ở đầu file nếu chưa có.

Trong `app/routes/chapters.py`, thêm route chạy job (đặt cạnh
`api_batch_suggest_glossary`):

```python
@router.post("/api/ebooks/{slug}/batch/extract-characters")
async def api_batch_extract_characters(
    request: Request,
    slug: str,
    indexes: str = Form(...),
):
    """AI trích nhân vật & quan hệ từ các chương đã chọn → hàng chờ duyệt.

    KHÁC batch/suggest-glossary: KHÔNG lặp từng chương. Chương được gom thành
    nhóm vừa ngân sách prompt rồi phân tích theo nhóm — mốc đổi xưng hô chỉ tồn
    tại khi AI so sánh được hai thời điểm trong cùng một lời gọi.
    """
    from novel2epub import characters_ai

    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]

    def _target(log):
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        chapters: list[tuple[int, str, str]] = []
        for ch in (manifest.chapters if manifest else []):
            if ch.index not in index_list:
                continue
            raw = storage.read_raw(ch)
            if not raw.strip():
                continue
            chapters.append((ch.index, raw, storage.read_translated(ch)))
        if not chapters:
            log("[trích-nhân-vật] Không có chương nào có raw. Dừng.")
            return
        existing = {r[0]: r[1] for r in storage.read_character_entries()}
        glossary = {s: t for s, t, _n in storage.read_glossary_entries_merged()}
        budget = cfg.translate.prompt_max_chars or 20000
        result = characters_ai.extract_characters(
            cfg.translate.openai, chapters, existing, glossary,
            genre=cfg.translate.genre, max_chars=budget, log=log,
        )
        storage.write_extra_json("characters_pending", result)
        log(f"[trích-nhân-vật] Xong: {len(result['characters'])} nhân vật, "
            f"{len(result['relations'])} quan hệ vào hàng chờ duyệt.")

    started = request.app.state.job.start_custom(
        f"extract-characters-{len(index_list)}", _target, category="translate"
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"started": True, "total": len(index_list)})
```

Các hàm `Storage` dùng ở trên đã được xác minh tồn tại: `load_manifest()`
(storage.py:164), `read_raw(ch)` (:349), `read_translated(ch)` (:376),
`read_glossary_entries_merged()` (:502, trả list `(source, target, note)`).
`TranslateConfig.prompt_max_chars` có ở config.py:373.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_characters_ai.py tests/test_routes_characters.py -v`
Expected: PASS.

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add novel2epub/characters_ai.py app/routes/characters.py app/routes/chapters.py tests/test_characters_ai.py tests/test_routes_characters.py
git commit -m "feat: route trích nhân vật qua JobQueue + hàng chờ duyệt"
```

---

### Task 4: Tab "Đề xuất" trên trang Nhân vật

**Files:**
- Modify: `app/templates/characters.html`
- Modify: `app/templates/ebook.html` (nút chạy)
- Test: thủ công qua trình duyệt (UI thuần, logic đã có test ở Task 3)

**Interfaces:**
- Consumes: ba route pending từ Task 3.
- Produces: không có API mới.

**Đọc trước khi viết:** `app/templates/characters.html` (bảng chính + hàng con
`<details>` của A) và cách trang Glossary hiện tab "Đề xuất AI" — nhân bản đúng
kiểu đó, đừng phát minh kiểu mới.

- [ ] **Step 1: Thêm tab và bảng đề xuất**

Trong `app/templates/characters.html`: thêm thanh tab hai mục — **Bảng nhân vật**
(nội dung hiện có) và **Đề xuất (N)** với N lấy từ `counts` của
`GET .../characters/pending`, nạp khi mở trang.

Tab Đề xuất chứa hai bảng con:

*Nhân vật* — checkbox · Tên gốc · Tên Việt · Alias (raw + vi) · Giới · Tự xưng ·
Lời kể gọi · ⭐main · lý do · độ tin. Mục `update_only` hiện nhãn riêng
("chỉ bổ sung alias") và chỉ hiện các alias mới.

*Quan hệ* — checkbox và mỗi dòng PHẢI hiện bằng chứng, vì đó là toàn bộ mục đích
của việc lưu `evidence`/`inferred`/`confidence`:

```
☑ Lâm Phàm → Huyền Trần Tử · từ ch.1
  gọi "sư phụ" (师父) · xưng "đồ nhi" (弟子)
  bằng chứng: 师父，弟子回来了。          [high]

☑ Lâm Phàm → Tô Thanh Tuyết · từ ch.2
  gọi "Tô cô nương" (suy luận) · xưng "tại hạ" (suy luận)
  bằng chứng: 林公子，请自重。            [medium · suy luận]
```

Quy tắc hiển thị:
- `*_raw` rỗng → hiện "(suy luận)" thay vì chuỗi Hán.
- `inferred: true` → nhãn "suy luận".
- `confidence: "low"` → cảnh báo trực quan.
- `conflict: true` → hiện CẢ HAI bản (bản chính và `conflict_with`) với radio để
  người dùng chọn một; không được tự chọn hộ.

Escape mọi giá trị bằng hàm `escapeHtml` sẵn có trong file — nội dung đến từ
văn bản truyện và từ AI.

- [ ] **Step 2: Nối nút Duyệt / Bỏ**

Nút **Duyệt đã chọn** gửi `POST .../characters/pending/approve` với cả hai mảng
trong một lời gọi (nhân vật trước, quan hệ sau là việc của server). Phản hồi có
`blocked` khác rỗng thì hiện từng thông báo cho người dùng — đây là ca "tick
quan hệ nhưng quên tick nhân vật", phải nói rõ chứ không được im lặng.

Nút **Bỏ đã chọn** và **Bỏ tất cả** gửi `POST .../characters/pending/clear`.

Sau mỗi thao tác gọi lại `loadAll()` và cập nhật số trên nhãn tab.

- [ ] **Step 3: Thêm nút chạy ở trang ebook**

Trong `app/templates/ebook.html`, cạnh nút "AI gợi ý glossary", thêm nút
**AI trích nhân vật** dùng lại đúng luồng chọn chương sẵn có, gửi
`POST /api/ebooks/{slug}/batch/extract-characters` với `indexes` là danh sách
ngăn phẩy. Dùng đúng class nút của các nút lân cận.

- [ ] **Step 4: Kiểm chứng trong trình duyệt**

Khởi động preview, mở một ebook có ít nhất 2 chương đã crawl, chọn chương, bấm
**AI trích nhân vật**, theo dõi log job, rồi mở tab Đề xuất trên trang Nhân vật.
Kiểm: bằng chứng hiện đúng; tick một quan hệ nhưng bỏ tick nhân vật đầu kia thì
nhận được thông báo chặn nêu tên; duyệt xong hàng chờ giảm và bảng chính có dữ
liệu mới.

**Dọn sạch dữ liệu thử sau khi kiểm** — đây là DB thật của người dùng, không
phải DB test.

- [ ] **Step 5: Chạy toàn bộ suite**

Run: `pytest tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add app/templates/characters.html app/templates/ebook.html
git commit -m "feat: tab Đề xuất trên trang Nhân vật + nút AI trích nhân vật"
```

---

### Task 5: Cập nhật CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Thêm mô tả module**

Thêm bullet sau bullet `characters.py` trong mục Architecture:

```markdown
- `characters_ai.py` — AI trích bảng nhân vật & quan hệ từ chương raw → hàng chờ duyệt (`ebook_extra_json` khoá `characters_pending`, cùng cơ chế `glossary_pending`). GOM NHÓM chương chứ không chạy từng chương như `batch/suggest-glossary`: mốc đổi xưng hô chỉ tồn tại khi AI so sánh được hai thời điểm trong cùng một lời gọi, chạy rời rạc thì chương 2 và chương 120 không biết nhau. Logic thuần (`group_chapters`/`format_chapters_block`/`parse_extraction`/`merge_extractions`) tách khỏi hàm duy nhất chạm mạng (`extract_characters`); một nhóm lỗi không giết cả job. Ràng buộc trung tâm: chữ Hán gốc KHÁC bản Việt hoá — `师父`/`弟子` có trong bản gốc, "sư phụ"/"đồ nhi" là lựa chọn dịch, nên mỗi xưng hô lưu hai phần `*_raw`/`*_vi` kèm `evidence`/`inferred`/`confidence`; `raw` KHÔNG bao giờ vào prompt dịch, chỉ phục vụ người duyệt và việc map lại khi đổi phong cách. Luật xung đột (confidence → có raw → evidence dài hơn → đánh dấu `conflict` cho user chọn) chạy ở `merge_extractions` chứ KHÔNG ở DB, vì khoá chính `(slug, a, b, from_chapter)` khiến hai mốc trùng chương ghi đè nhau âm thầm. Duyệt: nhân vật TRƯỚC, quan hệ SAU; quan hệ thiếu đầu bị chặn kèm tên, không tạo mồ côi.
```

- [ ] **Step 2: Ghi chú `to_chapter` vào Technical Notes**

```markdown
- `character_relations.to_chapter` (schema v6) để TRỐNG là mặc định, nghĩa là "còn hiệu lực tới mốc kế tiếp, hoặc mãi mãi nếu không có mốc nào sau". Chỉ điền khi quan hệ chấm dứt dứt khoát mà không có mốc thay thế (nhân vật chết, đoạn tuyệt) — ca mà `from_chapter` một mình không diễn đạt được vì mốc cuối sẽ kéo dài vô tận. KHÔNG điền giá trị chỉ để lặp lại ranh giới của mốc kế tiếp: giá trị đó suy ra được, lưu cả hai là dữ liệu thừa có thể mâu thuẫn khi sửa một bên mà quên bên kia.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: ghi chú characters_ai + to_chapter vào CLAUDE.md"
```

---

## Ghi chú cho người thực thi

**Thứ tự bắt buộc.** Task 1 độc lập (thuần, làm việc trên dict). Task 2 độc lập
với Task 1. Task 3 cần CẢ HAI. Task 4 cần Task 3. Task 5 cuối.

**Bốn chỗ dễ hỏng âm thầm:**
1. Cột mới chỉ khai trong `CREATE TABLE` mà quên `_ADDED_COLUMNS` → DB v5 hiện
   có của người dùng thiếu cột, còn máy cài mới vẫn chạy tốt nên test không bắt
   được.
2. Chèn cột mới vào GIỮA tuple thay vì nối vào cuối → `relations_from_rows` đọc
   theo vị trí sẽ lệch dữ liệu mà không raise.
3. Luật xung đột đặt nhầm ở tầng DB → `ON CONFLICT DO UPDATE` ghi đè âm thầm,
   luật không bao giờ chạy.
4. Duyệt quan hệ trước nhân vật → quan hệ mồ côi.

**Ngoài phạm vi:** dùng `aliases_vi`/`target` để lọc nhân vật trên đường export
bản `translated` (Task 2 tạo cột, KHÔNG đổi logic lọc); nạp lại bảng nhân vật
giữa job đang chạy; sub-project C.
