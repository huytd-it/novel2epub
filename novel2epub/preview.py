"""Preview token chính xác cho bản nháp AI — logic thuần (không I/O).

Vấn đề: khi người dùng "xem trước bản sẽ áp" rồi quay lại xác nhận, phải chắc
chắn rằng bản họ vừa duyệt vẫn là bản sẽ được áp — không thể nhầm lẫn với bản
khác (chương đổi giữa chừng, hoặc người dùng mở 2 tab). Token xác thực bằng
CHÍNH snapshot nội dung tại thời điểm cấp:

- `base_rev` + `base_text` — snapshot "exact set" mà bản nháp sinh ra từ đó.
- `expires_at` — token có hạn; quá hạn phải xin token mới.
- `consumed` — một token chỉ dùng được 1 lần.

`validate_token` kiểm tra hết (hạn, snapshot khớp bản dịch HIỆN TẠI của nhánh,
chưa dùng, chưa vô hiệu) và trả lý do cụ thể nếu không hợp lệ. Storage giữ tầng
phát hành/lưu/đánh dấu đã dùng; `invalidate` (xoá token chưa dùng của chương+
nhánh) là để khi bản dịch đổi thì token cũ hết hiệu lực ngay, không cần chờ hạn.
"""
from __future__ import annotations

from dataclasses import dataclass

# Hạn dùng mặc định của preview token (giây). Ngắn hơn hạn bản nháp — người dùng
# duyệt rồi áp trong phiên làm việc, không phải 14 ngày.
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60 * 12  # 12 giờ


@dataclass(frozen=True)
class PreviewToken:
    """Snapshot token đã cấp. `base_rev`/`base_text` là tập nội dung đúng tại
    thời điểm cấp — dùng để đối chiếu chính xác với bản hiện tại lúc xác nhận."""
    token: str
    idx: int
    branch: str
    revision_id: int
    base_rev: int
    base_text: str
    expires_at: str = ""
    consumed: bool = False
    created_at: str = ""


class PreviewTokenError(RuntimeError):
    """Token không hợp lệ (hết hạn / đã dùng / snapshot lệch)."""


def validate_token(
    tok: PreviewToken,
    *,
    current_rev: int,
    current_text: str,
    now: float | None = None,
) -> str | None:
    """Trả None nếu token còn dùng được, hoặc thông báo lý do từ chối.

    `current_rev`/`current_text` là trạng thái HIỆN TẠI của nhánh bản dịch mà
    bản nháp sẽ ghi đè — phải khớp tuyệt đối `base_rev`/`base_text` của token.
    """
    import time as _time

    if tok.consumed:
        return "Token đã được dùng."
    if tok.expires_at:
        from novel2epub.revisions import _iso_as_epoch
        if _iso_as_epoch(tok.expires_at) < (now if now is not None else _time.time()):
            return "Token đã hết hạn — xin token mới rồi duyệt lại."
    if current_rev != tok.base_rev or current_text != tok.base_text:
        return "Bản dịch đã thay đổi sau khi cấp token — xin token mới."
    return None
