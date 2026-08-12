"""Hợp đồng bulk-preview / bulk-confirm cho hành động hàng loạt chương.

Tách logic thuần (đánh giá đủ điều kiện, vân tay config, kế hoạch) khỏi route —
cùng lối `reader_sync.py`/`revisions.py`: không import Storage phức tạp, chỉ
nhận đối tượng `storage` và `manifest` từ bên gọi.

Hợp đồng:
- `POST /chapters/bulk-preview`: KHÔNG đổi trạng thái, không gọi model. Trả
  token có hạn chứa snapshot đánh giá (từng chương đủ điều kiện/lý do từ chối,
  vân tay workspace mỗi chương, vân tay config) để UI hiển thị trước khi xác
  nhận.
- `POST /chapters/bulk-confirm`: nhận token, xác thực (chưa dùng, chưa hết hạn,
  config còn khớp, workspace từng chương còn khớp) rồi mới thực thi. Lệch →
  409 + phải preview lại.

`translate`/`local-mt`/`build`/`ai-edit-draft` là action dài → confirm đẩy job
nền; `switch-branch`/`skip`/`unskip`/`delete-translation` là thao tác nhanh →
confirm chạy đồng bộ.
"""
from __future__ import annotations

import hashlib
import json

# Action hỗ trợ trong hợp đồng bulk. `build` dùng strict (chặn chương chưa có
# bản dịch), `ai-edit-draft` chỉ biên tập bản dịch Local NMT.
BULK_ACTIONS: tuple[str, ...] = (
    "translate", "local-mt", "ai-edit-draft", "switch-branch",
    "skip", "unskip", "delete-translation", "build",
)

# Action chạy nền qua job (dài), còn lại chạy đồng bộ trong confirm.
JOB_ACTIONS: frozenset[str] = frozenset({"translate", "local-mt", "ai-edit-draft", "build"})

# Hạn dùng mặc định token bulk preview (giây).
BULK_TOKEN_TTL_SECONDS = 60 * 30


def chapter_eligibility(
    storage, ch, *, action: str, branch: str = "", force: bool = False
) -> tuple[bool, str]:
    """Chương `ch` có thực thi được action không? Trả `(ok, reason)` — KHÔNG đổi
    trạng thái, không gọi model."""
    from . import revisions

    if action in ("skip", "unskip"):
        return (ch.skipped != (action == "skip")), "Không cần đổi (đã đúng trạng thái)."
    if action == "switch-branch":
        if branch not in revisions.BRANCHES:
            return False, f"Nhánh không hợp lệ: {branch!r}."
        return (storage.active_branch(ch) != branch), "Đã ở nhánh này."
    if action == "delete-translation":
        return storage.has_any_translation_data(ch), "Chương chưa có bản dịch nào để xóa."
    if action == "ai-edit-draft":
        if not storage.has_branch_text(ch, revisions.BRANCH_LOCAL_MT):
            return False, "Chưa có bản dịch Local MT — bỏ qua (không gọi AI)."
        return True, ""
    if action in ("translate", "local-mt"):
        target_branch = revisions.BRANCH_LOCAL_MT if action == "local-mt" else revisions.normalize_branch(branch)
        if not storage.has_raw(ch):
            return False, "Chưa crawl nội dung gốc của chương — TOC/tiêu đề không phải nội dung để dịch."
        if not force and storage.has_branch_text(ch, target_branch):
            return False, "Đã có bản dịch ở nhánh này (bật force để dịch lại)."
        return True, ""
    if action == "build":
        active = storage.active_branch(ch)
        if not storage.has_branch_text(ch, active):
            return False, f"Nhánh '{revisions.branch_label(active)}' chưa có bản dịch."
        return True, ""
    return False, f"Action không hợp lệ: {action!r}."


def chapter_fingerprint(storage, ch, *, action: str, branch: str = "") -> dict:
    """Vân tay workspace chương phụ thuộc action — dùng để phát hiện thay đổi
    giữa preview và confirm (đổi giữa chừng → 409, phải preview lại). Gồm cả
    `content_hash` của bản dịch nhánh liên quan (vì `write_translated` không
    tự bump revision) + revision (bump tay) để bắt mọi đường sửa."""
    from . import revisions

    if action in ("translate", "local-mt"):
        target_branch = revisions.BRANCH_LOCAL_MT if action == "local-mt" else revisions.normalize_branch(branch)
        text = storage.read_branch_text(ch, target_branch) if storage.has_branch_text(ch, target_branch) else ""
        return {
            "index": ch.index, "branch": target_branch,
            "revision": storage.read_branch_revision(ch, target_branch),
            "content_hash": _text_hash(text),
            "raw_hash": _text_hash(storage.read_raw(ch) if storage.has_raw(ch) else ""),
        }
    if action == "ai-edit-draft":
        text = storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT) if storage.has_branch_text(ch, revisions.BRANCH_LOCAL_MT) else ""
        return {
            "index": ch.index, "branch": revisions.BRANCH_LOCAL_MT,
            "revision": storage.read_branch_revision(ch, revisions.BRANCH_LOCAL_MT),
            "content_hash": _text_hash(text),
        }
    if action in ("switch-branch", "build"):
        active = storage.active_branch(ch)
        text = storage.read_branch_text(ch, active) if storage.has_branch_text(ch, active) else ""
        return {
            "index": ch.index, "branch": active,
            "revision": storage.read_branch_revision(ch, active),
            "content_hash": _text_hash(text),
        }
    if action in ("skip", "unskip", "delete-translation"):
        return {"index": ch.index, "skipped": ch.skipped}
    return {"index": ch.index}


