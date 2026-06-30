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
# để khoan dung hoa/thường khi AI viết lại tiêu đề.
CHAPTER_MARKER_RE = re.compile(r"^(?:#{1,6}\s*|={3,}\s*)CHƯƠNG\s+(\d+)\b", re.IGNORECASE)
GLOSSARY_MARKER_RE = re.compile(r"^(?:#{1,6}\s*|={3,}\s*)GLOSSARY\b", re.IGNORECASE)

_NAMES_HEADERS = {"[NAMES]", "[NAME]", "[TÊN]", "[TEN]", "NAMES", "NAME", "TÊN", "TEN"}
_VIETPHRASE_HEADERS = {
    "[VIETPHRASE]", "[VP]", "[THUẬT NGỮ]", "[THUAT NGU]",
    "VIETPHRASE", "VP", "THUẬT NGỮ", "THUAT NGU",
}
_BULLET_RE = re.compile(r"^[-*+]\s+")


def chapter_marker(index: int, title: str = "") -> str:
    """Dòng tiêu đề Markdown mở đầu một chương."""
    label = f"Chương {index}"
    if title.strip():
        label += f": {title.strip()}"
    return f"## {label}"


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
- Ở CUỐI kết quả, thêm một mục `## GLOSSARY` liệt kê tên riêng/thuật ngữ MỚI bạn \
gặp (chưa có trong glossary tham khảo), theo đúng định dạng:

## GLOSSARY

### NAMES
- <chữ Hán> = <Hán Việt>

### VIETPHRASE
- <chữ Hán> = <nghĩa tiếng Việt>
"""


# Prompt dịch (Trung → Việt) cho luồng "xuất raw để dịch" — nguyên tắc 1-7 lấy
# nguyên từ `DEFAULT_PROMPT` trong `config.py` (prompt dịch chính thức của hệ
# thống, dùng cho backend AI `openai`), chỉ đổi phần đầu/cuối cho phù hợp batch
# nhiều chương theo Markdown, để dịch thủ công qua web chat nhất quán với dịch
# bằng AI backend trong app.
TRANSLATE_PROMPT = """# Yêu cầu dịch truyện Trung → Việt

Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt, theo phong cách \
edit mượt mà mà độc giả Việt quen thuộc. Hãy DỊCH bản gốc tiếng Trung bên dưới \
sang tiếng Việt, theo các nguyên tắc sau:

1. Dịch sang tiếng Việt tự nhiên, đúng ngữ pháp Việt: đảo trật tự từ cho thuận, \
đưa trạng ngữ lên đầu câu khi hợp lý, câu phải đủ chủ — vị.
2. Ngôi xưng phải theo quan hệ và ngữ cảnh, KHÔNG bê nguyên ta/ngươi. Chọn phù \
hợp giữa cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/nàng/ông ấy/bà ấy/ngài/người/con/cháu...
3. Tên riêng, công pháp, địa danh, chiêu thức: giữ theo lối Hán Việt quen \
thuộc, viết hoa và NHẤT QUÁN xuyên suốt. Dùng đúng các tên trong phần Glossary \
tham khảo.
4. Hạn chế lạm dụng từ Hán Việt khó hiểu; ưu tiên thuần Việt nếu rõ nghĩa hơn, \
nhưng vẫn giữ chất cổ trang khi cần.
5. Giữ nguyên cách chia đoạn của bản gốc.
6. Thành ngữ nên dịch thoát ý, tự nhiên, không máy móc.
7. Thơ từ, ca phú, trích dẫn cổ văn: nếu nhận ra bản dịch tiếng Việt phổ biến \
thì dùng và ghi tên dịch giả trong ngoặc; nếu không, tự chuyển ngữ cho người \
đọc hiểu được nghĩa. TUYỆT ĐỐI không dịch kiểu Vietphrase-một-nghĩa (ghép \
nghĩa từng chữ máy móc, từ nào dịch được thì dịch từ nào không thì giữ \
nguyên Hán).

## Quy tắc định dạng đầu ra (bắt buộc để nạp ngược vào hệ thống)

- GIỮ NGUYÊN các dòng tiêu đề `## Chương N`; điền bản dịch tiếng Việt BÊN DƯỚI \
mỗi tiêu đề (không để sót chữ Hán chưa dịch). Tiêu đề chương trong ngoặc sau \
`## Chương N:` cũng dịch cho hay, gọn — không dịch sát nghĩa kiểu máy. KHÔNG \
gộp/đổi/xóa tiêu đề, không tự thêm tiêu đề chương mới.
- Ở CUỐI kết quả, thêm một mục `## GLOSSARY` liệt kê tên riêng/thuật ngữ MỚI \
bạn gặp (chưa có trong glossary tham khảo), theo đúng định dạng:

## GLOSSARY

### NAMES
- <chữ Hán> = <Hán Việt>

### VIETPHRASE
- <chữ Hán> = <nghĩa tiếng Việt>
"""


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


def parse_import(text: str) -> list[tuple[int, str]]:
    """Tách văn bản đã biên tập thành list `(index, content)` theo marker chương.

    Bỏ qua mọi nội dung trước marker chương đầu tiên (prompt, glossary tham khảo)
    và cắt nội dung chương cuối tại marker GLOSSARY nếu có.
    """
    results: list[tuple[int, str]] = []
    current_index: int | None = None
    buf: list[str] = []

    def _flush() -> None:
        if current_index is not None:
            results.append((current_index, "\n".join(buf).strip()))

    for line in text.splitlines():
        ch = CHAPTER_MARKER_RE.match(line)
        if ch:
            _flush()
            current_index = int(ch.group(1))
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
