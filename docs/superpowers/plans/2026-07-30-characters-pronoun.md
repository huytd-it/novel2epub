# Bảng nhân vật & ngôi xưng — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho model biết nhân vật là ai và xưng hô với nhau thế nào, để bản dịch
Trung→Việt hết lỗi ngôi xưng.

**Architecture:** Hai bảng SQLite per-ebook (`characters`, `character_relations`)
+ hai module logic thuần (`characters.py` render khối prompt, `genre.py` render
luật xưng hô theo thể loại). Khối được chèn vào prompt dịch API và vào file Xuất
RAW qua cùng một hàm render, nên preview luôn khớp thứ job gửi.

**Tech Stack:** Python 3.10+, SQLite (`sqlite3`), FastAPI + Jinja2, Pico CSS v2,
pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-characters-pronoun-design.md`

## Global Constraints

- Module logic thuần (`characters.py`, `genre.py`) KHÔNG import `Storage`, không
  đụng filesystem — test chạy được không cần DB. Theo đúng khuôn `idioms.py`.
- Comment và docstring viết tiếng Việt, khớp phần còn lại của repo.
- Bảng SQLite khai bằng `CREATE TABLE IF NOT EXISTS`, `WITHOUT ROWID`, có
  `REFERENCES ebooks(slug) ON DELETE CASCADE`.
- `SCHEMA_VERSION` trong `novel2epub/db.py` bump 4 → 5.
- Hàm render khối trả chuỗi rỗng `""` khi không có dữ liệu, để placeholder biến
  mất sạch khỏi prompt.
- Chạy test: `pytest tests/ -v`. Chạy một file: `pytest tests/test_characters.py -v`.
- Mỗi task kết thúc bằng một commit.
- **Chỉ backend `openai` được hưởng lợi.** `hachimimt` (NMT cục bộ), `google`,
  `libretranslate` dịch thẳng văn bản như Google Translate — không nhận chỉ dẫn,
  không có `_build_prompt`. Bảng nhân vật và preset thể loại không tác động gì
  tới chúng. Đừng cố nhét khối vào các đường đó.

---

### Task 1: `characters.py` — dataclass và dựng từ row DB

**Files:**
- Create: `novel2epub/characters.py`
- Test: `tests/test_characters.py`

**Interfaces:**
- Consumes: không có.
- Produces: `Character(source, target, aliases, gender, self_pronoun,
  narrator_ref, role_note, importance)` — `aliases` là `tuple[str, ...]`;
  `Relation(a_source, b_source, from_chapter, a_calls_b, a_self, note)` —
  `from_chapter` là `int`. Hai hàm
  `characters_from_rows(rows) -> list[Character]` và
  `relations_from_rows(rows) -> list[Relation]`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_characters.py`:

```python
"""Tests cho bảng nhân vật & ngôi xưng (logic thuần, không cần DB)."""
from novel2epub import characters as C
from novel2epub.characters import Character, Relation


def test_characters_from_rows_parses_aliases():
    rows = [
        ("林凡", "Lâm Phàm", "凡儿|林少爷", "nam", "ta", "hắn", "đồ đệ của Huyền Trần Tử", "main"),
        ("苏清雪", "Tô Thanh Tuyết", "", "nu", "ta", "nàng", "", "side"),
    ]
    out = C.characters_from_rows(rows)
    assert len(out) == 2
    assert out[0] == Character(
        source="林凡", target="Lâm Phàm", aliases=("凡儿", "林少爷"),
        gender="nam", self_pronoun="ta", narrator_ref="hắn",
        role_note="đồ đệ của Huyền Trần Tử", importance="main",
    )
    assert out[1].aliases == ()


def test_characters_from_rows_skips_missing_source():
    rows = [("", "Bỏ", "", "", "", "", "", "side")]
    assert C.characters_from_rows(rows) == []


def test_relations_from_rows_skips_missing_endpoint():
    rows = [
        ("林凡", "苏清雪", 120, "em", "anh", ""),
        ("林凡", "", 0, "x", "y", ""),
    ]
    out = C.relations_from_rows(rows)
    assert out == [Relation("林凡", "苏清雪", 120, "em", "anh", "")]
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_characters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novel2epub.characters'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `novel2epub/characters.py`:

```python
"""Bảng nhân vật & ngôi xưng theo ebook — logic thuần (không đụng DB/OS).

Giải bài toán: tiếng Trung chỉ có 我/你/他/她, còn tiếng Việt cần biết giới tính,
vai vế, độ thân sơ và GIAI ĐOẠN quan hệ mới chọn được ngôi xưng. Không thứ nào
nằm trong văn bản chunk, nên phải cấp cho model từ ngoài.

- `Character` : thuộc tính một nhân vật. `role_note` cố ý là văn xuôi tự do —
  vai vế trong truyện Trung không phải thuộc tính tuyệt đối của một người (A là
  sư phụ của B đồng thời là đồ đệ của C), nên mọi enum đơn trường đều sai, và
  LLM đọc văn xuôi chính xác hơn bất kỳ cấu trúc nào ép được.
- `Relation` : quan hệ CÓ HƯỚNG giữa hai nhân vật, kèm mốc `from_chapter` — thứ
  duy nhất cần cấu trúc chặt, vì LLM không đoán được thời điểm quan hệ chuyển
  giai đoạn (cô–tôi → em–anh).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    source: str
    target: str = ""
    aliases: tuple[str, ...] = ()
    gender: str = ""
    self_pronoun: str = ""
    narrator_ref: str = ""
    role_note: str = ""
    importance: str = "side"


@dataclass(frozen=True)
class Relation:
    a_source: str
    b_source: str
    from_chapter: int = 0
    a_calls_b: str = ""
    a_self: str = ""
    note: str = ""


def _split_aliases(raw: str) -> tuple[str, ...]:
    """Tách ô aliases (`凡儿|林少爷`) → tuple, trim, bỏ rỗng."""
    return tuple(p.strip() for p in (raw or "").split("|") if p.strip())


def characters_from_rows(rows) -> list[Character]:
    """Dựng list Character từ row DB
    `(source, target, aliases, gender, self_pronoun, narrator_ref, role_note,
    importance)`. Bỏ row thiếu `source`."""
    out: list[Character] = []
    for row in rows:
        source = (row[0] or "").strip()
        if not source:
            continue
        importance = (row[7] or "").strip() if len(row) > 7 else ""
        out.append(
            Character(
                source=source,
                target=(row[1] or "").strip(),
                aliases=_split_aliases(row[2] if len(row) > 2 else ""),
                gender=(row[3] or "").strip() if len(row) > 3 else "",
                self_pronoun=(row[4] or "").strip() if len(row) > 4 else "",
                narrator_ref=(row[5] or "").strip() if len(row) > 5 else "",
                role_note=(row[6] or "").strip() if len(row) > 6 else "",
                importance=importance or "side",
            )
        )
    return out


def relations_from_rows(rows) -> list[Relation]:
    """Dựng list Relation từ row DB
    `(a_source, b_source, from_chapter, a_calls_b, a_self, note)`.
    Bỏ row thiếu một trong hai đầu."""
    out: list[Relation] = []
    for row in rows:
        a = (row[0] or "").strip()
        b = (row[1] or "").strip()
        if not a or not b:
            continue
        try:
            from_chapter = int(row[2]) if len(row) > 2 and row[2] is not None else 0
        except (TypeError, ValueError):
            from_chapter = 0
        out.append(
            Relation(
                a_source=a,
                b_source=b,
                from_chapter=from_chapter,
                a_calls_b=(row[3] or "").strip() if len(row) > 3 else "",
                a_self=(row[4] or "").strip() if len(row) > 4 else "",
                note=(row[5] or "").strip() if len(row) > 5 else "",
            )
        )
    return out
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_characters.py -v`
Expected: PASS — 3 test.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/characters.py tests/test_characters.py
git commit -m "feat: dataclass Character/Relation + dựng từ row DB"
```

---

### Task 2: `characters.py` — lọc theo chunk và chọn mốc quan hệ

**Files:**
- Modify: `novel2epub/characters.py`
- Test: `tests/test_characters.py`

**Interfaces:**
- Consumes: `Character`, `Relation` từ Task 1.
- Produces: `filter_for_text(chars, text, *, source_language="") -> list[Character]`
  và `resolve_relations(relations, chapter_idx) -> list[Relation]` với
  `chapter_idx: int | None`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_characters.py`:

```python
# ---------- lọc theo chunk ----------

_LAM = Character(source="林凡", target="Lâm Phàm", aliases=("凡儿",),
                 narrator_ref="hắn", self_pronoun="ta", importance="main")
_TO = Character(source="苏清雪", target="Tô Thanh Tuyết", narrator_ref="nàng",
                importance="side")
_HUYEN = Character(source="玄尘子", target="Huyền Trần Tử", importance="side")


def test_filter_keeps_main_even_when_absent():
    # Chunk toàn đại từ, không nêu tên ai — main vẫn phải có mặt để giữ
    # narrator_ref, side thì không.
    out = C.filter_for_text([_LAM, _TO], "他看着她，沉默不语。")
    assert [c.source for c in out] == ["林凡"]


def test_filter_matches_alias():
    out = C.filter_for_text([_TO, _HUYEN], "凡儿，你回来了。玄尘子点头。")
    assert [c.source for c in out] == ["玄尘子"]

    lam_side = Character(source="林凡", aliases=("凡儿",), importance="side")
    out = C.filter_for_text([lam_side], "凡儿，你回来了。")
    assert [c.source for c in out] == ["林凡"]


def test_filter_latin_uses_word_boundary():
    lin = Character(source="Lin", importance="side")
    assert C.filter_for_text([lin], "Linda smiled.", source_language="en") == []
    assert C.filter_for_text([lin], "Lin smiled.", source_language="en") == [lin]


# ---------- chọn mốc quan hệ ----------

_R0 = Relation("林凡", "苏清雪", 0, "nàng", "ta")
_R120 = Relation("林凡", "苏清雪", 120, "em", "anh")
_R300 = Relation("林凡", "苏清雪", 300, "vợ", "anh")


def test_resolve_relations_picks_latest_at_or_before():
    assert C.resolve_relations([_R0, _R120, _R300], 200) == [_R120]
    assert C.resolve_relations([_R0, _R120, _R300], 300) == [_R300]
    assert C.resolve_relations([_R0, _R120, _R300], 50) == [_R0]


def test_resolve_relations_none_uses_chapter_zero():
    assert C.resolve_relations([_R0, _R120], None) == [_R0]


def test_resolve_relations_drops_pair_with_no_valid_milestone():
    assert C.resolve_relations([_R120], 50) == []
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_characters.py -v`
Expected: FAIL — `AttributeError: module 'novel2epub.characters' has no attribute 'filter_for_text'`

- [ ] **Step 3: Viết implementation tối thiểu**

Thêm vào `novel2epub/characters.py` (sau `relations_from_rows`):

```python
import re


def _mentions(needle: str, text: str, latin: bool) -> bool:
    """Nguồn Hán: khớp substring (chữ Hán không có ranh giới từ, giống
    idioms.filter_for_text). Nguồn Latin: khớp theo ranh giới từ để "Lin"
    không trúng "Linda"."""
    if not needle:
        return False
    if not latin:
        return needle in text
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text) is not None


def filter_for_text(
    chars: list[Character], text: str, *, source_language: str = ""
) -> list[Character]:
    """Giữ nhân vật đáng chèn vào prompt cho đoạn `text` này.

    Giữ khi: `importance == "main"` (LUÔN giữ, kể cả không xuất hiện), hoặc
    `source`/alias bất kỳ có mặt trong text.

    Luật "main luôn giữ" xử lý ca thật và hay gặp: cả chunk chỉ có "他… 他…"
    không nêu tên lần nào nên không match được gì, và thế là mất đúng
    `narrator_ref` cần nhất. Main thường <= 8 người nên chi phí token nhỏ.
    """
    latin = (source_language or "").strip().lower() not in ("", "zh", "cn", "zh-cn")
    out: list[Character] = []
    for c in chars:
        if c.importance == "main":
            out.append(c)
            continue
        if _mentions(c.source, text, latin):
            out.append(c)
            continue
        if any(_mentions(a, text, latin) for a in c.aliases):
            out.append(c)
    return out


def resolve_relations(
    relations: list[Relation], chapter_idx: int | None
) -> list[Relation]:
    """Với mỗi cặp (a,b) có hướng, chọn row có `from_chapter <= chapter_idx` lớn
    nhất; cặp không có mốc nào thoả thì bỏ.

    `chapter_idx is None` → chỉ lấy mốc 0. Chủ ý: khi không biết đang ở chương
    nào, đoán "quan hệ chưa thân" gây hại ít hơn đoán ngược lại.
    """
    limit = 0 if chapter_idx is None else int(chapter_idx)
    best: dict[tuple[str, str], Relation] = {}
    for rel in relations:
        if rel.from_chapter > limit:
            continue
        key = (rel.a_source, rel.b_source)
        current = best.get(key)
        if current is None or rel.from_chapter > current.from_chapter:
            best[key] = rel
    return list(best.values())
```

Chuyển `import re` lên khối import đầu file cho gọn (`from __future__` phải là
dòng đầu tiên).

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_characters.py -v`
Expected: PASS — 9 test.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/characters.py tests/test_characters.py
git commit -m "feat: lọc nhân vật theo chunk + chọn mốc quan hệ theo chương"
```

---

### Task 3: `characters.py` — render khối prompt và dòng ghim

**Files:**
- Modify: `novel2epub/characters.py`
- Test: `tests/test_characters.py`

**Interfaces:**
- Consumes: `Character`, `Relation`, `filter_for_text`, `resolve_relations`.
- Produces: `format_llm_block(chars, relations) -> str` và
  `format_pin_line(chars, forbid_words="") -> str`. Cả hai trả `""` khi rỗng.

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_characters.py`:

```python
# ---------- render khối prompt ----------

def test_format_llm_block_empty_returns_empty_string():
    assert C.format_llm_block([], []) == ""


def test_format_llm_block_renders_attributes_and_aliases():
    block = C.format_llm_block([_LAM], [])
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in block
    assert "林凡 = Lâm Phàm" in block
    assert "còn gọi: 凡儿" in block
    assert 'tự xưng "ta"' in block
    assert 'lời kể gọi "hắn"' in block


def test_format_llm_block_relation_needs_both_characters_present():
    # Chỉ có Lâm Phàm trong chars → dòng quan hệ tới Tô Thanh Tuyết bị bỏ.
    only_lam = C.format_llm_block([_LAM], [_R120])
    assert "với" not in only_lam

    both = C.format_llm_block([_LAM, _TO], [_R120])
    assert 'với Tô Thanh Tuyết: gọi "em", tự xưng "anh"' in both


def test_format_pin_line_lists_main_only():
    pin = C.format_pin_line([_LAM, _TO], forbid_words="anh/em/cậu/bạn")
    assert "Lâm Phàm" in pin
    assert "Tô Thanh Tuyết" not in pin   # side, không lên dòng ghim
    assert "CẤM dùng anh/em/cậu/bạn" in pin


def test_format_pin_line_empty_without_main():
    assert C.format_pin_line([_TO], forbid_words="x") == ""
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_characters.py -v`
Expected: FAIL — `AttributeError: module 'novel2epub.characters' has no attribute 'format_llm_block'`

- [ ] **Step 3: Viết implementation tối thiểu**

Thêm vào `novel2epub/characters.py`:

```python
_BLOCK_HEADER = "BẢNG NHÂN VẬT & NGÔI XƯNG (bắt buộc, không tự ý đổi):"


def _display(char: Character) -> str:
    """Tên hiển thị: ưu tiên bản Việt, không có thì dùng bản gốc."""
    return char.target or char.source


def format_llm_block(chars: list[Character], relations: list[Relation]) -> str:
    """Khối bảng nhân vật cho prompt LLM. Trả "" khi rỗng để placeholder
    {characters} biến mất sạch (giống idioms.format_llm_block).

    Dòng quan hệ chỉ render khi CẢ HAI nhân vật đều nằm trong `chars` đã lọc —
    nhắc tới người không có mặt trong đoạn chỉ làm loãng prompt.
    """
    if not chars:
        return ""
    present = {c.source: c for c in chars}
    by_a: dict[str, list[Relation]] = {}
    for rel in relations:
        if rel.a_source in present and rel.b_source in present:
            by_a.setdefault(rel.a_source, []).append(rel)

    lines: list[str] = [_BLOCK_HEADER]
    for char in chars:
        head = f"{char.source} = {_display(char)}"
        if char.aliases:
            head += f" (còn gọi: {', '.join(char.aliases)})"
        if char.gender:
            head += f" · {char.gender}"
        lines.append(head)

        bits: list[str] = []
        if char.self_pronoun:
            bits.append(f'tự xưng "{char.self_pronoun}"')
        if char.narrator_ref:
            bits.append(f'lời kể gọi "{char.narrator_ref}"')
        if bits:
            lines.append("  · " + " · ".join(bits))
        if char.role_note:
            lines.append(f"  · {char.role_note}")

        for rel in by_a.get(char.source, []):
            parts = []
            if rel.a_calls_b:
                parts.append(f'gọi "{rel.a_calls_b}"')
            if rel.a_self:
                parts.append(f'tự xưng "{rel.a_self}"')
            if parts:
                lines.append(
                    f"  · với {_display(present[rel.b_source])}: " + ", ".join(parts)
                )
    return "\n".join(lines)


def format_pin_line(chars: list[Character], forbid_words: str = "") -> str:
    """Dòng nhắc ngắn nối vào CUỐI prompt (sau {text}).

    Chỉ nhân vật `main`, tối đa 2 dòng. Đặt sau nội dung vì chỉ dẫn ở cuối prompt
    được tuân thủ tốt hơn chỉ dẫn kẹp giữa.
    """
    mains = [c for c in chars if c.importance == "main"]
    bits: list[str] = []
    for char in mains:
        parts = []
        if char.self_pronoun:
            parts.append(f'tự xưng "{char.self_pronoun}"')
        if char.narrator_ref:
            parts.append(f'lời kể "{char.narrator_ref}"')
        if parts:
            bits.append(f"{_display(char)} = " + ", ".join(parts))
    if not bits:
        return ""
    out = "NHẮC LẠI: " + ". ".join(bits) + "."
    if forbid_words:
        out += f"\nCẤM dùng {forbid_words}."
    return out
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_characters.py -v`
Expected: PASS — 14 test.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/characters.py tests/test_characters.py
git commit -m "feat: render khối bảng nhân vật + dòng ghim cuối prompt"
```

---

### Task 4: `genre.py` — preset xưng hô theo thể loại

**Files:**
- Create: `novel2epub/genre.py`
- Test: `tests/test_genre.py`

**Interfaces:**
- Consumes: `novel2epub.hachimimt.honorific_normalize.is_classical` (đã có sẵn).
- Produces: `GENRE_PRESETS: dict[str, GenrePreset]`, `GENRE_KEYS: tuple[str, ...]`,
  `format_pronoun_rules(genre, user_policy="", text="") -> str`,
  `forbid_words(genre, text="") -> str`,
  `format_style_value(field, value) -> str`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_genre.py`:

```python
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
    assert "ngươi" in G.forbid_words("urban")
    assert G.forbid_words("xianxia") != G.forbid_words("urban")


def test_auto_detects_classical_from_text():
    # Text đậm tín hiệu tu tiên → nhánh cổ trang.
    classical = G.format_pronoun_rules("auto", text="他修真筑基，结丹成功，法宝在手。")
    assert "tại hạ" in classical
    # Text đậm tín hiệu hiện đại → nhánh hiện đại.
    modern = G.format_pronoun_rules("auto", text="他在公司用电脑打电话给经理。")
    assert "tại hạ" not in modern


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
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_genre.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novel2epub.genre'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `novel2epub/genre.py`:

```python
"""Preset xưng hô theo thể loại truyện — logic thuần (không đụng DB/OS).