def preview_plan(
    storage,
    manifest,
    *,
    action: str,
    indexes: list[int],
    branch: str = "",
    force: bool = False,
) -> dict:
    """Đánh giá không đụng chạm cho danh sách chương. Trả
    `{action, branch, force, total, eligible, blocked, chapters, estimates}`.
    `chapters[i]` = `{index, title, ok, reason, fingerprint}`."""
    from . import revisions

    chapters = list(manifest.chapters)
    wanted = set(int(i) for i in indexes)
    items: list[dict] = []
    for ch in chapters:
        if ch.index not in wanted:
            continue
        ok, reason = chapter_eligibility(storage, ch, action=action, branch=branch, force=force)
        fingerprint = chapter_fingerprint(storage, ch, action=action, branch=branch)
        input_chars = 0
        if action == "ai-edit-draft":
            input_chars = len(storage.read_branch_text(ch, revisions.BRANCH_LOCAL_MT)) if ok else 0
        elif action == "translate":
            input_chars = len(storage.read_raw(ch)) if ok else 0
        input_tokens = (input_chars + 3) // 4
        output_tokens = max(0, int(input_tokens * 1.15))
        items.append({
            "index": ch.index,
            "title": ch.title or f"Chương {ch.index}",
            "ok": ok,
            "reason": reason,
            "fingerprint": fingerprint,
            "estimate": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                # Giá phụ thuộc provider/model; 0 nghĩa chưa cấu hình bảng giá,
                # không đoán chi phí và không gọi model trong preview.
                "cost_usd": 0.0,
            },
        })
    eligible = [i for i in items if i["ok"]]
    blocked = [i for i in items if not i["ok"]]
    return {
        "action": action,
        "branch": branch,
        "force": bool(force),
        "total": len(items),
        "eligible": len(eligible),
        "blocked": len(blocked),
        "chapters": items,
        "estimates": {
            "eligible": len(eligible),
            "blocked": len(blocked),
            "blocked_indexes": [i["index"] for i in blocked],
            "input_tokens": sum(i["estimate"]["input_tokens"] for i in eligible),
            "output_tokens": sum(i["estimate"]["output_tokens"] for i in eligible),
            "cost_usd": sum(i["estimate"]["cost_usd"] for i in eligible),
            "per_chapter": [
                {"index": i["index"], **i["estimate"]} for i in eligible
            ],
        },
    }


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def config_fingerprint(cfg) -> str:
    """Vân tay cấu hình dịch/AI ảnh hưởng kết quả action — đổi config giữa
    preview và confirm → token mất hiệu lực (409, phải preview lại)."""
    translate = getattr(cfg, "translate", None)
    ai = getattr(cfg, "ai", None)
    t = {
        "translate.type": getattr(translate, "type", ""),
        "translate.model": getattr(translate, "model", ""),
        "translate.genre": getattr(translate, "genre", ""),
        "translate.profile": getattr(translate, "profile", ""),
    }
    if ai is not None:
        openai = getattr(ai, "openai", None)
        if openai is not None:
            t["ai.openai.model"] = getattr(openai, "model", "")
            t["ai.openai.base_url"] = getattr(openai, "base_url", "")
            t["ai.openai.engine"] = getattr(openai, "engine", "")
    payload = json.dumps(t, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def verify_fingerprints(plan: dict, storage, manifest) -> list[int]:
    """Rà lại vân tay workspace từng chương sau preview; trả list index bị đổi
    (phải 409 + preview lại)."""
    by_index = {c.index: c for c in manifest.chapters}
    changed: list[int] = []
    for item in plan.get("chapters", []):
        ch = by_index.get(item["index"])
        if ch is None:
            changed.append(item["index"])
            continue
        current = chapter_fingerprint(storage, ch, action=plan.get("action", ""), branch=plan.get("branch", ""))
        if current != item.get("fingerprint"):
            changed.append(item["index"])
    return changed
