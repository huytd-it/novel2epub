"""Xuất/nhập biên tập hàng loạt: gom nhiều chương thành một file Markdown để dán
hoặc upload lên web chat AI biên tập, rồi parse kết quả trả về nạp ngược vào hệ
thống. Markdown (thay vì marker `=====` thô) giúp AI nhận diện cấu trúc tốt hơn
và có thể tải xuống/upload thẳng dạng file `.md`.

Module thuần (không phụ thuộc web/FastAPI) để dễ unit-test. Routes trong
`app/routes/chapters.py` lo phần I/O (đọc `translated/`, glossary) + ghi đè.

Cấu trúc một khối xuất:

    <PROMPT biên tập, dạng markdown>

    ## Glossary tham khảo (dùng đúng các tên này)
    - 萧炎 = Tiêu Viêm
    - 斗气 = Đấu khí

    ## idx:1: <tiêu đề>
    <bản dịch chương 1>

    ## idx:2
    <bản dịch chương 2>

Marker dùng `idx:N` (N = VỊ TRÍ trong manifest, không phải số chương thật)
thay vì `Chương N` — tránh AI nhầm lẫn giữa số thứ tự này và số chương thật
thường nằm ngay trong tiêu đề gốc (vd tiêu đề "第1338章 番外一" bên trong dòng
`## idx:1353: 第1338章 番外一` dễ khiến AI tưởng 1353 là số chương thật nếu
marker viết "Chương 1353"). Web chat trả về các chương đã dịch/biên tập (giữ
nguyên `idx:N`, chỉ dịch phần tiêu đề sau đó) kèm một mục `## GLOSSARY` mới ở
cuối — `parse_import` tách chương, `parse_glossary` gom glossary. Marker
`## Chương N` (định dạng cũ) và `===== CHƯƠNG N =====` (kiểu cũ hơn) vẫn được
nhận diện để tương thích ngược với các bản xuất trước đó.
"""
from __future__ import annotations

import re

from .storage import parse_glossary_line

# Marker phân tách — chấp nhận tiêu đề Markdown `## idx:N` (định dạng hiện tại,
# N = vị trí trong manifest, KHÔNG phải số chương thật — dùng "idx" thay vì
# "Chương" để AI không nhầm N với số chương thật thường có sẵn trong tiêu đề
# gốc), lẫn `## CHƯƠNG N` (định dạng cũ) và marker `=====` kiểu cũ hơn (tương
# thích ngược với các bản xuất trước đó). `re.IGNORECASE` để khoan dung hoa/
# thường khi AI viết lại tiêu đề. Group 2 = phần tiêu đề sau số (có thể rỗng),
# chuẩn hóa qua `_marker_title`.
# Cũng bắt biến thể AI hay tự thêm bold/italic: `## **idx:N**`, `**idx:N**`.
# Vẫn yêu cầu ít nhất một trong `#` / `=` / `*` làm prefix để tránh parse nhầm
# các dòng văn bản thường bắt đầu bằng "idx" hoặc "Chương ...".
CHAPTER_MARKER_RE = re.compile(
    r"^(?:\*{1,2}\s*)?(?:#{1,6}\s*\*{0,2}\s*|={3,}\s*|\*{1,2}\s*)"
    r"(?:IDX\s*[:.]?\s*|CHƯƠNG\s+)(\d+)\b\s*(.*)$",
    re.IGNORECASE,
)
GLOSSARY_MARKER_RE = re.compile(r"^(?:#{1,6}\s*|={3,}\s*)GLOSSARY\b", re.IGNORECASE)

_BULLET_RE = re.compile(r"^[-*+]\s+")


# Số chương THẬT ở đầu tiêu đề gốc (第911章/第十二章/卷/回).
_ZH_NUM_PREFIX_RE = re.compile(r"^第\s*([\d零〇一二两三四五六七八九十百千万]+)\s*(章|卷|回)")
_ZH_NUM_LABELS = {"章": "Chương", "卷": "Quyển", "回": "Hồi"}