Trước đây `translate.style.pronoun_policy` mặc định là chuỗi "contextual" và
được nhét thẳng vào prompt, tức model đọc được đúng một từ vô nghĩa. Module này
biến lựa chọn thể loại thành BỘ LUẬT THẬT: từ nên dùng, từ cấm, mức Hán Việt.

`auto` không tự phát minh cách đoán thể loại mà dùng lại
`hachimimt.honorific_normalize.is_classical()` — nơi đã có sẵn danh sách tín
hiệu tu tiên / hiện đại.

Lưu ý phân biệt: `hachimimt/postprocess_policy.py` có `classify_genre()` cho
mục đích khác (chính sách hậu xử lý MT), không liên quan module này.
"""
from __future__ import annotations

from dataclasses import dataclass

from .hachimimt.honorific_normalize import is_classical

# Giá trị mặc định cũ của style.pronoun_policy — coi như "người dùng chưa ghi
# gì", không nối vào luật.
_DEFAULT_POLICY = "contextual"


@dataclass(frozen=True)
class GenrePreset:
    key: str
    label: str
    use_words: str
    forbid_words: str
    han_viet_hint: str
    extra_rules: tuple[str, ...] = ()


GENRE_PRESETS: dict[str, GenrePreset] = {
    "auto": GenrePreset(
        key="auto",
        label="Tự động (theo nội dung)",
        use_words="",
        forbid_words="",
        han_viet_hint="Cân bằng: giữ Hán Việt cho tên riêng và thuật ngữ đặc thù, "
                      "phần còn lại ưu tiên thuần Việt.",
    ),
    "xianxia": GenrePreset(
        key="xianxia",
        label="Tiên hiệp / Huyền huyễn / Cổ trang",
        use_words="ta, ngươi, hắn, y, gã, nàng, tại hạ, bổn tọa, lão phu, thiếp, "
                  "tiểu nữ, đạo hữu, tiền bối, vãn bối, sư phụ, sư huynh, sư tỷ, "
                  "sư đệ, sư muội, công tử, cô nương",
        forbid_words="tôi, cậu, bạn, anh ấy, cô ấy",
        han_viet_hint="Hán Việt cao: tên riêng, công pháp, cảnh giới, chức danh giữ "
                      "nguyên dạng Hán Việt, viết hoa, nhất quán toàn truyện.",
        extra_rules=(
            "Lời kể dùng hắn/y/gã (nam), nàng (nữ) — KHÔNG dùng anh/cô ấy.",
            "Đơn vị đo cổ (里/丈/尺/两/更/时辰) giữ hệ cổ: dặm, trượng, thước, "
            "lượng, canh, canh giờ.",
        ),
    ),
    "urban": GenrePreset(
        key="urban",
        label="Đô thị / Hiện đại",
        use_words="tôi, cậu, anh, chị, em, ông, bà, nó, tao, mày",
        forbid_words="ta, ngươi, hắn, nàng, chàng, tiểu tử, tại hạ",
        han_viet_hint="Hán Việt thấp: 心动 → \"tim đập loạn\", KHÔNG \"tâm động\"; "
                      "总裁 → \"tổng giám đốc\"; 微信 → \"WeChat\".",
        extra_rules=(
            "Xưng hô gia đình và công sở theo đúng thứ bậc (ba/mẹ/anh/chị, "
            "anh/chị + tên, sếp, giám đốc X).",
        ),
    ),
    "romance": GenrePreset(
        key="romance",
        label="Ngôn tình / Đam mỹ",
        use_words="tôi, cậu, anh, em, cô, mình",
        forbid_words="ta, ngươi, hắn, nàng, tại hạ",
        han_viet_hint="Hán Việt thấp, ưu tiên từ mềm và tự nhiên.",
        extra_rules=(
            "Xưng hô ĐỔI theo tiến triển quan hệ — tuân thủ đúng mốc ghi trong "
            "BẢNG NHÂN VẬT, không tự ý đổi sớm hay muộn.",
            "Ưu tiên câu mềm, nhiều nội tâm.",
        ),
    ),
    "system_game": GenrePreset(
        key="system_game",
        label="Võng du / Hệ thống / Vô hạn lưu",
        use_words="tôi, cậu, anh, em, Ký chủ, Người chơi",
        forbid_words="tại hạ, bổn tọa, thiếp",
        han_viet_hint="Hán Việt thấp; thuật ngữ game giữ nguyên hoặc thuần Việt "
                      "nhất quán (HP, MP, buff, kỹ năng).",
        extra_rules=(
            "Khối thông báo hệ thống giữ nguyên cấu trúc ngoặc, chuẩn hoá 【】 "
            "thành [ ], và KHÔNG đổi số liệu.",
            "Giọng hệ thống xưng \"Ký chủ\"/\"Người chơi\", máy móc, không cảm xúc.",
        ),
    ),
    "western": GenrePreset(
        key="western",
        label="Khoa huyễn / Dị giới Tây phương",
        use_words="tôi, cậu, anh, cô, ngài",
        forbid_words="ta, ngươi, tại hạ, bổn tọa, đạo hữu",
        han_viet_hint="Thuật ngữ kỹ thuật KHÔNG Hán Việt hoá: 基因 → gen (không "
                      "\"cơ nhân\"), 病毒 → virus, 芯片 → chip.",
        extra_rules=(
            "Tên riêng giữ dạng chữ Latin gốc; chức danh Tây phương dùng bá tước, "
            "hiệp sĩ, pháp sư, thánh nữ.",
        ),
    ),
}

GENRE_KEYS: tuple[str, ...] = tuple(GENRE_PRESETS)


def resolve_genre(genre: str, text: str = "") -> GenrePreset:
    """Trả preset thực dùng. Giá trị lạ hoặc rỗng → `auto`; `auto` thì đoán từ
    nội dung qua `is_classical()`."""
    key = (genre or "").strip().lower() or "auto"
    if key not in GENRE_PRESETS:
        key = "auto"
    if key != "auto":
        return GENRE_PRESETS[key]
    if text and is_classical(text):
        return GENRE_PRESETS["xianxia"]
    if text:
        return GENRE_PRESETS["urban"]
    return GENRE_PRESETS["auto"]


def forbid_words(genre: str, text: str = "") -> str:
    """Danh sách từ cấm của thể loại — dùng cho dòng ghim cuối prompt."""
    return resolve_genre(genre, text).forbid_words


def format_pronoun_rules(genre: str, user_policy: str = "", text: str = "") -> str:
    """Render luật xưng hô để thay vào placeholder {pronoun_policy}.

    `user_policy` chỉ được nối thêm khi người dùng thực sự ghi gì đó khác giá trị
    mặc định cũ ("contextual") — giữ được quyền ghi đè mà không rò enum vào prompt.
    """
    preset = resolve_genre(genre, text)
    lines: list[str] = []
    if preset.use_words:
        lines.append(f"Dùng: {preset.use_words}.")
    if preset.forbid_words:
        lines.append(f"CẤM: {preset.forbid_words}.")
    if preset.han_viet_hint:
        lines.append(preset.han_viet_hint)
    lines.extend(preset.extra_rules)
    policy = (user_policy or "").strip()
    if policy and policy.lower() != _DEFAULT_POLICY:
        lines.append(policy)
    return "\n".join(lines)


# Enum style → câu mô tả đầy đủ. Trước đây các giá trị này ("balanced",
# "creative"...) được nhét thẳng vào prompt, model đọc được đúng một từ trần.
_STYLE_VALUES: dict[str, dict[str, str]] = {
    "han_viet_level": {
        "low": "Hán Việt thấp: ưu tiên thuần Việt, chỉ giữ Hán Việt cho tên riêng.",
        "balanced": "Hán Việt cân bằng: giữ cho tên riêng, công pháp, cảnh giới, "
                    "chức danh; các từ mô tả thường dùng thuần Việt.",
        "high": "Hán Việt cao: giữ đậm chất cổ trang, dùng Hán Việt cho cả từ mô tả "
                "khi vẫn dễ hiểu.",
    },
    "title_mode": {
        "literal": "Dịch tiêu đề sát nghĩa, không thêm bớt.",
        "creative": "Dịch tiêu đề thoát ý cho hay và gọn, giữ đúng tinh thần bản gốc.",
    },
}


def format_style_value(field: str, value: str) -> str:
    """Map giá trị enum của style sang mô tả đầy đủ. Giá trị người dùng tự gõ
    (không có trong bảng) được trả nguyên văn."""
    return _STYLE_VALUES.get(field, {}).get((value or "").strip(), value)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_genre.py -v`
Expected: PASS — 7 test.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/genre.py tests/test_genre.py
git commit -m "feat: preset xưng hô theo thể loại + map enum style sang mô tả"
```

---

### Task 5: Schema DB và CRUD trong Storage

**Files:**
- Modify: `novel2epub/db.py` (thêm 2 bảng vào danh sách DDL, `SCHEMA_VERSION` 4 → 5)
- Modify: `novel2epub/storage.py` (thêm methods cuối class `Storage`)
- Test: `tests/test_db_schema.py` (bổ sung), `tests/test_storage_characters.py` (mới)

**Interfaces:**
- Consumes: `Storage.conn`, `Storage.slug` (đã có).
- Produces: `read_character_entries() -> list[tuple]` (8 phần tử, thứ tự khớp
  `characters_from_rows`), `upsert_character(source, target, aliases, gender,
  self_pronoun, narrator_ref, role_note, importance) -> bool`,
  `delete_character(source) -> bool`, `read_relation_entries() -> list[tuple]`
  (6 phần tử, khớp `relations_from_rows`),
  `upsert_relation(a_source, b_source, from_chapter, a_calls_b, a_self, note) -> bool`,
  `delete_relation(a_source, b_source, from_chapter) -> bool`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_storage_characters.py`:

```python
"""Tests CRUD bảng nhân vật & quan hệ trong Storage."""
import pytest

from novel2epub.storage import Storage


@pytest.fixture()
def storage(tmp_path):
    return Storage(str(tmp_path), "truyen-test")


def test_upsert_and_read_character(storage):
    assert storage.upsert_character("林凡", "Lâm Phàm", "凡儿|林少爷", "nam",
                                    "ta", "hắn", "đồ đệ", "main") is True
    rows = storage.read_character_entries()
    assert rows == [("林凡", "Lâm Phàm", "凡儿|林少爷", "nam", "ta", "hắn", "đồ đệ", "main")]


def test_upsert_character_requires_source(storage):
    assert storage.upsert_character("", "Lâm Phàm") is False
    assert storage.read_character_entries() == []


def test_upsert_character_updates_in_place(storage):
    storage.upsert_character("林凡", "Lâm Phàm", importance="side")
    storage.upsert_character("林凡", "Lâm Phong", importance="main")
    rows = storage.read_character_entries()
    assert len(rows) == 1
    assert rows[0][1] == "Lâm Phong"
    assert rows[0][7] == "main"


def test_relation_roundtrip_and_multiple_milestones(storage):
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("林凡", "苏清雪", 120, "em", "anh")
    rows = storage.read_relation_entries()
    assert len(rows) == 2
    assert {r[2] for r in rows} == {0, 120}


def test_delete_character_cascades_to_relations(storage):
    storage.upsert_character("林凡", "Lâm Phàm")
    storage.upsert_character("苏清雪", "Tô Thanh Tuyết")
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("苏清雪", "林凡", 0, "chàng", "ta")

    assert storage.delete_character("林凡") is True
    assert storage.read_relation_entries() == []
    assert [r[0] for r in storage.read_character_entries()] == ["苏清雪"]


def test_delete_relation_targets_one_milestone(storage):
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("林凡", "苏清雪", 120, "em", "anh")
    assert storage.delete_relation("林凡", "苏清雪", 120) is True
    rows = storage.read_relation_entries()
    assert [r[2] for r in rows] == [0]
```

Thêm vào `tests/test_db_schema.py` (giữ nguyên style import/fixture sẵn có của
file đó — đọc file trước khi thêm):

```python
def test_characters_tables_exist(tmp_path):
    from novel2epub import db
    conn = db.get_thread_connection(str(tmp_path / "n2e.db"))
    db.init_schema(conn)
    names = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "characters" in names
    assert "character_relations" in names
    assert db.SCHEMA_VERSION == 5
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_storage_characters.py tests/test_db_schema.py -v`
Expected: FAIL — `AttributeError: 'Storage' object has no attribute 'upsert_character'`
và `assert 'characters' in names`.

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `novel2epub/db.py`: đổi `SCHEMA_VERSION = 4` thành `SCHEMA_VERSION = 5`,
và thêm hai DDL vào danh sách (đặt ngay sau khối `idioms`):

```python
    # ── bảng nhân vật & ngôi xưng theo ebook ──────────────────────────────
    # Giải lỗi ngôi xưng: tiếng Trung chỉ có 我/你/他/她, tiếng Việt cần biết
    # giới tính, vai vế, alias và GIAI ĐOẠN quan hệ. `role_note` cố ý là văn
    # xuôi tự do — LLM đọc tốt hơn mọi enum ép được.
    """
    CREATE TABLE IF NOT EXISTS characters (
        ebook_slug   TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        source       TEXT NOT NULL,
        target       TEXT NOT NULL DEFAULT '',
        aliases      TEXT NOT NULL DEFAULT '',
        gender       TEXT NOT NULL DEFAULT '',
        self_pronoun TEXT NOT NULL DEFAULT '',
        narrator_ref TEXT NOT NULL DEFAULT '',
        role_note    TEXT NOT NULL DEFAULT '',
        importance   TEXT NOT NULL DEFAULT 'side',
        position     INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (ebook_slug, source)
    ) WITHOUT ROWID
    """,
    # Quan hệ CÓ HƯỚNG (A→B khác B→A: đồ đệ gọi sư phụ khác chiều ngược lại).
    # `from_chapter` nằm trong khoá chính để một cặp có nhiều mốc xưng hô.
    """
    CREATE TABLE IF NOT EXISTS character_relations (
        ebook_slug   TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        a_source     TEXT NOT NULL,
        b_source     TEXT NOT NULL,
        from_chapter INTEGER NOT NULL DEFAULT 0,
        a_calls_b    TEXT NOT NULL DEFAULT '',
        a_self       TEXT NOT NULL DEFAULT '',
        note         TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (ebook_slug, a_source, b_source, from_chapter)
    ) WITHOUT ROWID
    """,
```

Trong `novel2epub/storage.py`, thêm vào cuối class `Storage`:

```python
    # ----- nhân vật & ngôi xưng (per-ebook) -----
    def read_character_entries(self) -> list[tuple[str, str, str, str, str, str, str, str]]:
        """Đọc nhân vật của ebook → list tuple 8 phần tử, thứ tự khớp
        `characters.characters_from_rows`."""
        rows = self.conn.execute(
            "SELECT source, target, aliases, gender, self_pronoun, narrator_ref, "
            "role_note, importance FROM characters WHERE ebook_slug=? ORDER BY position",
            (self.slug,),
        ).fetchall()
        return [
            (r["source"], r["target"], r["aliases"], r["gender"], r["self_pronoun"],
             r["narrator_ref"], r["role_note"], r["importance"])
            for r in rows
        ]

    def upsert_character(
        self,
        source: str,
        target: str = "",
        aliases: str = "",
        gender: str = "",
        self_pronoun: str = "",
        narrator_ref: str = "",
        role_note: str = "",
        importance: str = "side",
    ) -> bool:
        """Thêm/cập nhật MỘT nhân vật. Trim; bỏ qua nếu thiếu source. Mục mới
        nhận position = max+1; trùng source → cập nhật tại chỗ."""
        source = (source or "").strip()
        if not source:
            return False
        importance = (importance or "").strip() or "side"
        self.ensure_dirs()
        with self.conn:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM characters "
                "WHERE ebook_slug=?",
                (self.slug,),
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO characters (ebook_slug, source, target, aliases, gender,
                    self_pronoun, narrator_ref, role_note, importance, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, source) DO UPDATE SET
                    target = excluded.target, aliases = excluded.aliases,
                    gender = excluded.gender, self_pronoun = excluded.self_pronoun,
                    narrator_ref = excluded.narrator_ref, role_note = excluded.role_note,
                    importance = excluded.importance
                """,
                (self.slug, source, (target or "").strip(), (aliases or "").strip(),
                 (gender or "").strip(), (self_pronoun or "").strip(),
                 (narrator_ref or "").strip(), (role_note or "").strip(),
                 importance, row["next_pos"]),
            )
        return True

    def delete_character(self, source: str) -> bool:
        """Xoá nhân vật VÀ mọi quan hệ dính tới nó (cả hai chiều).

        Dọn tường minh ở đây thay vì FK ghép khoá tới `characters` — quan hệ mồ
        côi không gây lỗi nhưng làm bẩn dữ liệu và bảng quan hệ trên web.
        """
        source = (source or "").strip()
        if not source:
            return False
        with self.conn:
            self.conn.execute(
                "DELETE FROM character_relations WHERE ebook_slug=? AND (a_source=? OR b_source=?)",
                (self.slug, source, source),
            )
            cur = self.conn.execute(
                "DELETE FROM characters WHERE ebook_slug=? AND source=?",
                (self.slug, source),
            )
        return cur.rowcount > 0

    def read_relation_entries(self) -> list[tuple[str, str, int, str, str, str]]:
        """Đọc quan hệ của ebook → list tuple 6 phần tử, thứ tự khớp
        `characters.relations_from_rows`."""
        rows = self.conn.execute(
            "SELECT a_source, b_source, from_chapter, a_calls_b, a_self, note "
            "FROM character_relations WHERE ebook_slug=? "
            "ORDER BY a_source, b_source, from_chapter",
            (self.slug,),
        ).fetchall()
        return [
            (r["a_source"], r["b_source"], int(r["from_chapter"]),
             r["a_calls_b"], r["a_self"], r["note"])
            for r in rows
        ]

    def upsert_relation(
        self,
        a_source: str,
        b_source: str,
        from_chapter: int = 0,
        a_calls_b: str = "",
        a_self: str = "",
        note: str = "",
    ) -> bool:
        """Thêm/cập nhật MỘT mốc quan hệ có hướng. Bỏ qua nếu thiếu một đầu."""
        a_source = (a_source or "").strip()
        b_source = (b_source or "").strip()
        if not a_source or not b_source:
            return False
        try:
            from_chapter = int(from_chapter)
        except (TypeError, ValueError):
            from_chapter = 0
        self.ensure_dirs()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO character_relations (ebook_slug, a_source, b_source,
                    from_chapter, a_calls_b, a_self, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, a_source, b_source, from_chapter) DO UPDATE SET
                    a_calls_b = excluded.a_calls_b, a_self = excluded.a_self,
                    note = excluded.note
                """,
                (self.slug, a_source, b_source, from_chapter,
                 (a_calls_b or "").strip(), (a_self or "").strip(), (note or "").strip()),
            )
        return True

    def delete_relation(self, a_source: str, b_source: str, from_chapter: int = 0) -> bool:
        a_source = (a_source or "").strip()
        b_source = (b_source or "").strip()
        if not a_source or not b_source:
            return False
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM character_relations WHERE ebook_slug=? AND a_source=? "
                "AND b_source=? AND from_chapter=?",
                (self.slug, a_source, b_source, int(from_chapter)),
            )
        return cur.rowcount > 0
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_storage_characters.py tests/test_db_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Chạy toàn bộ test để chắc schema mới không phá gì**

Run: `pytest tests/ -v`
Expected: PASS toàn bộ.

- [ ] **Step 6: Commit**

```bash
git add novel2epub/db.py novel2epub/storage.py tests/test_storage_characters.py tests/test_db_schema.py
git commit -m "feat: bảng characters/character_relations + CRUD trong Storage"
```

---

### Task 6: Config — hồi sinh `translate.genre` và sửa prompt mặc định

**Files:**
- Modify: `novel2epub/config.py` (`TranslateConfig.genre` mặc định, `DEFAULT_PROMPT`,
  `EN_DEFAULT_PROMPT`)
- Modify: `novel2epub/config_writer.py:25-27` (gỡ `genre` khỏi deprecated)
- Modify: `novel2epub/presets/go.py` (`GO_PROMPT` thêm `{characters}`)
- Test: `tests/test_config.py` (bổ sung)

**Interfaces:**
- Consumes: không có.
- Produces: `TranslateConfig.genre` mặc định `"auto"` và được `config_writer`
  ghi xuống DB; ba template prompt đều chứa placeholder `{characters}`.

**Bối cảnh:** `TranslateConfig.genre` đã tồn tại từ trước nhưng bị liệt vào
`_DEPRECATED_TRANSLATE_FIELDS` với lý do "không có UI". Task 9 cấp UI cho nó,
nên ở đây ta gỡ khỏi danh sách deprecated thay vì tạo field mới trùng tên.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_config.py`:

```python
def test_translate_genre_defaults_to_auto():
    from novel2epub.config import TranslateConfig
    assert TranslateConfig().genre == "auto"


def test_genre_no_longer_deprecated():
    from novel2epub.config_writer import _DEPRECATED_TRANSLATE_FIELDS
    assert "genre" not in _DEPRECATED_TRANSLATE_FIELDS


def test_default_prompts_carry_characters_placeholder():
    from novel2epub.config import DEFAULT_PROMPT, EN_DEFAULT_PROMPT
    from novel2epub.presets.go import GO_PROMPT
    for tpl in (DEFAULT_PROMPT, EN_DEFAULT_PROMPT, GO_PROMPT):
        assert "{characters}" in tpl


def test_default_prompt_no_longer_bans_ta_nguoi_globally():
    # Vế "KHÔNG bê nguyên ta/ngươi" sai với cổ trang — đã chuyển xuống preset
    # urban/romance, nơi nó đúng.
    from novel2epub.config import DEFAULT_PROMPT
    assert "KHÔNG bê nguyên ta/ngươi" not in DEFAULT_PROMPT
    assert "[LỜI KỂ]" in DEFAULT_PROMPT
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_config.py -v -k "genre or characters or ta_nguoi"`
Expected: FAIL — `assert '' == 'auto'` và `assert '{characters}' in tpl`.

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `novel2epub/config.py`, dòng 328:

```python
    genre: str = "auto"
```

Trong `novel2epub/config_writer.py`, dòng 25-27:

```python
_DEPRECATED_TRANSLATE_FIELDS = frozenset({
    "glossary", "glossary_files", "profile",
})
```

Trong `DEFAULT_PROMPT`, thay luật 2 (dòng bắt đầu `2. Ngôi xưng theo quan hệ`)
bằng khối sau:

```
2. Ngôi xưng theo quan hệ và ngữ cảnh — tuân thủ BẢNG NHÂN VẬT và quy tắc xưng hô bên dưới.
   - [LỜI KỂ] ngôi 3 nhất quán theo bảng nhân vật.
   - [THOẠI] ngôi xưng theo quan hệ người nói ↔ người nghe, độc lập với lời kể.
   - [NỘI TÂM] dùng cách nhân vật tự gọi mình.
   - [HỆ THỐNG] giọng máy, xưng "Ký chủ"/"Người chơi", không cảm xúc.
```

Vẫn trong `DEFAULT_PROMPT`, thêm `{characters}` ngay sau dòng `{idioms}`:

```
{glossary}
{idioms}
{characters}
--- Nội dung cần dịch ---
{text}{auto_glossary_block}
```

Áp cùng hai thay đổi cho `EN_DEFAULT_PROMPT` (luật 2 tiếng Anh thành
`2. Pronouns follow the CHARACTER TABLE and pronoun rules below.` kèm bốn dòng
`[LỜI KỂ]/[THOẠI]/[NỘI TÂM]/[HỆ THỐNG]` giữ nguyên tiếng Việt vì đầu ra là tiếng
Việt, và thêm `{characters}` sau `{idioms}`).

Trong `novel2epub/presets/go.py`, `GO_PROMPT` thêm `{characters}` sau `{glossary}`:

```
{glossary}
{characters}
--- Văn bản gốc ---
{text}{auto_glossary_block}
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/config.py novel2epub/config_writer.py novel2epub/presets/go.py tests/test_config.py
git commit -m "feat: hồi sinh translate.genre + placeholder {characters} trong prompt mặc định"
```

---

### Task 7: Đấu nối vào translator và pipeline

**Files:**
- Modify: `novel2epub/translator.py` (import, `__init__`, `_build_prompt`,
  `_clamp_to_prompt_budget`, `translate`)
- Modify: `novel2epub/pipeline.py:839` (truyền `chapter_idx`)
- Test: `tests/test_pipeline_translate_chunk.py` (bổ sung)

**Interfaces:**
- Consumes: `characters.filter_for_text/resolve_relations/format_llm_block/
  format_pin_line`, `genre.format_pronoun_rules/forbid_words/format_style_value`,
  `Storage.read_character_entries/read_relation_entries`.
- Produces: `Translator.translate(text, *, chapter_idx=None, on_chunk=None,
  on_glossary=None)` — kwarg mới, tương thích ngược.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_pipeline_translate_chunk.py` (đọc file trước để dùng đúng
fixture/helper sẵn có; nếu file chưa có helper dựng `OpenAITranslator` thì dựng
trực tiếp như dưới):

```python
def _translator_with_characters(tmp_path, template):
    from novel2epub.config import TranslateConfig
    from novel2epub.storage import Storage
    from novel2epub.translator import OpenAITranslator

    storage = Storage(str(tmp_path), "truyen-test")
    storage.upsert_character("林凡", "Lâm Phàm", "凡儿", "nam", "ta", "hắn", "", "main")
    storage.upsert_character("苏清雪", "Tô Thanh Tuyết", "", "nu", "", "nàng", "", "side")
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("林凡", "苏清雪", 120, "em", "anh")

    cfg = TranslateConfig()
    cfg.genre = "xianxia"
    cfg.openai.prompt_template = template
    return OpenAITranslator(cfg, storage=storage), storage


def test_prompt_contains_character_block(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "A\n{characters}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=200)
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in prompt
    assert "林凡 = Lâm Phàm" in prompt          # main, luôn chèn
    assert 'với Tô Thanh Tuyết: gọi "em", tự xưng "anh"' in prompt   # mốc 120


def test_prompt_uses_chapter_zero_milestone_when_idx_missing(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "A\n{characters}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=None)
    assert 'gọi "nàng"' in prompt
    assert 'gọi "em"' not in prompt


def test_block_injected_when_template_lacks_placeholder(tmp_path):
    # Template pin cũ không có {characters} → vẫn phải được chèn, ngay trước nội dung.
    tr, _ = _translator_with_characters(tmp_path, "A\n{glossary}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=0)
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in prompt
    assert prompt.index("BẢNG NHÂN VẬT") < prompt.index("苏清雪 走了进来。")


def test_pin_line_is_last(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "A\n{characters}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=0)
    assert "NHẮC LẠI:" in prompt
    assert prompt.index("NHẮC LẠI:") > prompt.index("苏清雪 走了进来。")


def test_pronoun_policy_renders_genre_rules(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "P={pronoun_policy}\n{text}")
    prompt = tr._build_prompt("走。", chapter_idx=0)
    assert "tại hạ" in prompt
    assert "contextual" not in prompt
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_pipeline_translate_chunk.py -v -k character or pin or pronoun`
Expected: FAIL — `TypeError: _build_prompt() got an unexpected keyword argument 'chapter_idx'`

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `novel2epub/translator.py`, thêm import cạnh `from . import idioms as idioms_mod`:

```python
from . import characters as characters_mod
from . import genre as genre_mod
```

Thêm loader cạnh `load_idioms_list`:

```python
def load_characters(cfg: TranslateConfig, storage: "Storage | None") -> list:
    """Đọc bảng nhân vật của ebook. Trả [] khi chưa có storage."""
    if storage is None:
        return []
    return characters_mod.characters_from_rows(storage.read_character_entries())


def load_relations(cfg: TranslateConfig, storage: "Storage | None") -> list:
    """Đọc bảng quan hệ của ebook. Trả [] khi chưa có storage."""
    if storage is None:
        return []
    return characters_mod.relations_from_rows(storage.read_relation_entries())
```

Trong `__init__` (sau `self.idioms = ...`):

```python
        self.characters = load_characters(cfg, storage)
        self.relations = load_relations(cfg, storage)
```

Thay `_build_prompt` (translator.py:380) bằng:

```python
    def _build_prompt(self, text: str, chapter_idx: int | None = None) -> str:
        tpl = self.openai.prompt_template
        auto_block = _AUTO_GLOSSARY_BLOCK if self.cfg.auto_glossary else ""
        # Use .replace() instead of .format() so that {auto_glossary_block}
        # stays as literal text in the template visible in the settings textarea
        # (autosave pins whatever the textarea contains).
        idiom_block = idioms_mod.format_llm_block(
            idioms_mod.filter_for_text(self.idioms, text)
        )
        chars = characters_mod.filter_for_text(
            self.characters, text, source_language=self.cfg.source_language
        )
        rels = characters_mod.resolve_relations(self.relations, chapter_idx)
        char_block = characters_mod.format_llm_block(chars, rels)
        style = self.cfg.style
        prompt = (
            tpl
            .replace("{text}", text)
            .replace("{glossary}", _format_glossary(self._glossary_for_prompt(text)))
            .replace("{idioms}", idiom_block)
            .replace("{characters}", char_block)
            .replace("{tone}", style.tone)
            .replace("{pronoun_policy}", genre_mod.format_pronoun_rules(
                self.cfg.genre, style.pronoun_policy, text))
            .replace("{keep_paragraphs}", str(style.keep_paragraphs))
            .replace("{title_mode}", genre_mod.format_style_value("title_mode", style.title_mode))
            .replace("{han_viet_level}", genre_mod.format_style_value(
                "han_viet_level", style.han_viet_level))
        )
        # Back-compat: template pin cũ không có {characters} → chèn ngay trước
        # nội dung (đúng chỗ mong muốn về mặt recency) thay vì im lặng bỏ qua.
        if char_block and "{characters}" not in tpl:
            prompt = prompt.replace(text, f"{char_block}\n\n{text}", 1)
        # Back-compat: old pinned templates without the placeholder → append.
        if "{auto_glossary_block}" in tpl:
            prompt = prompt.replace("{auto_glossary_block}", auto_block)
        elif auto_block:
            prompt += auto_block
        # Back-compat: strip the removed {fixup_warning} placeholder from old
        # pinned templates so it doesn't leak into the prompt literally.
        prompt = prompt.replace("{fixup_warning}", "")
        # Dòng ghim nối bằng code (không qua placeholder) nên chạy được với MỌI
        # template, kể cả prompt người dùng đã pin từ trước.
        pin = characters_mod.format_pin_line(
            chars, genre_mod.forbid_words(self.cfg.genre, text)
        )
        if pin:
            prompt = f"{prompt}\n\n{pin}"
        return prompt
```

Sửa `_translate_chunk` để mang `chapter_idx` xuống:

```python
    def _translate_chunk(
        self,
        chunk_text: str,
        glossary_accumulator: list[dict] | None = None,
        meta_accumulator: dict[str, Any] | None = None,
        chapter_idx: int | None = None,
    ) -> str:
```

và dòng gọi bên trong:

```python
        out, meta = self._run_chat_with_retry_meta(
            self._build_prompt(chunk_text, chapter_idx)
        )
```

Trong `_clamp_to_prompt_budget`, đổi docstring và dòng đo overhead để tính cả
khối characters (khối này nằm trong `_build_prompt` nên chỉ cần truyền
`chapter_idx`):

```python
    def _clamp_to_prompt_budget(
        self, max_chars: int, text: str, chapter_idx: int | None = None
    ) -> int:
        """Thu nhỏ budget nội dung mỗi chunk để TỔNG prompt (template + glossary
        + idiom + bảng nhân vật + nội dung) không vượt cfg.prompt_max_chars.
        ...
        """
        budget = self.cfg.prompt_max_chars
        if budget <= 0:
            return max_chars
        overhead = len(self._build_prompt(text, chapter_idx)) - len(text)
```

Trong `translate`, thêm kwarg và truyền xuống ba chỗ:

```python
    def translate(
        self,
        text: str,
        *,
        chapter_idx: int | None = None,
        on_chunk: Callable[[int, int, str, bool], None] | None = None,
        on_glossary: Callable[[list[dict]], None] | None = None,
    ) -> str:
        if not text.strip():
            return text
        max_chars = self.cfg.chunk.max_chars or self.DEFAULT_MAX_CHARS
        max_chars = self._clamp_to_prompt_budget(max_chars, text, chapter_idx)
```

và hai lời gọi `self._translate_chunk(...)` trong hàm nhận thêm
`chapter_idx=chapter_idx`.

Cuối cùng, thêm kwarg `chapter_idx: int | None = None` vào chữ ký `translate`
của **tất cả** lớp translator để chúng thay thế lẫn nhau được:

| Lớp | Dòng | Xử lý `chapter_idx` |
|---|---|---|
| `Translator` (Protocol) | 231 | khai báo trong chữ ký |
| `NoopTranslator` | 242 | nhận và bỏ qua |
| `OpenAITranslator` | 572 | **dùng thật** (đường duy nhất có prompt) |
| `GoogleTranslator` | 685 | nhận và bỏ qua |
| `HachimiMTTranslator` | 735 | nhận và bỏ qua |
| `LibreTranslateTranslator` | 811 | nhận và bỏ qua |
| `RateLimited` | 864 | **chuyển tiếp** xuống translator bên trong |

`RateLimited` là wrapper — quên chuyển tiếp ở đây thì mọi ebook có giới hạn tốc
độ sẽ mất mốc `from_chapter` mà không báo lỗi gì.

**Vì sao các backend kia chỉ nhận rồi bỏ qua:** `hachimimt` (NMT cục bộ),
`google` và `libretranslate` dịch thẳng văn bản, không nhận chỉ dẫn — giống
Google Translate. Chúng không có `_build_prompt`, nên bảng nhân vật và preset
thể loại **không tác động gì** tới các backend này; toàn bộ giá trị của plan này
nằm ở backend `openai`. Giữ kwarg đồng nhất chỉ để các lớp còn hoán đổi được cho
nhau, KHÔNG phải để sau này nhét khối vào đó.

Trong `novel2epub/pipeline.py:839`:

```python
            lambda: translator.translate(
                source_text, chapter_idx=ch.idx,
                on_chunk=_on_chunk, on_glossary=_on_glossary,
            ),
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_pipeline_translate_chunk.py -v`
Expected: PASS.

- [ ] **Step 5: Chạy toàn bộ test**

Run: `pytest tests/ -v`
Expected: PASS toàn bộ — đặc biệt để ý các test gọi `translate()` không truyền
`chapter_idx` vẫn chạy.

- [ ] **Step 6: Commit**

```bash
git add novel2epub/translator.py novel2epub/pipeline.py tests/test_pipeline_translate_chunk.py
git commit -m "feat: chèn bảng nhân vật + luật thể loại vào prompt dịch"
```

---

### Task 8: Đấu nối vào Xuất RAW và vá `{idioms}` rò

**Files:**
- Modify: `novel2epub/bulk_transfer.py` (`build_export`, `build_translate_prompt_from_cfg`)
- Modify: `app/routes/chapters.py` (hai route `batch/export` và `batch/translate`)
- Test: `tests/test_bulk_transfer.py` (bổ sung)

**Interfaces:**
- Consumes: `characters.format_llm_block/filter_for_text/resolve_relations`,
  `genre.format_pronoun_rules`.
- Produces: `build_export(items, *, glossary=None, characters="", prompt=EDIT_PROMPT)`.

**Bối cảnh:** người dùng preview file này rồi dịch tay qua web chat, nên khối
nhân vật phải có mặt — thiếu thì bản dịch tay lệch xưng hô so với bản dịch API.
Ngoài ra `build_translate_prompt_from_cfg` hiện không xử lý `{idioms}`, nên
placeholder đó đang rò nguyên văn vào file export.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_bulk_transfer.py`:

```python
def test_build_export_includes_character_block():
    out = b.build_export(
        [(1, "Chương 1", "Nội dung")],
        glossary={"林凡": "Lâm Phàm"},
        characters="BẢNG NHÂN VẬT & NGÔI XƯNG (bắt buộc, không tự ý đổi):\n林凡 = Lâm Phàm",
    )
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in out
    # Khối nhân vật đứng sau glossary, trước chương đầu tiên.
    assert out.index("Glossary tham khảo") < out.index("BẢNG NHÂN VẬT")
    assert out.index("BẢNG NHÂN VẬT") < out.index("## idx:1")


def test_build_export_omits_empty_character_block():
    out = b.build_export([(1, "Chương 1", "Nội dung")], characters="")
    assert "BẢNG NHÂN VẬT" not in out


def test_translate_prompt_from_cfg_leaks_no_placeholders():
    # `config.Config` (config.py:449) là dataclass gốc, mọi field đều có default
    # nên dựng rỗng là đủ — hàm chỉ đọc cfg.translate.{openai,style,genre}.
    cfg = config.Config()
    out = b.build_translate_prompt_from_cfg(cfg)
    for placeholder in ("{idioms}", "{characters}", "{glossary}", "{text}",
                        "{pronoun_policy}", "{tone}", "{han_viet_level}"):
        assert placeholder not in out
    # Luật thể loại phải được render ra, không phải chuỗi enum trần.
    assert "contextual" not in out
```

`tests/test_bulk_transfer.py` đã có sẵn `from novel2epub import bulk_transfer as b`
và `from novel2epub import config` ở đầu file, nên hai test đầu cũng dùng `b.build_export(...)`
thay vì import lại.

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_bulk_transfer.py -v -k character or placeholder`
Expected: FAIL — `TypeError: build_export() got an unexpected keyword argument 'characters'`

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `novel2epub/bulk_transfer.py`, sửa `build_export`:

```python
def build_export(
    items: list[tuple[int, str, str]],
    *,
    glossary: dict[str, str] | None = None,
    characters: str = "",
    prompt: str = EDIT_PROMPT,
) -> str:
    """Gom các chương thành một khối xuất.

    items: list `(index, title, content)`; sẽ được sắp theo `index` tăng dần.
    glossary: bảng glossary hiện có để đính kèm (tham khảo, có thể rỗng).
    characters: khối bảng nhân vật ĐÃ render sẵn (có thể rỗng) — người dùng dịch
        tay qua web chat cần nó để xưng hô khớp với bản dịch API.
    """
    parts: list[str] = [prompt.rstrip()]

    glossary_block = _format_glossary_block(glossary or {})
    if glossary_block:
        parts.append(glossary_block)
    if characters.strip():
        parts.append(characters.strip())

    for index, title, content in sorted(items, key=lambda it: it[0]):
        parts.append(f"{chapter_marker(index, title)}\n{content.strip()}")

    return "\n\n".join(parts) + "\n"
```

Trong `build_translate_prompt_from_cfg`, sửa khối `.replace(...)`:

```python
    from . import genre as genre_mod

    tpl = cfg.translate.openai.prompt_template
    style = cfg.translate.style
    prompt = (
        tpl
        .replace("{tone}", style.tone)
        .replace("{pronoun_policy}", genre_mod.format_pronoun_rules(
            cfg.translate.genre, style.pronoun_policy))
        .replace("{keep_paragraphs}", str(style.keep_paragraphs))
        .replace("{title_mode}", genre_mod.format_style_value("title_mode", style.title_mode))
        .replace("{han_viet_level}", genre_mod.format_style_value(
            "han_viet_level", style.han_viet_level))
        .replace("{auto_glossary_block}", "")
        .replace("{fixup_warning}", "")
        .replace("{glossary}", "")
        # {idioms} và {characters} được build_export gắn riêng bên dưới, giống
        # cách glossary đang làm — nếu không xoá ở đây, placeholder rò nguyên
        # văn vào file export.
        .replace("{idioms}", "")
        .replace("{characters}", "")
    )
```

Trong `app/routes/chapters.py`, ở cả hai route `batch/export` và
`batch/translate`, dựng khối nhân vật trước khi gọi `build_export`:

```python
from novel2epub import characters as characters_mod

# ... bên trong route, sau khi đã có `storage` và danh sách `items`:
_chars_all = characters_mod.characters_from_rows(storage.read_character_entries())
_rels_all = characters_mod.relations_from_rows(storage.read_relation_entries())
# Một lô export trải nhiều chương nên không có chapter_idx duy nhất — dùng index
# NHỎ NHẤT trong lô (giữ trạng thái quan hệ ở đầu lô, an toàn hơn lấy mốc cuối),
# và lọc nhân vật trên toàn bộ raw của lô nối lại.
_batch_idx = min((idx for idx, _t, _c in items), default=0)
_batch_text = "\n".join(content for _i, _t, content in items)
characters_block = characters_mod.format_llm_block(
    characters_mod.filter_for_text(_chars_all, _batch_text),
    characters_mod.resolve_relations(_rels_all, _batch_idx),
)
```

rồi truyền `characters=characters_block` vào `build_export(...)`.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_bulk_transfer.py tests/test_bulk_transfer_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/bulk_transfer.py app/routes/chapters.py tests/test_bulk_transfer.py
git commit -m "feat: khối nhân vật trong Xuất RAW + vá {idioms} rò vào file export"
```

---

### Task 9: Trang web `/ebook/<slug>/characters` và dropdown Thể loại

**Files:**
- Create: `app/routes/characters.py`
- Create: `app/templates/characters.html`
- Modify: `app/main.py` (đăng ký router)
- Modify: `app/templates/ebook.html` (link sang trang mới)
- Modify: `app/templates/settings.html` (dropdown Thể loại)
- Test: `tests/test_routes_characters.py`

**Interfaces:**
- Consumes: `Storage.upsert_character/delete_character/read_character_entries/
  upsert_relation/delete_relation/read_relation_entries`, `genre.GENRE_PRESETS`.
- Produces: các endpoint `GET /ebook/{slug}/characters`,
  `GET /api/ebook/{slug}/characters/list`, `POST /api/ebook/{slug}/characters/entry`,
  `POST /api/ebook/{slug}/characters/delete`,
  `POST /api/ebook/{slug}/characters/relation`,
  `POST /api/ebook/{slug}/characters/relation/delete`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_routes_characters.py` (đọc `tests/test_routes_idioms.py` trước
để dùng đúng fixture client/tmp workspace sẵn có của repo, rồi viết theo mẫu đó):

```python
"""Tests route CRUD bảng nhân vật."""


def test_characters_page_renders(client, slug):
    resp = client.get(f"/ebook/{slug}/characters")
    assert resp.status_code == 200
    assert "Nhân vật" in resp.text


def test_upsert_and_list_character(client, slug):
    resp = client.post(
        f"/api/ebook/{slug}/characters/entry",
        data={"source": "林凡", "target": "Lâm Phàm", "aliases": "凡儿",
              "gender": "nam", "self_pronoun": "ta", "narrator_ref": "hắn",
              "role_note": "đồ đệ", "importance": "main"},
    )
    assert resp.status_code == 200

    entries = client.get(f"/api/ebook/{slug}/characters/list").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["target"] == "Lâm Phàm"
    assert entries[0]["importance"] == "main"


def test_relation_crud(client, slug):
    client.post(f"/api/ebook/{slug}/characters/entry",
                data={"source": "林凡", "target": "Lâm Phàm"})
    client.post(f"/api/ebook/{slug}/characters/entry",
                data={"source": "苏清雪", "target": "Tô Thanh Tuyết"})
    client.post(f"/api/ebook/{slug}/characters/relation",
                data={"a_source": "林凡", "b_source": "苏清雪",
                      "from_chapter": "120", "a_calls_b": "em", "a_self": "anh"})

    entries = client.get(f"/api/ebook/{slug}/characters/list").json()["entries"]
    lam = next(e for e in entries if e["source"] == "林凡")
    assert lam["relations"] == [
        {"b_source": "苏清雪", "b_target": "Tô Thanh Tuyết", "from_chapter": 120,
         "a_calls_b": "em", "a_self": "anh", "note": ""}
    ]

    client.post(f"/api/ebook/{slug}/characters/relation/delete",
                data={"a_source": "林凡", "b_source": "苏清雪", "from_chapter": "120"})
    entries = client.get(f"/api/ebook/{slug}/characters/list").json()["entries"]
    assert next(e for e in entries if e["source"] == "林凡")["relations"] == []


def test_delete_character_removes_its_relations(client, slug):
    client.post(f"/api/ebook/{slug}/characters/entry", data={"source": "林凡"})
    client.post(f"/api/ebook/{slug}/characters/entry", data={"source": "苏清雪"})
    client.post(f"/api/ebook/{slug}/characters/relation",
                data={"a_source": "林凡", "b_source": "苏清雪", "a_calls_b": "nàng"})

    client.post(f"/api/ebook/{slug}/characters/delete", data={"sources": "林凡"})
    entries = client.get(f"/api/ebook/{slug}/characters/list").json()["entries"]
    assert [e["source"] for e in entries] == ["苏清雪"]
    assert entries[0]["relations"] == []
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_routes_characters.py -v`
Expected: FAIL — 404 trên `/ebook/{slug}/characters`.

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `app/routes/characters.py`:

```python
"""Trang "Nhân vật" theo ebook — bảng nhân vật + ngôi xưng dùng cho prompt dịch.

