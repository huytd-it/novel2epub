"""Go preset — ships Go-optimised prompt templates for the OpenAI-Compatible
translator backend. Only overrides prompt templates; base_url/api_key/model
still come from translate.openai config.
"""

from __future__ import annotations

from typing import Any

GO_PROMPT = """Dịch đoạn văn Trung Quốc sau đây sang tiếng Việt.

Luật:
1. Dịch tự nhiên, đúng ngữ pháp Việt Nam.
2. Tên riêng, công pháp, địa danh giữ nguyên Hán Việt.
3. Ngôi xưng theo quan hệ nhân vật (cha/mẹ/sư phụ/chàng/nàng/ngài…).
4. Thành ngữ, thơ từ dịch thoát ý, không máy móc.
5. Giữ nguyên cách chia đoạn.

Chỉ trả về bản dịch, không thêm lời dẫn hay chú thích.
{glossary}
--- Văn bản gốc ---
{text}"""

GO_TITLE_PROMPT = """Dịch {kind} sau sang tiếng Việt thật hay, tự nhiên.

Luật:
- Không dịch sát nghĩa từng chữ.
- Giữ tên riêng dạng Hán Việt.
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
