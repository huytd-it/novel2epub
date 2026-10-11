"""Pure helpers cho tab "Nghi vấn" trang Glossary: gom mục đáng ngờ (2+ Hán
cùng 1 target Việt, source lồng nhau) + map conflicts từ lần dịch tự mở rộng
glossary, và kế hoạch sửa hàng loạt cho nút "Áp dụng" của bảng glossary.
Thuần dữ liệu — không DB/route để test không cần app."""
from __future__ import annotations

import re

from .han_cleanup import count_han
from .proper_names import _SURNAME

Entry = tuple[str, str, str]  # (source, target, note)


def _entry_dict(e: Entry) -> dict:
    return {"source": e[0], "target": e[1], "note": e[2]}


def same_target_groups(entries: list[Entry]) -> list[dict]:
    """Nhóm 2+ source có cùng target (so sau trim, không phân biệt hoa
    thường). Giữ thứ tự xuất hiện; target hiển thị lấy từ mục đầu nhóm."""
    by_key: dict[str, list[Entry]] = {}
    order: list[str] = []
    for e in entries:
        key = e[1].strip().lower()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = []
            order.append(key)
        by_key[key].append(e)
    return [
        {
            "target": by_key[k][0][1].strip(),
            "entries": [_entry_dict(e) for e in by_key[k]],
        }
        for k in order
        if len(by_key[k]) >= 2
    ]


def nested_source_pairs(entries: list[Entry]) -> list[dict]:
    """Cặp mục mà source này là chuỗi con thực sự của source kia (张三 ⊂
    张三爷). O(n²) — vài nghìn mục vẫn tức thì, không cần index."""
    pairs: list[dict] = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            sa, sb = a[0], b[0]
            if sa == sb or not sa or not sb:
                continue
            if sa in sb:
                pairs.append({"outer": _entry_dict(b), "inner": _entry_dict(a)})
            elif sb in sa:
                pairs.append({"outer": _entry_dict(a), "inner": _entry_dict(b)})
    return pairs


def map_conflicts(raw) -> list[dict]:
    """Map conflicts từ extra json (`{"source","existing","new"}`; entry cũ có
    thể mang thêm `target_file` — bỏ) về format UI `{source, kept, new}`."""
    out: list[dict] = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        source = str(c.get("source", "")).strip()
        kept = str(c.get("existing", "")).strip()
        new = str(c.get("new", "")).strip()
        if source and new:
            out.append({"source": source, "kept": kept, "new": new})
    return out


def find_suspects(entries: list[Entry], conflicts_raw) -> dict:
    """Gộp cả 3 nhóm nghi vấn cho route /glossary/suspects."""
    return {
        "same_target": same_target_groups(entries),
        "nested_source": nested_source_pairs(entries),
        "conflicts": map_conflicts(conflicts_raw),
    }


# ── Kế hoạch sửa hàng loạt (nút "Áp dụng" trên bảng glossary) ──────────

INVALID_SOURCE_DETAIL = "Source phải chứa chữ Hán, không nhập tiếng Việt."

EMPTY_FIELD_DETAIL = "Cần cả Hán và Việt."
DUPLICATE_IN_BATCH_DETAIL = "Trùng Hán với một dòng khác trong đợt sửa này."
RENAME_COLLIDES_DETAIL = "Hán mới đã có sẵn trong glossary."


