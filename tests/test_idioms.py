"""Tests cho từ điển idiom dùng chung + longest-match glossary."""
from novel2epub import idioms as I
from novel2epub.idioms import Idiom
from novel2epub.storage import Storage
from novel2epub.translator import _apply_glossary, HachimiMTTranslator
from novel2epub.config import TranslateConfig


# ---------- Part A: glossary longest-match ----------

def test_apply_glossary_longest_match():
    # Tên ngắn không được phá tên dài chứa nó.
    out = _apply_glossary("韩溯 và 韩", {"韩": "Hàn", "韩溯": "Hàn Tố"})
    assert out == "Hàn Tố và Hàn"


# ---------- idioms.py: parse / build ----------

def test_parse_idiom_note_literals_and_protect():
    assert I.parse_idiom_note("Ngàn phương trăm kế") == (["Ngàn phương trăm kế"], False)
    assert I.parse_idiom_note("lit1 | lit2") == (["lit1", "lit2"], False)
    assert I.parse_idiom_note("@protect") == ([], True)
    assert I.parse_idiom_note("lit1 | @protect") == (["lit1"], True)
    assert I.parse_idiom_note("") == ([], False)


def test_make_idiom_requires_zh_and_natural():
    assert I.make_idiom("", "x") is None
    assert I.make_idiom("千方百计", "") is None
    idi = I.make_idiom("千方百计", "Trăm phương nghìn kế", "Ngàn phương trăm kế")
    assert idi == Idiom("千方百计", "Trăm phương nghìn kế", ("Ngàn phương trăm kế",), False)


def test_idioms_from_rows():
    rows = [
        ("千方百计", "Trăm phương nghìn kế", "Ngàn phương trăm kế", 0),
        ("势不可挡", "Thế như chẻ tre", "", 1),
        ("", "bỏ", "", 0),  # thiếu source -> bỏ
    ]
    out = I.idioms_from_rows(rows)
    assert len(out) == 2
    assert out[1] == Idiom("势不可挡", "Thế như chẻ tre", (), True)


# ---------- idioms.py: LLM block ----------

def test_filter_and_format_llm_block():
    idioms = [
        Idiom("千方百计", "Trăm phương nghìn kế"),
        Idiom("一举两得", "Một mũi tên trúng hai đích"),
    ]
    filtered = I.filter_for_text(idioms, "他千方百计想成功")
    assert [i.zh for i in filtered] == ["千方百计"]
    block = I.format_llm_block(filtered)
    assert "千方百计 = Trăm phương nghìn kế" in block
    assert I.format_llm_block([]) == ""


# ---------- idioms.py: MT protect + literal ----------

def test_protect_and_restore_roundtrip():
    idioms = [Idiom("千方百计", "Trăm phương nghìn kế", protect=True)]
    protected, restore = I.protect_source("他千方百计", idioms)
    assert "千方百计" not in protected
    assert protected == "他〖0〗"
    # MT "dịch" giữ nguyên placeholder
    out = I.restore_placeholders("hắn 〖0〗", restore)
    assert out == "hắn Trăm phương nghìn kế"


def test_restore_tolerant_to_spaces():
    idioms = [Idiom("千方百计", "Trăm phương nghìn kế", protect=True)]
    _protected, restore = I.protect_source("千方百计", idioms)
    assert I.restore_placeholders("〖 0 〗", restore) == "Trăm phương nghìn kế"


def test_normalize_literals_longest_first():
    idioms = [
        Idiom("一举两得", "Một mũi tên trúng hai đích", ("Một lần được hai lợi",)),
        # protect idiom KHÔNG được normalize theo literal
        Idiom("千方百计", "Trăm phương nghìn kế", ("X",), protect=True),
    ]
    out = I.normalize_literals("Kết quả Một lần được hai lợi và X", idioms)
    assert out == "Kết quả Một mũi tên trúng hai đích và X"


def test_apply_mt_post_combines_restore_and_literal():
    idioms = [
        Idiom("一举两得", "Một mũi tên trúng hai đích", ("Một lần được hai lợi",)),
        Idiom("千方百计", "Trăm phương nghìn kế", protect=True),
    ]
    _p, restore = I.protect_source("千方百计", idioms)
    out = I.apply_mt_post("〖0〗, Một lần được hai lợi", idioms, restore)
    assert out == "Trăm phương nghìn kế, Một mũi tên trúng hai đích"


# ---------- Storage: idiom CRUD + seed ----------

def test_storage_idiom_crud(tmp_path):
    s = Storage(tmp_path, "slug")
    assert s.count_idioms() == 0
    assert s.upsert_idiom("千方百计", "Trăm phương nghìn kế", "Ngàn phương trăm kế", 0)
    assert s.upsert_idiom("势不可挡", "Thế như chẻ tre", "", 1)
    assert s.count_idioms() == 2
    rows = s.read_idiom_entries()
    assert rows[0] == ("千方百计", "Trăm phương nghìn kế", "Ngàn phương trăm kế", 0)
    assert rows[1] == ("势不可挡", "Thế như chẻ tre", "", 1)
    # update giữ nguyên (không nhân đôi)
    s.upsert_idiom("千方百计", "Bản mới", "", 0)
    assert s.count_idioms() == 2
    assert s.read_idiom_entries()[0][1] == "Bản mới"
    # delete
    assert s.delete_idiom("势不可挡")
    assert s.count_idioms() == 1
    # page + search
    assert len(s.read_idioms_page(0, 10)) == 1
    assert s.count_idioms("千方") == 1


def test_storage_seed_idempotent(tmp_path):
    s = Storage(tmp_path, "slug")
    n = s.seed_idioms_if_empty(I.DEFAULT_IDIOM_SEED)
    assert n == len(I.DEFAULT_IDIOM_SEED)
    # lần 2 không seed lại
    assert s.seed_idioms_if_empty(I.DEFAULT_IDIOM_SEED) == 0
    assert s.count_idioms() == len(I.DEFAULT_IDIOM_SEED)


# ---------- HachimiMTTranslator integration (không cần model thật) ----------

class _FakeInner:
    def translate_text(self, text, *, beam_size, chunk_mode):
        # Giả lập MT: dịch phần thường ra bản máy (literal), GIỮ placeholder.
        return (
            text.replace("他", "hắn ")
            .replace("一举两得", "Một lần được hai lợi")
            .replace("，", ", ")
            .replace("。", ".")
        )


def test_mt_translator_applies_protect_and_literal(monkeypatch):
    cfg = TranslateConfig(type="moxhimt", use_idioms=True)
    t = HachimiMTTranslator(cfg, storage=None)
    t.idioms = [
        Idiom("千方百计", "Trăm phương nghìn kế", protect=True),
        Idiom("一举两得", "Một mũi tên trúng hai đích", ("Một lần được hai lợi",)),
    ]
    t._inner = _FakeInner()  # bỏ qua _ensure_loaded (đã có inner)
    out = t.translate("他千方百计，一举两得。")
    assert out == "hắn Trăm phương nghìn kế, Một mũi tên trúng hai đích."


def test_mt_translator_noop_when_idioms_disabled():
    cfg = TranslateConfig(type="moxhimt", use_idioms=False)
    t = HachimiMTTranslator(cfg, storage=None)
    assert t.idioms == []
    t._inner = _FakeInner()
    out = t.translate("他一举两得。")
    # Không có idiom -> literal giữ nguyên bản máy
    assert out == "hắn Một lần được hai lợi."
