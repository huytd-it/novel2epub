"""Điều phối pipeline: crawl -> translate -> build.

Mỗi bước đều dùng cache trên đĩa nên có thể dừng và chạy lại bất cứ lúc nào
mà không crawl/dịch lại những chương đã hoàn tất.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from .config import Config, CrawlRetryConfig
from .crawl_throttle import AdaptiveConcurrency, DomainRateLimiter
from .crawler import ScraplingCrawler, is_rate_limited
from .epub_builder import build_epub
from .storage import Chapter, Manifest, Storage
from .toc import mark_duplicate_chapters
from .translator import RateLimited, make_translator
from . import han_cleanup

# Kiểu hàm ghi log; mặc định in ra stdout, UI truyền callback riêng để stream.
LogFn = Callable[[str], None]
CancelFn = Callable[[], bool]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_config_warnings(cfg: Config, log: LogFn) -> None:
    """In cảnh báo xung đột config (preset đè type, selector sai engine...).

    Để trên web UI thấy được nguyên nhân thật khi job lỗi, thay vì chỉ nằm
    trong logging nội bộ không ai xem (xem Config.warnings trong config.py).
    """
    for w in cfg.warnings:
        log(f"[config] CẢNH BÁO: {w}")


def _fmt(value: object, empty: str = "(trống)") -> str:
    """Hiển thị giá trị config gọn gàng: rỗng -> nhãn, bool -> on/off."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None or value == "" or value == 0:
        return empty
    return str(value)


def _emit_crawl_config(cfg: Config, log: LogFn) -> None:
    """Echo config thực sự dùng cho tính năng CRAWL."""
    c = cfg.crawl
    s = c.scrapling
    log(f"[config] CRAWL dùng: scrapling.mode={s.mode} "
        f"| toc_url={_fmt(c.toc_url)} "
        f"| content_selector={_fmt(c.content_selector, '(auto OG/body)')} "
        f"| chapter_link_pattern={c.chapter_link_pattern} "
        f"| max_chapters={_fmt(c.max_chapters, '∞')} | delay={c.delay_seconds}s "
        f"| max_workers={c.max_workers}")
    if c.next_page_selector or c.next_page_url_pattern:
        rule = c.next_page_selector or f"url~{c.next_page_url_pattern}"
        log(f"[config] CRAWL pagination: {rule} (tối đa {c.max_pages_per_chapter} trang/chương)")
    else:
        log("[config] CRAWL pagination: off")
    if s.mode == "stealthy" and s.solve_cloudflare:
        log("[config] CRAWL scrapling: stealth + solve_cloudflare")
    if s.mode == "fetcher" and s.impersonate:
        log(f"[config] CRAWL scrapling: fetcher impersonate={s.impersonate}")
    if c.ai_fallback:
        log(f"[config] CRAWL AI fallback: ON (≤{c.ai_fallback_max_html} ký tự HTML gửi AI)")
    else:
        log("[config] CRAWL AI fallback: off")
    r = c.retry
    if r.attempts > 0:
        log(f"[config] CRAWL retry (429/anti-bot): {r.attempts} lần | chờ {r.delay_seconds}s "
            f"×{r.backoff} (trần {r.max_delay_seconds}s) | respect_retry_after={_fmt(r.respect_retry_after)}")
    else:
        log("[config] CRAWL retry (429/anti-bot): off (attempts=0)")


def _emit_translate_config(cfg: Config, log: LogFn, *, feature: str = "DỊCH") -> None:
    """Echo config thực sự dùng cho các tính năng gọi AI dịch/biên tập
    (dịch chương, dịch metadata, review/suggest/rewrite/đánh giá)."""
    t = cfg.translate
    log(f"[config] {feature} dùng: type={t.type} | preset={_fmt(t.preset, '(không)')} "
        f"| profile={t.profile} | delay={t.delay_seconds}s | max_workers={t.max_workers}")
    if t.type.lower() == "openai":
        log(f"[config] {feature} OpenAI-Compatible: base_url={t.openai.base_url!r} "
            f"| model={_fmt(t.openai.model, '(chưa cấu hình)')} "
            f"| timeout={t.openai.timeout_seconds}s")
    elif t.type.lower() == "none":
        log(f"[config] {feature}: type=none — KHÔNG gọi AI, giữ nguyên bản gốc.")
    s = t.style
    log(f"[config] {feature} style: tone={s.tone!r} | pronoun_policy={s.pronoun_policy} "
        f"| han_viet_level={s.han_viet_level} | title_mode={s.title_mode} "
        f"| keep_paragraphs={_fmt(s.keep_paragraphs)}")
    chunk = (f"max_chars={t.chunk.max_chars}, overlap={t.chunk.overlap_paragraphs} đoạn"
             if t.chunk.max_chars else "off (dịch nguyên chương)")
    log(f"[config] {feature} chunk: {chunk} | retry: {t.retry.attempts} lần "
        f"(chờ {t.retry.delay_seconds}s)")
    log(f"[config] {feature} glossary: names={_fmt(t.glossary_files.names)} "
        f"| vietphrase={_fmt(t.glossary_files.vietphrase)}")
    if t.type.lower() in ("hachimimt", "moxhimt"):
        m = t.hachimimt
        log(f"[config] {feature} hachimimt: model_key={m.model_key} | beam={m.beam_size} "
            f"| backend={m.backend} | chunk_mode={m.chunk_mode}")


def _emit_build_config(cfg: Config, log: LogFn) -> None:
    """Echo config thực sự dùng cho tính năng BUILD EPUB."""
    log(f"[config] BUILD dùng: epub_path={cfg.epub_path} | language={cfg.novel.language} "
        f"| slug={cfg.novel.slug} | data_dir={cfg.output.data_dir}")


