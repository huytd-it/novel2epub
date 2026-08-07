"""Tests cho han_cleanup: phát hiện và sửa chữ Hán còn sót."""
from novel2epub.han_cleanup import (
    find_han_regions,
    build_cleanup_prompt,
    _extract_replacement,
    cleanup_han_with_local_mt,
    count_han,
    splice_local_mt_translation,
)


def test_splice_local_mt_translation_adds_spaces_only_at_word_boundaries():
    assert splice_local_mt_translation("anh说đi", 3, 4, "nói") == "anh nói đi"
    assert splice_local_mt_translation("(说)", 1, 2, "nói") == "(nói)"
    assert splice_local_mt_translation("gọi他.", 3, 4, "hắn") == "gọi hắn."
    assert splice_local_mt_translation("说, rồi", 0, 1, "nói") == "nói, rồi"


def test_cleanup_han_with_local_mt_replaces_regions_right_to_left():
    calls = []
    mapping = {"说": "nói", "他": "hắn"}

    def translate(text):
        calls.append(text)
        return mapping[text]

    cleaned, fixed, warnings = cleanup_han_with_local_mt("anh说đi và gọi他.", translate)

    assert cleaned == "anh nói đi và gọi hắn."
    assert fixed == 2
    assert warnings == []
    assert calls == ["他", "说"]


def test_cleanup_han_with_local_mt_skips_clean_text():
    calls = []
    cleaned, fixed, warnings = cleanup_han_with_local_mt("Chỉ có tiếng Việt.", calls.append)
    assert cleaned == "Chỉ có tiếng Việt."
    assert fixed == 0
    assert warnings == []
    assert calls == []


def test_find_han_regions_empty():
    assert find_han_regions("") == []


def test_find_han_regions_no_han():
    text = "Chồng bà, Lý Duy Hán, cũng không đi."
    assert find_han_regions(text) == []


def test_find_han_regions_simple():
    text = "Lý do không đi là vì 不好意思 (ngại)."
    regions = find_han_regions(text)
    assert len(regions) == 1
    r = regions[0]
    assert "不好意思" in r["chinese_text"]
    assert r["paragraph_index"] == 0
    assert r["full_paragraph"] == text


def test_find_han_regions_multiple_in_one_paragraph():
    text = "vì 不好意思 nên tư thế 吃相 khó coi."
    regions = find_han_regions(text)
    # 不好意思 và 吃相 cách nhau 3 ký tự tiếng Việt " nên ", default max_gap=3
    # Nếu 2 chữ Hán cách nhau <= 3 ký tự, chúng được gộp
    # "  nên " = 6 ký tự > max_gap=3 → tách riêng
    assert len(regions) == 2
    assert "不好意思" in regions[0]["chinese_text"]
    assert "吃相" in regions[1]["chinese_text"]


def test_find_han_regions_adjacent_merged():
    """Các ký tự Hán gần nhau (cách ≤ max_gap) được gộp."""
    text = "A 你好吗 B"
    regions = find_han_regions(text, max_gap=5)
    assert len(regions) == 1
    assert "你好吗" in regions[0]["chinese_text"]


def test_find_han_regions_context():
    text = "Trước đó rất lâu, 不好意思, sau đó thì sao."
    regions = find_han_regions(text, min_context_chars=10)
    assert len(regions) == 1
    r = regions[0]
    assert "rất lâu," in r["context_before"]  # 10 ký tự trước "不好意思"
    assert ", sau đó" in r["context_after"]


def test_count_han_zero():
    assert count_han("Tiếng Việt không có Hán") == 0


def test_count_han_some():
    assert count_han("不好意思 và 吃相") == 6


def test_count_han_mixed():
    assert count_han("Xin chào 你好") == 2


def test_build_cleanup_prompt():
    text = "Lý do không đi là vì 不好意思 (ngại); dù sao"
    regions = find_han_regions(text)
    assert len(regions) == 1
    region = regions[0]
    prompt = build_cleanup_prompt(
        "不去的原因是不好意思",
        region["full_paragraph"],
        [region],
    )
    assert "<HAN>不好意思</HAN>" in prompt
    assert "CLEANUP_PROMPT" not in prompt  # không leak tên biến
    assert "Lý do không đi" in prompt
    assert "不去的原因" in prompt


