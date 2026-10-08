"""SQLite projection of current content warnings; rules live in build_validation.

No chapter text is duplicated here. All writes participate in the caller's
transaction, so a failed canonical commit cannot publish a newer warning state.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import time
import hashlib

from . import build_validation as validation
from .chapter_versions import full_content_hash

PREFIX = "content_validation:chapter:"
BOOK_KEY = "content_validation:book"
VERSION = 2


def rules_signature():
    payload = {"version": VERSION, "contract": validation.validation_contract(),
               "checks": [(c.code, c.pattern.pattern, c.pattern.flags, c.min_hits, sorted(c.ignore)) for c in validation.CONTENT_CHECKS],
               "thresholds": [validation.MIN_CHAPTER_WORDS, validation.SHORT_CHAPTER_WORDS]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@contextmanager
def transaction(storage):
    owned = not storage.conn.in_transaction
    if owned:
        storage.conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        if owned:
            storage.conn.commit()
    except Exception:
        if owned:
            storage.conn.rollback()
        raise


def _write(storage, key, value):
    storage.conn.execute(
        "INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, ?, ?) "
        "ON CONFLICT(ebook_slug, key) DO UPDATE SET data_json=excluded.data_json",
        (storage.slug, key, json.dumps(value, ensure_ascii=False)),
    )


def _stamps(storage):
    return {r["idx"]: r["translated_updated_at"] for r in storage.conn.execute(
        "SELECT idx, translated_updated_at FROM chapter_ui_state WHERE ebook_slug=?", (storage.slug,)
    )}


def _chapter(storage, ch, publication, stamp):
    report = validation.chapter_validation_report(ch, storage, publication)
    report.update(checked_at=time.time(), validator_version=VERSION, rules_signature=rules_signature(), stamp=stamp,
                  source={"branch": publication.branch, "revision": publication.revision,
                          "hash": full_content_hash(publication.title, publication.text)} if publication else None,
                  manifest_title=ch.title, skipped=ch.skipped, duplicate_of=ch.duplicate_of)
    if publication is None and not ch.skipped:
        report["error"] = "Chưa có bản AI/Local MT hoàn chỉnh; chưa rà được nội dung."
    return report


def _book(storage, chapters, versions):
    rows = [{"index": ch.index, "title": versions[ch.index].title if versions.get(ch.index) else ch.title,
             "text": versions[ch.index].text if versions.get(ch.index) else "", "skipped": ch.skipped} for ch in chapters if not ch.skipped]
    report = validation.validate_book(rows)
    report.update(checked_at=time.time(), validator_version=VERSION)
    _write(storage, BOOK_KEY, report)


def _issue_brief(issue) -> str:
    code = issue.get("code", "?")
    message = issue.get("message", "")
    para = issue.get("paraIndex", -1)
    suffix = f" · đoạn {para + 1}" if isinstance(para, int) and para >= 0 else ""
    return f"{code}: {message}{suffix}"


def refresh_book(storage, log=lambda _: None):
    """Explicit scan / Build preview: persist every chapter row.

    Mỗi chương được rà + ghi trong phạm vi lỗi riêng: một chương hỏng không
    rollback toàn bộ lần quét (trước đây một exception giữa chừng là DB giữ
    nguyên như chưa hề rà). Mọi vấn đề phát hiện được log NGAY khi thấy để
    nhật kí job cho biết chương nào lỗi gì mà không cần mở báo cáo.
    """
    manifest = storage.load_manifest()
    chapters = manifest.chapters if manifest else []
    versions, stamps = storage.bulk_publication_versions(), _stamps(storage)
    total = len(chapters)
    log(f"[validation] Bắt đầu rà {total} chương...")
    counts: dict[str, int] = {}
    chapters_with_issues = 0
    failed: list[int] = []
    for pos, ch in enumerate(chapters):
        if ch.skipped:
            with transaction(storage):
                storage.conn.execute("DELETE FROM ebook_extra_json WHERE ebook_slug=? AND key=?", (storage.slug, PREFIX + str(ch.index)))
            continue
        try:
            report = _chapter(storage, ch, versions.get(ch.index), stamps.get(ch.index))
        except Exception as exc:  # noqa: BLE001 - chương hỏng không được chặn các chương còn lại
            failed.append(ch.index)
            log(f"[validation] Chương {ch.index}: không rà được ({exc}); giữ kết quả cũ, tiếp tục chương khác.")
            continue
        try:
            with transaction(storage):
                _write(storage, PREFIX + str(ch.index), report)
        except Exception as exc:  # noqa: BLE001 - chỉ mất dòng của chương này
            failed.append(ch.index)
            log(f"[validation] Chương {ch.index}: không lưu được lỗi ({exc}).")
            continue
        if report.get("error"):
            log(f"[validation] Chương {ch.index} ({report.get('title') or ch.title}): {report['error']}")
        for issue in report.get("issues", []):
            code = issue.get("code", "?")
            counts[code] = counts.get(code, 0) + 1
            log(f"[validation] Chương {ch.index}: {_issue_brief(issue)}")
        if report.get("issues"):
            chapters_with_issues += 1
        if (pos + 1) % 100 == 0:
            log(f"[validation] Đã rà {pos + 1}/{total} chương...")
    log("[validation] Kiểm tra trùng nội dung/số chương...")
    try:
        with transaction(storage):
            _book(storage, chapters, versions)
    except Exception as exc:  # noqa: BLE001 - vẫn giữ lỗi từng chương đã lưu
        log(f"[validation] Không kiểm tra được trùng/số chương ({exc}).")
    try:
        book_issues = (storage.read_extra_json(BOOK_KEY) or {}).get("issues", [])
    except Exception:
        book_issues = []
    for issue in book_issues:
        code = issue.get("code", "?")
        counts[code] = counts.get(code, 0) + 1
        log(f"[validation] Toàn sách: {code}: {issue.get('message', '')}")
    result = saved_report(storage)
    summary = "; ".join(f"{code}={n}" for code, n in sorted(counts.items()))
    log(f"[validation] Đã lưu lỗi {result['checked']} chương vào SQLite"
        + (f" ({chapters_with_issues} chương có lỗi: {summary})" if summary else " (không phát hiện lỗi)")
        + (f"; {len(failed)} chương rà lỗi: {failed}" if failed else "")
        + "; dùng chung kiểm tra Build EPUB.")
    return result


def refresh_chapter(storage, index):
    """Re-check only the changed chapter; recompute cross-chapter relations."""
    with transaction(storage):
        manifest = storage.load_manifest()
        chapters = manifest.chapters if manifest else []
        ch = next((ch for ch in chapters if ch.index == index), None)
        if ch is None:
            return
        versions = storage.bulk_publication_versions()
        if ch.skipped:
            storage.conn.execute("DELETE FROM ebook_extra_json WHERE ebook_slug=? AND key=?", (storage.slug, PREFIX + str(index)))
        else:
            stamp = _stamps(storage).get(index)
            _write(storage, PREFIX + str(index), _chapter(storage, ch, versions.get(index), stamp))
        # No re-parsing of other chapters. This also clears duplicate/number
        # warnings on peers after a chapter's text/title changes.
        _book(storage, chapters, versions)


def saved_report(storage):
    owned = not storage.conn.in_transaction
    if owned:
        storage.conn.execute("BEGIN")
    try:
        result = _saved_report(storage)
        if owned:
            storage.conn.commit()
        return result
    except Exception:
        if owned:
            storage.conn.rollback()
        raise


def _saved_report(storage):
    """Read diagnostics only; overview does not load chapter text or run checks."""
    manifest = storage.load_manifest()
    chapters = manifest.chapters if manifest else []
    stamps = _stamps(storage)
    cached = {int(row["key"][len(PREFIX):]): json.loads(row["data_json"]) for row in storage.conn.execute(
        "SELECT key, data_json FROM ebook_extra_json WHERE ebook_slug=? AND key LIKE ?", (storage.slug, PREFIX + "%")
    )}
    book = storage.read_extra_json(BOOK_KEY) or {}
    eligible = {ch.index for ch in chapters if not ch.skipped}
    grouped = {}
    for issue in book.get("issues", []):
        if not {issue["index"], *issue.get("related_indexes", [])}.issubset(eligible):
            continue
        for index in {issue["index"], *issue.get("related_indexes", [])}:
            grouped.setdefault(index, []).append({**issue, "paraIndex": -1, "start": 0, "end": 0, "snippet": ""})
    rows = []
    signature = rules_signature()
    for ch in chapters:
        if ch.skipped:
            continue
        report = cached.get(ch.index)
        if report is None or report.get("skipped"):
            continue
        stale = (report.get("validator_version") != VERSION or report.get("rules_signature") != signature or report.get("stamp") != stamps.get(ch.index)
                 or report.get("manifest_title") != ch.title or report.get("skipped") != ch.skipped
                 or report.get("duplicate_of") != ch.duplicate_of)
        merged = {**report, "issues": report["issues"] + grouped.get(ch.index, []), "stale": stale}
        validation.decorate_issues(merged["issues"])
        rows.append(merged)
    return {"scan": True, "persisted": True, "checked": len(rows), "total": len(eligible),
            "skipped": len(chapters) - len(eligible), "unchecked": len(eligible) - len(rows), "checked_at": book.get("checked_at"), "chapters": rows}
