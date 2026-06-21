"""Điều phối pipeline: crawl -> translate -> build.

Mỗi bước đều dùng cache trên đĩa nên có thể dừng và chạy lại bất cứ lúc nào
mà không crawl/dịch lại những chương đã hoàn tất.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from .config import Config
from .crawler import make_crawler
from .epub_builder import build_epub
from .storage import Chapter, Manifest, Storage
from .toc import mark_duplicate_chapters
from .translator import RateLimited, make_translator

# Kiểu hàm ghi log; mặc định in ra stdout, UI truyền callback riêng để stream.
LogFn = Callable[[str], None]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_with_heartbeat(log: LogFn, prefix: str, fn: Callable[[], object], *, interval: float = 5.0):
    """Chạy fn ở thread phụ, định kỳ log một nhịp 'vẫn đang chạy' để UI biết job còn sống.

    Nhiều bộ dịch (AI CLI) xử lý một chương mất hàng chục giây mà không in gì ra;
    nếu không có nhịp này, người dùng nhìn log đứng yên sẽ tưởng job bị treo hoặc
    đã lỗi. Lỗi phát sinh trong fn được ném lại nguyên vẹn ở thread chính.
    """
    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            result["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - ném lại ở thread chính
            error["error"] = e

    worker = threading.Thread(target=_worker, daemon=True)
    started = time.monotonic()
    worker.start()
    while True:
        worker.join(timeout=interval)
        if not worker.is_alive():
            break
        log(f"{prefix} … vẫn đang dịch ({time.monotonic() - started:.0f}s)")
    if "error" in error:
        raise error["error"]
    return result.get("value")


def _log_chapter_done(log: LogFn, prefix: str, title: str, elapsed: float, translated: str, warnings: list[str]) -> None:
    """Một dòng xác nhận đã dịch xong 1 chương: thời gian + độ dài + cảnh báo chất lượng."""
    msg = f"{prefix} ✓ {title} — {elapsed:.0f}s, {len(translated)} ký tự"
    if warnings:
        msg += f" ⚠ {'; '.join(warnings)}"
    log(msg)


def _clean_title(vi: str) -> str:
    """Chuẩn hóa tiền tố số chương bị LLM bỏ sót dạng Hán (第N章/卷/回).

    Dịch số chương bằng regex cho chắc chắn, không phụ thuộc LLM. Hỗ trợ chữ số
    Ả Rập (第2章) — đủ cho phần lớn site. Các nhãn đặc biệt cũng được Việt hóa.
    """
    vi = vi.strip()
    vi = re.sub(r"第\s*(\d+)\s*章", r"Chương \1", vi)
    vi = re.sub(r"第\s*(\d+)\s*卷", r"Quyển \1", vi)
    vi = re.sub(r"第\s*(\d+)\s*回", r"Hồi \1", vi)
    vi = vi.replace("楔子", "Mở đầu").replace("序章", "Khúc dạo đầu")
    return vi.strip()


def _strip_repeated_title(content: str, ch: Chapter) -> str:
    """Bỏ dòng tiêu đề chương bị lặp ở đầu nội dung.

    Nhiều site (shuhaige...) nhúng lại tiêu đề chương vào đầu vùng #content,
    gây trùng với tiêu đề H1 do epub_builder sinh ra. So khớp sau khi bỏ khoảng
    trắng để tránh lệ thuộc vào dấu cách.
    """
    if not ch.title_zh:
        return content
    norm = lambda s: re.sub(r"\s+", "", s)
    target = norm(ch.title_zh)
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if norm(line) == target or norm(line).startswith(target):
            del lines[i]
            return "\n".join(lines).lstrip("\n")
        break  # chỉ xét dòng có nội dung đầu tiên
    return content


def _chapter_range(chapters: list[Chapter], chapter: int | None, start: int | None, end: int | None):
    if chapter is not None:
        return [c for c in chapters if c.index == chapter]
    selected = chapters
    if start is not None:
        selected = [c for c in selected if c.index >= start]
    if end is not None:
        selected = [c for c in selected if c.index <= end]
    return selected


def _chapter_selection(
    chapters: list[Chapter],
    chapter: int | None,
    start: int | None,
    end: int | None,
    selected_indexes: list[int] | None,
):
    if selected_indexes is not None:
        wanted = set(selected_indexes)
        return [c for c in chapters if c.index in wanted]
    return _chapter_range(chapters, chapter, start, end)


def _apply_default_crawl_limit(cfg: Config, selected: list[Chapter], start: int | None, end: int | None, selected_indexes: list[int] | None) -> list[Chapter]:
    """Limit default crawl runs without truncating the stored TOC."""
    if start is not None or end is not None or selected_indexes is not None:
        return selected
    limit = cfg.crawl.max_chapters
    if limit and limit > 0:
        return selected[:limit]
    return selected


def _build_meta(cfg: Config, ch: Chapter, translated: str, warnings: list[str]) -> dict:
    return {
        "chapter": ch.stem,
        "index": ch.index,
        "title_zh": ch.title_zh,
        "title_vi": ch.title_vi,
        "translator": cfg.translate.type,
        "model": cfg.translate.cli.model,
        "profile": cfg.translate.profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "length_raw": len(translated),
    }


def _quality_warnings(raw: str, translated: str) -> list[str]:
    warnings: list[str] = []
    chinese_chars = sum(1 for ch in translated if "\u4e00" <= ch <= "\u9fff")
    if chinese_chars:
        warnings.append(f"Bản dịch còn {chinese_chars} ký tự Trung")
    if len(translated.strip()) < max(30, len(raw.strip()) // 10 if raw.strip() else 30):
        warnings.append("Bản dịch quá ngắn so với bản gốc")
    if re.search(r"(dưới đây là|bản dịch|sau đây là)", translated, re.IGNORECASE):
        warnings.append("Có dấu hiệu LLM thêm lời mở đầu")
    return warnings


def _refresh_manifest(cfg: Config, storage: Storage, crawler, log: LogFn, *, force_meta: bool = False) -> Manifest:
    """Lấy mục lục mới (nếu được) và trộn vào manifest cache, giữ title_vi cũ.

    Nếu không lấy được mục lục mới mà đã có cache => dùng lại cache. Nếu vừa
    không lấy được vừa chưa có cache => báo lỗi.
    """
    manifest = storage.load_manifest()
    try:
        log(f"[crawl] Đọc mục lục: {cfg.crawl.toc_url}")
        toc = crawler.fetch_toc()

        if manifest is None:
            manifest = Manifest(
                slug=cfg.novel.slug,
                source_url=toc.source_url or cfg.crawl.toc_url,
                title=cfg.novel.title or toc.title,
                author=cfg.novel.author or toc.author,
                description=toc.description,
                cover_url=toc.cover_url,
                metadata_missing=toc.metadata_missing,
                chapters=toc.chapters,
            )
        else:
            manifest.source_url = toc.source_url or manifest.source_url or cfg.crawl.toc_url
            if force_meta or not manifest.title:
                manifest.title = cfg.novel.title or toc.title or manifest.title
            if force_meta or not manifest.author:
                manifest.author = cfg.novel.author or toc.author or manifest.author
            if force_meta or not manifest.description:
                manifest.description = toc.description or manifest.description
            if force_meta or not manifest.cover_url:
                manifest.cover_url = toc.cover_url or manifest.cover_url
            manifest.metadata_missing = toc.metadata_missing

            # Trộn danh sách chương: giữ lại title_vi của các chương đã dịch
            old_chapters_by_url = {ch.url: ch for ch in manifest.chapters}
            merged_chapters = []
            for new_ch in toc.chapters:
                old_ch = old_chapters_by_url.get(new_ch.url)
                if old_ch:
                    new_ch.title_vi = old_ch.title_vi or new_ch.title_vi
                merged_chapters.append(new_ch)
            manifest.chapters = mark_duplicate_chapters(merged_chapters)

        _download_cover(storage, manifest, log)
        storage.save_manifest(manifest)
        log(f"[crawl] Cập nhật mục lục thành công: {len(manifest.chapters)} chương.")
    except Exception as e:
        if manifest is None or not manifest.chapters:
            raise RuntimeError(f"Không thể lấy mục lục và chưa có cache cục bộ: {e}") from e
        log(f"[crawl] Không thể cập nhật mục lục mới ({e}). Sử dụng lại cache mục lục có sẵn: {len(manifest.chapters)} chương.")
    return manifest


def _download_cover(storage: Storage, manifest: Manifest, log: LogFn) -> None:
    """Tải ảnh bìa về (best-effort) nếu có cover_url mà chưa lưu file."""
    if not manifest.cover_url or manifest.cover_file:
        return
    try:
        import requests

        resp = requests.get(manifest.cover_url, timeout=30)
        resp.raise_for_status()
        ext = _cover_ext(manifest.cover_url, resp.headers.get("Content-Type", ""))
        manifest.cover_file = storage.write_cover(resp.content, ext)
        log(f"[crawl] Đã tải ảnh bìa: {manifest.cover_file}")
    except Exception as e:  # noqa: BLE001 - bìa không bắt buộc
        log(f"[crawl]   ! Không tải được ảnh bìa ({e}).")


def _cover_ext(url: str, content_type: str) -> str:
    """Đoán đuôi file ảnh từ Content-Type rồi tới URL, mặc định jpg."""
    ct = (content_type or "").lower()
    for key, ext in (("png", "png"), ("webp", "webp"), ("gif", "gif"), ("jpeg", "jpg"), ("jpg", "jpg")):
        if key in ct:
            return ext
    m = re.search(r"\.(png|webp|gif|jpe?g)(?:\?|$)", url, re.IGNORECASE)
    if m:
        ext = m.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    return "jpg"


def _fetch_chapter_with_retry(crawler, ch: Chapter, retries: int, retry_delay: float, log: LogFn) -> str | None:
    """Tải 1 chương, thử lại tối đa `retries` lần nếu lỗi. Trả None nếu thất bại
    sau khi đã thử hết — để caller bỏ qua chương đó thay vì giết cả job."""
    attempts = max(1, retries + 1)
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _strip_repeated_title(crawler.fetch_chapter(ch), ch)
        except Exception as e:  # noqa: BLE001 - lỗi mạng/parse bất kỳ
            last_err = e
            log(f"[crawl]   ! Lỗi tải chương {ch.stem} (lần {attempt}/{attempts}): {e}")
            if attempt < attempts and retry_delay > 0:
                time.sleep(retry_delay)
    log(f"[crawl]   ! Bỏ qua chương {ch.stem} sau {attempts} lần thử: {last_err}")
    return None


def step_crawl(cfg: Config, log: LogFn = _print) -> Manifest:
    return step_crawl_selected(cfg, log)


def step_crawl_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    start: int | None = None,
    end: int | None = None,
    force: bool = False,
    retries: int = 0,
    retry_delay: float = 2.0,
    selected_indexes: list[int] | None = None,
) -> Manifest:
    """Crawl nội dung chương trong phạm vi [start, end].

    Tùy chọn:
      - force: tải lại cả chương đã có raw (mặc định chỉ tải chương còn thiếu).
      - retries / retry_delay: số lần thử lại + thời gian chờ giữa các lần khi
        một chương tải lỗi; chương lỗi sau khi thử hết sẽ bị bỏ qua, không làm
        gián đoạn cả job.
    """
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    crawler = make_crawler(cfg.crawl)
    try:
        manifest = _refresh_manifest(cfg, storage, crawler, log)

        selected = _chapter_selection(manifest.chapters, None, start, end, selected_indexes)
        selected = _apply_default_crawl_limit(cfg, selected, start, end, selected_indexes)
        if start is not None or end is not None:
            log(f"[crawl] Phạm vi: {len(selected)} chương "
                f"(từ {start or 1} đến {end or len(manifest.chapters)}).")

        total = len(selected)
        crawled = 0
        skipped = 0
        failed = 0
        replaced = 0
        for i, ch in enumerate(selected, 1):
            if storage.has_raw(ch) and not force:
                skipped += 1
                ch.last_action_status = "skipped"
                continue
            had_raw = storage.has_raw(ch)
            log(f"[crawl] ({i}/{total}) {ch.url}")
            content = _fetch_chapter_with_retry(crawler, ch, retries, retry_delay, log)
            if content is None:
                failed += 1
                ch.last_action_status = "failed"
                continue
            if not content.strip():
                log(f"[crawl]   ! Chương {ch.stem} rỗng, bỏ qua.")
            storage.write_raw(ch, content)
            ch.last_action_status = "replaced" if had_raw and force else "completed"
            if had_raw and force:
                replaced += 1
            crawled += 1
            crawler.sleep()
        storage.save_manifest(manifest)
    finally:
        crawler.close()

    log(f"[crawl] Hoàn tất. Đã tải {crawled} chương, bỏ qua {skipped}, lỗi {failed}, ghi đè {replaced}.")
    return manifest


def step_fetch_toc(cfg: Config, log: LogFn = _print, *, force: bool = False) -> Manifest:
    """Chỉ lấy mục lục + metadata (không crawl nội dung chương).

    Dùng để xem nhanh danh sách chương + thông tin truyện trước khi chọn phạm vi
    crawl, hoặc làm mới ảnh bìa/mô tả.
    """
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    crawler = make_crawler(cfg.crawl)
    try:
        manifest = _refresh_manifest(cfg, storage, crawler, log, force_meta=force)
    finally:
        crawler.close()
    log("[crawl] Lấy mục lục xong.")
    return manifest


def _translate_meta_inplace(
    manifest: Manifest, translator, is_noop: bool, log: LogFn, *, force: bool
) -> bool:
    """Dịch title/author/description -> *_vi tại chỗ. Trả True nếu có thay đổi."""
    if is_noop:
        return False
    changed = False
    if manifest.title and (force or not manifest.title_vi):
        title, note = translator.translate_title(manifest.title, kind="tên truyện")
        manifest.title_vi = _clean_title(title)
        manifest.title_note = note
        log(f"[meta] Tên truyện: {manifest.title_vi}")
        if note:
            log(f"[meta]   Giải thích: {note}")
        changed = True
    if manifest.author and (force or not manifest.author_vi):
        manifest.author_vi = translator.translate(manifest.author).strip()
        log(f"[meta] Tác giả: {manifest.author_vi}")
        changed = True
    if manifest.description and (force or not manifest.description_vi):
        manifest.description_vi = translator.translate(manifest.description).strip()
        log("[meta] Đã dịch mô tả truyện.")
        changed = True
    return changed


def step_translate_meta(cfg: Config, log: LogFn = _print, *, force: bool = False) -> Manifest:
    """Dịch metadata truyện (title/author/description) sang tiếng Việt bằng AI CLI."""
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy 'Lấy mục lục' hoặc 'crawl' trước.")

    is_noop = cfg.translate.type.lower() == "none"
    if is_noop:
        log("[meta] translate.type = none — bỏ qua dịch metadata.")
        return manifest

    translator = RateLimited(make_translator(cfg.translate), cfg.translate.delay_seconds)
    if _translate_meta_inplace(manifest, translator, is_noop, log, force=force):
        storage.save_manifest(manifest)
        log("[meta] Hoàn tất.")
    else:
        log("[meta] Không có gì cần dịch (đã có sẵn — dùng 'force' để dịch lại).")
    return manifest


def step_translate(cfg: Config, log: LogFn = _print) -> Manifest:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    translator = RateLimited(make_translator(cfg.translate), cfg.translate.delay_seconds)
    is_noop = cfg.translate.type.lower() == "none"

    # Dịch metadata truyện (nếu chưa có) để EPUB hiển thị title/tác giả tiếng Việt.
    changed = _translate_meta_inplace(manifest, translator, is_noop, log, force=False)

    total = len(manifest.chapters)
    pending = sum(1 for ch in manifest.chapters if storage.has_raw(ch) and not storage.has_translated(ch))
    log(f"[dịch] Bắt đầu: {pending}/{total} chương cần dịch.")
    done = 0
    failed = 0
    for i, ch in enumerate(manifest.chapters, 1):
        if not storage.has_raw(ch):
            log(f"[dịch] ({i}/{total}) chưa có raw cho {ch.stem}, bỏ qua.")
            continue
        if storage.has_translated(ch):
            continue

        raw = storage.read_raw(ch)
        log(f"[dịch] ({i}/{total}) → {ch.title_zh or ch.stem} ({len(raw)} ký tự)")
        started = time.monotonic()

        try:
            # Dịch tiêu đề (nếu có) + nội dung.
            if ch.title_zh and not is_noop:
                title, note = translator.translate_title(ch.title_zh, kind="tên chương")
                ch.title_vi = _clean_title(title)
                ch.title_note = note
                changed = True
            translated = _run_with_heartbeat(log, f"[dịch]   ({i}/{total})", lambda: translator.translate(raw))
        except Exception as e:  # noqa: BLE001 - báo lỗi từng chương thay vì giết cả job
            failed += 1
            ch.last_action_status = "failed"
            log(f"[dịch]   ({i}/{total}) ! Lỗi chương {ch.stem}: {e}")
            if done == 0:
                # Lỗi ngay chương đầu tiên dịch được => gần như chắc do cấu hình/CLI;
                # dừng sớm và báo lỗi rõ thay vì thử lỗi hàng loạt.
                if changed:
                    storage.save_manifest(manifest)
                raise RuntimeError(f"Dịch lỗi ngay chương đầu ({ch.stem}): {e}") from e
            continue

        elapsed = time.monotonic() - started
        storage.write_translated(ch, translated)
        warnings = _quality_warnings(raw, translated)
        storage.write_meta(ch, _build_meta(cfg, ch, translated, warnings))
        done += 1
        _log_chapter_done(log, f"[dịch]   ({i}/{total})", ch.title_vi or ch.title_zh or ch.stem, elapsed, translated, warnings)

    if changed:
        storage.save_manifest(manifest)
    log(f"[dịch] Hoàn tất. Đã dịch {done} chương, lỗi {failed}.")
    return manifest


def step_translate_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    chapter: int | None = None,
    start: int | None = None,
    end: int | None = None,
    force: bool = False,
    missing: bool = False,
    selected_indexes: list[int] | None = None,
) -> Manifest:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    translator = RateLimited(make_translator(cfg.translate), cfg.translate.delay_seconds)
    is_noop = cfg.translate.type.lower() == "none"
    selected = _chapter_selection(manifest.chapters, chapter, start, end, selected_indexes)
    total = len(selected)
    log(f"[dịch] Bắt đầu xử lý {total} chương trong phạm vi đã chọn.")
    changed = False
    translated_count = 0
    skipped = 0
    replaced = 0
    failed = 0
    for i, ch in enumerate(selected, 1):
        if not storage.has_raw(ch):
            log(f"[dịch] ({i}/{total}) chưa có raw cho {ch.stem}, bỏ qua.")
            skipped += 1
            ch.last_action_status = "skipped"
            continue
        had_translated = storage.has_translated(ch)
        if not force and missing and had_translated:
            skipped += 1
            ch.last_action_status = "skipped"
            continue
        if not force and not missing and had_translated:
            skipped += 1
            ch.last_action_status = "skipped"
            continue
        raw = storage.read_raw(ch)
        log(f"[dịch] ({i}/{total}) → {ch.title_zh or ch.stem} ({len(raw)} ký tự)")
        started = time.monotonic()
        try:
            if ch.title_zh and not is_noop:
                title, note = translator.translate_title(ch.title_zh, kind="tên chương")
                ch.title_vi = _clean_title(title)
                ch.title_note = note
                changed = True
            translated = _run_with_heartbeat(log, f"[dịch]   ({i}/{total})", lambda: translator.translate(raw))
        except Exception as e:  # noqa: BLE001 - báo lỗi từng chương thay vì giết cả job
            failed += 1
            ch.last_action_status = "failed"
            log(f"[dịch]   ({i}/{total}) ! Lỗi chương {ch.stem}: {e}")
            if translated_count == 0:
                # Lỗi ngay chương đầu tiên dịch được => gần như chắc do cấu hình/CLI;
                # dừng sớm và báo lỗi rõ thay vì thử lỗi hàng loạt.
                if changed:
                    storage.save_manifest(manifest)
                raise RuntimeError(f"Dịch lỗi ngay chương đầu ({ch.stem}): {e}") from e
            continue
        elapsed = time.monotonic() - started
        storage.write_translated(ch, translated)
        warnings = _quality_warnings(raw, translated)
        storage.write_meta(ch, _build_meta(cfg, ch, translated, warnings))
        ch.last_action_status = "replaced" if had_translated and force else "completed"
        translated_count += 1
        _log_chapter_done(log, f"[dịch]   ({i}/{total})", ch.title_vi or ch.title_zh or ch.stem, elapsed, translated, warnings)
        if had_translated and force:
            replaced += 1
    if changed or translated_count or skipped or failed:
        storage.save_manifest(manifest)
    log(f"[dịch] Hoàn tất. Đã dịch {translated_count} chương, bỏ qua {skipped}, lỗi {failed}, ghi đè {replaced}.")
    return manifest


def step_rewrite_chapters(
    cfg: Config,
    log: LogFn = _print,
    *,
    start: int | None = None,
    end: int | None = None,
) -> Manifest:
    """Biên tập lại (rewrite) các chương đã dịch theo glossary + nguyên tắc 'edit hay'.

    Ghi đè translated/{stem}.md; bản trước khi rewrite được lưu vào meta
    (key 'before_rewrite') để có thể xem lại/khôi phục.
    """
    from . import glossary_ai

    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    glossary = glossary_ai.load_glossary(cfg.translate)
    selected = _chapter_range(manifest.chapters, None, start, end)
    selected = [c for c in selected if storage.has_translated(c)]
    total = len(selected)
    if total == 0:
        log("[rewrite] Không có chương đã dịch nào trong phạm vi đã chọn.")
        return manifest

    for i, ch in enumerate(selected, 1):
        log(f"[rewrite] ({i}/{total}) {ch.title_vi or ch.title_zh or ch.stem}")
        raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
        current = storage.read_translated(ch)
        try:
            rewritten = glossary_ai.rewrite_chapter(cfg.translate, raw, current, glossary)
        except Exception as e:
            log(f"[rewrite]   ! Lỗi chương {ch.stem}: {e}")
            continue
        if not rewritten.strip():
            log(f"[rewrite]   ! Kết quả rỗng, giữ nguyên chương {ch.stem}.")
            continue
        meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
        meta["before_rewrite"] = current
        storage.write_meta(ch, meta)
        storage.write_translated(ch, rewritten)

    log("[rewrite] Hoàn tất.")
    return manifest


def step_evaluate_translation(
    cfg: Config,
    log: LogFn = _print,
    *,
    start: int | None = None,
    end: int | None = None,
) -> dict:
    """Đánh giá glossary + bản dịch của các chương trong phạm vi (chỉ đọc, không sửa).

    Trả về report (dict). Lỗi gọi CLI không raise — report rỗng được log lại.
    """
    from . import glossary_ai

    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    glossary = glossary_ai.load_glossary(cfg.translate)
    selected = _chapter_range(manifest.chapters, None, start, end)
    selected = [c for c in selected if storage.has_translated(c)]
    if not selected:
        log("[đánh giá] Không có chương đã dịch nào trong phạm vi đã chọn.")
        return dict(glossary_ai._EMPTY_REPORT)

    chapters_text = [
        (storage.read_raw(c) if storage.has_raw(c) else "", storage.read_translated(c))
        for c in selected
    ]
    log(f"[đánh giá] Phân tích {len(selected)} chương...")
    report = glossary_ai.evaluate_translation(cfg.translate, chapters_text, glossary)
    log(glossary_ai.format_evaluation_text(report))
    return report


# ---------------------------------------------------------------------------
# AI hỗ trợ NGAY TRONG editor của 1 chương (review / rewrite-preview / suggest).
#
# Khác với các hàm theo phạm vi ở trên (dùng cho trang Glossary), nhóm này thao
# tác đúng 1 chương và lưu kết quả vào meta của chương đó (translation_meta/*.json)
# để editor đọc lại sau khi job nền chạy xong — luồng "AI gợi ý, người review
# quyết định" của docs/rule.md mục III.
# ---------------------------------------------------------------------------


def _require_chapter(cfg: Config, index: int) -> tuple[Storage, "Manifest", "Chapter"]:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise RuntimeError(f"Không tìm thấy chương index={index}.")
    return storage, manifest, ch


def _update_chapter_meta(storage: Storage, ch: "Chapter", **changes) -> dict:
    """Đọc–sửa–ghi meta của 1 chương, chỉ chạm các key được truyền vào.

    Giá trị None nghĩa là xóa key đó khỏi meta (dùng để bỏ preview/review)."""
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    storage.write_meta(ch, meta)
    return meta


def step_review_chapter(cfg: Config, log: LogFn = _print, *, index: int) -> dict:
    """AI review 1 chương (read-only) — lưu báo cáo vào meta['ai_review']."""
    from . import glossary_ai

    storage, _manifest, ch = _require_chapter(cfg, index)
    if not storage.has_translated(ch):
        log("[review] Chương chưa có bản dịch, không có gì để review.")
        return dict(glossary_ai._EMPTY_REPORT)

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch)
    glossary = glossary_ai.load_glossary(cfg.translate)
    log(f"[review] Đang phân tích chương {ch.index}: {ch.title_vi or ch.title_zh or ch.stem}")
    report = glossary_ai.evaluate_translation(cfg.translate, [(raw, translated)], glossary)
    _update_chapter_meta(storage, ch, ai_review={"report": report, "generated_at": _now_iso()})
    log(glossary_ai.format_evaluation_text(report))
    log("[review] Hoàn tất. Mở lại trang chương để xem báo cáo.")
    return report


def step_suggest_chapter(cfg: Config, log: LogFn = _print, *, index: int) -> list[dict]:
    """AI gợi ý glossary cho 1 chương — lưu vào meta['ai_suggestions']."""
    from . import glossary_ai

    storage, _manifest, ch = _require_chapter(cfg, index)
    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    existing = glossary_ai.load_glossary(cfg.translate)
    log(f"[gợi ý] Đang phân tích chương {ch.index}: {ch.title_vi or ch.title_zh or ch.stem}")
    suggestions = glossary_ai.suggest_glossary(cfg.translate, [(raw, translated)], existing)
    _update_chapter_meta(storage, ch, ai_suggestions=suggestions)
    log(f"[gợi ý] Hoàn tất. {len(suggestions)} đề xuất. Mở lại trang chương để chọn áp dụng.")
    return suggestions


def step_rewrite_preview(cfg: Config, log: LogFn = _print, *, index: int) -> str:
    """AI biên tập lại 1 chương nhưng KHÔNG ghi đè — lưu bản nháp vào
    meta['ai_rewrite'] để người review xem diff rồi quyết định áp dụng."""
    from . import glossary_ai

    storage, _manifest, ch = _require_chapter(cfg, index)
    if not storage.has_translated(ch):
        log("[rewrite] Chương chưa có bản dịch, không có gì để biên tập.")
        return ""

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    current = storage.read_translated(ch)
    glossary = glossary_ai.load_glossary(cfg.translate)
    log(f"[rewrite] Đang biên tập lại chương {ch.index}: {ch.title_vi or ch.title_zh or ch.stem}")
    rewritten = glossary_ai.rewrite_chapter(cfg.translate, raw, current, glossary)
    if not rewritten.strip():
        log("[rewrite] AI trả về rỗng — giữ nguyên, không tạo bản nháp.")
        return ""
    _update_chapter_meta(storage, ch, ai_rewrite={"text": rewritten, "generated_at": _now_iso()})
    log("[rewrite] Đã tạo bản nháp. Mở lại trang chương để xem diff và áp dụng.")
    return rewritten


def step_build(cfg: Config, log: LogFn = _print) -> str:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    chapters_html = []
    for ch in manifest.chapters:
        if storage.has_translated(ch):
            md = storage.read_translated(ch)
            title = ch.title_vi or ch.title_zh or f"Chương {ch.index}"
        elif storage.has_raw(ch):
            md = storage.read_raw(ch)
            title = ch.title_zh or f"Chương {ch.index}"
        else:
            continue
        chapters_html.append((ch, title, md))

    if not chapters_html:
        raise RuntimeError("Không có chương nào để build. Hãy crawl/dịch trước.")

    cover_path = storage.cover_fs_path(manifest)
    out = build_epub(
        manifest, chapters_html, cfg.epub_path, cfg.novel.language, cover_path=cover_path
    )
    log(f"[build] Đã tạo EPUB: {out}  ({len(chapters_html)} chương)")
    return str(out)


def run_all(cfg: Config, log: LogFn = _print) -> str:
    step_crawl(cfg, log)
    step_translate(cfg, log)
    return step_build(cfg, log)
