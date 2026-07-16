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
4. Ngôi xưng theo quan hệ nhân vật (cha/mẹ/sư phụ/chàng/nàng/ngài…).
5. Thành ngữ, khẩu ngữ, thơ từ dịch thoát ý, không máy móc.
6. Từ đời thường (động tác, nấu nướng, ăn uống, cảm giác...) dịch tự nhiên như văn nói tiếng Việt, không phiên âm Hán Việt cứng nhắc.
7. Giữ nguyên cách chia đoạn. Nếu dòng đầu là tiêu đề chương, dịch tiêu đề cho hay, gọn.

Chỉ trả về bản dịch, không thêm lời dẫn hay chú thích.
KIỂM TRA CUỐI: rà lại toàn bộ đầu ra; nếu còn ký tự Trung Quốc nào, dịch nốt sang tiếng Việt rồi mới trả lời.
{glossary}
--- Văn bản gốc ---
{text}"""

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
