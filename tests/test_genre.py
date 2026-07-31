"""Tests cho preset xưng hô theo thể loại."""
from novel2epub import genre as G


def test_every_preset_has_rules_except_auto():
    for key in G.GENRE_KEYS:
        preset = G.GENRE_PRESETS[key]
        if key == "auto":
            continue
        assert preset.use_words, key
        assert preset.forbid_words, key


def test_xianxia_rules_mention_expected_pronouns():
    out = G.format_pronoun_rules("xianxia")
    assert "tại hạ" in out
    assert "tôi" in out          # xuất hiện trong danh sách CẤM


def test_urban_forbids_classical_pronouns():
    forbidden = G.forbid_words("urban")
    for contextual in ("ta", "ngươi", "hắn"):
        assert contextual not in {w.strip() for w in forbidden.split(",")}
    assert "tại hạ" in forbidden
    assert G.forbid_words("xianxia") != G.forbid_words("urban")


def test_contextual_pronouns_are_not_absolutely_forbidden_by_any_genre():
    for key in G.GENRE_KEYS:
        forbidden = {w.strip() for w in G.forbid_words(key).split(",")}
        assert not ({"ta", "ngươi", "hắn"} & forbidden), key


def test_pronoun_rules_explain_context_and_priority():
    out = G.format_pronoun_rules("urban")
    assert "Có thể dùng khi phù hợp" in out
    assert "Thường tránh nếu BẢNG NHÂN VẬT" in out
    assert "CẤM:" not in out
    assert G.CONTEXTUAL_PRONOUN_RULE not in out


def test_runtime_pin_has_complete_pronoun_priority():
    pin = G.RUNTIME_PRONOUN_PIN
    assert "Bảng nhân vật > ngôi kể > ngữ cảnh > thể loại" in pin
    assert "hắn/ta/ngươi chỉ dùng khi tự nhiên" in pin
    assert len(pin) < 100


def test_genre_module_does_not_import_hachimimt():
    # hachimimt kéo theo sentencepiece + huggingface_hub (dep TÙY CHỌN) qua
    # __init__.py của nó; genre.py nằm trên đường dịch mặc định nên không được
    # phụ thuộc vào chúng — nếu lỡ import, lỗi này sẽ KHÔNG lộ ra trên máy dev
    # (đã có sẵn 2 dep đó) mà chỉ vỡ trên một cài đặt sạch (clean install).
    # Check bằng AST thay vì scan chuỗi trong source: cấm IMPORT THẬT SỰ (kể
    # cả import lồng trong hàm), không cấm nhắc tên package trong prose/docstring
    # để giải thích lý do — đó chính là thứ ngăn dev tương lai vô tình thêm lại.
    import ast
    import inspect
    from novel2epub import genre

    tree = ast.parse(inspect.getsource(genre))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "hachimimt" not in alias.name, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert "hachimimt" not in (node.module or ""), node.module
            for alias in node.names:
                assert "hachimimt" not in alias.name, alias.name


def test_auto_is_neutral_and_forbids_nothing():
    out = G.format_pronoun_rules("auto")
    assert "tại hạ" not in out
    assert G.forbid_words("auto") == ""


def test_auto_still_gives_pronoun_guidance_without_duplicating_han_viet_slot():
    # Trước bản vá: auto.use_words rỗng, chỗ này gần như không có nội dung —
    # regression so với DEFAULT_PROMPT cũ (rule 2 từng liệt kê thẳng các dạng
    # xưng hô này). Sau vá: auto phải còn hướng dẫn xưng hô thật, KHÔNG lặp
    # lại câu Hán Việt mà {han_viet_level} đã render riêng.
    out = G.format_pronoun_rules("auto")
    assert out.strip()
    for word in ("cha", "mẹ", "sư phụ", "tiền bối", "chàng", "nàng"):
        assert word in out, word

    han_viet_sentence = G.format_style_value("han_viet_level", "balanced")
    assert han_viet_sentence not in out

    assert G.forbid_words("auto") == ""


def test_user_policy_appended_only_when_customised():
    plain = G.format_pronoun_rules("xianxia")
    assert G.format_pronoun_rules("xianxia", user_policy="contextual") == plain
    custom = G.format_pronoun_rules("xianxia", user_policy="Gọi sư phụ là thầy")
    assert custom.endswith("Gọi sư phụ là thầy")


def test_unknown_genre_falls_back_to_auto():
    assert G.format_pronoun_rules("khong-ton-tai") == G.format_pronoun_rules("auto")


def test_format_style_value_maps_enum_and_passes_through_unknown():
    assert G.format_style_value("han_viet_level", "balanced") != "balanced"
    assert "Hán Việt" in G.format_style_value("han_viet_level", "balanced")
    assert G.format_style_value("han_viet_level", "tự do gõ") == "tự do gõ"
    assert G.format_style_value("khong_biet", "x") == "x"
