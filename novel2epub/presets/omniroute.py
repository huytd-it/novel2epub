"""OmniRoute preset — prompt templates tối ưu cho novel dài khi dịch qua
OmniRoute gateway (https://github.com/diegosouzapw/OmniRoute). Tận dụng
RTK + Caveman compression tiết kiệm 15-95% tokens qua hơn 237 providers.

Chỉ override prompt templates; base_url/api_key/model vẫn đến từ
`translate.openai` trong config. Khi bật `translate.preset: omniroute`:
- Tự động detect response header `X-OmniRoute-Version` để capture cost/latency
  (xem openai_client.run_chat_with_meta + pipeline._translate_one).
- Output JSON glossary kèm bản dịch qua marker `===GLOSSARY===` (tương thích
  với auto-glossary đã có trong OpenAITranslator).
"""
from __future__ import annotations

from typing import Any

OMNIPROUTE_PROMPT = """Bạn là dịch giả Trung → Việt chuyên web novel. Mục tiêu: bản dịch MƯỢT, tự nhiên, nhất quán tên riêng.

Luật dịch:
1. Dịch tự nhiên, đúng ngữ pháp Việt, KHÔNG dịch sát từng chữ.
2. Tên riêng, công pháp, địa danh giữ Hán Việt quen thuộc, viết hoa, nhất quán.
3. Ngôi xưng theo quan hệ nhân vật và ngữ cảnh (ta/ngươi, chàng/nàng, sư phụ/đồ nhi, lão phu/tiểu hữu…). Tránh dùng "ta/ngươi" máy móc.
4. Thành ngữ, điển tích, thơ từ dịch thoát ý hoặc dùng bản quen thuộc.
5. Giữ nguyên cách chia đoạn. Nếu dòng đầu là tiêu đề chương, dịch tiêu đề cho hay, gọn.
6. Output phải là tiếng Việt 100% — KHÔNG để sót chữ Hán, KHÔNG chú thích song ngữ kiểu "từ gốc (nghĩa)". Từ không chắc nghĩa: dịch thoát theo ngữ cảnh, không giữ chữ Hán. Trước khi trả lời, rà lại: nếu còn ký tự Trung Quốc nào trong bản dịch, dịch nốt rồi mới trả lời.

{glossary}
--- Văn bản gốc ---
{text}

Sau khi dịch xong toàn bộ văn bản trên, in đúng 1 dòng ===GLOSSARY=== rồi đến JSON array các thuật ngữ/tên riêng MỚI xuất hiện trong chương này mà CHƯA có trong glossary trên (không lặp lại, không bịa).
Mỗi mục: {{"source": "<Hán>", "suggested": "<Việt>", "type": "name|place|skill|item|term|phrase", "target_file": "names.txt|vietphrase.txt"}}
Nếu không có mục mới: ===GLOSSARY===
[]"""

OMNIPROUTE_TITLE_PROMPT = """Dịch {kind} chương Trung Quốc sau sang tiếng Việt thật hay, có ý vị, tự nhiên.

Luật:
- Không dịch sát nghĩa từng chữ; ưu tiên bản dịch bay bổng, gợi hình.
- Giữ tên riêng dạng Hán Việt.
- Nếu {kind} gốc đã rõ nghĩa, dịch thoát.
- Nếu khó chuyển ngữ, dịch nghĩa + thêm GIẢI THÍCH ngắn.

{glossary}
Trả lời đúng 2 dòng (không thêm gì khác):
TIÊU ĐỀ: <bản dịch>
GIẢI THÍCH: <lý do / chú thích — để trống nếu đã rõ>

--- {kind} ---
{text}"""


def load_preset() -> dict[str, Any]:
    return {
        "prompt_template": OMNIPROUTE_PROMPT,
        "title_prompt_template": OMNIPROUTE_TITLE_PROMPT,
    }
