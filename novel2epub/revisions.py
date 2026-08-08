"""Khối/box bản nháp AI cho bản dịch — "candidate revisions" của workflow biên tập.

Vấn đề cũ: bản nháp AI (rewrite) được nhét vào `meta_json["ai_rewrite"]` như một
dict nội tuyến, không có vòng đời riêng — không hết hạn, không ghi snapshot gốc,
không ghi số phiên bản mà nó sinh ra, và mọi engine rewrite trong prompt đều nhận
`raw_text` mà không nói rõ nó có cần hay không.

Module này định nghĩa:

1. **Hộp bản nháp tập trung** — bảng `ai_revisions` lưu mỗi bản nháp AI như một
   hàng: engine nào sinh, trạng thái (candidate chưa kích hoạt / đã áp / bỏ /
   hết hạn), snapshot gốc (`base_rev` + `base_translated_text`), hạn dùng, và cờ
   `had_raw` cho biết engine đó có được cấp `raw_text` hay không.

2. **Nguyên tắc "xác nhận mới thành bản dịch"** — `create_revision` và
   `check_still_valid` tách hẳn "sinh bản nháp" khỏi "đưa lên bản dịch đang hoạt
   động". Bản nháp KHÔNG tự áp dụng; có lời "chấp nhận" của người dùng mới được
   ghi đè.

3. **Không rò rỉ raw vào AI edit** — registry engine khai `allows_raw`; engine
   `rewrite`/`han-cleanup` KHÔNG được quyền bê `raw_text` vào prompt. Pipeline
   tước raw trước khi gọi AI và ghi lại `had_raw` để audit.

4. **Snapshot có hạn + đúng tập** — mỗi candidate giữ `base_translated_text` và
   `base_rev` đúng thời điểm sinh. Lúc áp dụng, bản dịch hoạt động phải khớp
   `base_rev` (optimistic lock) thì mới ghi; không khớp hoặc hết hạn → từ chối,
   tuyệt đối không ghi đè mù.

5. **Workspace hoạt động** — build/EPUB chỉ đọc `translated_text` (bản "hoạt
   động"); bản nháp candidate KHÔNG bao giờ đi vào EPUB.

6. **Engine độc lập** — registry `ENGINES` tách biệt loại đối tượng mỗi engine
   tạo ra (`candidate` áp lên bản dịch vs `report`/`suggestion` chỉ đọc), và cờ
   `allows_raw`. Review dùng raw (đối chiếu), rewrite bản dịch thì không.

Logic ở đây là THUẦN (không import Storage, không I/O) để test độc lập; Storage
chỉ là ổ cắm/ổ đĩa lưu trạng thái của các hàm này.
"""
from __future__ import annotations

import json

from dataclasses import dataclass

# Hạn dùng mặc định của một bản nháp AI (giây). Quá hạn coi như stale: không còn
# được áp dụng nữa, cần tạo bản nháp mới từ bản dịch hiện tại.
DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 ngày

# Trạng thái một bản nháp. `pending` = candidate chưa kích hoạt (mặc định);
# `applied` = đã ghi vào bản dịch hoạt động; `discarded` = người dùng bỏ;
# `expired` = quá hạn.
STATUS_PENDING = "pending"
STATUS_APPLIED = "applied"
STATUS_DISCARDED = "discarded"
STATUS_EXPIRED = "expired"

# Nhánh bản dịch độc lập của một chương. `ai` = ai_translation (bản dịch AI
# truyền thống — cột `translated_text`); `local_mt` = Local NMT (cột
# `local_mt_*`). Mỗi nhánh có title/workspace/revision/edit RIÊNG; bản dịch
# của nhánh đang hoạt động (`chapters.active_branch`) là thứ đi vào EPUB.
BRANCH_AI = "ai"
BRANCH_LOCAL_MT = "local_mt"
BRANCHES = (BRANCH_AI, BRANCH_LOCAL_MT)
_BRANCH_LABELS = {BRANCH_AI: "AI", BRANCH_LOCAL_MT: "Local MT"}


def normalize_branch(value: str | None) -> str:
    """Chuẩn hoá giá trị branch; không hợp lệ thì fallback về `ai`."""
    if value in BRANCHES:
        return value
    return BRANCH_AI


def branch_label(branch: str) -> str:
    return _BRANCH_LABELS.get(normalize_branch(branch), branch)

# Loại engine trong registry.
KIND_CANDIDATE = "candidate"        # sinh bản nháp có thể áp lên bản dịch
KIND_REPORT = "report"              # read-only: trả báo cáo (review)
KIND_SUGGESTION = "suggestion"      # read-only: trả đề xuất (glossary)
_APPLICABLE_KINDS = frozenset({KIND_CANDIDATE})


@dataclass(frozen=True)
class Engine:
    """Một engine AI độc lập trong workflow.

    - `kind`: loại đối tượng engine tạo ra.
    - `allows_raw`: engine có được phép đưa `raw_text` vào prompt không? Bản
      rewrite bản dịch (rewrite/han-cleanup) thuộc nhóm **không** — đưa raw vào
      prompt khiến AI viết lại theo bản gốc thay vì "biên tập bản dịch", và đem
      raw tới AI edit là rò rỉ vùng ranh giới mong muốn.
    - `applies_to_translated`: kết quả có thể ghi vào `translated_text` (chỉ
      `candidate` mới có; `report`/`suggestion` thì không).
    """
    kind: str
    allows_raw: bool
    applies_to_translation: bool


