"""Baseline migration cho ledger hai chiều — snapshot nguyên trạng từng nhánh.

Vấn đề: `chapter_revisions` (v13) lưu lịch sử nội dung theo nhánh để sau này
"dựng lại trạng thái" và đối chiếu với bản hiện hành, nhưng toàn bộ chương
đã dịch từ TRƯỚC v13 không có revision nào. Bước này tạo baseline cho chúng.

`initialize_branch_revisions` là HÀM RÕ RÀNG (callable migration/domain), chạy
thủ công — không tự chạy âm thầm lúc khởi động (5000+ chương, nén zlib + hash
canonical từng cái). Idempotent: chạy lại không sinh trùng revision/operation,
có thể dừng giữa chừng rồi chạy tiếp (resumable).

Những gì baseline KHÔNG làm (an toàn tuyệt đối):

- Không sửa `chapters.translated_text`, `local_mt_text`, revision, tiêu đề,
  `active_branch` hay bất kỳ cột dữ liệu hiện hành nào.
- Baseline dùng ĐÚNG `chapters.revision` (nhánh `ai`) / `chapters.local_mt_revision`
  (nhánh `local_mt`) làm `revision_number` — snapshot "tại revision hiện hành"
  theo đúng hợp đồng sản phẩm. Không đổi revision hiện hành.
- Chỉ tạo baseline cho nhánh CHƯA CÓ revision nào. Nếu history đã chiếm
  `revision_number` đó (vd chương đã được pipeline hai chiều ghi từ trước),
  baseline KHÔNG ghi đè — bỏ qua.
- Không xoá/ghi đè revision hay operation đã tồn tại.

Quy ước canonical (xem `canonical_chapter_payload`):

    `{len_bytes(title)}:{title}{len_bytes(text)}:{text}`   (bytes UTF-8)

Title và text KHÔNG được trim, KHÔNG đổi ký tự xuống dòng, không thay đổi ký
tự nào. Độ dài đo bằng BYTE của chuỗi UTF-8 (không phải code point) nên
representation độc lập ngôn ngữ/lập trình: bất kỳ ngôn ngữ nào đọc cũng tách
được đúng ranh giới title/text. Toàn bộ canonical là bytes; hash SHA-256 tính
trên chính canonical bytes đó. Content nén bằng `zlib.compress` (mức mặc định)
với encoding `zlib`.

Idempotency theo ebook: `client_operation_id` là UNIQUE TOÀN DB, nên baseline
của mỗi ebook phải có id riêng chứa slug (tránh hai ebook cùng id làm trùng
UNIQUE toàn cục) — `baseline_client_operation_id(slug)`.
"""
from __future__ import annotations

import hashlib
import sqlite3
import zlib
from typing import Iterable

from .db import get_thread_connection
from .revisions import BRANCH_LOCAL_MT, BRANCHES, normalize_branch

# Kind của operation baseline — thao tác migration tạo mốc gốc cho nhánh.
KIND_MIGRATION_BASELINE = "migration_baseline"

# Encoding chuẩn của `content_blob`. Tách hằng để không gõ sai chuỗi ma thuật.
ENCODING_ZLIB = "zlib"

# Tiền tố cố định cho `client_operation_id` của baseline. Id đầy đủ = tiền tố
# này + slug ebook, vì `chapter_operations.client_operation_id` là UNIQUE trên
# TOÀN DB (không theo ebook) — một hằng số chung sẽ đụng nhau giữa các ebook.
_BACKFILL_CLIENT_OPERATION_PREFIX = "chapter-revisions-backfill-v1:"

# Phân tách hai trường trong canonical — ký tự `:` không xuất hiện trong số độ
# dài (chỉ chữ số) nên không bao giờ gây mơ hồ khi parse.
_CANONICAL_SEP = ":"


def baseline_client_operation_id(slug: str) -> str:
    """`client_operation_id` ổn định của baseline cho một ebook.

    Gồm cả slug để idempotency không đụng nhau giữa các ebook (UNIQUE toàn
    DB). Slug bản thân là chuỗi ngắn, không có vấn đề độ dài; không cần hash —
    nhìn thẳng slug dễ gỡ rối hơn."""
    return f"{_BACKFILL_CLIENT_OPERATION_PREFIX}{slug}"