def _run_with_heartbeat(log: LogFn, prefix: str, fn: Callable[[], object], *, interval: float = 5.0):
    """Chạy fn ở thread phụ, định kỳ log một nhịp 'vẫn đang chạy' để UI biết job còn sống.

    Nhiều bộ dịch (AI) xử lý một chương mất hàng chục giây mà không in gì ra;
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
    if not ch.title:
        return content
    norm = lambda s: re.sub(r"\s+", "", s)
    target = norm(ch.title)
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
    selected = _chapter_range(chapters, chapter, start, end)
    return [c for c in selected if not c.skipped]


def _apply_default_crawl_limit(cfg: Config, selected: list[Chapter], start: int | None, end: int | None, selected_indexes: list[int] | None) -> list[Chapter]:
    """Limit default crawl runs without truncating the stored TOC."""
    if start is not None or end is not None or selected_indexes is not None:
        return selected
    limit = cfg.crawl.max_chapters
    if limit and limit > 0:
        return selected[:limit]
    return selected


def _resolve_translator_model(cfg: Config) -> str:
    """Tên model/backend thực sự dùng để dịch, gắn với translator type hiện tại.

    - openai: trả về model id thật (vd opencode-go/kimi-k2.6)
    - hachimimt/moxhimt: trả về hachimimt.model_key (vd HachimiMT-60)
    - libretranslate: trả về tên + base_url nếu có
    - google: "google-translate"
    - none: "noop"
    """
    t = (cfg.translate.type or "").lower()
    if t == "openai":
        return cfg.translate.openai.model
    if t in ("hachimimt", "moxhimt"):
        return cfg.translate.hachimimt.model_key
    if t == "libretranslate":
        base = cfg.translate.libretranslate.base_url or ""
        return f"libretranslate@{base}" if base else "libretranslate"
    if t == "google":
        return "google-translate"
    if t == "none":
        return "noop"
    return t or "unknown"


def _build_meta(cfg: Config, ch: Chapter, translated: str, warnings: list[str]) -> dict:
    return {
        "chapter": ch.stem,
        "index": ch.index,
        "title": ch.title,
        "translator": cfg.translate.type,
        "model": _resolve_translator_model(cfg),
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
    """Lấy mục lục mới (nếu được) và trộn vào manifest cache, giữ title cũ.

    Nếu không lấy được mục lục mới mà đã có cache => dùng lại cache. Nếu vừa
    không lấy được vừa chưa có cache => báo lỗi.
    """
    manifest = storage.load_manifest()
    try:
        log(f"[crawl] Đọc mục lục: {cfg.crawl.toc_url}")
        toc = crawler.fetch_toc()

        # TOC rỗng gần như chắc chắn là fetch hỏng "êm" (anti-bot trả 200,
        # site đổi cấu trúc HTML, chapter_link_pattern hết khớp...) — coi như
        # lỗi để rơi xuống nhánh dùng cache, tránh ghi đè manifest đang có.
        if not toc.chapters:
            raise RuntimeError(
                "Mục lục trả về 0 chương (trang có thể bị chặn hoặc đã đổi cấu trúc)"
            )

        if manifest is None:
            manifest = Manifest(
                slug=cfg.novel.slug,
                source_url=toc.source_url or cfg.crawl.toc_url,
                title=cfg.novel.title or toc.title,
                author=cfg.novel.author or toc.author,
                description=toc.description,
                cover_url=cfg.novel.cover_url or toc.cover_url,
                metadata_missing=toc.metadata_missing,
                chapters=toc.chapters,
            )
        else:
            manifest.source_url = toc.source_url or manifest.source_url or cfg.crawl.toc_url
            if force_meta or not manifest.title:
                manifest.title = cfg.novel.title or manifest.title
            if force_meta or not manifest.author:
                manifest.author = cfg.novel.author or manifest.author
            if force_meta or not manifest.description:
                manifest.description = toc.description or manifest.description
            if force_meta or not manifest.cover_url:
                manifest.cover_url = cfg.novel.cover_url or toc.cover_url or manifest.cover_url
            manifest.metadata_missing = toc.metadata_missing

            # Trộn danh sách chương: giữ nguyên index và thứ tự cũ của các
            # chương đã tồn tại, chỉ thêm chương mới vào cuối.
            #
            # KHÔNG dùng thứ tự từ toc.chapters vì fetch_toc gán index theo vị
            # trí trên trang. Nếu trang TOC đổi thứ tự (do phân trang, site thay
            # đổi...), index cũ bị gán lại → file raw/translated trên đĩa (đặt
            # tên theo index) không còn khớp với manifest.
            #
            # KHÔNG xóa chương cũ vắng mặt trong TOC mới: TOC có thể thiếu tạm
            # thời (chỉ load được trang đầu khi phân trang, site đổi định dạng
            # URL...) — xóa entry sẽ mồ côi file raw/translated đã có trên đĩa.
            new_by_url = {ch.url: ch for ch in toc.chapters}
            merged = []
            seen = {ch.url for ch in manifest.chapters}
            for old_ch in manifest.chapters:
                new_ch = new_by_url.get(old_ch.url)
                if new_ch is not None:
                    old_ch.title = old_ch.title or new_ch.title
                    old_ch.title_zh = old_ch.title_zh or new_ch.title
                merged.append(old_ch)
            next_idx = max((ch.index for ch in merged), default=0) + 1
            for new_ch in toc.chapters:
                if new_ch.url not in seen:
                    new_ch.index = next_idx
                    new_ch.title_zh = new_ch.title
                    next_idx += 1
                    merged.append(new_ch)
            manifest.chapters = mark_duplicate_chapters(merged)

        _download_cover(storage, manifest, log, proxy=cfg.crawl.scrapling.proxy)
        storage.save_manifest(manifest)
        log(f"[crawl] Cập nhật mục lục thành công: {len(manifest.chapters)} chương.")
    except Exception as e:
        if manifest is None or not manifest.chapters:
            raise RuntimeError(f"Không thể lấy mục lục và chưa có cache cục bộ: {e}") from e
        log(f"[crawl] Không thể cập nhật mục lục mới ({e}). Sử dụng lại cache mục lục có sẵn: {len(manifest.chapters)} chương.")
    return manifest


def _download_cover(storage: Storage, manifest: Manifest, log: LogFn, proxy: str = "") -> None:
    """Tải ảnh bìa về (best-effort) nếu có cover_url mà chưa lưu file."""
    if not manifest.cover_url or manifest.cover_file:
        return
    try:
        import requests

        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = requests.get(manifest.cover_url, timeout=30, proxies=proxies)
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


def _resolve_crawl_retry(base: CrawlRetryConfig, retries: int | None, retry_delay: float | None) -> CrawlRetryConfig:
    """Lấy cấu hình retry hiệu lực: mặc định từ config (cfg.crawl.retry), chỉ ghi
    đè attempts/delay khi caller (vd CLI --retries) truyền giá trị tường minh."""
    if retries is None and retry_delay is None:
        return base
    return replace(
        base,
        attempts=base.attempts if retries is None else retries,
        delay_seconds=base.delay_seconds if retry_delay is None else retry_delay,
    )


def _retry_wait_seconds(retry: CrawlRetryConfig, attempt: int, retry_after: float | None) -> float:
    """Tính thời gian chờ trước lần thử kế tiếp.

    - Nếu server gửi Retry-After và bật respect_retry_after -> ưu tiên giá trị đó.
    - Ngược lại backoff cấp số nhân: delay × backoff^(attempt-1), chặn trần
      max_delay_seconds. attempt tính từ 1 (lần thất bại đầu tiên).
    """
    if retry_after is not None and retry.respect_retry_after:
        return min(max(retry_after, 0.0), retry.max_delay_seconds)
    wait = retry.delay_seconds * (retry.backoff ** (attempt - 1))
    return min(wait, retry.max_delay_seconds)


def _fetch_chapter_with_retry(crawler, ch: Chapter, retry: CrawlRetryConfig, log: LogFn) -> str | None:
    """Tải 1 chương, thử lại tối đa `retry.attempts` lần nếu lỗi. Trả None nếu
    thất bại sau khi đã thử hết — để caller bỏ qua chương đó thay vì giết cả job.

    Lỗi bị giới hạn tốc độ (HTTP 429 / anti-bot) được lùi dần theo cấp số nhân và
    tôn trọng header Retry-After nếu có, giúp vượt qua chặn tạm thời."""
    attempts = max(1, retry.attempts + 1)
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _strip_repeated_title(crawler.fetch_chapter(ch), ch)
        except Exception as e:  # noqa: BLE001 - lỗi mạng/parse bất kỳ
            last_err = e
            limited, retry_after = is_rate_limited(e)
            tag = " [rate-limit 429]" if limited else ""
            log(f"[crawl]   ! Lỗi tải chương {ch.stem} (lần {attempt}/{attempts}){tag}: {e}")
            if attempt < attempts:
                wait = _retry_wait_seconds(retry, attempt, retry_after)
                if wait > 0:
                    src = "Retry-After" if (retry_after is not None and retry.respect_retry_after) else "backoff"
                    log(f"[crawl]   … chờ {wait:.0f}s ({src}) rồi thử lại.")
                    time.sleep(wait)
    log(f"[crawl]   ! Bỏ qua chương {ch.stem} sau {attempts} lần thử: {last_err}")
    return None


def step_crawl(cfg: Config, log: LogFn = _print, *, should_cancel: CancelFn | None = None) -> Manifest:
    return step_crawl_selected(cfg, log, should_cancel=should_cancel)


def _crawl_one(crawler, storage: Storage, ch: Chapter, force: bool, retry: CrawlRetryConfig, log: LogFn, i: int, total: int) -> str:
    """Tải 1 chương, ghi raw, trả về last_action_status ('completed'/'replaced'/'failed').

    Dùng chung cho cả nhánh tuần tự và song song.
    """
    had_raw = storage.has_raw(ch)
    log(f"[crawl] ({i}/{total}) {ch.url}")
    content = _fetch_chapter_with_retry(crawler, ch, retry, log)
    crawler.sleep()
    if content is None:
        ch.last_action_status = "failed"
        return "failed"
    if not content.strip():
        log(f"[crawl]   ! Chương {ch.stem} rỗng, bỏ qua.")
    storage.write_raw(ch, content)
    ch.last_action_status = "replaced" if had_raw and force else "completed"
    return ch.last_action_status


def _crawl_chapters_sequential(crawler, storage: Storage, chapters: list[Chapter], force: bool, retry: CrawlRetryConfig, log: LogFn, total: int, should_cancel: CancelFn | None = None) -> tuple[int, int, int]:
    crawled = failed = replaced = 0
    for i, ch in enumerate(chapters, 1):
        if should_cancel and should_cancel():
            log(f"[crawl] Đã dừng theo yêu cầu — còn {total - i + 1} chương chưa xử lý.")
            break
        status = _crawl_one(crawler, storage, ch, force, retry, log, i, total)
        if status == "failed":
            failed += 1
        else:
            crawled += 1
            if status == "replaced":
                replaced += 1
    return crawled, failed, replaced


def _crawl_chapters_parallel(cfg: Config, storage: Storage, chapters: list[Chapter], force: bool, retry: CrawlRetryConfig, log: LogFn, total: int, workers: int, should_cancel: CancelFn | None = None) -> tuple[int, int, int]:
    """Tải nhiều chương song song bằng ThreadPoolExecutor.

    Mỗi luồng tự tạo + giữ riêng 1 ScraplingCrawler. Crawler được đóng lại
    khi luồng kết thúc qua thread-local cleanup.
    """
    local = threading.local()
    instances: list = []
    instances_lock = threading.Lock()
    progress = {"done": 0}
    progress_lock = threading.Lock()
    counters = {"crawled": 0, "failed": 0, "replaced": 0}
    counters_lock = threading.Lock()
    limiter = DomainRateLimiter(cfg.crawl.delay_seconds)
    throttle = AdaptiveConcurrency(workers)

    def _get_crawler():
        crawler = getattr(local, "crawler", None)
        if crawler is None:
            crawler = ScraplingCrawler(cfg.crawl)
            with instances_lock:
                instances.append(crawler)
            local.crawler = crawler
        return crawler

    def _work(ch: Chapter) -> None:
        if should_cancel and should_cancel():
            return
        throttle.acquire()
        try:
            with progress_lock:
                progress["done"] += 1
                i = progress["done"]
            limiter.acquire()
            try:
                status = _crawl_one(_get_crawler(), storage, ch, force, retry, log, i, total)
            except Exception as e:  # noqa: BLE001 - 1 chương lỗi không được giết cả batch song song
                ch.last_action_status = "failed"
                log(f"[crawl]   ! Lỗi không lường được ở chương {ch.stem}: {e}")
                status = "failed"
            if status == "failed":
                throttle.report_failure(log)
            else:
                throttle.report_success(log)
        finally:
            throttle.release()
        with counters_lock:
            if status == "failed":
                counters["failed"] += 1
            else:
                counters["crawled"] += 1
                if status == "replaced":
                    counters["replaced"] += 1

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_work, chapters))
    finally:
        for inst in instances:
            try:
                inst.close()
            except Exception:  # noqa: BLE001 - đóng best-effort, không che lỗi chính
                pass

    return counters["crawled"], counters["failed"], counters["replaced"]


def step_crawl_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    start: int | None = None,
    end: int | None = None,
    force: bool = False,
    retries: int | None = None,
    retry_delay: float | None = None,
    selected_indexes: list[int] | None = None,
    should_cancel: CancelFn | None = None,
) -> Manifest:
    """Crawl nội dung chương trong phạm vi [start, end].

    Tùy chọn:
      - force: tải lại cả chương đã có raw (mặc định chỉ tải chương còn thiếu).
      - retries / retry_delay: ghi đè số lần thử lại + thời gian chờ ban đầu khi
        một chương tải lỗi (mặc định lấy từ cfg.crawl.retry). Chương lỗi sau khi
        thử hết sẽ bị bỏ qua, không làm gián đoạn cả job. Lỗi HTTP 429 / anti-bot
        được lùi dần theo cấp số nhân và tôn trọng header Retry-After.

    crawl.max_workers > 1 trong config sẽ tải nhiều chương song song (mỗi
    luồng tự giữ 1 crawler riêng — xem _crawl_chapters_parallel).
    """
    _emit_config_warnings(cfg, log)
    _emit_crawl_config(cfg, log)
    retry = _resolve_crawl_retry(cfg.crawl.retry, retries, retry_delay)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    if cfg.crawl.ai_fallback:
        cfg.crawl._openai_fallback = cfg.translate.openai
        _emit_translate_config(cfg, log, feature="CRAWL AI fallback")

    manifest = storage.load_manifest()
    if manifest is None or not manifest.chapters:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'fetch-toc' trước.")

    selected = _chapter_selection(manifest.chapters, None, start, end, selected_indexes)
    selected = _apply_default_crawl_limit(cfg, selected, start, end, selected_indexes)
    if start is not None or end is not None:
        log(f"[crawl] Phạm vi: {len(selected)} chương "
            f"(từ {start or 1} đến {end or len(manifest.chapters)}).")

    total = len(selected)
    to_fetch = []
    skipped = 0
    for ch in selected:
        if storage.has_raw(ch) and not force:
            skipped += 1
            ch.last_action_status = "skipped"
        else:
            to_fetch.append(ch)

    workers = cfg.crawl.effective_workers(cfg.crawl.max_workers)
    if workers > 1 and len(to_fetch) > 1:
        crawled, failed, replaced = _crawl_chapters_parallel(
            cfg, storage, to_fetch, force, retry, log, total, workers, should_cancel
        )
    elif to_fetch:
        crawler = ScraplingCrawler(cfg.crawl)
        try:
            crawled, failed, replaced = _crawl_chapters_sequential(
                crawler, storage, to_fetch, force, retry, log, total, should_cancel
            )
        finally:
            crawler.close()
    else:
        crawled = failed = replaced = 0

    for ch in selected:
        storage.save_chapter(ch)

    log(f"[crawl] Hoàn tất. Đã tải {crawled} chương, bỏ qua {skipped}, lỗi {failed}, ghi đè {replaced}.")
    return manifest


def step_fetch_toc(cfg: Config, log: LogFn = _print, *, force: bool = False, should_cancel: CancelFn | None = None) -> Manifest:
    """Chỉ lấy mục lục + metadata (không crawl nội dung chương).

    Dùng để xem nhanh danh sách chương + thông tin truyện trước khi chọn phạm vi
    crawl, hoặc làm mới ảnh bìa/mô tả.
    """
    _emit_config_warnings(cfg, log)
    _emit_crawl_config(cfg, log)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    if cfg.crawl.ai_fallback:
        cfg.crawl._openai_fallback = cfg.translate.openai
        _emit_translate_config(cfg, log, feature="CRAWL AI fallback")
    crawler = ScraplingCrawler(cfg.crawl)
    try:
        manifest = _refresh_manifest(cfg, storage, crawler, log, force_meta=force)
    finally:
        crawler.close()
    log("[crawl] Lấy mục lục xong.")
    return manifest


def step_translate(cfg: Config, log: LogFn = _print, *, should_cancel: CancelFn | None = None) -> Manifest:
    return step_translate_selected(cfg, log, should_cancel=should_cancel)


def _batch_translate_titles(
    translator, chapters: list[Chapter], log: LogFn,
) -> dict[int, str]:
    """Dịch hàng loạt tiêu đề chương bằng 1 lần gọi translate_batch.

    LUÔN dịch từ `title_zh` (tiêu đề gốc chữ Hán) nếu chương đã từng dịch tiêu
    đề trước đó — KHÔNG dùng `title` hiện tại làm nguồn, vì lúc đó `title` đã
    là bản dịch tiếng Việt của lần dịch trước, gửi cho AI "dịch" lại tiếng
    Việt là sai. Chưa dịch lần nào thì `title_zh` còn rỗng, dùng `title` (lúc
    này vẫn là ZH gốc từ crawl). Trả dict mapping index chương → tiêu đề đã
    dịch. Fallback về dịch từng cái nếu translator không hỗ trợ batch.
    """
    inner = translator.inner if hasattr(translator, "inner") else translator
    if not hasattr(inner, "translate_titles"):
        return {}
    items = [(ch.index, ch.title_zh or ch.title) for ch in chapters if (ch.title_zh or ch.title)]
    if not items:
        return {}
    indexes, sources = zip(*items)
    log(f"[dịch] Đang dịch hàng loạt {len(sources)} tiêu đề…")
    translated = inner.translate_titles(list(sources))
    return dict(zip(indexes, translated))


def _translate_one(cfg: Config, storage: Storage, translator, is_noop: bool, ch: Chapter, force: bool, log: LogFn, i: int, total: int, title_lookup: dict[str, str] | None = None, *, translate_title: bool = False, should_cancel: CancelFn | None = None) -> tuple[str, bool]:
    """Dịch nội dung 1 chương (và tiêu đề nếu translate_title=True), ghi translated+meta.

    Mặc định translate_title=False — title được dịch riêng qua "Dịch TOC" hoặc
    "Dịch lại tiêu đề" để tiết kiệm token AI và tránh lãng phí (tiêu đề ngắn,
    không cần chunk). Khi translate_title=True: nhánh gốc (từ CLI pipeline cũ)
    vẫn dịch cả title như trước.

    Trả (status, title_changed) với status 'completed'/'replaced'/'failed'.
    Raise lại exception sau khi đã log + đánh dấu failed, để caller (nhánh
    tuần tự) tự quyết định có dừng sớm hay không.

    Streaming: truyền `on_chunk` cho translator để mỗi chunk dịch xong được
    ghi ngay vào `translated/{stem}.md` (chunk đầu = write, các chunk sau =
    append với `\n` ngăn cách). Cuối cùng `mark_translated_complete` set
    `complete: true` trong meta — phân biệt với partial do job bị crash.
    Xem spec `translate-chunk-streaming`.
    """
    had_translated = storage.has_translated(ch)
    raw = storage.read_raw(ch)
    log(f"[dịch] ({i}/{total}) → {ch.title or ch.stem} ({len(raw)} ký tự)")
    started = time.monotonic()
    title_changed = False
    pieces: list[str] = []
    chapter_glossary: list[dict] = []

    def _on_chunk(index: int, total_chunks: int, chunk_text: str, is_final: bool) -> None:
        log(f"[dịch]   ({i}/{total}) → đang lưu chunk {index}/{total_chunks} vào file "
            f"({len(chunk_text)} ký tự)")
        storage.append_translated_chunk(ch, chunk_text, is_first=(index == 1))
        pieces.append(chunk_text)

    def _on_glossary(entries: list[dict]) -> None:
        chapter_glossary.extend(entries)

    try:
        if ch.title and not is_noop and translate_title:
            zh_title = ch.title_zh or ch.title
            if title_lookup and ch.index in title_lookup:
                if not ch.title_zh:
                    ch.title_zh = ch.title
                ch.title = _clean_title(title_lookup[ch.index])
                ch.title_note = ""
                title_changed = True
            else:
                log(f"[dịch]   ({i}/{total}) → đang dịch tiêu đề…")
                if not ch.title_zh:
                    ch.title_zh = ch.title
                title, note = _run_with_heartbeat(
                    log, f"[dịch]   ({i}/{total})",
                    lambda: translator.translate_title(zh_title, kind="tên chương"),
                )
                ch.title = _clean_title(title)
                ch.title_note = note
                title_changed = True
        _run_with_heartbeat(
            log, f"[dịch]   ({i}/{total})",
            lambda: translator.translate(raw, on_chunk=_on_chunk, on_glossary=_on_glossary),
        )
    except Exception as e:  # noqa: BLE001 - caller quyết định dừng sớm hay tiếp tục
        ch.last_action_status = "failed"
        storage.save_chapter(ch)
        log(f"[dịch]   ({i}/{total}) ! Lỗi chương {ch.stem}: {e}")
        # File `translated/{stem}.md` có thể đã chứa 1 vài chunk trước khi
        # lỗi — đánh dấu `complete: false` vào meta để `has_translated` trả
        # False ở lần chạy kế (cache đúng: chapter partial sẽ được dịch lại
        # từ đầu thay vì bị coi là đã xong — xem spec translate-chunk-streaming).
        partial_meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
        partial_meta["complete"] = False
        partial_meta["last_error"] = str(e)
        storage.write_meta(ch, partial_meta)
        # Gắn title_changed vào exception để caller biết tiêu đề đã dịch
        # xong trước khi nội dung lỗi (cần lưu manifest dù chương bị bỏ qua).
        e.title_changed = title_changed
        raise

    elapsed = time.monotonic() - started
    translated = "\n".join(pieces)
    # Snapshot bản dịch máy (cột "VI" editor 3 cột): ghi bản máy gốc tách khỏi
    # `translated` (cột "Biên tập" — sẽ bị sửa tay/AI rewrite về sau). Cho phép
    # luôn đối chiếu "máy dịch ra gì" kể cả sau khi đã biên tập nhiều.
    storage.write_translated_mt(ch, translated)
    warnings = _quality_warnings(raw, translated)
    meta = _build_meta(cfg, ch, translated, warnings)
    # Capture cost/latency từ OmniRoute (nếu response có header X-OmniRoute-Version).
    # _run_chat_with_retry_meta đã cộng dồn cost/tokens/latency vào _last_chapter_meta.
    if hasattr(translator, "drain_last_meta"):
        omni_meta = translator.drain_last_meta()
        if omni_meta:
            meta["omniroute"] = omni_meta
            log(
                f"[dịch]   ({i}/{total}) 💰 "
                f"${omni_meta.get('cost_usd', 0):.4f} · "
                f"{omni_meta.get('tokens_in', 0)}+{omni_meta.get('tokens_out', 0)} tokens · "
                f"{omni_meta.get('actual_model', '?')} · "
                f"{omni_meta.get('latency_ms', 0)}ms"
                + (" · cache HIT" if omni_meta.get("cache_hit") else "")
            )
    meta["complete"] = True
    # File đã được _on_chunk ghi từng phần rồi; chỉ cần đánh dấu complete.
    storage.mark_translated_complete(ch, meta_extra=meta)
    ch.last_action_status = "replaced" if had_translated and force else "completed"
    _log_chapter_done(log, f"[dịch]   ({i}/{total})", ch.title or ch.stem, elapsed, translated, warnings)

    # Auto-glossary: merge glossary do AI trả kèm trong response dịch.
    if (
        cfg.translate.auto_glossary
        and not is_noop
        and cfg.translate.type.lower() == "openai"
        and not (should_cancel and should_cancel())
    ):
        _maybe_extract_chapter_glossary(cfg, translator, storage, ch, chapter_glossary, log, i, total)

    # Auto-cleanup Hán: rà soát bản dịch, sửa chữ Hán còn sót.
    # Dùng config AI biên tập (ai.openai) — chạy được với mọi backend dịch.
    if (
        cfg.translate.auto_cleanup_han
        and not is_noop
        and (cfg.ai.openai.base_url or cfg.ai.openai.api_key)
    ):
        try:
            cleanup_cfg = cfg.translate.cleanup_han
            cleaned, fixed_count, cleanup_warnings = han_cleanup.cleanup_chapter(
                raw, translated, cfg.ai.openai, log,
                max_chars=cleanup_cfg.max_chars,
                retries=cleanup_cfg.retries,
            )
            han_before_cleanup = han_cleanup.count_han(translated)
            han_after_cleanup = han_cleanup.count_han(cleaned)
            # Ghi meta đánh dấu đã cleanup (gate 'han_cleanup_complete' chỉ set khi
            # pipeline đã xử lý xong — cùng cấu trúc với step_cleanup_han_selected).
            chapter_meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            chapter_meta["han_cleanup_complete"] = True
            chapter_meta["han_cleanup"] = {
                "before": han_before_cleanup,
                "after": han_after_cleanup,
                "fixed_count": fixed_count,
            }
            storage.write_meta(ch, chapter_meta)
            if fixed_count > 0 or han_after_cleanup < han_before_cleanup:
                storage.write_translated(ch, cleaned)
                log(f"[dịch]   ({i}/{total}) → cleanup Hán: sửa {fixed_count} chỗ")
                # Cập nhật translated local để quality_warnings phản ánh bản đã sửa
                translated = cleaned
            for w in cleanup_warnings:
                log(f"[dịch]   ({i}/{total}) ⚠ {w}")
        except Exception as e:
            log(f"[dịch]   ({i}/{total}) ! Lỗi cleanup Hán: {e}")

    storage.save_chapter(ch)
    return ch.last_action_status, title_changed


def _maybe_extract_chapter_glossary(
    cfg: Config,
    translator,
    storage: Storage,
    ch: Chapter,
    chapter_glossary: list[dict],
    log: LogFn,
    i: int,
    total: int,
) -> None:
    if not chapter_glossary:
        return

    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    for s in chapter_glossary:
        grouped[s["target_file"]][s["source"]] = s["suggested"]

    chapter_conflicts: list[dict] = []
    for target_file, entries in grouped.items():
        if target_file not in ("names.txt", "vietphrase.txt"):
            continue
        result = translator.extend_glossary(entries, target_file, storage)
        for source, target in result["added"]:
            log(f"[dịch]   ({i}/{total}) + glossary ({target_file}): {source} = {target}")
        for c in result["conflicts"]:
            c["chapter_index"] = ch.index
            chapter_conflicts.append(c)
            log(
                f"[dịch]   ({i}/{total}) ⚠ conflict {c['source']}: "
                f"hiện có '{c['existing']}', AI đề xuất '{c['new']}' (giữ giá trị cũ)"
            )

    if chapter_conflicts:
        try:
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            meta["glossary_conflicts"] = chapter_conflicts
            storage.write_meta(ch, meta)
        except Exception as e:
            log(f"[dịch]   ({i}/{total}) ! Không ghi được glossary_conflicts vào meta: {e}")


def _translate_chapters_sequential(cfg: Config, storage: Storage, manifest: Manifest, translator, is_noop: bool, chapters: list[Chapter], force: bool, log: LogFn, total: int, changed: bool, should_cancel: CancelFn | None = None, title_lookup: dict[str, str] | None = None) -> tuple[int, int, int, bool]:
    translated_count = failed = replaced = 0
    for i, ch in enumerate(chapters, 1):
        if should_cancel and should_cancel():
            log(f"[dịch] Đã dừng theo yêu cầu — còn {total - i + 1} chương chưa xử lý.")
            break
        try:
            status, title_changed = _translate_one(cfg, storage, translator, is_noop, ch, force, log, i, total, title_lookup=title_lookup, should_cancel=should_cancel)
        except Exception as e:
            failed += 1
            changed = changed or getattr(e, "title_changed", False)
            if translated_count == 0:
                # Lỗi ngay chương đầu tiên dịch được => gần như chắc do cấu hình/CLI;
                # dừng sớm và báo lỗi rõ thay vì thử lỗi hàng loạt.
                raise RuntimeError(f"Dịch lỗi ngay chương đầu ({ch.stem}): {e}") from e
            continue
        changed = changed or title_changed
        translated_count += 1
        if status == "replaced":
            replaced += 1
    return translated_count, failed, replaced, changed


def _translate_chapters_parallel(cfg: Config, storage: Storage, manifest: Manifest, translator, is_noop: bool, chapters: list[Chapter], force: bool, log: LogFn, total: int, workers: int, changed: bool, should_cancel: CancelFn | None = None, title_lookup: dict[str, str] | None = None) -> tuple[int, int, int, bool]:
    """Dịch nhiều chương song song. Translator được dùng chung giữa các luồng:
    OpenAITranslator chỉ gửi 1 HTTP request riêng mỗi lần gọi (không state dùng
    chung), GoogleTranslator gọi HTTP riêng mỗi lần — cả hai an toàn gọi đồng
    thời. Không dừng sớm khi 1 chương lỗi (các chương khác đã đang chạy song
    song); chỉ raise nếu TẤT CẢ chương trong batch đều lỗi.

    Streaming: mỗi worker chỉ xử lý 1 chapter tại 1 thời điểm (`pool.map`
    ánh xạ 1-1), nên callback `on_chunk` chạy tuần tự trong worker đó —
    không có race khi 2 worker cùng ghi 1 file. Hai worker khác nhau chạm
    2 file khác nhau (path `translated/{stem}.md` khác `stem`) nên cũng
    không xung đột I/O. Không cần lock.
    """
    progress = {"done": 0}
    progress_lock = threading.Lock()
    counters = {"translated": 0, "failed": 0, "replaced": 0, "changed": changed}
    counters_lock = threading.Lock()
    first_error: list[BaseException] = []

    def _work(ch: Chapter) -> None:
        if should_cancel and should_cancel():
            return
        with progress_lock:
            progress["done"] += 1
            i = progress["done"]
        try:
            status, title_changed = _translate_one(cfg, storage, translator, is_noop, ch, force, log, i, total, title_lookup=title_lookup, should_cancel=should_cancel)
        except Exception as e:  # noqa: BLE001 - đã log trong _translate_one, gom lại để quyết định ở cuối
            with counters_lock:
                counters["failed"] += 1
                counters["changed"] = counters["changed"] or getattr(e, "title_changed", False)
                if not first_error:
                    first_error.append(e)
            return
        with counters_lock:
            counters["translated"] += 1
            counters["changed"] = counters["changed"] or title_changed
            if status == "replaced":
                counters["replaced"] += 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_work, chapters))

    if counters["translated"] == 0 and first_error:
        raise RuntimeError(f"Dịch lỗi toàn bộ {counters['failed']} chương đã chọn: {first_error[0]}") from first_error[0]

    return counters["translated"], counters["failed"], counters["replaced"], counters["changed"]


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
    should_cancel: CancelFn | None = None,
    translate_title: bool = False,
) -> Manifest:
    """translate.max_workers > 1 trong config sẽ dịch nhiều chương song song
    bằng 1 translator dùng chung (xem _translate_chapters_parallel).

    translate_title=False (mặc định): chỉ dịch nội dung, không dịch tiêu đề.
    Tiêu đề được dịch riêng qua 'Dịch TOC' hoặc 'Dịch lại tiêu đề' — tiết kiệm
    token AI (không cần chunk cho title ngắn) và tránh lãng phí khi dịch selected.
    """
    _emit_config_warnings(cfg, log)
    _emit_translate_config(cfg, log)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    translator = RateLimited(make_translator(cfg.translate, log), cfg.translate.delay_seconds)
    is_noop = cfg.translate.type.lower() == "none"

    selected = _chapter_selection(manifest.chapters, chapter, start, end, selected_indexes)
    total = len(selected)
    log(f"[dịch] Bắt đầu xử lý {total} chương trong phạm vi đã chọn.")

    to_translate = []
    skipped = 0
    for ch in selected:
        if not storage.has_raw(ch):
            log(f"[dịch] chưa có raw cho {ch.stem}, bỏ qua.")
            skipped += 1
            ch.last_action_status = "skipped"
            storage.save_chapter(ch)
            continue
        if not force and storage.has_translated(ch):
            skipped += 1
            ch.last_action_status = "skipped"
            storage.save_chapter(ch)
            continue
        to_translate.append(ch)

    # Local NMT song song hóa qua CT2 inter/intra threads + translate_batch nội
    # bộ mỗi chương; không fan-out luồng Python mỗi chương để tránh
    # oversubscription nhân CPU.
    if cfg.translate.type.lower() in ("hachimimt", "moxhimt"):
        workers = 1
    else:
        workers = max(1, int(cfg.translate.max_workers))

    # Batch translate all chapter titles before the content loop (nếu translate_title).
    title_lookup = _batch_translate_titles(translator, to_translate, log) if translate_title else {}

    changed = 0
    if workers > 1 and len(to_translate) > 1:
        translated_count, failed, replaced, changed = _translate_chapters_parallel(
            cfg, storage, manifest, translator, is_noop, to_translate, force, log, total, workers, changed, should_cancel, title_lookup=title_lookup
        )
    else:
        translated_count, failed, replaced, changed = _translate_chapters_sequential(
            cfg, storage, manifest, translator, is_noop, to_translate, force, log, total, changed, should_cancel, title_lookup=title_lookup
        )

    if cfg.translate.auto_glossary and cfg.translate.type.lower() == "openai":
        inner = translator.inner if hasattr(translator, "inner") else translator
        if hasattr(inner, "drain_conflicts"):
            conflicts = inner.drain_conflicts()
            if conflicts:
                existing = storage.read_extra_json("glossary_conflicts")
                if not isinstance(existing, list):
                    existing = []
                seen = {(c["source"], c["new"], c["target_file"]) for c in existing}
                for c in conflicts:
                    key = (c["source"], c["new"], c["target_file"])
                    if key not in seen:
                        existing.append(c)
                        seen.add(key)
                storage.write_extra_json("glossary_conflicts", existing)
                log(f"[dịch] Auto-glossary: {len(conflicts)} xung đột — xem trang Glossary")

    # OmniRoute cost summary: aggregate từ meta.omniroute của các chương vừa dịch.
    _write_omniroute_cost_summary(storage, to_translate, log)

    log(f"[dịch] Hoàn tất. Đã dịch {translated_count} chương, bỏ qua {skipped}, lỗi {failed}, ghi đè {replaced}.")
    return manifest


def _write_omniroute_cost_summary(
    storage: Storage,
    chapters: list[Chapter],
    log: LogFn,
) -> None:
    """Gom meta.omniroute của tất cả chương → ghi _cost_summary.json cho UI.

    Chỉ ghi khi có ít nhất 1 chương có meta.omniroute (response từ OmniRoute).
    Trường hợp provider khác (OpenAI, OpenRouter) thì skip yên lặng.
    """
    total_cost = 0.0
    total_cost_saved = 0.0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cache_hits = 0
    total_latency_ms = 0
    by_model: dict[str, dict] = {}
    version = ""
    chapter_count = 0

    for ch in chapters:
        if not storage.has_meta(ch):
            continue
        meta = storage.read_meta(ch)
        omni = meta.get("omniroute")
        if not omni or not isinstance(omni, dict):
            continue
        chapter_count += 1
        total_cost += float(omni.get("cost_usd", 0) or 0)
        total_cost_saved += float(omni.get("cost_saved_usd", 0) or 0)
        total_tokens_in += int(omni.get("tokens_in", 0) or 0)
        total_tokens_out += int(omni.get("tokens_out", 0) or 0)
        total_cache_hits += int(omni.get("cache_hits", 0) or 0)
        total_latency_ms += int(omni.get("latency_ms", 0) or 0)
        version = omni.get("version", version) or version
        model_key = omni.get("actual_model") or "unknown"
        m = by_model.setdefault(model_key, {
            "cost_usd": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "chapters": 0,
            "cache_hits": 0,
        })
        m["cost_usd"] += float(omni.get("cost_usd", 0) or 0)
        m["tokens_in"] += int(omni.get("tokens_in", 0) or 0)
        m["tokens_out"] += int(omni.get("tokens_out", 0) or 0)
        m["chapters"] += 1
        if omni.get("cache_hit"):
            m["cache_hits"] += 1

    if chapter_count == 0:
        return

    summary = {
        "version": version,
        "chapter_count": chapter_count,
        "total_cost_usd": round(total_cost, 10),
        "total_cost_saved_usd": round(total_cost_saved, 10),
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "total_cache_hits": total_cache_hits,
        "total_latency_ms": total_latency_ms,
        "by_model": {k: {**v, "cost_usd": round(v["cost_usd"], 10)} for k, v in by_model.items()},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.write_extra_json("cost_summary", summary)
    log(
        f"[dịch] OmniRoute tổng: ${total_cost:.4f} · {total_tokens_in}+{total_tokens_out} tokens · "
        f"{total_cache_hits} cache hits · {chapter_count} chương · {version or '?'}"
    )


def step_cleanup_han_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    chapter: int | None = None,
    start: int | None = None,
    end: int | None = None,
    force: bool = False,
    selected_indexes: list[int] | None = None,
    should_cancel: CancelFn | None = None,
) -> Manifest:
    """Rà soát các chương đã dịch, phát hiện và sửa chữ Hán còn sót.

    Dùng config AI biên tập (ai.openai) — không phụ thuộc backend dịch, nên
    chạy được cả khi dịch bằng moxhimt/hachimimt. Bỏ qua chương chưa có bản dịch.
    Nếu force=True, quét lại cả chương đã được cleanup trước đó.
    """
    _emit_config_warnings(cfg, log)
    ai_cfg = cfg.ai.openai
    log(f"[config] CLEANUP HÁN dùng AI biên tập: base_url={ai_cfg.base_url!r} "
        f"| model={_fmt(ai_cfg.model, '(chưa cấu hình)')} "
        f"| timeout={ai_cfg.timeout_seconds}s")
    if not ai_cfg.base_url and not ai_cfg.api_key:
        log("[cleanup-han] Chưa cấu hình AI biên tập (Settings → AI biên tập). Bỏ qua.")
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        return manifest

    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    selected = _chapter_selection(manifest.chapters, chapter, start, end, selected_indexes)
    total = len(selected)
    log(f"[cleanup-han] Quét {total} chương trong phạm vi đã chọn.")

    to_clean = []
    skipped = 0
    for ch in selected:
        if not storage.has_translated(ch):
            log(f"[cleanup-han] chưa có bản dịch cho {ch.stem}, bỏ qua.")
            skipped += 1
            continue
        meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
        if not force and meta.get("han_cleanup_complete"):
            skipped += 1
            continue
        to_clean.append(ch)

    cleanup_cfg = cfg.translate.cleanup_han
    total_cleaned = 0
    total_fixed = 0

    for i, ch in enumerate(to_clean, 1):
        if should_cancel and should_cancel():
            log(f"[cleanup-han] Đã dừng theo yêu cầu — còn {len(to_clean) - i + 1} chương chưa xử lý.")
            break

        raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
        translated = storage.read_translated(ch)

        han_before = han_cleanup.count_han(translated)
        if han_before == 0:
            log(f"[cleanup-han] ({i}/{total}) → {ch.title or ch.stem}: sạch (0 Hán).")
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            meta["han_cleanup_complete"] = True
            storage.write_meta(ch, meta)
            total_cleaned += 1
            continue

        log(f"[cleanup-han] ({i}/{total}) → {ch.title or ch.stem}: {han_before} Hán.")
        try:
            cleaned, fixed_count, cleanup_warnings = han_cleanup.cleanup_chapter(
                raw, translated, ai_cfg, log,
                max_chars=cleanup_cfg.max_chars,
                retries=cleanup_cfg.retries,
            )
        except Exception as e:
            log(f"[cleanup-han] ({i}/{total}) ! Lỗi: {e}")
            continue

        han_after = han_cleanup.count_han(cleaned)

        if fixed_count > 0 or han_after < han_before:
            storage.write_translated(ch, cleaned)
            total_fixed += max(fixed_count, han_before - han_after)
            log(f"[cleanup-han] ({i}/{total}) ✓ {ch.title or ch.stem}: "
                f"sửa {han_before - han_after}/{han_before} Hán (AI xử lý {fixed_count} chỗ).")
        for w in cleanup_warnings:
            log(f"[cleanup-han] ({i}/{total}) ⚠ {w}")

        meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
        meta["han_cleanup_complete"] = True
        meta["han_cleanup"] = {
            "before": han_before,
            "after": han_after,
            "fixed_count": fixed_count,
        }
        storage.write_meta(ch, meta)
        total_cleaned += 1

    log(f"[cleanup-han] Hoàn tất. Đã quét {total_cleaned}/{total} chương, "
        f"sửa {total_fixed} chỗ Hán, bỏ qua {skipped}.")
    return manifest


def step_translate_toc_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    force: bool = False,
    selected_indexes: list[int] | None = None,
    should_cancel: CancelFn | None = None,
) -> Manifest:
    """Dịch tiêu đề chương (TOC) cho các chương đã chọn, không đụng nội dung.

    LUÔN dịch từ `title_zh` (tiêu đề gốc chữ Hán) khi chương đã từng dịch tiêu
    đề trước đó — KHÔNG dùng `title` hiện tại (lúc đó đã là bản dịch tiếng
    Việt) làm nguồn gửi AI. Chưa dịch lần nào thì `title_zh` còn rỗng, dùng
    chính `title` (vẫn là ZH gốc từ crawl) — xem `_batch_translate_titles`.

    force=False (mặc định): CHỈ dịch chương CHƯA có `title_zh` (chưa dịch tiêu
    đề lần nào). force=True: dịch lại TẤT CẢ chương đã chọn có tiêu đề gốc,
    ghi đè `title` hiện tại — `title_zh` (tiêu đề gốc) không bị đụng vào.
    Không dùng prompt template — gọi trực tiếp translator.translate_title().
    """
    _emit_translate_config(cfg, log, feature="DỊCH TIÊU ĐỀ TOC")
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    translator = RateLimited(make_translator(cfg.translate, log), cfg.translate.delay_seconds)
    selected = _chapter_selection(manifest.chapters, None, None, None, selected_indexes)
    total = len(selected)
    if total == 0:
        log("[toc] Không có chương nào được chọn.")
        return manifest

    log(f"[toc] Xử lý {total} tiêu đề chương.")
    if force:
        to_translate = [ch for ch in selected if (ch.title_zh or ch.title)]
    else:
        to_translate = [ch for ch in selected if not ch.title_zh and ch.title]
    if not to_translate:
        log("[toc] Không có tiêu đề nào cần dịch (đã có sẵn — dùng 'force' để dịch lại).")
        return manifest

    title_lookup = _batch_translate_titles(translator, to_translate, log)
    changed = 0
    for ch in to_translate:
        if ch.index in title_lookup:
            if not ch.title_zh:
                ch.title_zh = ch.title
            ch.title = _clean_title(title_lookup[ch.index])
            ch.title_note = ""
            changed += 1

    if changed:
        for ch in to_translate:
            storage.save_chapter(ch)
        log(f"[toc] Đã dịch {changed}/{total} tiêu đề.")
    else:
        log("[toc] Không có tiêu đề nào thay đổi.")
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

    _emit_translate_config(cfg, log, feature="REWRITE")
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
        log(f"[rewrite] ({i}/{total}) {ch.title or ch.stem}")
        raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
        current = storage.read_translated(ch)
        try:
            rewritten = glossary_ai.rewrite_chapter(
                cfg.ai.openai, raw, current, glossary,
                filter_glossary=cfg.translate.glossary_filter,
            )
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


def step_find_replace(
    cfg: Config,
    log: LogFn = _print,
    *,
    find: str,
    replace: str,
    start: int | None = None,
    end: int | None = None,
    also_raw: bool = False,
) -> Manifest:
    """Tìm & thay thế literal trên các chương đã dịch (không gọi AI).

    Nhanh, dùng để đổi tên riêng đã dịch hoặc sửa lỗi hàng loạt. Bản trước khi
    thay được lưu vào meta['before_find_replace'] để có thể khôi phục.
    """
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    if not find:
        log("[find-replace] Bỏ qua: ô 'tìm' đang rỗng.")
        return manifest

    selected = _chapter_range(manifest.chapters, None, start, end)
    changed_chapters = 0
    total_replacements = 0
    for ch in selected:
        if storage.has_translated(ch):
            content = storage.read_translated(ch)
            count = content.count(find)
            if count:
                meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
                meta["before_find_replace"] = content
                storage.write_meta(ch, meta)
                storage.write_translated(ch, content.replace(find, replace))
                changed_chapters += 1
                total_replacements += count
                log(f"[find-replace] Chương {ch.index}: thay {count} chỗ (bản dịch).")
        if also_raw and storage.has_raw(ch):
            raw = storage.read_raw(ch)
            raw_count = raw.count(find)
            if raw_count:
                storage.write_raw(ch, raw.replace(find, replace))
                total_replacements += raw_count
                log(f"[find-replace] Chương {ch.index}: thay {raw_count} chỗ (bản gốc).")

    log(
        f"[find-replace] Hoàn tất. Đổi {changed_chapters} chương, "
        f"tổng {total_replacements} lần thay."
    )
    return manifest


def step_evaluate_translation(
    cfg: Config,
    log: LogFn = _print,
    *,
    start: int | None = None,
    end: int | None = None,
) -> dict:
    """Đánh giá glossary + bản dịch của các chương trong phạm vi (chỉ đọc, không sửa).

    Trả về report (dict). Lỗi gọi AI không raise — report rỗng được log lại.
    """
    from . import glossary_ai

    _emit_translate_config(cfg, log, feature="ĐÁNH GIÁ")
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
    report = glossary_ai.evaluate_translation(cfg.ai.openai, chapters_text, glossary)
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

    _emit_translate_config(cfg, log, feature="REVIEW")
    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch)
    glossary = glossary_ai.load_glossary(cfg.translate)
    log(f"[review] Đang phân tích chương {ch.index}: {ch.title or ch.stem}")
    report = glossary_ai.evaluate_translation(cfg.ai.openai, [(raw, translated)], glossary)
    _update_chapter_meta(storage, ch, ai_review={"report": report, "generated_at": _now_iso()})
    log(glossary_ai.format_evaluation_text(report))
    log("[review] Hoàn tất. Mở lại trang chương để xem báo cáo.")
    return report


def step_suggest_chapter(cfg: Config, log: LogFn = _print, *, index: int) -> list[dict]:
    """AI gợi ý glossary cho 1 chương — lưu vào meta['ai_suggestions']."""
    from . import glossary_ai

    storage, _manifest, ch = _require_chapter(cfg, index)
    _emit_translate_config(cfg, log, feature="GỢI Ý GLOSSARY")
    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    existing = glossary_ai.load_glossary(cfg.translate)
    log(f"[gợi ý] Đang phân tích chương {ch.index}: {ch.title or ch.stem}")
    suggestions = glossary_ai.suggest_glossary(
        cfg.ai.openai, [(raw, translated)], existing,
        filter_glossary=cfg.translate.glossary_filter,
    )
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

    _emit_translate_config(cfg, log, feature="REWRITE PREVIEW")
    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    current = storage.read_translated(ch)
    glossary = glossary_ai.load_glossary(cfg.translate)
    log(f"[rewrite] Đang biên tập lại chương {ch.index}: {ch.title or ch.stem}")
    rewritten = glossary_ai.rewrite_chapter(
        cfg.ai.openai, raw, current, glossary,
        filter_glossary=cfg.translate.glossary_filter,
    )
    if not rewritten.strip():
        log("[rewrite] AI trả về rỗng — giữ nguyên, không tạo bản nháp.")
        return ""
    _update_chapter_meta(storage, ch, ai_rewrite={"text": rewritten, "generated_at": _now_iso()})
    log("[rewrite] Đã tạo bản nháp. Mở lại trang chương để xem diff và áp dụng.")
    return rewritten


def step_delete_translation_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    selected_indexes: list[int] | None = None,
    should_cancel: CancelFn | None = None,
) -> Manifest:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    selected = _chapter_selection(manifest.chapters, None, None, None, selected_indexes)
    total = len(selected)
    deleted = 0
    for ch in selected:
        if should_cancel and should_cancel():
            log("[xóa-dịch] Đã dừng theo yêu cầu.")
            break
        if not storage.has_any_translation_data(ch):
            continue
        storage.delete_translated(ch)
        ch.last_action_status = ""
        deleted += 1
        log(f"[xóa-dịch] ({deleted}/{total}) {ch.stem}")

    if deleted:
        storage.save_manifest(manifest)
    log(f"[xóa-dịch] Hoàn tất. Đã xóa {deleted} chương.")
    return manifest


_RETRANSLATE_TITLE_PROMPT = """Bạn là biên tập tiêu đề cho truyện dịch Trung-Việt.