def test_extract_replacement_different():
    original = "vì 不好意思 nên"
    response = "vì ngại ngùng nên"
    result = _extract_replacement(response, original)
    assert result == "vì ngại ngùng nên"


def test_extract_replacement_same():
    original = "vì 不好意思 nên"
    result = _extract_replacement(original, original)
    assert result is None


def test_extract_replacement_strips_fence():
    original = "vì 不好意思 nên"
    response = "```\nvì ngại ngùng nên\n```"
    result = _extract_replacement(response, original)
    assert result == "vì ngại ngùng nên"


def test_extract_replacement_strips_han_tags():
    """Nếu AI trả về vẫn còn tag HAN, chúng bị xoá."""
    response = "vì <HAN>ngại ngùng</HAN> nên"
    original = "vì 不好意思 nên"
    result = _extract_replacement(response, original)
    assert result == "vì ngại ngùng nên"


def test_find_han_regions_multiple_paragraphs():
    text = "Đoạn một sạch.\nĐoạn hai有Hán.\nĐoạn ba cũng乾淨."
    regions = find_han_regions(text)
    assert len(regions) == 2
    assert regions[0]["paragraph_index"] == 1
    assert regions[1]["paragraph_index"] == 2


def test_build_cleanup_prompt_multiple_regions():
    """Bug: nhiều region trong cùng 1 đoạn phải được đánh dấu đủ cả hai.

    Trước đây _mark_region được gọi theo thứ tự start tăng dần, làm offset của
    region thứ 2 trỏ vào giữa tag <HAN>...</HAN> của region thứ 1 (do mỗi tag
    thêm 12 ký tự), khiến region thứ 2 bị "ăn" một phần và tag lệch.
    """
    text = "vì 不好意思 nên tư thế 吃相 khó coi."
    regions = find_han_regions(text)
    # 不好意思 và 吃相 cách nhau > max_gap=3 (có " nên tư thế ")
    assert len(regions) == 2
    prompt = build_cleanup_prompt("không có gì", text, regions)
    assert "<HAN>不好意思</HAN>" in prompt
    assert "<HAN>吃相</HAN>" in prompt
    # Không có tag lệch (như <HAN>...</HAN>nên...)
    assert "<HAN>...nên" not in prompt
    # Chỉ đếm tag trong phần marked_text (cách dòng header bằng dòng trống).
    marked_section = prompt.split("--- Bản dịch cần sửa")[1]
    # Bỏ phần hướng dẫn phía sau: chỉ lấy phần giữa dòng header và dòng trống kế tiếp.
    marked_only = marked_section.split("\n\n", 1)[0]
    assert marked_only.count("<HAN>") == 2
    assert marked_only.count("</HAN>") == 2


def test_count_han_in_paragraph_for_actual_fixes():
    """fixed_count phải đếm dựa trên Hán before/after, không phải len(regions)."""
    from novel2epub.han_cleanup import cleanup_paragraph
    from novel2epub.config import OpenAIConfig

    text = "vì 不好意思 và 吃相 khó coi"
    regions = find_han_regions(text)

    # Mock AI: trả về chỉ sửa 1 trong 2 region
    class _FakeRunChat:
        def __init__(self, response_text):
            self.response_text = response_text
            self.calls = 0

        def __call__(self, ai_cfg, prompt):
            self.calls += 1
            return self.response_text

    fake = _FakeRunChat("vì ngại ngùng và 吃相 khó coi")
    import novel2epub.han_cleanup as hc
    orig_run = hc.openai_client.run_chat
    hc.openai_client.run_chat = fake
    try:
        fixed, count = cleanup_paragraph("", text, regions, OpenAIConfig())
    finally:
        hc.openai_client.run_chat = orig_run

    # 不好意思 (4 ký tự Hán) được sửa thành "ngại ngùng" (0 Hán) → fixed = 4
    # 吃相 (2 ký tự Hán) vẫn còn → không tính
    assert count == 4
    assert "吃相" in fixed
    assert "ngại ngùng" in fixed