def canonical_chapter_payload(title: str, text: str) -> bytes:
    """Canonical bytes của (title, text) — độc lập ngôn ngữ.

    KHÔNG trim/normalize, giữ nguyên từng ký tự và ký tự xuống dòng. Độ dài đo
    bằng BYTE UTF-8 (`len(title.encode())`) chứ không phải code point, và hai
    số được phân tách bằng `:` — representation duy nhất cho một (title, text),
    parse được trong bất kỳ ngôn ngữ nào. Hash SHA-256 chạy trên chính bytes
    này."""
    t_bytes = title.encode("utf-8")
    x_bytes = text.encode("utf-8")
    return (
        str(len(t_bytes)).encode("ascii")
        + _CANONICAL_SEP.encode("ascii")
        + t_bytes
        + str(len(x_bytes)).encode("ascii")
        + _CANONICAL_SEP.encode("ascii")
        + x_bytes
    )


def full_content_hash(title: str, text: str) -> str:
    """Full SHA-256 (64 ký tự hex) của canonical `title` + `text`.

    Bất biến sản phẩm: hash PHẢI đủ 64 ký tự (không cắt gọn như
    `reader_sync.content_hash` — đó là hash của plaintext đã qua `md_to_plaintext`,
    không phải bản dịch nguyên trạng)."""
    return hashlib.sha256(canonical_chapter_payload(title, text)).hexdigest()


def compress_content(text: str) -> bytes:
    """Nén văn bản thành `content_blob` (encoding `zlib`)."""
    return zlib.compress(text.encode("utf-8"))


def decompress_content(blob: bytes) -> str:
    """Giải nén `content_blob` về văn bản gốc."""
    return zlib.decompress(blob).decode("utf-8")


def branch_text_columns(branch: str) -> tuple[str, str, str]:
    """Cột (title, text) tương ứng của nhánh trong bảng `chapters`."""
    branch = normalize_branch(branch)
    if branch == BRANCH_LOCAL_MT:
        return "local_mt_title", "local_mt_text"
    return "title", "translated_text"


def branch_revision_column(branch: str) -> str:
    """Cột revision hiện hành của nhánh trong bảng `chapters`."""
    branch = normalize_branch(branch)
    if branch == BRANCH_LOCAL_MT:
        return "local_mt_revision"
    return "revision"


def branch_hash_column(branch: str) -> str:
    """Cột hash "bản hiện hành" của nhánh trong bảng `chapters`."""
    branch = normalize_branch(branch)
    if branch == BRANCH_LOCAL_MT:
        return "local_mt_content_hash"
    return "ai_content_hash"