Tôi cần bạn dịch lại tiêu đề chương sau, dựa vào nội dung đã dịch của chương đó để có ngữ cảnh, giúp bản dịch tiêu đề HAY, CÓ HỒN, phù hợp với nội dung bên trong.

Nguyên tắc bắt buộc:
1. Không bê nguyên âm Hán Việt nếu người đọc Việt không hiểu nghĩa.
2. Có thể đảo cấu trúc, dùng hình ảnh/ẩn dụ tương đương trong tiếng Việt, miễn giữ đúng tinh thần và nội dung cốt lõi.
3. Dùng nội dung tóm tắt bên dưới để hiểu bối cảnh và chọn từ ngữ phù hợp nhất.
4. Nếu thực sự không tìm được cách chuyển ngữ hay mà vẫn giữ đúng nghĩa, hãy dịch nghĩa rõ ràng dù kém mượt hơn là giữ Hán Việt khó hiểu, và điền dòng GIẢI THÍCH để người đọc hiểu nghĩa gốc/lý do chọn từ.

{glossary}
Trả lời ĐÚNG 2 dòng theo định dạng sau, không thêm gì khác:
TIÊU ĐỀ: <bản dịch tiếng Việt>
GIẢI THÍCH: <để trống nếu tên đã rõ nghĩa, tự nhiên; chỉ điền nếu cần giải thích thêm cho người đọc>