def _parse_zh_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = section = number = 0
    for char in value:
        if char in digits:
            number = digits[char]
        else:
            unit = units[char]
            if unit == 10000:
                total += (section + number) * unit
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
    return total + section + number


def split_zh_title_number(zh_title: str) -> tuple[str, str]:
    """Tách tiền tố ``第N章/卷/回`` khỏi phần tên chương tiếng Trung.

    Trả ``(nhãn tiếng Việt + số, phần tiêu đề cần dịch)``. Nếu tiêu đề không
    có tiền tố được hỗ trợ thì nhãn rỗng và toàn bộ chuỗi là phần cần dịch.
    """
    source = zh_title.strip()
    match = _ZH_NUM_PREFIX_RE.match(source)
    if not match:
        return "", source
    number = _parse_zh_number(match.group(1))
    label = _ZH_NUM_LABELS[match.group(2)]
    remainder = source[match.end():].strip().lstrip(":：-–—.、").strip()
    return f"{label} {number}", remainder


def ensure_title_number(zh_title: str, vi_title: str) -> str:
    """Giữ SỐ CHƯƠNG THẬT từ tiêu đề gốc khi AI dịch tiêu đề.

    Số trong marker `## Chương N` là index VỊ TRÍ trong manifest (vd 961),
    còn số chương thật nằm trong tiêu đề gốc (vd 第911章) — AI thường dịch
    "gọn" làm rơi mất, hoặc echo nhầm số vị trí. Nếu `zh_title` mở đầu bằng
    `第M章/卷/回`: bỏ prefix `Chương/Quyển/Hồi <số>` sẵn có trong `vi_title`
    (đúng hay sai số) rồi gắn lại `<nhãn> M: ` theo bản gốc. Không có prefix
    số trong bản gốc → trả `vi_title` nguyên vẹn.
    """
    vi_title = vi_title.strip()
    m = _ZH_NUM_PREFIX_RE.match(zh_title.strip())
    if not m or not vi_title:
        return vi_title
    num, label = _parse_zh_number(m.group(1)), _ZH_NUM_LABELS[m.group(2)]
    rest = re.sub(
        rf"^{label}\s+\d+\s*[:：\-–—.]?\s*", "", vi_title, flags=re.IGNORECASE
    ).strip()
    if not rest:
        return f"{label} {num}"
    return f"{label} {num}: {rest}"


def _marker_title(rest: str) -> str:
    """Chuẩn hóa phần tiêu đề bắt được sau `CHƯƠNG N` trong dòng marker.

    Bỏ run `=` hoặc `**` cuối dòng (marker legacy `===== CHƯƠNG 12 =====` →
    title rỗng; bold AI `## **Chương 1** → title rỗng) và separator mở đầu
    (`:`, `：`, `-`, `.`...) giữa số chương và tiêu đề.
    """
    rest = re.sub(r"=+\s*$", "", rest)
    rest = re.sub(r"\*+\s*$", "", rest)
    return rest.strip().lstrip(":：-–—.").strip()


def chapter_marker(index: int, title: str = "") -> str:
    """Dòng tiêu đề Markdown mở đầu một chương.

    Dùng `idx:N` chứ không phải `Chương N` — N là vị trí trong manifest, không
    phải số chương thật (số đó nằm trong `title`, vd `第1338章 ...`). Ghi
    "Chương N" sẽ khiến AI nhầm N là số chương thật khi title cũng chứa một số
    chương khác ngay sau đó.
    """
    label = f"idx:{index}"
    if title.strip():
        label += f": {title.strip()}"
    return f"## {label}"