Khác trang Glossary (map tên → tên), bảng này mang thuộc tính (giới tính, tự
xưng, cách lời kể gọi, alias) và quan hệ CÓ HƯỚNG giữa hai nhân vật kèm mốc
chương — thứ LLM không đoán được từ văn bản.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from novel2epub.storage import Storage

from .. import deps

router = APIRouter()


def _storage(slug: str) -> Storage:
    return Storage(deps.cfg().output.data_dir, slug)


@router.get("/ebook/{slug}/characters")
def characters_page(request: Request, slug: str):
    return deps.templates.TemplateResponse(
        request,
        "characters.html",
        {"slug": slug, "job": request.app.state.job.status()},
    )


@router.get("/api/ebook/{slug}/characters/list")
def characters_list(slug: str):
    storage = _storage(slug)
    targets = {row[0]: row[1] for row in storage.read_character_entries()}
    by_a: dict[str, list[dict]] = {}
    for a, b, from_chapter, a_calls_b, a_self, note in storage.read_relation_entries():
        by_a.setdefault(a, []).append({
            "b_source": b,
            "b_target": targets.get(b, ""),
            "from_chapter": from_chapter,
            "a_calls_b": a_calls_b,
            "a_self": a_self,
            "note": note,
        })
    entries = [
        {
            "source": source, "target": target, "aliases": aliases, "gender": gender,
            "self_pronoun": self_pronoun, "narrator_ref": narrator_ref,
            "role_note": role_note, "importance": importance,
            "relations": by_a.get(source, []),
        }
        for source, target, aliases, gender, self_pronoun, narrator_ref, role_note,
            importance in storage.read_character_entries()
    ]
    return JSONResponse({"entries": entries, "total": len(entries)})


