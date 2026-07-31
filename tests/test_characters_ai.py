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


# ---------- extract_characters (hàm gọi mạng, mock openai_client) ----------

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
