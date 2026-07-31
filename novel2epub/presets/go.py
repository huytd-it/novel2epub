"""Go preset — ships Go-optimised prompt templates for the OpenAI-Compatible
translator backend. Only overrides prompt templates; base_url/api_key/model
still come from translate.openai config.
"""

from __future__ import annotations

from typing import Any

GO_PROMPT = """Dịch đoạn văn Trung Quốc sau đây sang tiếng Việt.

LUẬT CỐT LÕI:
- Đầu ra phải là tiếng Việt 100% — dịch TOÀN BỘ, không để lại chữ Hán nào.
- KHÔNG dùng kiểu "từ gốc (dịch nghĩa)" hay chú thích song ngữ.
- Từ khó, không chắc nghĩa: chọn từ tiếng Việt gần nghĩa nhất theo ngữ cảnh — thà dịch thoát ý còn hơn giữ chữ Hán.

Luật dịch:
1. Dịch tự nhiên, đúng ngữ pháp Việt Nam.
2. Tên riêng, công pháp, địa danh giữ Hán Việt.
3. NGOẠI LỆ luật 2 — tên người nước ngoài phiên âm sang chữ Hán: trả về dạng chữ Latin gốc (夏洛克 → Sherlock, 鸣人 → Naruto), KHÔNG dùng Hán Việt. Không chắc tên gốc thì theo luật 2.
4. Ngôi xưng ưu tiên BẢNG NHÂN VẬT > ngôi kể > quan hệ/ngữ cảnh > thể loại. [LỜI KỂ] có thể dùng "hắn" khi tự nhiên, kể cả truyện hiện đại, nhưng không thay mọi 他 bằng "hắn" và không lặp đại từ dày đặc. [LỜI KỂ NGÔI 1/2], [THOẠI] và [NỘI TÂM] chỉ dùng "ta/ngươi" khi đúng giọng, thân phận và quan hệ. Không ánh xạ đại từ máy móc.
5. Thành ngữ, khẩu ngữ, thơ từ dịch thoát ý, không máy móc.
6. Từ đời thường (động tác, nấu nướng, ăn uống, cảm giác...) dịch tự nhiên như văn nói tiếng Việt, không phiên âm Hán Việt cứng nhắc.
7. Giữ nguyên cách chia đoạn. Nếu dòng đầu là tiêu đề chương, dịch tiêu đề cho hay, gọn.

Chỉ trả về bản dịch, không thêm lời dẫn hay chú thích.
KIỂM TRA CUỐI: rà lại toàn bộ đầu ra; nếu còn ký tự Trung Quốc nào, dịch nốt sang tiếng Việt rồi mới trả lời.
{glossary}
{characters}
Quy tắc ngôi xưng theo thể loại: {pronoun_policy}
--- Văn bản gốc ---
{text}{auto_glossary_block}"""

GO_TITLE_PROMPT = """Dịch {kind} sau sang tiếng Việt thật hay, tự nhiên.

Luật:
- Không dịch sát nghĩa từng chữ.
- Giữ tên riêng dạng Hán Việt.
- Riêng tên người nước ngoài giữ dạng chữ Latin gốc (夏洛克 → Sherlock), không chuyển Hán Việt.
- Nếu tiêu đề gốc rõ nghĩa, dịch thoát.
- Nếu khó chuyển ngữ, dịch nghĩa và thêm GIẢI THÍCH.

{glossary}
Trả lời đúng 2 dòng:
TIÊU ĐỀ: <bản dịch>
GIẢI THÍCH: <để trống nếu đã rõ>

--- {kind} ---
{text}"""

GO_EXTRACT_PROMPT = """Extract the chapter content (正文) from the following Chinese web novel HTML page.
Return ONLY the clean chapter text in Chinese, removing all navigation, ads, scripts, CSS, and non-content elements.
Keep paragraph breaks.
If no chapter content is found, return an empty string.

--- HTML ---
{html}"""


def load_preset() -> dict[str, Any]:
    return {
        "prompt_template": GO_PROMPT,
        "title_prompt_template": GO_TITLE_PROMPT,
    }