# Quy tắc trích glossary ở cuối output — DÙNG CHUNG cho EDIT_PROMPT và
# TRANSLATE_PROMPT. Siết chặt tiêu chí để AI KHÔNG nhét từ đời thường vào
# glossary (lỗi hay gặp: "kệ hàng", "cơm thừa canh cặn", "chạy việc vặt"...).
# Ghép vào cuối mỗi prompt bằng nối chuỗi.
_GLOSSARY_OUTPUT_RULE = """- Ở CUỐI kết quả, thêm một mục `## GLOSSARY`. \
CHỈ liệt kê tên riêng/thuật ngữ MỚI (chưa có trong glossary tham khảo) mà \
BẮT BUỘC phải nhất quán xuyên suốt truyện. Đây là bảng để đồng bộ cách dịch, \
KHÔNG phải từ điển — thà bỏ sót còn hơn đưa nhầm từ thông thường vào.

TIÊU CHÍ đưa vào (chỉ khi thỏa mãn): tên riêng — nhân vật, địa danh, môn \
phái/tổ chức, chức danh/tước vị; hoặc thuật ngữ ĐẶC THÙ của thế giới truyện, \
lặp lại nhiều lần — công pháp, chiêu thức, cảnh giới tu luyện, pháp bảo, đan \
dược, chủng tộc, hệ thống sức mạnh, biệt danh/xưng hiệu cố định của nhân vật.

Tên người nước ngoài ghi ở dạng chữ Latin gốc đúng như trong bản dịch \
(vd 夏洛克 → Sherlock), KHÔNG ghi Hán Việt.

TUYỆT ĐỐI KHÔNG đưa vào (đây là lỗi làm bẩn glossary):
- Từ ngữ đời thường: đồ ăn thức uống, mua sắm, động tác, cảm xúc, nghề nghiệp \
thông thường, vật dụng phổ thông (vd: kệ hàng, cơm thừa canh cặn, chạy việc \
vặt, gà thả vườn, thu dọn, bày hàng...).
- Thành ngữ/tục ngữ/khẩu ngữ/tiếng lóng dịch thoát ý (vd: khó đỡ, yêu nhau \
giết nhau, phát điên, oan gia ngõ hẹp...).
- Từ ngữ hiện đại phổ thông (vd: ứng dụng đặt xe, khu du lịch sinh thái, tên \
lửa đẩy, công tác bên ngoài...) — TRỪ KHI là khái niệm đặc thù, lặp lại nhiều \
lần và cần dịch thống nhất.
- Bất kỳ từ nào độc giả Việt đọc hiểu ngay, hoặc chỉ xuất hiện một lần.

Nếu không có mục nào đạt tiêu chí, để mục `## GLOSSARY` trống (chỉ ghi tiêu đề, \
không kèm mục con). Định dạng:

## GLOSSARY
- <chữ Hán> = <tiếng Việt>
"""