def test_cleanup_chapter_retries_wired():
    """retries=2: nếu lần 1 không sửa, retry tối đa 2 lần nữa.

    Khi AI trả về giống nguyên văn (không sửa gì), fixed_count=0 → cleanup_chapter
    dừng retry. Nếu lần 1 có sửa một phần (Hán giảm nhưng còn), retry chạy tiếp.
    """
    from novel2epub.han_cleanup import cleanup_chapter
    from novel2epub.config import OpenAIConfig

    text = "vì 不好意思 nên 吃相 khó coi"

    class _FakeRunChat:
        def __init__(self):
            self.calls = 0

        def __call__(self, ai_cfg, prompt):
            self.calls += 1
            # Lần 1: sửa 1 region (4 Hán), còn 1 region (2 Hán) → retry
            if self.calls == 1:
                return "vì ngại ngùng nên 吃相 khó coi"
            # Lần 2: sửa nốt
            return "vì ngại ngùng nên tư thế ăn khó coi"

    fake = _FakeRunChat()
    import novel2epub.han_cleanup as hc
    orig_run = hc.openai_client.run_chat
    hc.openai_client.run_chat = fake
    try:
        cleaned, count, warnings = cleanup_chapter(
            "", text, OpenAIConfig(), retries=2,
        )
    finally:
        hc.openai_client.run_chat = orig_run

    assert fake.calls == 2  # lần 1 fix 1 phần → retry lần 2 sửa nốt
    assert "吃相" not in cleaned
    assert "ngại ngùng" in cleaned
    assert count == 6  # 4 + 2 Hán đã sửa


def test_cleanup_chapter_no_retry_when_ai_noop():
    """Khi AI trả về giống nguyên văn → cleanup_chapter không retry (vì không có cải thiện)."""
    from novel2epub.han_cleanup import cleanup_chapter
    from novel2epub.config import OpenAIConfig

    text = "vì 不好意思 nên"

    fake_called = {"n": 0}

    def _fake(ai_cfg, prompt):
        fake_called["n"] += 1
        return text  # trả về y nguyên

    import novel2epub.han_cleanup as hc
    orig_run = hc.openai_client.run_chat
    hc.openai_client.run_chat = _fake
    try:
        cleaned, count, warnings = cleanup_chapter(
            "", text, OpenAIConfig(), retries=5,
        )
    finally:
        hc.openai_client.run_chat = orig_run

    assert fake_called["n"] == 1  # chỉ 1 lần gọi, không retry
    assert cleaned == text
    assert count == 0


def test_cleanup_chapter_batches_all_han_paragraphs_in_one_request():
    """Nhiều đoạn còn Hán → gom hết vào 1 request duy nhất, sửa đúng từng đoạn."""
    from novel2epub.han_cleanup import cleanup_chapter
    from novel2epub.config import OpenAIConfig

    text = "sạch một.\nvì 不好 nên\nsạch hai.\ntư thế 吃相 khó coi"
    calls = {"n": 0, "prompts": []}

    def _fake(ai_cfg, prompt):
        calls["n"] += 1
        calls["prompts"].append(prompt)
        return (
            '<DOAN id="2">\nvì không tốt nên\n</DOAN>\n'
            '<DOAN id="4">\ntư thế ăn uống khó coi\n</DOAN>'
        )

    import novel2epub.han_cleanup as hc
    orig_run = hc.openai_client.run_chat
    hc.openai_client.run_chat = _fake
    try:
        cleaned, count, warnings = cleanup_chapter(
            "", text, OpenAIConfig(), retries=1,
        )
    finally:
        hc.openai_client.run_chat = orig_run

    assert calls["n"] == 1  # 2 đoạn Hán nhưng chỉ 1 request
    prompt = calls["prompts"][0]
    assert "<HAN>不好</HAN>" in prompt
    assert "<HAN>吃相</HAN>" in prompt
    assert 'id=2' in prompt and 'id=4' in prompt
    assert cleaned == "sạch một.\nvì không tốt nên\nsạch hai.\ntư thế ăn uống khó coi"
    assert count == 4  # 2 + 2 ký tự Hán đã sửa
    assert warnings == []


