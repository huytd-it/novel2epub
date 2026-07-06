"""Xuất/nhập biên tập hàng loạt: gom nhiều chương thành một file Markdown để dán
hoặc upload lên web chat AI biên tập, rồi parse kết quả trả về nạp ngược vào hệ
thống. Markdown (thay vì marker `=====` thô) giúp AI nhận diện cấu trúc tốt hơn
và có thể tải xuống/upload thẳng dạng file `.md`.

Module thuần (không phụ thuộc web/FastAPI) để dễ unit-test. Routes trong
`app/routes/chapters.py` lo phần I/O (đọc `translated/`, glossary) + ghi đè.

Cấu trúc một khối xuất:

    <PROMPT biên tập, dạng markdown>

    ## Glossary tham khảo (dùng đúng các tên này)
    ### Tên riêng
    - 萧炎 = Tiêu Viêm
    ### Thuật ngữ
    - 斗气 = Đấu khí

    ## Chương 1: <tiêu đề>
    <bản dịch chương 1>

    ## Chương 2
    <bản dịch chương 2>

Web chat trả về các chương đã biên tập (giữ tiêu đề `## Chương N`) kèm một mục
`## GLOSSARY` mới ở cuối — `parse_import` tách chương, `parse_glossary` gom
glossary. Marker `===== CHƯƠNG N =====` kiểu cũ vẫn được nhận diện để tương
thích ngược với các bản xuất trước đó.
"""
from __future__ import annotations

import re

from .storage import parse_glossary_line

# Marker phân tách — chấp nhận cả tiêu đề Markdown (`## CHƯƠNG N`, định dạng mới,
# tốt cho AI hơn) lẫn marker `=====` kiểu cũ (tương thích ngược). `re.IGNORECASE`
# để khoan dung hoa/thường khi AI viết lại tiêu đề. Group 2 = phần tiêu đề sau
# số chương (có thể rỗng), chuẩn hóa qua `_marker_title`.
# Cũng bắt biến thể AI hay tự thêm bold/italic: `## **CHƯƠNG N**`, `**CHƯƠNG N**`.
# Vẫn yêu cầu ít nhất một trong `#` / `=` / `*` làm prefix để tránh parse nhầm
# các dòng văn bản thường bắt đầu bằng "Chương ...".
CHAPTER_MARKER_RE = re.compile(
    r"^(?:\*{1,2}\s*)?(?:#{1,6}\s*\*{0,2}\s*|={3,}\s*|\*{1,2}\s*)CHƯƠNG\s+(\d+)\b\s*(.*)$",
    re.IGNORECASE,
)
GLOSSARY_MARKER_RE = re.compile(r"^(?:#{1,6}\s*|={3,}\s*)GLOSSARY\b", re.IGNORECASE)

_NAMES_HEADERS = {"[NAMES]", "[NAME]", "[TÊN]", "[TEN]", "NAMES", "NAME", "TÊN", "TEN"}
_VIETPHRASE_HEADERS = {
    "[VIETPHRASE]", "[VP]", "[THUẬT NGỮ]", "[THUAT NGU]",
    "VIETPHRASE", "VP", "THUẬT NGỮ", "THUAT NGU",
}
_BULLET_RE = re.compile(r"^[-*+]\s+")


# Số chương THẬT ở đầu tiêu đề gốc (第911章/卷/回) — chỉ hỗ trợ chữ số Ả Rập,
# nhất quán với `pipeline._clean_title`.
_ZH_NUM_PREFIX_RE = re.compile(r"^第\s*(\d+)\s*(章|卷|回)")
_ZH_NUM_LABELS = {"章": "Chương", "卷": "Quyển", "回": "Hồi"}


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
    num, label = int(m.group(1)), _ZH_NUM_LABELS[m.group(2)]
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
    """Dòng tiêu đề Markdown mở đầu một chương."""
    label = f"Chương {index}"
    if title.strip():
        label += f": {title.strip()}"
    return f"## {label}"


# Quy tắc trích glossary ở cuối output — DÙNG CHUNG cho EDIT_PROMPT và
# TRANSLATE_PROMPT. Siết chặt tiêu chí để AI KHÔNG nhét từ đời thường vào
# vietphrase.txt (lỗi hay gặp: "kệ hàng", "cơm thừa canh cặn", "chạy việc
# vặt"...). Ghép vào cuối mỗi prompt bằng nối chuỗi.
_GLOSSARY_OUTPUT_RULE = """- Ở CUỐI kết quả, thêm một mục `## GLOSSARY`. \
CHỈ liệt kê tên riêng/thuật ngữ MỚI (chưa có trong glossary tham khảo) mà \
BẮT BUỘC phải nhất quán xuyên suốt truyện. Đây là bảng để đồng bộ cách dịch, \
KHÔNG phải từ điển — thà bỏ sót còn hơn đưa nhầm từ thông thường vào.

TIÊU CHÍ đưa vào (chỉ khi thỏa mãn):
- `### NAMES`: tên riêng — nhân vật, địa danh, môn phái/tổ chức, chức danh/tước vị.
- `### VIETPHRASE`: thuật ngữ ĐẶC THÙ của thế giới truyện, lặp lại nhiều lần — \
công pháp, chiêu thức, cảnh giới tu luyện, pháp bảo, đan dược, chủng tộc, hệ \
thống sức mạnh, biệt danh/xưng hiệu cố định của nhân vật.

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

### NAMES
- <chữ Hán> = <Hán Việt>

### VIETPHRASE
- <chữ Hán> = <nghĩa tiếng Việt>
"""