@router.post("/api/ebook/{slug}/characters/entry")
def characters_upsert(
    slug: str,
    source: str = Form(...),
    target: str = Form(""),
    aliases: str = Form(""),
    gender: str = Form(""),
    self_pronoun: str = Form(""),
    narrator_ref: str = Form(""),
    role_note: str = Form(""),
    importance: str = Form("side"),
    original_source: str = Form(""),
):
    """Autosave MỘT nhân vật. Đổi tên gốc (original_source khác source) → xoá
    mục cũ trước, giống cách trang Idioms xử lý."""
    source = source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Cần tên gốc của nhân vật.")
    storage = _storage(slug)
    orig = original_source.strip()
    if orig and orig != source:
        storage.delete_character(orig)
    storage.upsert_character(source, target, aliases, gender, self_pronoun,
                             narrator_ref, role_note, importance)
    return JSONResponse({"ok": True})


@router.post("/api/ebook/{slug}/characters/delete")
def characters_delete(slug: str, sources: str = Form(...)):
    """Xoá một hoặc nhiều nhân vật (ngăn bằng `|`), kéo theo quan hệ liên quan."""
    storage = _storage(slug)
    removed = sum(1 for s in sources.split("|") if storage.delete_character(s))
    return JSONResponse({"ok": True, "removed": removed})