# Prompt biên tập chắt lọc nguyên tắc "edit đúng/hay" từ docs/rule.md, viết dạng
# Markdown để AI và người đọc dễ theo dõi cấu trúc hơn.
EDIT_PROMPT = """# Yêu cầu biên tập truyện dịch Trung → Việt

Bạn là biên tập viên truyện dịch Trung → Việt. Hãy BIÊN TẬP LẠI bản dịch \
tiếng Việt bên dưới cho hay, chính xác và tự nhiên, theo các nguyên tắc sau:

1. Đối chiếu ngữ cảnh để giữ ĐÚNG nghĩa, KHÔNG thêm bớt nội dung; gặp từ/điển \
tích đáng ngờ thì hiểu cho đúng rồi mới viết lại.
2. NGÔI XƯNG: Bảng nhân vật > ngôi kể thực tế > quan hệ/ngữ cảnh > thể loại. \
Giữ "hắn" trong lời kể khi tự nhiên, kể cả truyện hiện đại; không máy móc đổi \
thành "anh/anh ta/anh ấy". "ta/ngươi" hợp lệ trong lời kể đúng ngôi, thoại và \
nội tâm khi đúng giọng, thân phận và quan hệ; không ánh xạ máy móc 我/你/他. \
Không thay mọi 他 bằng "hắn", không lặp đại từ dày đặc và không sửa một hệ \
thống xưng hô đang đúng chỉ vì sở thích văn phong.
3. Sửa NGỮ PHÁP và trật tự từ cho thuần tiếng Việt (đưa trạng ngữ lên đầu câu, \
câu đủ chủ – vị, ngắt câu/dấu câu hợp lý).
4. CÂN BẰNG Hán – Việt và thuần Việt: giữ sắc thái (nhất là truyện cổ đại) nhưng \
đừng để câu khó hiểu; thành ngữ/tục ngữ phải đúng nghĩa gốc.
5. TÊN RIÊNG (nhân vật, địa danh, môn phái, chức danh) giữ ở dạng Hán Việt viết \
hoa, NHẤT QUÁN xuyên suốt. Dùng đúng các tên trong phần Glossary tham khảo.
6. TÊN NGƯỜI NƯỚC NGOÀI (Âu-Mỹ, Nhật, Hàn...) phải ở dạng chữ Latin gốc, KHÔNG \
phải Hán Việt: gặp "Hạ Lạc Khắc" → sửa thành "Sherlock", "Minh Nhân" → \
"Naruto", "Tiểu Anh" → "Sakura". CHỈ sửa khi nhận ra CHẮC CHẮN tên gốc; không \
chắc thì giữ nguyên như bản dịch. Ưu tiên tên trong Glossary tham khảo.

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

- GIỮ NGUYÊN các dòng tiêu đề `## idx:N` (N chỉ là số thứ tự để đối chiếu, \
KHÔNG phải số chương thật — KHÔNG sửa/xóa số này); chỉ sửa phần tiêu đề/nội \
dung phía sau. KHÔNG gộp/đổi/xóa dòng tiêu đề, không tự thêm tiêu đề chương mới.
""" + _GLOSSARY_OUTPUT_RULE