--- Tiêu đề gốc (chữ Hán) ---
{title}

--- Tóm tắt nội dung đã dịch (để tham khảo ngữ cảnh) ---
{summary}"""

_RETRANSLATE_TITLE_SIMPLE_PROMPT = """Dịch tiêu đề sau sang tiếng Việt. Chỉ trả về bản dịch, không giải thích:

{title}"""

_TITLE_DESCRIPTION_PROMPT = """Bạn là biên tập viên truyện dịch Trung → Việt.

Hãy giải thích vì sao chương sau được đặt tên như vậy, dựa vào tiêu đề gốc (chữ Hán) và nội dung đã dịch.

Nguyên tắc:
1. Giải thích nguồn gốc ý nghĩa của tên chương (địa danh, nhân vật, sự kiện, ẩn dụ...)
2. Giải thích tại sao tên này phù hợp với nội dung chương
3. Nếu có Hán Việt khó hiểu, giải thích nghĩa gốc
4. Trả lời bằng tiếng Việt, ngắn gọn (2-4 câu)

{glossary}

--- Tiêu đề gốc (chữ Hán) ---
{title}

--- Tiêu đề đã dịch ---
{title_vi}

--- Tóm tắt nội dung chương ---
{summary}

Trả lời ĐÚNG 1 dòng theo định dạng:
GIẢI THÍCH: <giải thích>"""


def _generate_title_description(
    cfg: Config,
    title_zh: str,
    title_vi: str,
    translated_content: str,
    glossary: dict,
    log: LogFn = _print,
    summary_max_chars: int = 800,
) -> str | None:
    """Generate description explaining why the chapter title is named so."""
    from .openai_client import run_chat
    from .translator import _filter_glossary, _format_glossary

    if cfg.translate.type.lower() != "openai":
        log("[mô-tả-tiêu-đề] Chỉ hỗ trợ OpenAI. Bỏ qua.")
        return None

    summary = translated_content.strip()[:summary_max_chars]
    if len(translated_content) > summary_max_chars:
        summary = summary.rsplit("\n", 1)[0] or summary

    if cfg.translate.glossary_filter:
        glossary = _filter_glossary(
            glossary, zh_text=title_zh, vi_text=f"{title_vi}\n{summary}"
        )
    prompt = _TITLE_DESCRIPTION_PROMPT.format(
        title=title_zh,
        title_vi=title_vi,
        summary=summary,
        glossary=_format_glossary(glossary),
    )

    raw = run_chat(cfg.translate.openai, prompt)
    # Parse response: look for "GIẢI THÍCH:" prefix
    if "GIẢI THÍCH:" in raw:
        description = raw.split("GIẢI THÍCH:", 1)[1].strip()
    else:
        description = raw.strip()

    return description if description else None


def step_retranslate_title(
    cfg: Config,
    log: LogFn = _print,
    *,
    slug: str,
    index: int,
    summary_max_chars: int = 800,
    engine: str | None = None,
    model: str | None = None,
    custom_prompt: str | None = None,
    generate_description: bool = True,
) -> dict:
    """Dịch lại tiêu đề chương dùng nội dung đã dịch làm ngữ cảnh.

    Trả dict {title_vi, title_note, title, title_description}.
    engine: "openai" | "google" | "hachimimt" (default: cfg.translate.type)
    """

    from .openai_client import run_chat
    from .translator import (
        _filter_glossary,
        _format_glossary,
        _parse_title_response,
        load_glossary_dict,
        make_translator,
    )

    # Resolve engine (default: cfg.translate.type)
    selected_engine = (engine or cfg.translate.type).lower()
    
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise RuntimeError(f"Không tìm thấy chương {index}.")

    if not ch.title and not ch.title_zh:
        raise RuntimeError(f"Chương {index} không có tiêu đề (title).")

    if not storage.has_translated(ch):
        raise RuntimeError(f"Chương {index} chưa có bản dịch. Hãy dịch chương trước.")

    # Luôn dịch từ tiêu đề gốc chữ Hán (title_zh) nếu chương đã từng dịch tiêu
    # đề trước đó — `title` lúc này đã là bản dịch tiếng Việt, gửi cho AI
    # "dịch lại" tiếng Việt là sai. Chưa dịch lần nào thì title_zh còn rỗng,
    # dùng chính title (vẫn là ZH gốc từ crawl).
    zh_title = ch.title_zh or ch.title

    translated = storage.read_translated(ch)
    summary = translated.strip()[:summary_max_chars]
    if len(translated) > summary_max_chars:
        summary = summary.rsplit("\n", 1)[0] or summary

    glossary = load_glossary_dict(cfg.translate)
    prompt_glossary = glossary
    if cfg.translate.glossary_filter:
        prompt_glossary = _filter_glossary(glossary, zh_text=zh_title, vi_text=summary)

    # Use custom prompt if provided, otherwise use default
    if custom_prompt:
        prompt = custom_prompt.format(
            title=zh_title,
            summary=summary,
            glossary=_format_glossary(prompt_glossary),
        )
    else:
        prompt = _RETRANSLATE_TITLE_PROMPT.format(
            title=zh_title,
            summary=summary,
            glossary=_format_glossary(prompt_glossary),
        )

    log(f"[dịch-tiêu-đề] Chương {index}: {zh_title} (engine: {selected_engine})")
    
    if selected_engine == "openai":
        # OpenAI supports prompt-based translation with context
        # Temporarily override model if specified
        orig_model = cfg.translate.openai.model
        if model:
            cfg.translate.openai.model = model
        try:
            raw = run_chat(cfg.translate.openai, prompt)
        finally:
            cfg.translate.openai.model = orig_model
        title_vi, title_note = _parse_title_response(raw)
        title_vi = _clean_title(title_vi)
    elif selected_engine in ("google", "hachimimt"):
        # Google/HachimiMT: literal translation without context
        # Use simple prompt for these engines
        simple_prompt = _RETRANSLATE_TITLE_SIMPLE_PROMPT.format(title=zh_title)
        translator = make_translator(cfg.translate)
        title_vi = translator.translate(simple_prompt)
        title_vi = _clean_title(title_vi)
        title_note = ""  # No explanation for simple translation
        log(f"[dịch-tiêu-đề] Backend {selected_engine} không hỗ trợ context-based. Dịch literal.")
    else:
        raise RuntimeError(f"Engine không hỗ trợ: {selected_engine!r}")

    if not ch.title_zh:
        ch.title_zh = ch.title
    ch.title = title_vi
    ch.title_note = title_note
    storage.save_manifest(manifest)
    log(f"[dịch-tiêu-đề] → {title_vi}" + (f" ({title_note})" if title_note else ""))

    result = {"title_vi": title_vi, "title_note": title_note, "title": ch.title}
    
    # Generate description if requested
    if generate_description and selected_engine == "openai":
        description = _generate_title_description(
            cfg, ch.title_zh or ch.title, title_vi, translated, glossary, log
        )
        if description:
            ch.title_note = description
            storage.save_manifest(manifest)
            result["title_description"] = description
            log(f"[dịch-tiêu-đề] Description: {description[:50]}...")

    return result


def step_reindex(cfg: Config, log: LogFn = _print, *, should_cancel: CancelFn | None = None) -> Manifest:
    """Đánh lại index theo thứ tự chapters list trong manifest.

    Chương đầu list → index=1, tiếp → index=2, ...
    **KHÔNG** rename file trên đĩa — chỉ update trường index trong manifest.

    Dùng sau khi sắp xếp chapters list trong manifest.json bằng tay: sắp
    xong rồi chạy reindex để index tuần tự 1..N khớp với thứ tự mới.
    """
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest.")

    chapters = manifest.chapters
    if not chapters:
        log("[reindex] Không có chương nào.")
        return manifest

    old_indexes = [ch.index for ch in chapters]
    new_indexes = list(range(1, len(chapters) + 1))

    if old_indexes == new_indexes:
        log("[reindex] Index đã tuần tự 1..N, không cần thay đổi.")
        return manifest

    for i, ch in enumerate(chapters, 1):
        ch.index = i
        if i % 100 == 0:
            log(f"[reindex] Đã cập nhật {i}/{len(chapters)} chương...")

    from .toc import mark_duplicate_chapters

    manifest.chapters = mark_duplicate_chapters(chapters)
    storage.save_manifest(manifest)
    log(f"[reindex] Hoàn tất. {len(chapters)} chương: index {old_indexes[0]}..{old_indexes[-1]} → 1..{len(chapters)}.")
    return manifest


def step_reorder(cfg: Config, log: LogFn = _print, *, desired_order: list[int], should_cancel: CancelFn | None = None) -> Manifest:
    """Sắp xếp lại chapters trong manifest theo `desired_order` (dãy index),
    rồi đánh index lại 1..N.

    Các chương không có trong `desired_order` được xếp cuối.
    Dùng sau preview reindex: UI gửi thứ tự đang hiển thị để áp dụng.
    """
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest.")

    by_index = {ch.index: ch for ch in manifest.chapters}

    reordered = []
    seen = set()
    for idx in desired_order:
        ch = by_index.get(idx)
        if ch is None:
            log(f"[reorder] Bỏ qua index {idx} không tồn tại trong manifest.")
            continue
        if ch.index in seen:
            continue
        reordered.append(ch)
        seen.add(ch.index)

    for ch in manifest.chapters:
        if ch.index not in seen:
            reordered.append(ch)

    if len(reordered) != len(manifest.chapters):
        log(f"[reorder] Cảnh báo: số chương thay đổi ({len(reordered)} vs {len(manifest.chapters)}).")

    old_indexes = [ch.index for ch in reordered]
    for i, ch in enumerate(reordered, 1):
        ch.index = i
        if i % 100 == 0:
            log(f"[reorder] Đã cập nhật {i}/{len(reordered)} chương...")

    from .toc import mark_duplicate_chapters

    manifest.chapters = mark_duplicate_chapters(reordered)
    storage.save_manifest(manifest)
    log(f"[reorder] Hoàn tất. Đã sắp xếp {len(reordered)} chương, index {old_indexes[0]}..{old_indexes[-1]} → 1..{len(reordered)}.")
    return manifest


def step_build(cfg: Config, log: LogFn = _print, *, should_cancel: CancelFn | None = None) -> str:
    return step_build_selected(cfg, log, should_cancel=should_cancel)


def step_build_selected(
    cfg: Config,
    log: LogFn = _print,
    *,
    selected_indexes: list[int] | None = None,
    should_cancel: CancelFn | None = None,
) -> str:
    _emit_build_config(cfg, log)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    from . import footnotes as _footnotes

    if selected_indexes is not None:
        wanted = set(selected_indexes)
        chapters = [c for c in manifest.chapters if c.index in wanted]
        log(f"[build] Phạm vi: {len(chapters)} chương được chọn (tổng {len(manifest.chapters)}).")
    else:
        chapters = [c for c in manifest.chapters if not c.skipped]

    notes = storage.read_glossary_notes()
    chapters_html = []
    footnotes_by_stem: dict[str, list[dict]] = {}
    for ch in chapters:
        if storage.has_translated(ch):
            md = storage.read_translated(ch)
            title = ch.title or f"Chương {ch.index}"
            md, fns = _footnotes.annotate(md, notes)
            if fns:
                footnotes_by_stem[ch.stem] = fns
        elif storage.has_raw(ch):
            md = storage.read_raw(ch)
            title = ch.title or f"Chương {ch.index}"
        else:
            continue
        chapters_html.append((ch, title, md))

    if not chapters_html:
        raise RuntimeError("Không có chương nào để build. Hãy crawl/dịch trước.")

    _download_cover(storage, manifest, log, proxy=cfg.crawl.scrapling.proxy)
    if manifest.cover_file:
        storage.save_manifest(manifest)
    cover_path = storage.cover_fs_path(manifest)
    out = build_epub(
        manifest,
        chapters_html,
        cfg.epub_path,
        cfg.novel.language,
        cover_path=cover_path,
        footnotes_by_stem=footnotes_by_stem,
        metadata=cfg.novel,
    )
    log(f"[build] Đã tạo EPUB: {out}  ({len(chapters_html)} chương)")
    return str(out)


def run_all(cfg: Config, log: LogFn = _print, *, should_cancel: CancelFn | None = None) -> str:
    step_crawl(cfg, log, should_cancel=should_cancel)
    if should_cancel and should_cancel():
        log("[run] Đã dừng theo yêu cầu — bỏ qua bước dịch và build.")
        return ""
    step_translate(cfg, log, should_cancel=should_cancel)
    if should_cancel and should_cancel():
        log("[run] Đã dừng theo yêu cầu — bỏ qua bước build.")
        return ""
    return step_build(cfg, log)