# Prompt biên tập chắt lọc nguyên tắc "edit đúng/hay" từ docs/rule.md, viết dạng
# Markdown để AI và người đọc dễ theo dõi cấu trúc hơn.
EDIT_PROMPT = """# Yêu cầu biên tập truyện dịch Trung → Việt

Bạn là biên tập viên truyện dịch Trung → Việt. Hãy BIÊN TẬP LẠI bản dịch \
tiếng Việt bên dưới cho hay, chính xác và tự nhiên, theo các nguyên tắc sau:

1. Đối chiếu ngữ cảnh để giữ ĐÚNG nghĩa, KHÔNG thêm bớt nội dung; gặp từ/điển \
tích đáng ngờ thì hiểu cho đúng rồi mới viết lại.
2. NGÔI XƯNG theo quan hệ, tuổi tác, thân phận và cảm xúc nhân vật — hạn chế \
"ta – ngươi" máy móc (cha/mẹ/con, huynh/đệ/tỷ/muội, chàng/nàng, ông ấy/bà ấy...).
3. Sửa NGỮ PHÁP và trật tự từ cho thuần tiếng Việt (đưa trạng ngữ lên đầu câu, \
câu đủ chủ – vị, ngắt câu/dấu câu hợp lý).
4. CÂN BẰNG Hán – Việt và thuần Việt: giữ sắc thái (nhất là truyện cổ đại) nhưng \
đừng để câu khó hiểu; thành ngữ/tục ngữ phải đúng nghĩa gốc.
5. TÊN RIÊNG (nhân vật, địa danh, môn phái, chức danh) giữ ở dạng Hán Việt viết \
hoa, NHẤT QUÁN xuyên suốt. Dùng đúng các tên trong phần Glossary tham khảo.

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

- GIỮ NGUYÊN các dòng tiêu đề `## Chương N`; chỉ sửa phần nội dung BÊN DƯỚI mỗi \
tiêu đề. KHÔNG gộp/đổi/xóa tiêu đề, không tự thêm tiêu đề chương mới.
""" + _GLOSSARY_OUTPUT_RULE


# Prompt dịch (Trung → Việt) cho luồng "xuất raw để dịch" — nguyên tắc 1-8 lấy
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
2. Ngôi xưng theo quan hệ và ngữ cảnh, KHÔNG bê nguyên ta/ngươi. Chọn phù hợp \
giữa cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/nàng/ông ấy/bà ấy/ngài/người/con/cháu...
3. Tên riêng, công pháp, địa danh, chiêu thức: giữ Hán Việt quen thuộc, viết \
hoa và NHẤT QUÁN xuyên suốt. Dùng đúng các tên trong phần Glossary tham khảo.
4. Hạn chế lạm dụng từ Hán Việt khó hiểu; ưu tiên thuần Việt nếu rõ nghĩa hơn, \
nhưng giữ chất cổ trang khi cần.
5. Giữ nguyên cách chia đoạn của bản gốc.
6. Thành ngữ, tục ngữ, khẩu ngữ: dịch thoát ý bằng cách nói tự nhiên của người \
Việt, không máy móc (khẩu ngữ chỉ sự e dè thì dịch "ngại", "ngại ngùng"; chê \
tác phong ăn uống thì "ăn uống khó coi"...).
7. Từ vựng đời thường (động tác, nấu nướng, ăn uống, cảm giác, tiếng lóng...): \
dịch tự nhiên như văn nói tiếng Việt thông thường, không cần giữ sắc thái Hán, \
không phiên âm Hán Việt cứng nhắc.
8. Thơ từ, ca phú, trích dẫn cổ văn: nếu có bản dịch phổ biến thì dùng và ghi \
tên dịch giả trong ngoặc (vd: "— (bản dịch Tản Đà)"); nếu không, tự chuyển ngữ \
cho người đọc hiểu, không dịch nguyên xi từng chữ kiểu Vietphrase.

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