# Prompt dịch (Trung → Việt) cho luồng "xuất raw để dịch" — nguyên tắc 1-9 lấy
# nguyên từ `DEFAULT_PROMPT` trong `config.py` (prompt dịch chính thức của hệ
# thống, dùng cho backend AI `openai`), giữ nguyên tinh thần, chỉ đổi phần
# đầu/cuối cho phù hợp batch nhiều chương theo Markdown, để dịch thủ công qua
# web chat nhất quán với dịch bằng AI backend trong app.
TRANSLATE_PROMPT = """# Yêu cầu dịch truyện Trung → Việt

Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt, theo phong cách \
edit mượt mà mà độc giả Việt quen thuộc. Hãy DỊCH bản gốc tiếng Trung bên dưới \
sang tiếng Việt, theo các nguyên tắc sau:

1. Dịch sang tiếng Việt tự nhiên, đúng ngữ pháp Việt: đảo trật tự từ cho thuận, \
câu phải đủ chủ — vị.
2. Ngôi xưng: Bảng nhân vật > ngôi kể thực tế > quan hệ/ngữ cảnh > thể loại. \
Lời kể được dùng "hắn" khi tự nhiên, kể cả truyện hiện đại, không máy móc đổi \
thành "anh/anh ta/anh ấy". "ta/ngươi" hợp lệ trong lời kể đúng ngôi, thoại và \
nội tâm khi đúng giọng, thân phận và quan hệ. Không ánh xạ máy móc 我→ta, \
你→ngươi, 他→hắn; không thay mọi 他 bằng "hắn" hoặc lặp đại từ dày đặc.
3. Tên riêng, công pháp, địa danh, chiêu thức: giữ Hán Việt quen thuộc, viết \
hoa và NHẤT QUÁN xuyên suốt. Dùng đúng các tên trong phần Glossary tham khảo.
4. NGOẠI LỆ của luật 3 — tên người nước ngoài (Âu-Mỹ, Nhật, Hàn...) được bản \
gốc phiên âm sang chữ Hán: trả về ĐÚNG dạng chữ Latin gốc (夏洛克 → Sherlock, \
鸣人 → Naruto, 小樱 → Sakura), KHÔNG chuyển thành Hán Việt (KHÔNG "Hạ Lạc Khắc", \
"Minh Nhân"). Viết hoa và NHẤT QUÁN xuyên suốt. CHỈ áp dụng khi nhận ra CHẮC \
CHẮN tên gốc; không chắc thì giữ Hán Việt theo luật 3.
5. Hạn chế lạm dụng từ Hán Việt khó hiểu; ưu tiên thuần Việt nếu rõ nghĩa hơn, \
nhưng giữ chất cổ trang khi cần.
6. Giữ nguyên cách chia đoạn của bản gốc.
7. Thành ngữ, tục ngữ, khẩu ngữ: dịch thoát ý bằng cách nói tự nhiên của người \
Việt, không máy móc (khẩu ngữ chỉ sự e dè thì dịch "ngại", "ngại ngùng"; chê \
tác phong ăn uống thì "ăn uống khó coi"...).
8. Từ vựng đời thường (động tác, nấu nướng, ăn uống, cảm giác, tiếng lóng...): \
dịch tự nhiên như văn nói tiếng Việt thông thường, không cần giữ sắc thái Hán, \
không phiên âm Hán Việt cứng nhắc.
9. Thơ từ, ca phú, trích dẫn cổ văn: nếu có bản dịch phổ biến thì dùng và ghi \
tên dịch giả trong ngoặc (vd: "— (bản dịch Tản Đà)"); nếu không, tự chuyển ngữ \
cho người đọc hiểu, không dịch nguyên xi từng chữ kiểu Vietphrase.

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

- CHỈ trả về bản dịch tiếng Việt thuần túy. KHÔNG thêm lời mở đầu, ghi chú, \
giải thích, hay đánh dấu song ngữ.
- KIỂM TRA CUỐI (bắt buộc): trước khi trả lời, rà lại toàn bộ nội dung các \
chương; nếu còn BẤT KỲ ký tự Trung Quốc nào ngoài mục `## GLOSSARY`, dịch nốt \
sang tiếng Việt rồi mới trả lời.
- GIỮ NGUYÊN số `idx:N` ở đầu mỗi dòng tiêu đề — đây CHỈ LÀ SỐ THỨ TỰ để đối \
chiếu, KHÔNG PHẢI số chương thật của truyện, TUYỆT ĐỐI không dùng số này khi \
dịch tiêu đề. Dịch phần tiêu đề tiếng Trung đứng sau `idx:N:` sang tiếng Việt \
cho hay, gọn — không dịch sát nghĩa kiểu máy; nếu phần đó chứa số chương thật \
kiểu `第M章`/`第M卷`/`第M回`, chuyển thành `Chương M`/`Quyển M`/`Hồi M` (dùng \
đúng số M trong tiêu đề, không phải N của idx). Ví dụ: dòng \
`## idx:1353: 第1338章 番外一` phải trả về dạng \
`## idx:1353: Chương 1338: Phiên ngoại 1` — giữ nguyên `idx:1353`, đổi \
`第1338章 番外一` thành tiêu đề tiếng Việt có số chương thật là 1338. Điền \
bản dịch tiếng Việt BÊN DƯỚI mỗi dòng tiêu đề. KHÔNG gộp/đổi/xóa dòng tiêu đề, \
không tự thêm tiêu đề chương mới.
""" + _GLOSSARY_OUTPUT_RULE


def _format_glossary_block(glossary: dict[str, str]) -> str:
    """Render glossary thành mục Markdown 1 danh sách phẳng (rỗng → "")."""
    if not glossary:
        return ""
    lines = "\n".join(f"- {s} = {t}" for s, t in glossary.items() if s and t)
    return f"## Glossary tham khảo (dùng đúng các tên này)\n{lines}"


