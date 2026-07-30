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

import re
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