@router.post("/api/ebook/{slug}/characters/relation")
def characters_upsert_relation(
    slug: str,
    a_source: str = Form(...),
    b_source: str = Form(...),
    from_chapter: int = Form(0),
    a_calls_b: str = Form(""),
    a_self: str = Form(""),
    note: str = Form(""),
):
    if not _storage(slug).upsert_relation(a_source, b_source, from_chapter,
                                          a_calls_b, a_self, note):
        raise HTTPException(status_code=400, detail="Cần cả hai nhân vật.")
    return JSONResponse({"ok": True})


@router.post("/api/ebook/{slug}/characters/relation/delete")
def characters_delete_relation(
    slug: str,
    a_source: str = Form(...),
    b_source: str = Form(...),
    from_chapter: int = Form(0),
):
    removed = _storage(slug).delete_relation(a_source, b_source, from_chapter)
    return JSONResponse({"ok": True, "removed": removed})
```

Đăng ký router trong `app/main.py` cạnh các `include_router` khác (đọc file để
đặt đúng chỗ, theo đúng cách `idioms`/`glossary` đang được đăng ký):

```python
from .routes import characters as characters_routes
app.include_router(characters_routes.router)
```

Tạo `app/templates/characters.html` theo đúng khuôn `app/templates/idioms.html`
(đọc file đó trước và nhân bản cấu trúc): bảng chính 8 cột **Tên gốc · Tên Việt ·
Alias · Giới · Tự xưng · Lời kể gọi · Vai trò · ⭐main** cộng cột thao tác, ô nhập
autosave gọi `POST /api/ebook/{slug}/characters/entry`, checkbox chọn nhiều +
nút xoá hàng loạt gọi `.../characters/delete`.

Quan hệ nằm trong hàng con `<details>` của từng nhân vật, mỗi dòng gồm select
nhân vật B, ô số chương, ô "gọi", ô "tự xưng", nút xoá — gọi hai endpoint
`relation` / `relation/delete`.

Nếu dùng `<dialog>` ở bất kỳ đâu trong template này, **bắt buộc bọc nội dung
trong `<article>`** — Pico CSS v2 không bọc sẽ render thành khung trắng chiếm
trọn viewport.

Trong `app/templates/ebook.html`, thêm link sang trang mới ngay cạnh link
Glossary:

```html
<a href="/ebook/{{ slug }}/characters" role="button" class="secondary outline">Nhân vật</a>
```

Trong `app/templates/settings.html`, tab Dịch, thêm dropdown Thể loại (đọc file
để khớp đúng cách các field khác đang bind + autosave):

```html
<label>Thể loại
  <select name="translate.genre">
    {% for key, preset in genre_presets.items() %}
    <option value="{{ key }}" {% if cfg.translate.genre == key %}selected{% endif %}>
      {{ preset.label }}
    </option>
    {% endfor %}
  </select>