def initialize_branch_revisions(
    storage,
    *,
    branches: Iterable[str] | None = None,
    message: str = "Backfill baseline từ dữ liệu hiện hành (v13)",
    actor_issuer: str = "",
    actor_subject: str = "",
) -> dict:
    """Tạo baseline cho mọi nhánh ĐÃ KHỞI TẠO của mọi chương trong ebook.

    "Đã khởi tạo" = cột text của nhánh KHÔNG NULL (chuỗi rỗng vẫn tính — chỉ
    NULL mới coi là chưa). Baseline snapshot đúng title+text hiện tại (nén
    zlib + hash canonical full SHA-256) với `revision_number` = ĐÚNG revision
    hiện hành của nhánh (`chapters.revision` / `local_mt_revision`),
    `parent_revision_id=NULL`, `base_content_hash=''`.

    An toàn:

    - Canonicalize/hash/compress toàn bộ candidate trước khi lấy write lock.
    - MỘT `BEGIN IMMEDIATE` transaction ngắn để xác minh exact source set rồi
      ghi operation/revisions/current hashes; lỗi giữa chừng rollback sạch.
    - Idempotent: chạy lại chỉ bỏ qua nhánh ĐÃ CÓ baseline (nhận diện qua
      operation kind `migration_baseline` + `base_content_hash=''` + parent
      NULL — KHÔNG dựa vào revision_number). Không duplicate; tái dùng cho
      "resume sau crash".
    - KHÔNG ghi đè: nếu một (chương, nhánh) đã có bất kỳ revision nào trong
      `chapter_revisions` (dù là baseline hay history ghi sau), bỏ qua — cột
      UNIQUE (ebook, index, branch, revision_number) chỉ bảo vệ khỏi trùng,
      còn điều kiện "chưa có history" đảm bảo không nuốt nhánh đã được ghi.
    - Không đổi bất kỳ cột dữ liệu hiện hành nào (text/revision/title/
      active_branch); chỉ điền `chapters.ai_content_hash`/`local_mt_content_hash`
      (cột mới, thuộc ledger này, default '').
    - Một operation `migration_baseline` cho toàn ebook — revision con tham
      chiếu qua `operation_id`; `client_operation_id` gồm slug ebook nên
      idempotent RIÊNG theo từng ebook (UNIQUE toàn DB).

    Trả dict thống kê: `{"branches": [...], "revisions": N, "chapters": N,
    "operations": N}` với `chapters` = SỐ chương KHÁC NHAU bị ảnh hưởng
    (không phải index cuối)."""
    branches = _normalize_branches(branches)
    if not branches:
        return {"branches": [], "revisions": 0, "chapters": 0, "operations": 0}

    conn = get_thread_connection(storage._db_path)
    slug = storage.slug

    # Phase 1 — đọc/canonicalize/hash/compress TRƯỚC write lock. Chỉ branch chưa
    # có history mới là candidate; transaction sẽ đọc lại và xác minh exact set.
    existing = {
        (int(row["chapter_index"]), row["branch"])
        for row in conn.execute(
            "SELECT DISTINCT chapter_index, branch FROM chapter_revisions WHERE ebook_slug=?",
            (slug,),
        )
    }
    prepared = []
    for idx, title, text, branch, rev_number in _iter_initialized_branches(conn, slug, branches):
        if (idx, branch) in existing:
            continue
        prepared.append(
            {
                "index": idx,
                "title": title,
                "text": text,
                "branch": branch,
                "revision": rev_number,
                "blob": compress_content(text),
                "hash": full_content_hash(title, text),
            }
        )

    # Không có revision cần tạo thì không được sinh operation rỗng. Đây cũng là
    # fast path idempotent; tuyệt đối không lấy write lock.
    if not prepared:
        return {"branches": [], "revisions": 0, "chapters": 0, "operations": 0}

    created = 0
    operation_created = False
    affected_indexes: set[int] = set()
    per_branch: dict[str, int] = {}
    try:
        _begin_immediate(conn)

        # Phase 2 — dưới lock, candidate phải còn đúng title/text/revision và
        # vẫn chưa có history. Bất kỳ drift nào rollback TOÀN batch.
        for item in prepared:
            title_col, text_col = branch_text_columns(item["branch"])
            rev_col = branch_revision_column(item["branch"])
            current = conn.execute(
                f"SELECT {title_col} AS title, {text_col} AS text, {rev_col} AS rev "
                "FROM chapters WHERE ebook_slug=? AND idx=?",
                (slug, item["index"]),
            ).fetchone()
            history = conn.execute(
                "SELECT 1 FROM chapter_revisions WHERE ebook_slug=? AND chapter_index=? "
                "AND branch=? LIMIT 1",
                (slug, item["index"], item["branch"]),
            ).fetchone()
            if (
                current is None
                or current["text"] is None
                or (current["title"] or "") != item["title"]
                or (current["text"] or "") != item["text"]
                or int(current["rev"] or 1) != item["revision"]
                or history is not None
            ):
                raise RuntimeError(
                    f"baseline source changed: chapter={item['index']} branch={item['branch']}"
                )

        operation_created = _ensure_backfill_operation(
            conn, slug, message, actor_issuer, actor_subject
        )
        operation_id = _find_backfill_operation_id(conn, slug)
        for item in prepared:
            conn.execute(
                """
                INSERT INTO chapter_revisions (
                    operation_id, ebook_slug, chapter_index, branch,
                    revision_number, parent_revision_id, title, content_blob,
                    content_encoding, content_hash, base_content_hash
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, '')
                """,
                (
                    operation_id, slug, item["index"], item["branch"],
                    item["revision"], item["title"], item["blob"],
                    ENCODING_ZLIB, item["hash"],
                ),
            )
            hash_col = branch_hash_column(item["branch"])
            current_rev_col = branch_revision_column(item["branch"])
            cur = conn.execute(
                f"UPDATE chapters SET {hash_col}=? WHERE ebook_slug=? AND idx=? "
                f"AND {current_rev_col}=?",
                (item["hash"], slug, item["index"], item["revision"]),
            )
            if cur.rowcount != 1:
                raise RuntimeError("baseline current hash CAS failed")
            created += 1
            affected_indexes.add(item["index"])
            per_branch[item["branch"]] = per_branch.get(item["branch"], 0) + 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "branches": sorted(per_branch),
        "revisions": created,
        "chapters": len(affected_indexes),
        "operations": 1 if operation_created else 0,
    }