def build_translate_prompt_from_cfg(cfg) -> str:
    """Render prompt dịch từ cfg.translate để nhúng vào file export.

    Render các style placeholder, bỏ phần nội dung ({text}, {glossary},
    --- Nội dung cần dịch ---, v.v.) vì build_export gắn glossary + chương
    riêng bên dưới theo format ## idx:N.
    """
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
    # Cắt phần "--- Nội dung cần dịch ---\n{text}" và các biến thể tương tự
    import re as _re
    prompt = _re.split(r"\n---[^\n]+---\s*\{text\}", prompt)[0]
    # Nếu template không có separator đó, bỏ {text} trực tiếp
    prompt = prompt.replace("{text}", "")
    prompt = prompt.rstrip()
    prompt += """

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

- GIỮ NGUYÊN số `idx:N` ở đầu mỗi dòng tiêu đề — đây CHỈ LÀ SỐ THỨ TỰ để đối chiếu, KHÔNG PHẢI số chương thật. Dịch phần tiêu đề tiếng Trung đứng sau `idx:N:` sang tiếng Việt. Ví dụ: `## idx:5: 第5章 拜师` phải trả về `## idx:5: Chương 5: Bái Sư`.
- Điền bản dịch tiếng Việt BÊN DƯỚI mỗi dòng tiêu đề. KHÔNG gộp/xóa/thêm dòng tiêu đề."""
    prompt += "\n" + _GLOSSARY_OUTPUT_RULE
    return prompt


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


# Prompt nhờ web chat AI DỌN LẠI glossary (dedup, sửa Hán-Việt, gộp mâu thuẫn).
# Trả về đúng format dòng `- Hán = Việt` để `parse_glossary` nạp ngược.
GLOSSARY_CLEAN_PROMPT = """# Yêu cầu dọn & chuẩn hoá bảng glossary truyện dịch Trung → Việt

Bạn là biên tập viên xây dựng glossary nhất quán cho truyện dịch. Dưới đây là \
bảng glossary hiện tại (tên riêng + thuật ngữ). Hãy RÀ SOÁT và trả về bảng đã \
được dọn sạch, theo các nguyên tắc sau:

1. GỘP TRÙNG LẶP: nếu cùng một chữ Hán xuất hiện nhiều lần, chỉ giữ MỘT mục với \
cách dịch tốt nhất, nhất quán.
2. XỬ LÝ MÂU THUẪN: một chữ Hán chỉ nên có MỘT cách dịch tiếng Việt. Nếu đang có \
nhiều cách dịch khác nhau, chọn cách phù hợp nhất và bỏ các cách còn lại.
3. SỬA HÁN-VIỆT SAI hoặc khó hiểu: chỉnh lại phiên âm Hán Việt cho đúng và tự nhiên.
4. LOẠI mục rác: từ đời thường, thành ngữ/khẩu ngữ dịch thoát ý, từ độc giả Việt \
đọc hiểu ngay — những mục KHÔNG cần đồng bộ xuyên suốt truyện.
5. KHÔNG bịa thêm mục mới không có trong bảng gốc. KHÔNG thêm bình luận, giải thích.

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

Chỉ trả về đúng cấu trúc sau, mỗi mục một dòng dạng `- <chữ Hán> = <tiếng Việt>`:

## GLOSSARY
- 萧炎 = Tiêu Viêm
- 斗气 = Đấu khí
"""


def build_glossary_export(
    glossary: dict[str, str], *, prompt: str = GLOSSARY_CLEAN_PROMPT
) -> str:
    """Gom glossary hiện tại thành khối xuất cho web chat AI dọn lại.

    Dùng heading `## GLOSSARY` + dòng `- Hán = Việt` để `parse_glossary` nạp
    ngược được kết quả AI trả về (round-trip). Bảng rỗng vẫn xuất khung để
    AI biết định dạng mong muốn.
    """
    lines = "\n".join(f"- {s} = {t}" for s, t in glossary.items() if s and t)
    parts: list[str] = [prompt.rstrip(), "## GLOSSARY\n" + (lines or "- ")]
    return "\n\n".join(parts) + "\n"