def test_parse_batch_response_ignores_unknown_id_and_noop():
    """Khối có id lạ hoặc nội dung y nguyên (AI noop) đều bị bỏ qua."""
    from novel2epub.han_cleanup import parse_batch_response

    items = [
        {"para_idx": 0, "raw": "", "marked": "vì <HAN>不好</HAN> nên", "original": "vì 不好 nên"},
    ]
    response = '<DOAN id="1">vì 不好 nên</DOAN>\n<DOAN id="9">rác không liên quan</DOAN>'
    assert parse_batch_response(response, items) == {}


def test_parse_batch_response_single_item_plain_fallback():
    """AI trả thẳng đoạn đã sửa không bọc <DOAN> → vẫn nhận khi batch chỉ có 1 đoạn."""
    from novel2epub.han_cleanup import parse_batch_response

    items = [
        {"para_idx": 3, "raw": "", "marked": "vì <HAN>不好</HAN> nên", "original": "vì 不好 nên"},
    ]
    assert parse_batch_response("vì không tốt nên", items) == {3: "vì không tốt nên"}


def test_pack_batches_splits_by_budget():
    """Tổng payload vượt max_chars → chia nhiều request; max_chars=0 → 1 request."""
    from novel2epub.han_cleanup import _pack_batches

    items = [
        {"para_idx": i, "raw": "r" * 30, "marked": "m" * 30, "original": ""}
        for i in range(3)
    ]  # mỗi item 60 ký tự payload
    assert len(_pack_batches(items, 0)) == 1
    assert len(_pack_batches(items, 120)) == 2  # 2 item / batch
    assert len(_pack_batches(items, 60)) == 3
    assert _pack_batches([], 0) == []


def test_cleanup_chapter_max_chars_skips_long_paragraph():
    """max_chars > 0: đoạn văn dài quá ngưỡng sẽ không gửi AI."""
    from novel2epub.han_cleanup import cleanup_chapter
    from novel2epub.config import OpenAIConfig

    long_text = "a" * 100 + " 不好意思" + "b" * 200
    fake_called = {"n": 0}

    def _fake(ai_cfg, prompt):
        fake_called["n"] += 1
        return long_text

    import novel2epub.han_cleanup as hc
    orig_run = hc.openai_client.run_chat
    hc.openai_client.run_chat = _fake
    try:
        cleaned, count, warnings = cleanup_chapter(
            "", long_text, OpenAIConfig(), max_chars=50, retries=3,
        )
    finally:
        hc.openai_client.run_chat = orig_run

    assert fake_called["n"] == 0  # đoạn duy nhất dài 311 > max_chars=50, skip
    assert any("max_chars" in w for w in warnings)
    assert cleaned == long_text


def test_cleanup_chapter_long_chapter_short_han_paragraph_still_processed():
    """Chương tổng thể dài vượt max_chars nhưng đoạn chứa Hán ngắn -> vẫn gọi AI.

    Kịch bản thực tế: chương truyện mạng ~20k ký tự, chỉ vài đoạn ngắn còn sót
    Hán. max_chars áp theo ĐOẠN (payload mỗi lần gọi AI), không theo cả chương.
    """
    from novel2epub.han_cleanup import cleanup_chapter
    from novel2epub.config import OpenAIConfig

    han_para = "mở đầu 不好 kết thúc"
    chapter = ("x" * 500) + "\n" + han_para + "\n" + ("y" * 500)
    fake_called = {"n": 0}

    def _fake(ai_cfg, prompt):
        fake_called["n"] += 1
        return "mở đầu không tốt kết thúc"

    import novel2epub.han_cleanup as hc
    orig_run = hc.openai_client.run_chat
    hc.openai_client.run_chat = _fake
    try:
        cleaned, count, warnings = cleanup_chapter(
            "", chapter, OpenAIConfig(), max_chars=100, retries=1,
        )
    finally:
        hc.openai_client.run_chat = orig_run

    assert fake_called["n"] == 1  # chỉ đoạn có Hán được gửi, dù chương > 1000 ký tự
    assert count == 2  # 2 ký tự Hán được sửa
    assert "không tốt" in cleaned
    assert cleaned.startswith("x" * 500)
    assert cleaned.endswith("y" * 500)
    assert not any("max_chars" in w for w in warnings)