class EngineRegistry:
    """Đăng ký tập engine; quyết định "engine nào áp được + ai được raw" tập
    trung một chỗ để pipeline/route không phải nhò lại prompt thành nội dung."""

    def __init__(self) -> None:
        self._engines: dict[str, Engine] = {}

    def register(self, name: str, *, kind: str, allows_raw: bool,
                 applies_to_translation: bool | None = None) -> None:
        if applies_to_translation is None:
            applies_to_translation = kind in _APPLICABLE_KINDS
        self._engines[name] = Engine(kind, allows_raw, applies_to_translation)

    def get(self, name: str) -> Engine:
        if name not in self._engines:
            raise KeyError(f"engine không được đăng ký: {name!r}")
        return self._engines[name]

    def exists(self, name: str) -> bool:
        return name in self._engines

    def applies_to_translation(self, name: str) -> bool:
        return self._engines.get(name).applies_to_translation if name in self._engines else False

    def allows_raw(self, name: str) -> bool:
        return self._engines.get(name).allows_raw if name in self._engines else False

    def names(self) -> list[str]:
        return list(self._engines)

    def __contains__(self, name: str) -> bool:
        return name in self._engines


ENGINES = EngineRegistry()
ENGINES.register("rewrite", kind=KIND_CANDIDATE, allows_raw=False)
ENGINES.register("han-cleanup", kind=KIND_CANDIDATE, allows_raw=False)
ENGINES.register("translate", kind=KIND_CANDIDATE, allows_raw=True)
ENGINES.register("fix", kind=KIND_CANDIDATE, allows_raw=False)
ENGINES.register("review", kind=KIND_REPORT, allows_raw=True)
ENGINES.register("suggest", kind=KIND_SUGGESTION, allows_raw=True)


class RevisionError(RuntimeError):
    """Lỗi luồng locked: bản nháp hết hạn, hoặc bản dịch đã đổi khỏi snapshot."""


@dataclass
class RevisionCandidate:
    """Snapshot một bản nháp AI tại thời điểm sinh (pure data, không I/O).

    `payload` là bản dịch mới (engine candidate), hoặc JSON định dạng báo cáo/
    đề xuất (engine report/suggestion). `base_rev` + `base_translated_text` là
    "exact base set" để optimistic lock.
    """
    engine: str
    idx: int
    payload: str
    base_rev: int
    base_translated_text: str = ""
    has_raw: bool = False
    status: str = STATUS_PENDING
    created_at: str = ""
    expires_at: str = ""
    branch: str = BRANCH_AI


def _now() -> "datetime":
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _iso_as_epoch(value: str) -> float:
    from datetime import datetime, timezone
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _expires_at(ttl_seconds: int) -> str:
    from datetime import timedelta
    return (_now() + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _status_vi(status: str) -> str:
    return {"applied": "áp dụng", "discarded": "bỏ", "expired": "hết hạn"}.get(status, status)


def _is_expired(cand: "RevisionCandidate") -> bool:
    if not cand.expires_at:
        return False
    import time
    return _iso_as_epoch(cand.expires_at) < time.time()


def create_revision(
    *,
    engine: str,
    idx: int,
    payload: str,
    base_translated_text: str,
    base_rev: int,
    has_raw: bool,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    branch: str = BRANCH_AI,
) -> RevisionCandidate:
    """Tạo bản nháp MỚI — trạng thái mặc định `pending` (KHÔNG tự áp dụng).

    `base_rev` + `base_translated_text` là snapshot chính xác của bản dịch hoạt
    động lúc sinh, dùng làm "exact base set" khi apply (optimistic lock).
    """
    if not ENGINES.exists(engine):
        raise ValueError(f"engine không được đăng ký: {engine!r}")
    return RevisionCandidate(
        engine=engine,
        idx=idx,
        payload=payload,
        base_rev=base_rev,
        base_translated_text=base_translated_text,
        has_raw=has_raw,
        status=STATUS_PENDING,
        created_at=utc_now_iso(),
        expires_at=_expires_at(ttl_seconds),
        branch=normalize_branch(branch),
    )


def check_still_valid(
    cand: RevisionCandidate, *, current_rev: int, current_translated_text: str
) -> str | None:
    """Trả None nếu còn áp được, hoặc thông báo lý do từ chối.

    Các lý do từ chối: bản nháp không còn `pending`, hết hạn, hoặc bản dịch hoạt
    động đã đổi khỏi snapshot (`base_rev`/`base_translated_text` lệch).
    """
    if cand.status != STATUS_PENDING:
        return f"Bản nháp đã {_status_vi(cand.status)}."
    if _is_expired(cand):
        return "Bản nháp đã hết hạn — tạo lại từ bản dịch hiện tại."
    if current_rev != cand.base_rev or current_translated_text != cand.base_translated_text:
        return "Bản dịch đã thay đổi sau khi tạo bản nháp — tải lại trang."
    return None


def to_row(cand: RevisionCandidate) -> tuple:
    """Chuẩn hoá một candidate thành row SQLite cho `ai_revisions`."""
    return (
        cand.engine,
        cand.idx,
        cand.branch,
        cand.status,
        cand.base_rev,
        cand.base_translated_text,
        cand.payload,
        int(cand.has_raw),
        cand.created_at,
        cand.expires_at,
    )


def from_row(row) -> RevisionCandidate:
    """Chuyển một dòng `ai_revisions` (sqlite3.Row) về dataclass."""
    return RevisionCandidate(
        engine=row["engine"],
        idx=row["idx"],
        payload=row["payload_json"] or "",
        base_rev=row["base_rev"],
        base_translated_text=row["base_translated_text"] or "",
        has_raw=bool(row["has_raw"]),
        status=row["status"],
        created_at=row["created_at"] or "",
        expires_at=row["expires_at"] or "",
        branch=normalize_branch(row["branch"] if "branch" in row.keys() else BRANCH_AI),
    )


def json_payload(data) -> str:
    return json.dumps(data, ensure_ascii=False)