def parse_import(text: str) -> list[tuple[int, str, str]]:
    """Tách văn bản đã biên tập thành list `(index, title, content)` theo marker chương.

    `title` là phần sau `## Chương N:` (đã strip separator; `""` nếu heading
    không kèm tiêu đề). LƯU Ý: `index` là VỊ TRÍ trong manifest, còn tiêu đề
    thật có thể mang số chương khác (vd marker `## Chương 928: Chương 918: ...`)
    — giữ title nguyên văn, không suy diễn số từ index.

    Bỏ qua mọi nội dung trước marker chương đầu tiên (prompt, glossary tham khảo)
    và cắt nội dung chương cuối tại marker GLOSSARY nếu có.
    """
    results: list[tuple[int, str, str]] = []
    current_index: int | None = None
    current_title = ""
    buf: list[str] = []

    def _flush() -> None:
        if current_index is not None:
            results.append((current_index, current_title, "\n".join(buf).strip()))

    for line in text.splitlines():
        ch = CHAPTER_MARKER_RE.match(line)
        if ch:
            _flush()
            current_index = int(ch.group(1))
            current_title = _marker_title(ch.group(2))
            buf = []
            continue
        if GLOSSARY_MARKER_RE.match(line):
            # Khối glossary kết thúc phần chương đang gom.
            _flush()
            current_index = None
            buf = []
            continue
        if current_index is not None:
            buf.append(line)

    _flush()
    return results


def parse_glossary(text: str) -> dict[str, str]:
    """Gom các mục glossary từ MỌI khối `GLOSSARY` trong text thành 1 dict phẳng.

    Không còn phân loại names/vietphrase — mọi dòng `Hán = Việt` trong khối
    glossary đều được gom. Subheading cũ (`### NAMES`, `[VIETPHRASE]`...) không
    chứa `=` nên tự bị bỏ qua → file .md xuất theo định dạng cũ vẫn parse được,
    toàn bộ entry đổ vào một dict.
    """
    glossary: dict[str, str] = {}
    in_glossary = False

    for line in text.splitlines():
        if GLOSSARY_MARKER_RE.match(line):
            in_glossary = True
            continue
        if CHAPTER_MARKER_RE.match(line):
            in_glossary = False
            continue
        if not in_glossary:
            continue
        parsed = parse_glossary_line(_BULLET_RE.sub("", line.strip()))
        if parsed:
            source, target, _note = parsed
            # Bỏ qua dòng mẫu placeholder trong prompt (vd "<chữ Hán> = <tiếng Việt>").
            if "<" in source or ">" in source or "<" in target or ">" in target:
                continue
            glossary[source] = target

    return glossary


def validate_import(
    parsed_indexes: list[int],
    expected_indexes: list[int],
    manifest_indexes: list[int],
) -> dict[str, list[int]]:
    """Đối chiếu chương parse được với chương đã xuất và manifest.

    - matched: có trong text VÀ thuộc manifest (sẽ ghi đè được)
    - unknown: có trong text NHƯNG không thuộc manifest (index lạ)
    - missing: đã xuất nhưng không thấy trong text (AI bỏ sót)
    - extra: thuộc manifest, có trong text nhưng KHÔNG nằm trong tập đã xuất
    """
    parsed = set(parsed_indexes)
    expected = set(expected_indexes)
    manifest = set(manifest_indexes)

    matched = sorted(parsed & manifest)
    unknown = sorted(parsed - manifest)
    missing = sorted(expected - parsed)
    extra = sorted((parsed & manifest) - expected)
    return {"matched": matched, "unknown": unknown, "missing": missing, "extra": extra}
