"""Preset xưng hô theo thể loại truyện — logic thuần (không đụng DB/OS).

Trước đây `translate.style.pronoun_policy` mặc định là chuỗi "contextual" và
được nhét thẳng vào prompt, tức model đọc được đúng một từ vô nghĩa. Module này
biến lựa chọn thể loại thành BỘ LUẬT THẬT: từ nên dùng, từ cấm, mức Hán Việt.

`auto` là preset TRUNG TÍNH — không đoán thể loại từ nội dung. Module này KHÔNG
được import gì từ `novel2epub.hachimimt`: package đó kéo theo `sentencepiece` và
`huggingface_hub` (dep tùy chọn) ngay ở `__init__`, mà `genre.py` lại nằm trên
đường dịch mặc định của backend `openai`.
"""
from __future__ import annotations

from dataclasses import dataclass

# Giá trị mặc định cũ của style.pronoun_policy — coi như "người dùng chưa ghi
# gì", không nối vào luật.
_DEFAULT_POLICY = "contextual"

CONTEXTUAL_PRONOUN_RULE = (
    "Ưu tiên BẢNG NHÂN VẬT > ngôi kể thực tế > quan hệ/ngữ cảnh > gợi ý thể loại. "
    "Trong lời kể ngôi ba, được dùng \"hắn\" khi tự nhiên và nhất quán, kể cả "
    "truyện hiện đại; không máy móc đổi thành \"anh/anh ta/anh ấy\". Trong lời "
    "kể ngôi một hoặc ngôi hai, thoại và nội tâm, được dùng \"ta/ngươi\" khi "
    "đúng giọng kể, thân phận, quan hệ và cảm xúc. Không ánh xạ máy móc "
    "我→ta, 你→ngươi, 他→hắn; chọn đại từ theo chức năng của từng câu."
)

RUNTIME_PRONOUN_PIN = (
    "NGÔI XƯNG: Bảng nhân vật > ngôi kể > ngữ cảnh > thể loại; "
    "hắn/ta/ngươi chỉ dùng khi tự nhiên."
)


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
        # Trung tính — không đoán thể loại, nhưng vẫn cần liệt kê các dạng
        # xưng hô/kính ngữ chung mà rule 2 của DEFAULT_PROMPT từng ghi thẳng
        # trước khi có bảng nhân vật (cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/
        # nàng/ông ấy/bà ấy/ngài/người/con/cháu). KHÔNG cấm gì (forbid_words
        # rỗng) vì auto không biết thể loại nên không được loại trừ đăng ký
        # nào (không phải kiếm hiệp cũng không phải đô thị).
        use_words="cha, mẹ, thúc, bá, cô, sư phụ, tiền bối, chàng, nàng, "
                  "ông ấy, bà ấy, ngài, người, con, cháu",
        forbid_words="",
        # Bỏ trống — trục Hán Việt đã có slot {han_viet_level} riêng
        # (xem format_style_value); để câu ở đây chỉ lặp lại ý đó.
        han_viet_hint="",
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
            "Lời kể thường dùng hắn/y/gã (nam), nàng (nữ); chỉ dùng anh/cô ấy "
            "khi BẢNG NHÂN VẬT, ngôi kể hoặc ngữ cảnh yêu cầu.",
            "Đơn vị đo cổ (里/丈/尺/两/更/时辰) giữ hệ cổ: dặm, trượng, thước, "
            "lượng, canh, canh giờ.",
        ),
    ),
    "urban": GenrePreset(
        key="urban",
        label="Đô thị / Hiện đại",
        use_words="tôi, cậu, anh, chị, em, ông, bà, nó, tao, mày",
        forbid_words="chàng, tiểu tử, tại hạ, bổn tọa, lão phu",
        han_viet_hint="Hán Việt thấp: 心动 → \"tim đập loạn\", KHÔNG \"tâm động\"; "
                      "总裁 → \"tổng giám đốc\"; 微信 → \"WeChat\".",
        extra_rules=(
            "Xưng hô gia đình và công sở theo đúng thứ bậc (ba/mẹ/anh/chị, "
            "anh/chị + tên, sếp, giám đốc X).",
            "Trong thoại hiện đại thường ưu tiên tôi/anh/em/cậu; đây là gợi ý "
            "mềm, không được phủ định ngôi kể hoặc BẢNG NHÂN VẬT.",
        ),
    ),
    "romance": GenrePreset(
        key="romance",
        label="Ngôn tình / Đam mỹ",
        use_words="tôi, cậu, anh, em, cô, mình",
        forbid_words="tại hạ, bổn tọa, lão phu",
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
        forbid_words="tại hạ, bổn tọa, đạo hữu",
        han_viet_hint="Thuật ngữ kỹ thuật KHÔNG Hán Việt hoá: 基因 → gen (không "
                      "\"cơ nhân\"), 病毒 → virus, 芯片 → chip.",
        extra_rules=(
            "Tên riêng giữ dạng chữ Latin gốc; chức danh Tây phương dùng bá tước, "
            "hiệp sĩ, pháp sư, thánh nữ.",
        ),
    ),
}

GENRE_KEYS: tuple[str, ...] = tuple(GENRE_PRESETS)


def resolve_genre(genre: str) -> GenrePreset:
    """Trả preset thực dùng. Giá trị lạ hoặc rỗng → `auto` (trung tính)."""
    key = (genre or "").strip().lower() or "auto"
    return GENRE_PRESETS.get(key, GENRE_PRESETS["auto"])


def forbid_words(genre: str) -> str:
    """Các từ thường tránh theo thể loại, không phải lệnh cấm tuyệt đối."""
    return resolve_genre(genre).forbid_words


def format_pronoun_rules(genre: str, user_policy: str = "") -> str:
    """Render luật xưng hô để thay vào placeholder {pronoun_policy}.

    `user_policy` chỉ được nối thêm khi người dùng thực sự ghi gì đó khác giá trị
    mặc định cũ ("contextual") — giữ được quyền ghi đè mà không rò enum vào prompt.
    """
    preset = resolve_genre(genre)
    lines: list[str] = []
    if preset.use_words:
        lines.append(f"Có thể dùng khi phù hợp: {preset.use_words}.")
    if preset.forbid_words:
        lines.append(
            "Thường tránh nếu BẢNG NHÂN VẬT, ngôi kể hoặc ngữ cảnh không yêu cầu: "
            f"{preset.forbid_words}."
        )
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