def plan_glossary_edits(existing: list[Entry], edits: list[dict]) -> list[dict]:
    """Chuẩn hoá + phân loại từng bản nháp sửa glossary TRƯỚC khi ghi.

    `existing` là glossary hiện có (đã merge 2 list), mỗi `edits` là một dòng
    người dùng đã sửa trong bảng: `{source, target, note, original_source}`.
    Trả về đúng thứ tự đó, mỗi dòng kèm giá trị cũ, `kind`
    (new/update/rename/unchanged) và `error` (rỗng nếu ghi được).

    Thuần dữ liệu, không đụng DB: route preview và route ghi dùng chung hàm này
    nên modal xem trước và kết quả áp dụng không thể lệch nhau.
    """
    by_source = {source: (target, note) for source, target, note in existing}
    planned: list[dict] = []
    seen: set[str] = set()

    for edit in edits:
        source = str(edit.get("source", "")).strip()
        target = str(edit.get("target", "")).strip()
        note = str(edit.get("note", "")).strip()
        original = str(edit.get("original_source", "")).strip()
        # Dòng thêm mới không có original_source; dòng sửa tra theo khoá cũ để
        # còn biết giá trị đang bị thay (dùng cho diff + lan truyền).
        lookup = original or source
        old_target, old_note = by_source.get(lookup, ("", ""))

        row = {
            "source": source,
            "target": target,
            "note": note,
            "original_source": original,
            "existing_source": lookup if lookup in by_source else "",
            "existing_target": old_target,
            "existing_note": old_note,
            "kind": "unchanged",
            "error": "",
        }

        renamed = bool(original) and source != original
        if not source or not target:
            row["error"] = EMPTY_FIELD_DETAIL
        elif count_han(source) == 0:
            row["error"] = INVALID_SOURCE_DETAIL
        elif source in seen:
            row["error"] = DUPLICATE_IN_BATCH_DETAIL
        elif (renamed or not original) and source in by_source and source != lookup:
            row["error"] = RENAME_COLLIDES_DETAIL
        else:
            seen.add(source)
            if lookup not in by_source:
                row["kind"] = "new"
            elif renamed:
                row["kind"] = "rename"
            elif target != old_target or note != old_note:
                row["kind"] = "update"

        planned.append(row)

    return planned