- CHỈ trả về bản dịch tiếng Việt thuần túy. KHÔNG thêm lời mở đầu, ghi chú, \
giải thích, hay đánh dấu song ngữ.
- KIỂM TRA CUỐI (bắt buộc): trước khi trả lời, rà lại toàn bộ nội dung các \
chương; nếu còn BẤT KỲ ký tự Trung Quốc nào ngoài mục `## GLOSSARY`, dịch nốt \
sang tiếng Việt rồi mới trả lời.
- GIỮ NGUYÊN các dòng tiêu đề `## Chương N`; điền bản dịch tiếng Việt BÊN DƯỚI \
mỗi tiêu đề. Tiêu đề chương trong ngoặc sau `## Chương N:` cũng dịch cho hay, \
gọn — không dịch sát nghĩa kiểu máy. KHÔNG gộp/đổi/xóa tiêu đề, không tự thêm \
tiêu đề chương mới.
""" + _GLOSSARY_OUTPUT_RULE


def _format_glossary_block(names: dict[str, str], vietphrase: dict[str, str]) -> str:
    """Render glossary thành mục Markdown `### Tên riêng`/`### Thuật ngữ` (rỗng → "")."""
    if not names and not vietphrase:
        return ""
    sections = ["## Glossary tham khảo (dùng đúng các tên này)"]
    if names:
        lines = "\n".join(f"- {s} = {t}" for s, t in names.items() if s and t)
        sections.append(f"### Tên riêng\n{lines}")
    if vietphrase:
        lines = "\n".join(f"- {s} = {t}" for s, t in vietphrase.items() if s and t)
        sections.append(f"### Thuật ngữ\n{lines}")
    return "\n\n".join(sections)


def build_export(
    items: list[tuple[int, str, str]],
    *,
    names: dict[str, str] | None = None,
    vietphrase: dict[str, str] | None = None,
    prompt: str = EDIT_PROMPT,
) -> str:
    """Gom các chương thành một khối xuất.

    items: list `(index, title, content)`; sẽ được sắp theo `index` tăng dần.
    names/vietphrase: glossary hiện có để đính kèm (tham khảo, có thể rỗng).
    """
    parts: list[str] = [prompt.rstrip()]

    glossary_block = _format_glossary_block(names or {}, vietphrase or {})
    if glossary_block:
        parts.append(glossary_block)

    for index, title, content in sorted(items, key=lambda it: it[0]):
        parts.append(f"{chapter_marker(index, title)}\n{content.strip()}")

    return "\n\n".join(parts) + "\n"


# Prompt nhờ web chat AI DỌN LẠI glossary (dedup, sửa Hán-Việt, gộp mâu thuẫn).
# Trả về đúng format `### NAMES`/`### VIETPHRASE` để `parse_glossary` nạp ngược.
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
5. Phân loại đúng: tên riêng (nhân vật, địa danh, môn phái, chức danh) vào NAMES; \
thuật ngữ đặc thù của thế giới truyện (công pháp, chiêu thức, cảnh giới, pháp \
bảo, đan dược...) vào VIETPHRASE.
6. KHÔNG bịa thêm mục mới không có trong bảng gốc. KHÔNG thêm bình luận, giải thích.

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

Chỉ trả về đúng cấu trúc sau, mỗi mục một dòng dạng `- <chữ Hán> = <tiếng Việt>`:

## GLOSSARY

### NAMES
- 萧炎 = Tiêu Viêm

### VIETPHRASE
- 斗气 = Đấu khí
"""


def build_glossary_export(
    names: dict[str, str], vietphrase: dict[str, str], *, prompt: str = GLOSSARY_CLEAN_PROMPT
) -> str:
    """Gom glossary hiện tại thành khối xuất cho web chat AI dọn lại.

    Dùng heading `## GLOSSARY`/`### NAMES`/`### VIETPHRASE` để `parse_glossary`
    nạp ngược được kết quả AI trả về (round-trip). Bảng rỗng vẫn xuất khung để
    AI biết định dạng mong muốn.
    """
    parts: list[str] = [prompt.rstrip(), "## GLOSSARY"]
    names_lines = "\n".join(f"- {s} = {t}" for s, t in names.items() if s and t)
    vp_lines = "\n".join(f"- {s} = {t}" for s, t in vietphrase.items() if s and t)
    parts.append("### NAMES\n" + (names_lines or "- "))
    parts.append("### VIETPHRASE\n" + (vp_lines or "- "))
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


def parse_glossary(text: str) -> dict[str, dict[str, str]]:
    """Gom các mục glossary từ MỌI khối `GLOSSARY` trong text.

    Trả `{"names": {source: target}, "vietphrase": {source: target}}`; bỏ dòng
    thiếu source/target hoặc nằm ngoài nhóm `[NAMES]`/`[VIETPHRASE]`.
    """
    names: dict[str, str] = {}
    vietphrase: dict[str, str] = {}
    in_glossary = False
    current: dict[str, str] | None = None

    for line in text.splitlines():
        if GLOSSARY_MARKER_RE.match(line):
            in_glossary = True
            current = None
            continue
        if CHAPTER_MARKER_RE.match(line):
            in_glossary = False
            current = None
            continue
        if not in_glossary:
            continue
        stripped = line.strip()
        header = re.sub(r"^#{1,6}\s*", "", stripped).strip().upper()
        if header in _NAMES_HEADERS:
            current = names
            continue
        if header in _VIETPHRASE_HEADERS:
            current = vietphrase
            continue
        if current is None:
            continue
        parsed = parse_glossary_line(_BULLET_RE.sub("", stripped))
        if parsed:
            source, target, _note = parsed
            # Bỏ qua dòng mẫu placeholder trong prompt (vd "<chữ Hán> = <Hán Việt>").
            if "<" in source or ">" in source or "<" in target or ">" in target:
                continue
            current[source] = target

    return {"names": names, "vietphrase": vietphrase}


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
