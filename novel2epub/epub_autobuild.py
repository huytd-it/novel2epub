"""Quyết định ebook nào cần build lại EPUB cho catalog OPDS — logic THUẦN.

Không I/O, không DB, không FastAPI: tách theo đúng lối `opds.py` và
`api_auth.py` của GĐ1 nên test được mà không cần dựng file EPUB thật.

Ngữ cảnh: catalog OPDS chỉ liệt kê ebook ĐÃ có file EPUB, và trước đây file
đó phải build tay. Module này là phần "nghĩ" của việc tự động build — phần
"làm" nằm ở `app/routes/opds.py` (gom trạng thái, đẩy job) và
`pipeline.step_build_selected(translated_only=True)` (build thật).
"""
from __future__ import annotations

from dataclasses import dataclass

# Lý do một ebook được / không được build lại. Đi thẳng vào log job để người
# dùng nhìn /logs là hiểu vì sao sách của mình chưa xuất hiện trong catalog.
MISSING = "missing"            # chưa từng build EPUB
STALE = "stale"                # có bản dịch mới hơn file EPUB
FRESH = "fresh"                # EPUB đã là mới nhất
UNTRANSLATED = "untranslated"  # chưa có chương nào dịch xong

# `chapters.translated_updated_at` được ghi bằng `unixepoch('now')` nên chỉ có
# độ phân giải 1 GIÂY, trong khi mtime của file EPUB là float chính xác tới
# micro giây. Sửa bản dịch lúc 10:00:05.9 (lưu thành 5.0) rồi build xong lúc
# 10:00:05.2 (mtime 5.2) sẽ khiến so sánh trần trụi kết luận "EPUB mới hơn" —
# bản sửa vĩnh viễn không lên EPUB.
#
# Nới 1 giây để lệch đó luôn nghiêng về phía build THỪA thay vì build THIẾU.
# Cái giá: đúng một lần build lại dư ngay sau khi dịch, vì lần sau mtime đã
# vượt qua mốc nới. `reader_sync.content_hash` gặp đúng vấn đề độ phân giải
# này và chọn hash; ở đây hash cả cuốn 2907 chương mỗi request OPDS thì đắt
# hơn nhiều so với một lần build dư.
_RESOLUTION_SLACK_SECONDS = 1.0


@dataclass(frozen=True)
class BuildState:
    """Ảnh chụp một ebook, đủ để quyết định có build lại hay không."""

    slug: str
    translated_count: int
    latest_translated_at: float  # max(chapters.translated_updated_at), 0 nếu chưa có
    epub_mtime: float | None  # None = file EPUB chưa tồn tại


def decide(state: BuildState) -> str:
    """MISSING / STALE / FRESH / UNTRANSLATED cho một ebook."""
    if state.translated_count <= 0:
        return UNTRANSLATED
    if state.epub_mtime is None:
        return MISSING
    if state.latest_translated_at + _RESOLUTION_SLACK_SECONDS > state.epub_mtime:
        return STALE
    return FRESH


def needs_build(state: BuildState) -> bool:
    return decide(state) in (MISSING, STALE)


def pending_builds(states: list[BuildState]) -> list[BuildState]:
    """Các ebook cần build lại, giữ nguyên thứ tự đầu vào.

    Ebook chưa từng build đứng trước ebook chỉ cũ: sách vắng mặt hẳn khỏi
    catalog phiền hơn sách hiện ra với nội dung cũ vài phút.
    """
    missing = [s for s in states if decide(s) == MISSING]
    stale = [s for s in states if decide(s) == STALE]
    return missing + stale


def due_for_trigger(last_trigger_at: float, now: float, cooldown_seconds: float) -> bool:
    """Đã qua thời gian nghỉ giữa hai lần kích hoạt cho cùng một ebook chưa.

    readest hỏi lại catalog rất thường xuyên; không có mốc nghỉ này thì mỗi
    lần kéo-để-làm-mới lại đẻ thêm một job build cho cùng cuốn sách.
    """
    if last_trigger_at <= 0:
        return True
    if now < last_trigger_at:
        # Đồng hồ hệ thống bị chỉnh lùi — coi như đã hết hạn nghỉ, thà build
        # dư còn hơn khoá cứng việc build tới tận khi đồng hồ đuổi kịp.
        return True
    return now - last_trigger_at >= cooldown_seconds