def replacement_pairs(planned: list[dict]) -> list[tuple[str, str]]:
    """Các cặp `Việt cũ → Việt mới` cần lan truyền vào bản dịch đã có, lấy từ
    kế hoạch của `plan_glossary_edits` (bỏ dòng lỗi, dòng mới và dòng giữ
    nguyên target). Dedup theo `old` — `Storage.replacement_counts` và
    `apply_replacements` quét một lượt nên `old` trùng chỉ được tính một lần."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in planned:
        if row["error"] or row["kind"] == "unchanged":
            continue
        old, new = row["existing_target"], row["target"]
        if not old or old == new or old in seen:
            continue
        seen.add(old)
        pairs.append((old, new))
    return pairs


# ── Lọc mục có giá trị đáng ngờ (nút "Lọc" trên bảng glossary) ─────────

# Chữ cái Latin kể cả nguyên âm có dấu tiếng Việt (Latin-1 Supplement,
# Extended-A/B và Extended Additional — nơi chứa ạ ả ấ ầ ...).
_LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff]")

# Mỗi cờ: (nhãn hiển thị, mô tả ngắn cho tooltip UI).
GLOSSARY_FLAGS: dict[str, tuple[str, str]] = {
    "vi_han": ("Việt còn chữ Hán", "Cột Việt còn sót ký tự Trung — chưa dịch hết."),
    "han_latin": ("Hán lẫn Latin", "Cột Hán chứa chữ cái Latin/tiếng Việt — source sai."),
    "same": ("Việt trùng Hán", "Cột Việt chép y hệt cột Hán — chưa dịch."),
    "no_han": ("Hán không có chữ Hán", "Cột Hán không chứa ký tự Trung nào."),
}


def entry_flags(source: str, target: str) -> set[str]:
    """Các cờ "giá trị đáng ngờ" của MỘT mục glossary.

    Thuần chuỗi, không DB: dùng chung cho bộ đếm ở đầu bảng và cho bộ lọc phân
    trang, nên con số trên chip lọc luôn khớp số dòng lọc ra.
    """
    source, target = (source or "").strip(), (target or "").strip()
    flags: set[str] = set()
    if count_han(target):
        flags.add("vi_han")
    if _LATIN_RE.search(source):
        flags.add("han_latin")
    if source and source == target:
        flags.add("same")
    if not count_han(source):
        flags.add("no_han")
    return flags


def count_entry_flags(entries: list[Entry]) -> dict[str, int]:
    """Số mục dính từng cờ (một mục có thể dính nhiều cờ)."""
    counts = {name: 0 for name in GLOSSARY_FLAGS}
    for source, target, _note in entries:
        for flag in entry_flags(source, target):
            counts[flag] += 1
    return counts


def parse_flags(raw: str) -> list[str]:
    """`"vi_han,same"` → các cờ hợp lệ, giữ thứ tự, bỏ trùng và tên lạ."""
    out: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name in GLOSSARY_FLAGS and name not in out:
            out.append(name)
    return out


def filter_by_flags(entries: list[Entry], flags: list[str]) -> list[Entry]:
    """Giữ mục dính ÍT NHẤT MỘT cờ trong `flags` (OR). Danh sách cờ rỗng =
    không lọc (trả nguyên danh sách)."""
    if not flags:
        return list(entries)
    wanted = set(flags)
    return [e for e in entries if entry_flags(e[0], e[1]) & wanted]


# ── Lọc tên riêng (hàng nút "Lọc tên riêng" trên bảng glossary) ────────
#
# Heuristic thuần chuỗi trên cột Hán, không gọi model: đủ để gom nhanh tên
# người ra rà/dịch lại, không khẳng định entity. Tên phiên âm nước ngoài chỉ
# dùng một tập chữ hẹp (bảng phiên âm Tân Hoa Xã), nên một source nằm trọn
# trong tập đó gần như chắc là tên phiên âm.

# Chữ hay dùng để phiên âm tên nước ngoài.
_TRANSLIT_CHARS = set(
    "阿埃艾爱安昂奥巴白拜班邦保鲍贝本比彼毕宾波伯博布蔡策查柴昌彻楚茨达代戴丹当道德登邓迪蒂丁东杜敦多"
    "厄恩尔法凡范菲费芬丰冯弗福夫盖甘冈高戈哥格葛根贡古瓜圭哈海汉豪赫黑亨洪胡华怀惠霍基吉季加佳贾简杰捷"
    "金津京卡开凯坎康考柯科可克肯孔库夸奎拉莱赖兰朗劳勒雷蕾累里丽莉利立力黎理李林琳龙隆卢鲁露路伦罗洛吕"
    "略马玛迈麦曼芒毛梅美门蒙孟米密蜜敏明缪莫默姆穆娜纳奈南内妮尼宁纽农努诺欧帕派潘庞佩彭皮平珀普奇齐恰"
    "钱强乔切钦琴丘琼曲让热若萨塞赛桑瑟森沙莎山尚绍舍申圣施什史士舒斯丝思松苏索塔泰坦汤唐陶特腾提田铁廷"
    "通图土托瓦娃万旺威薇韦维伟魏温文翁沃乌伍武西希锡席夏肖谢辛欣兴休修雪逊雅亚扬尧耶叶伊依易因英尤于雨"
    "约泽曾扎詹珍芝朱卓兹佐姬妲娅琪黛茜芙珊"
)
# Chữ gần như chỉ gặp trong tên phiên âm, hiếm trong tên/thuật ngữ Trung Quốc.
_TRANSLIT_STRONG = set("斯尔克特姆兹茨夫伦顿森逊洛莱蕾薇菲芙恩奥埃厄欧乌瓦佩帕珀普赫萨塞瑟舍勒迪蒂娅")
# Chữ phiên âm nhưng cũng hay có trong tên nữ Trung Quốc (李丽, 王琳): chỉ tính
# khi source không mở đầu bằng họ Trung Quốc.
_TRANSLIT_SOFT = set("丽琳娜莉妮亚莎")
_NAME_SEPARATORS = "·•・‧-－ "

# Mỗi loại: (nhãn hiển thị, mô tả ngắn cho tooltip UI).
NAME_KINDS: dict[str, tuple[str, str]] = {
    "translit_hv": (
        "Phiên âm còn Hán Việt",
        "Tên nước ngoài phiên âm bằng chữ Hán nhưng cột Việt chưa ở dạng Latin — nên dịch lại (艾伦 → Allen).",
    ),
    "translit": ("Tên phiên âm", "Cột Hán là tên nước ngoài phiên âm (艾伦, 夏洛克, 艾伦·沃克)."),
    "cn_name": ("Tên người Trung Quốc", "Cột Hán 2–4 chữ mở đầu bằng họ Trung Quốc (heuristic, có thể lẫn thuật ngữ)."),
}


def is_transliterated_name(source: str) -> bool:
    """`source` trông như tên nước ngoài phiên âm bằng chữ Hán."""
    source = (source or "").strip()
    core = "".join(ch for ch in source if ch not in _NAME_SEPARATORS)
    if len(core) < 2 or count_han(core) != len(core):
        return False
    if any(sep in source for sep in "·•・‧"):
        return True
    if not set(core) <= _TRANSLIT_CHARS:
        return False
    if set(core) & _TRANSLIT_STRONG:
        return True
    return bool(set(core) & _TRANSLIT_SOFT) and core[0] not in _SURNAME


def name_kinds(source: str, target: str) -> set[str]:
    """Các loại tên riêng (xem `NAME_KINDS`) mà MỘT mục glossary thuộc về."""
    source, target = (source or "").strip(), (target or "").strip()
    kinds: set[str] = set()
    if is_transliterated_name(source):
        kinds.add("translit")
        # Dạng Latin gốc là ASCII; còn dấu tiếng Việt nghĩa là đang Hán Việt hóa.
        if any(ord(ch) > 127 for ch in target):
            kinds.add("translit_hv")
    elif 2 <= len(source) <= 4 and count_han(source) == len(source) and source[0] in _SURNAME:
        kinds.add("cn_name")
    return kinds


def count_name_kinds(entries: list[Entry]) -> dict[str, int]:
    """Số mục thuộc từng loại tên riêng."""
    counts = {name: 0 for name in NAME_KINDS}
    for source, target, _note in entries:
        for kind in name_kinds(source, target):
            counts[kind] += 1
    return counts


def parse_name_kinds(raw: str) -> list[str]:
    """`"translit,cn_name"` → các loại hợp lệ, giữ thứ tự, bỏ trùng và tên lạ."""
    out: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name in NAME_KINDS and name not in out:
            out.append(name)
    return out


def filter_by_name_kinds(entries: list[Entry], kinds: list[str]) -> list[Entry]:
    """Giữ mục thuộc ÍT NHẤT MỘT loại trong `kinds` (OR); rỗng = không lọc."""
    if not kinds:
        return list(entries)
    wanted = set(kinds)
    return [e for e in entries if name_kinds(e[0], e[1]) & wanted]


# ── Guard duyệt tự động (nút "AI tự động duyệt" + step automation) ───

# Cờ do AI gây ra ở cột Việt → chặn tự duyệt, giữ hàng chờ duyệt tay. `han_latin`
# và `no_han` xét cột Hán (AI không được đổi) nên không chặn ở đây.
AUTO_APPROVE_BLOCKED_FLAGS = {"vi_han", "same"}


def split_auto_approvable(
    current: dict[str, tuple[str, str]], results: list[dict]
) -> dict:
    """Chia kết quả AI thành `approved` (đủ an toàn để tự duyệt) và `held`
    (giữ hàng chờ duyệt tay kèm lý do).

    `current` là glossary hiện tại `{source: (target, note)}`; `results` là
    `[{source, target, ...}]` AI trả về. Guard hoàn toàn xác định, không tốn
    thêm lượt gọi AI:

    1. Target rỗng → giữ (AI không trả lời được mục này).
    2. Cặp mới dính cờ `vi_han`/`same` (sót chữ Hán, chép y Hán) → giữ, kể cả
       khi AI chỉ "giữ nguyên" một giá trị đang sai.
    3. Target mới trùng (không phân biệt hoa thường) với target của source
       KHÁC trong glossary hoặc trong cùng đợt → giữ để tránh nhập nhằng hai
       Hán về một Việt và lan truyền sai.

    Thuần dữ liệu, không DB: route `glossary-ai` (chế độ auto_approve) và step
    automation dùng chung nên hai đường tự duyệt không thể lệch nhau.
    """
    approved: list[dict] = []
    held: list[dict] = []
    taken_in_batch: set[str] = set()
    for r in results if isinstance(results, list) else []:
        if not isinstance(r, dict):
            continue
        source = str(r.get("source", "")).strip()
        target = str(r.get("target", "")).strip()
        if not source or not target:
            held.append({"source": source, "target": target, "reason": "AI trả về rỗng"})
            continue
        blocked = entry_flags(source, target) & AUTO_APPROVE_BLOCKED_FLAGS
        if blocked:
            labels = ", ".join(GLOSSARY_FLAGS[name][0] for name in sorted(blocked))
            held.append({"source": source, "target": target, "reason": f"Dính cờ kiểm định: {labels}"})
            continue
        key = target.lower()
        owner = next(
            (s for s, (t, _n) in current.items() if t.strip().lower() == key and s != source),
            "",
        )
        if owner:
            held.append(
                {
                    "source": source,
                    "target": target,
                    "reason": f"Trùng Việt với '{owner}' — giữ để duyệt tay",
                }
            )
            continue
        if key in taken_in_batch:
            held.append(
                {
                    "source": source,
                    "target": target,
                    "reason": "Trùng Việt với một mục khác trong cùng đợt — giữ để duyệt tay",
                }
            )
            continue
        taken_in_batch.add(key)
        approved.append({"source": source, "target": target})
    return {"approved": approved, "held": held}