</label>
```

và truyền `genre_presets=GENRE_PRESETS` từ route settings (import
`from novel2epub.genre import GENRE_PRESETS`).

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_routes_characters.py -v`
Expected: PASS — 4 test.

- [ ] **Step 5: Kiểm tra trang chạy thật trong trình duyệt**

Khởi động preview qua `.claude/launch.json` (tạo entry chạy
`uvicorn app.main:app --port 8010` nếu chưa có), mở `/ebook/<slug>/characters`,
thêm một nhân vật và một quan hệ, xác nhận không có lỗi console và bảng render
đúng. Kiểm tra `/settings` hiển thị dropdown Thể loại.

- [ ] **Step 6: Chạy toàn bộ test**

Run: `pytest tests/ -v`
Expected: PASS toàn bộ.

- [ ] **Step 7: Commit**

```bash
git add app/routes/characters.py app/templates/characters.html app/main.py app/templates/ebook.html app/templates/settings.html tests/test_routes_characters.py
git commit -m "feat: trang Nhân vật per-ebook + dropdown Thể loại trong Settings"
```

---

### Task 10: Cập nhật CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: toàn bộ Task 1-9.
- Produces: không có code.

- [ ] **Step 1: Thêm mô tả module vào phần Architecture**

Thêm hai gạch đầu dòng vào danh sách module trong `CLAUDE.md`, đặt ngay sau mục
`idioms.py`:

```markdown
- `characters.py` — bảng NHÂN VẬT & ngôi xưng theo ebook (khác `idioms.py` global): 2 bảng SQLite `characters` (source/target/aliases/gender/self_pronoun/narrator_ref/role_note/importance) + `character_relations` (quan hệ CÓ HƯỚNG, `from_chapter` trong khoá chính nên một cặp có nhiều mốc xưng hô). Logic thuần: `filter_for_text` (khớp cả alias; nhân vật `importance=main` LUÔN được chèn kể cả không xuất hiện — chunk toàn "他… 他…" không match được gì thì vẫn phải giữ `narrator_ref`), `resolve_relations(rels, chapter_idx)` (chọn mốc `from_chapter <= N` lớn nhất; `None` → mốc 0), `format_llm_block` (khối `{characters}` trong prompt), `format_pin_line` (dòng nhắc nối vào CUỐI prompt sau `{text}` — chỉ dẫn cuối prompt được tuân thủ tốt hơn kẹp giữa). Template pin cũ không có `{characters}` thì khối được chèn ngay trước `{text}`. Web page `/ebook/<slug>/characters`.
- `genre.py` — preset xưng hô theo thể loại (`auto`/`xianxia`/`urban`/`romance`/`system_game`/`western`), thay cho việc nhét chuỗi enum `pronoun_policy: contextual` vào prompt. `format_pronoun_rules` render từ dùng/từ cấm/mức Hán Việt vào placeholder `{pronoun_policy}` (KHÔNG đổi template nên prompt đã pin vẫn nhận luật mới); `auto` đoán thể loại bằng `hachimimt.honorific_normalize.is_classical()`. Chọn qua `translate.genre` (field cũ, trước bị deprecate vì "không có UI" — Settings→Dịch nay có dropdown). `format_style_value` map enum `han_viet_level`/`title_mode` sang câu mô tả đầy đủ.
```

- [ ] **Step 2: Ghi chú thay đổi luật ngôi xưng trong prompt**

Thêm vào phần Technical Notes:

```markdown
- Ngôi xưng: luật 2 của `DEFAULT_PROMPT` KHÔNG còn vế "KHÔNG bê nguyên ta/ngươi" — vế này sai với cổ trang/tiên hiệp và từng là nguyên nhân trực tiếp của lỗi "ta/ngươi sai thể loại"; nó đã chuyển xuống preset `urban`/`romance` trong `genre.py`, nơi nó đúng. Luật 2 nay trỏ sang BẢNG NHÂN VẬT + 4 dòng phân tầng `[LỜI KỂ]`/`[THOẠI]`/`[NỘI TÂM]`/`[HỆ THỐNG]`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: ghi chú module characters/genre vào CLAUDE.md"
```

---

## Ghi chú cho người thực thi

**Thứ tự bắt buộc.** Task 1→3 xây `characters.py` theo lớp; Task 5 cần Task 1
(thứ tự tuple phải khớp `characters_from_rows`); Task 7 cần Task 3, 4, 5, 6;
Task 8 cần Task 3, 4; Task 9 cần Task 5. Task 10 làm cuối.

**Ba chỗ dễ hỏng âm thầm, đừng bỏ test:**
1. Mốc `from_chapter` — sai thì ngôn tình dùng nhầm giai đoạn xưng hô mà không
   có lỗi nào nổi lên.
2. Fallback khi template pin cũ thiếu `{characters}` — hỏng thì bảng nhân vật im
   lặng vô tác dụng, rất khó phát hiện.
3. Luật "main luôn chèn" — bỏ mất thì chunk toàn đại từ sẽ không có
   `narrator_ref`, đúng ca cần nó nhất.

**Không thuộc plan này** (mỗi cái một spec riêng, xem §2 của spec): AI trích
nhân vật tự động (sub-project B), post-check thống kê phát hiện chương lệch xưng
hô (sub-project C), import/export text cho bảng nhân vật, cột `category` cho
glossary.
