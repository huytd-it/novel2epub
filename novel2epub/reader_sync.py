"""Logic thuần cho việc đẩy chương lên app đọc novel-reader (Supabase).

Tách khỏi `reader_client.py` (HTTP) và `pipeline.py` (I/O + job) để test được
không cần mạng lẫn DB — cùng lối với `bulk_transfer.py`.

Hai việc chính:

- `md_to_plaintext`: `translated_text` của ta là Markdown, còn
  `chapter_contents.content` bên Reader là plain text có ngắt đoạn.
- `classify_chapters`: phân loại MỚI / SỬA / KHÔNG ĐỔI để chỉ đẩy phần thay
  đổi, và quan trọng hơn là để **giữ nguyên `chapters.id`** bên Reader (đường
  ingest sẵn có của repo đó xoá sạch chapters rồi insert lại, làm hỏng
  bookmark/tiến độ đọc trỏ theo `chapter_id`).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import footnotes

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n")


def md_to_plaintext(md: str) -> str:
    """Markdown (đơn giản) -> plain text có ngắt đoạn bằng dòng trống.

    Cùng cách tách khối với `epub_builder._md_to_xhtml_body`, khác ở đầu ra:

    - Heading ĐẦU TIÊN bị bỏ — nó trùng với cột `title` bên Reader, giữ lại
      thì tiêu đề hiện hai lần.
    - Heading còn lại: bỏ dấu `#`, giữ nguyên chữ.
    - Marker footnote (ký tự PUA) bị xoá — Reader không có UI footnote.
    """
    return md_to_plaintext_with_anchors(md)[0]


def md_to_plaintext_with_anchors(md: str) -> tuple[str, list[int]]:
    """`(plaintext, anchors)` — thêm neo để sửa ngược từ app đọc về Xưởng.

    `anchors[j]` = chỉ số trong `notes.split_paras(md)` của **dòng thứ j** của
    plaintext. Dòng ở đây là dòng không rỗng, đếm xuyên suốt cả chương, KHÔNG
    phải block cách nhau bằng dòng trống:

        content.split("\\n")  (bỏ dòng rỗng)  ->  1:1 với anchors

    Vì sao đơn vị là DÒNG chứ không phải block: `notes.replace_para` — hàm duy
    nhất ghi bản sửa — thao tác theo dòng. Nếu một đoạn hiển thị bên Reader gộp
    hai dòng nguồn thì lúc editor viết lại đoạn đó, không có cách nào tách kết
    quả về đúng hai dòng. Đơn vị sửa và đơn vị lưu BẮT BUỘC 1:1, nếu không thì
    bản sửa không đi ngược về được.

    Dòng trống trong `plaintext` vẫn giữ nguyên vị trí, nên thông tin "hai dòng
    này thuộc cùng một đoạn" (lời dẫn + lời thoại) không mất — Reader dựa vào
    đó để render sát nhau, y như `<br/>` trong EPUB.

    Hai chỗ neo KHÔNG phải ánh xạ đồng nhất, và đó là lý do mảng này tồn tại:

    - Heading ĐẦU TIÊN bị bỏ khỏi plaintext (trùng cột `title` bên Reader)
      nhưng vẫn chiếm một chỗ trong `split_paras` -> mọi neo sau đó lệch 1.
    - Heading còn lại mất dấu `#` nên `plaintext[j] != split_paras[anchors[j]]`;
      neo trỏ đúng DÒNG, không hứa hẹn hai chuỗi bằng nhau.
    """
    blocks: list[str] = []
    anchors: list[int] = []
    src = 0  # chỉ số split_paras của dòng nguồn kế tiếp chưa tiêu thụ
    for raw_block in _BLOCK_SPLIT_RE.split(md.strip()):
        block = raw_block.strip()
        if not block:
            continue
        # `_HEADING_RE` neo `^...$` không bật MULTILINE nên chỉ khớp block MỘT
        # dòng — block nhiều dòng mở đầu bằng `#` rơi xuống nhánh dưới (xem
        # commit ae3279d "heading chỉ khớp block một dòng để neo không lệch").
        heading = _HEADING_RE.match(block)
        if heading:
            if not blocks:
                # Heading mở đầu = tiêu đề chương, đã có cột `title` riêng.
                # Bỏ khỏi đầu ra nhưng VẪN tiêu thụ một dòng nguồn — quên dòng
                # này là toàn bộ chương lệch một bậc.
                src += 1
                continue
            blocks.append(heading.group(1).strip())
            anchors.append(src)
            src += 1
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        blocks.append("\n".join(lines))
        for _ in lines:
            anchors.append(src)
            src += 1
    return footnotes.strip_markers("\n\n".join(blocks)).strip(), anchors


def content_hash(title: str, content: str) -> str:
    """Vân tay của ĐÚNG payload sẽ gửi lên Reader (tiêu đề + nội dung).

    Dùng hash chứ không dùng `chapters.translated_updated_at`: cột đó ghi bằng
    `unixepoch('now')` nên chỉ có độ phân giải 1 giây — sửa trong cùng giây với
    lần đẩy sẽ không bị phát hiện. Gộp cả `title` để sửa mỗi tiêu đề cũng tính
    là thay đổi.
    """
    payload = f"{title}\n{content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


@dataclass
class ChapterPush:
    """Một chương cần đẩy, đã tính sẵn payload."""
    index: int
    title: str
    content: str
    hash: str
    remote_id: str = ""  # rỗng với chương MỚI — điền sau khi upsert trả về id
    # Neo đoạn: anchors[j] = chỉ số split_paras của dòng thứ j trong `content`.
    # Phải đi CÙNG transaction với `content` — neo của bản cũ áp lên bản mới là
    # sai lệch âm thầm.
    anchors: list[int] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.content.split())


@dataclass
class PublishPlan:
    new: list[ChapterPush] = field(default_factory=list)
    edited: list[ChapterPush] = field(default_factory=list)
    unchanged: int = 0
    skipped: int = 0

    @property
    def total_changed(self) -> int:
        return len(self.new) + len(self.edited)

    def counts(self) -> dict[str, int]:
        return {
            "new": len(self.new),
            "edited": len(self.edited),
            "unchanged": self.unchanged,
            "skipped": self.skipped,
        }


def reader_meta(meta: dict) -> dict:
    """Khối trạng thái đẩy trong `chapters.meta_json` — `{"reader": {...}}`."""
    value = meta.get("reader")
    return value if isinstance(value, dict) else {}


def classify_chapters(
    items: list[tuple[int, str, str, dict]],
    remote_ids: dict[int, str],
) -> PublishPlan:
    """Chia chương thành MỚI / SỬA / KHÔNG ĐỔI.

    `items`: `(index, title, translated_markdown, meta)` của các chương ĐÃ
    dịch xong và không bị skip — việc lọc đó do bên gọi làm (pipeline) vì cần
    `Storage`. `remote_ids`: map `index -> chapters.id` đang có trên Reader.

    Hoà giải với remote (không chỉ tin state local) để tự phục hồi:

    - Local ghi đã đẩy nhưng remote KHÔNG có -> coi là MỚI. Đây là trường hợp
      Reader từng bị `ingest-epub.ts`/`admin-import` xoá sạch chapters.
    - Local chưa từng đẩy nhưng remote ĐÃ có -> nhận `id` đó và coi là SỬA,
      tránh tạo trùng (`unique(book_id, index)` sẽ chặn, nhưng nhận id thì
      state local mới đúng).
    """
    plan = PublishPlan()
    for index, title, md, meta in items:
        content, anchors = md_to_plaintext_with_anchors(md)
        if not content:
            plan.skipped += 1
            continue
        digest = content_hash(title, content)
        state = reader_meta(meta)
        remote_id = remote_ids.get(index, "")
        push = ChapterPush(
            index=index, title=title, content=content, hash=digest,
            remote_id=remote_id, anchors=anchors,
        )
        if not remote_id:
            plan.new.append(push)
        elif state.get("hash") != digest or state.get("remote_id") != remote_id:
            plan.edited.append(push)
        else:
            plan.unchanged += 1
    return plan


def is_free(index: int, free_chapters: int) -> bool:
    """`free_chapters` chương ĐẦU (theo index của manifest) đọc miễn phí."""
    return index <= free_chapters