def _normalize_branches(branches: Iterable[str] | None) -> tuple[str, ...]:
    if branches is None:
        return BRANCHES
    normalized = tuple(normalize_branch(b) for b in branches)
    seen: list[str] = []
    for b in normalized:
        if b not in seen:
            seen.append(b)
    return tuple(seen)


def _find_backfill_operation_id(conn: sqlite3.Connection, slug: str) -> int:
    row = conn.execute(
        "SELECT id FROM chapter_operations WHERE ebook_slug=? AND client_operation_id=?",
        (slug, baseline_client_operation_id(slug)),
    ).fetchone()
    if row is None:
        raise RuntimeError("baseline operation chưa được tạo trong transaction")
    return int(row["id"])


def _begin_immediate(conn: sqlite3.Connection) -> None:
    """Tách helper để test xác minh lock chỉ lấy sau phase precompute."""
    conn.execute("BEGIN IMMEDIATE")


def baseline_request_hash(slug: str) -> str:
    """Hash ổn định của logical baseline operation cho một ebook.

    Operation có thể được resume theo branch ở nhiều lần chạy, nên request hash
    đại diện intent toàn ebook thay vì danh sách candidate của riêng một batch.
    """
    return hashlib.sha256(f"chapter-revisions-backfill-v1:{slug}".encode("utf-8")).hexdigest()


def _ensure_backfill_operation(
    conn: sqlite3.Connection,
    slug: str,
    message: str,
    actor_issuer: str,
    actor_subject: str,
) -> bool:
    cur = conn.execute(
        """
        INSERT INTO chapter_operations (
            ebook_slug, kind, message, actor_issuer, actor_subject,
            client_operation_id, request_hash, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_operation_id) DO NOTHING
        """,
        (
            slug,
            KIND_MIGRATION_BASELINE,
            message,
            actor_issuer,
            actor_subject,
            baseline_client_operation_id(slug),
            baseline_request_hash(slug),
            "{}",
        ),
    )
    existing = conn.execute(
        "SELECT ebook_slug, kind, request_hash FROM chapter_operations "
        "WHERE client_operation_id=?",
        (baseline_client_operation_id(slug),),
    ).fetchone()
    if (
        existing is None
        or existing["ebook_slug"] != slug
        or existing["kind"] != KIND_MIGRATION_BASELINE
        or existing["request_hash"] != baseline_request_hash(slug)
    ):
        raise RuntimeError("baseline idempotency operation không khớp logical request")
    return cur.rowcount == 1


def _iter_initialized_branches(
    conn: sqlite3.Connection, slug: str, branches: tuple[str, ...]
):
    """Duyệt chương có text nhánh KHÔNG NULL (rỗng vẫn tính — chỉ NULL là chưa).

    Trả `(idx, title, text, branch, revision_number)` với `revision_number` =
    revision hiện hành của ĐÚNG nhánh đó (`chapters.revision` / `local_mt_revision`)."""
    for branch in branches:
        title_col, text_col = branch_text_columns(branch)
        rev_col = branch_revision_column(branch)
        for row in conn.execute(
            f"SELECT idx, {title_col} AS title, {text_col} AS text, "
            f"{rev_col} AS rev FROM chapters WHERE ebook_slug=? "
            f"AND {text_col} IS NOT NULL ORDER BY idx",
            (slug,),
        ):
            yield (
                int(row["idx"]),
                row["title"] or "",
                row["text"] or "",
                branch,
                int(row["rev"] or 1),
            )
