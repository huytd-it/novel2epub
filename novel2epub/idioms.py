"""Từ điển idiom/thành ngữ DÙNG CHUNG mọi ebook — logic thuần (không đụng DB/OS).

Idiom giải quyết bài toán: cả LLM lẫn MT 57M hay dịch thành ngữ theo kiểu "từng
chữ" (千方百计 → "Ngàn phương trăm kế") thay vì bản tự nhiên ("Trăm phương nghìn
kế"). Vì MT không nhận instruction, kênh duy nhất là thay-chuỗi.

Mỗi idiom gồm:
- `zh`       : nguồn Hán (千方百计) — dùng cho LLM (prompt tham chiếu) + protect.
- `natural`  : bản dịch đích đẹp (Trăm phương nghìn kế) — kết quả cuối.
- `literals` : các bản MT hay ra (Ngàn phương trăm kế, ...) — hậu-chuẩn-hoá VI→VI.
- `protect`  : True → thay zh bằng placeholder TRƯỚC khi đưa vào MT rồi khôi phục
  natural (dùng cho idiom mà bản máy quá thất thường, literal không bắt xuể).

Mỗi idiom chỉ dùng ĐÚNG MỘT cơ chế cho MT: mặc định literal→natural (an toàn,
test được); `protect` bật thủ công cho idiom cứng đầu. Không chạy cả hai trên
cùng một lần xuất hiện để tránh double-fail (nếu placeholder bị model 57M nghiền
thì đích không còn chuỗi literal để bắt).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Token đánh dấu entry protect trong ô "note" khi import dạng text
# (`zh = natural | @protect`). Tách riêng khỏi literal variants.
PROTECT_TOKEN = "@protect"

# Placeholder cho idiom protect: token CHỮ HOA ASCII + số thứ tự (IDIOM0,
# IDIOM1...). Đã smoke-test trên MoxhiMT-60 THẬT: token dạng này sống sót
# nguyên vẹn qua model (3/3), trong khi ngoặc CJK 〖〗 và mọi marker dùng dấu
# (`[[0]]`, `{0}`, `@@0@@`, `XX0XX`) bị SentencePiece nuốt/dịch mất (0/3) — model
# thậm chí BỊA chữ thay vào. Chữ HOA ASCII được model copy như tên riêng.
# Khôi phục khoan dung: chấp nhận model chèn khoảng trắng / đổi hoa-thường. Nếu
# placeholder vẫn hỏng, lớp literal→natural hậu xử lý là fallback cuối.
_PROTECT_PREFIX = "IDIOM"


# Bộ idiom mẫu seed khi kho còn trống (từ bảng đối chiếu trong test.md).
# Mỗi mục: (zh, natural, literals-ngăn-bằng-`|`, protect 0/1).
DEFAULT_IDIOM_SEED: list[tuple[str, str, str, int]] = [
    ("千方百计", "Trăm phương nghìn kế", "Ngàn phương trăm kế", 0),
    ("一举两得", "Một mũi tên trúng hai đích", "Một lần được hai lợi", 0),
    ("有目共睹", "Mọi người đều thấy rõ", "Có mắt cùng thấy", 0),
    ("势不可挡", "Thế như chẻ tre", "Thế không thể cản", 0),
    ("深入人心", "Ăn sâu vào lòng người", "Đi sâu vào lòng người", 0),
    ("防患未然", "Phòng ngừa từ trước", "Phòng bệnh khi chưa xảy ra", 0),
]


@dataclass(frozen=True)
class Idiom:
    zh: str
    natural: str
    literals: tuple[str, ...] = ()
    protect: bool = False


def parse_idiom_note(note: str) -> tuple[list[str], bool]:
    """Tách ô note (`literal1 | literal2` hoặc `@protect`) → (literals, protect).

    - `@protect` (đứng riêng hoặc lẫn trong danh sách) → protect=True.
    - Phần còn lại tách theo `|`, trim, bỏ rỗng → literal variants.
    """
    protect = False
    literals: list[str] = []
    for part in (note or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if part.lower() == PROTECT_TOKEN:
            protect = True
            continue
        literals.append(part)
    return literals, protect


def make_idiom(zh: str, natural: str, note: str = "") -> Idiom | None:
    """Dựng Idiom từ (zh, natural, note-string). Trả None nếu thiếu zh/natural."""
    zh = (zh or "").strip()
    natural = (natural or "").strip()
    if not zh or not natural:
        return None
    literals, protect = parse_idiom_note(note)
    return Idiom(zh=zh, natural=natural, literals=tuple(literals), protect=protect)


def idioms_from_rows(rows) -> list[Idiom]:
    """Dựng list Idiom từ các row DB `(source, target, literals, protect)`.

    `literals` là chuỗi ngăn bằng `|`; `protect` là 0/1. Bỏ row thiếu
    source/target.
    """
    out: list[Idiom] = []
    for row in rows:
        zh = (row[0] or "").strip()
        natural = (row[1] or "").strip()
        if not zh or not natural:
            continue
        literals = tuple(
            p.strip() for p in (row[2] or "").split("|") if p.strip()
        )
        protect = bool(row[3]) if len(row) > 3 else False
        out.append(Idiom(zh=zh, natural=natural, literals=literals, protect=protect))
    return out


def filter_for_text(idioms: list[Idiom], zh_text: str) -> list[Idiom]:
    """Chỉ giữ idiom có `zh` xuất hiện trong `zh_text` (tiết kiệm token prompt).

    Text Hán không có ranh giới từ nên so khớp substring là đủ chính xác.
    """
    if not zh_text:
        return []
    return [idi for idi in idioms if idi.zh and idi.zh in zh_text]


def format_llm_block(idioms: list[Idiom]) -> str:
    """Khối tham chiếu idiom cho prompt LLM (mềm, không ép nguyên văn).

    Trả "" nếu rỗng để placeholder {idioms} biến mất sạch.
    """
    if not idioms:
        return ""
    lines = "\n".join(f"{idi.zh} = {idi.natural}" for idi in idioms)
    return (
        "Thành ngữ/khẩu ngữ tham chiếu (dịch thoát ý tự nhiên theo gợi ý, "
        "KHÔNG bắt buộc nguyên văn):\n" + lines
    )


def _placeholder(n: int) -> str:
    return f"{_PROTECT_PREFIX}{n}"


def protect_source(text: str, idioms: list[Idiom]) -> tuple[str, dict[str, str]]:
    """Thay các idiom `protect` xuất hiện trong `text` bằng placeholder.

    Trả `(text_đã_thay, restore_map)` với restore_map: placeholder → natural.
    Chỉ xử lý idiom protect; idiom thường để MT dịch bình thường rồi chuẩn hoá
    literal sau. Áp longest-first để idiom dài không bị idiom con phá.
    """
    restore: dict[str, str] = {}
    protect_idioms = sorted(
        (idi for idi in idioms if idi.protect and idi.zh in text),
        key=lambda idi: len(idi.zh),
        reverse=True,
    )
    n = 0
    for idi in protect_idioms:
        if idi.zh not in text:
            continue
        ph = _placeholder(n)
        text = text.replace(idi.zh, ph)
        restore[ph] = idi.natural
        n += 1
    return text, restore


def restore_placeholders(text: str, restore_map: dict[str, str]) -> str:
    """Khôi phục placeholder → natural. Khoan dung với khoảng trắng model chèn
    giữa prefix và số, và với hoa/thường. Placeholder không tìm thấy (bị model
    nghiền) → bỏ qua, để lớp literal hậu xử lý làm fallback.

    Áp longest-first theo độ dài placeholder để IDIOM1 không nuốt IDIOM10.
    """
    for ph in sorted(restore_map, key=len, reverse=True):
        natural = restore_map[ph]
        if ph in text:
            text = text.replace(ph, natural)
            continue
        # Fallback khoan dung: PREFIX <spaces> N (N không dính số phía sau để
        # IDIOM1 không khớp trong IDIOM10), không phân biệt hoa/thường.
        num = ph[len(_PROTECT_PREFIX):]
        pattern = re.escape(_PROTECT_PREFIX) + r"\s*" + re.escape(num) + r"(?!\d)"
        text = re.sub(pattern, natural.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
    return text


def normalize_literals(text: str, idioms: list[Idiom]) -> str:
    """Thay các bản máy `literal → natural` trên output VI (longest-first).

    Chỉ áp idiom KHÔNG protect (protect đã xử lý ở nguồn). Longest-first để
    literal dài không bị literal con phá.
    """
    pairs: list[tuple[str, str]] = []
    for idi in idioms:
        if idi.protect:
            continue
        for lit in idi.literals:
            if lit:
                pairs.append((lit, idi.natural))
    for lit, natural in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
        text = text.replace(lit, natural)
    return text


def apply_mt_post(text: str, idioms: list[Idiom], restore_map: dict[str, str]) -> str:
    """Hậu xử lý output MT: khôi phục placeholder rồi chuẩn hoá literal.

    restore chạy trước để placeholder biến thành natural; literal là lớp cuối
    bắt những idiom thường (và fallback khi placeholder hỏng — dù khi đó natural
    đã mất, literal ít nhất vá được nếu idiom cũng có biến thể literal khai báo).
    """
    text = restore_placeholders(text, restore_map)
    text = normalize_literals(text, idioms)
    return text
