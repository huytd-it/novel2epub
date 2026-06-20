"""Điều phối pipeline: crawl -> translate -> build.

Mỗi bước đều dùng cache trên đĩa nên có thể dừng và chạy lại bất cứ lúc nào
mà không crawl/dịch lại những chương đã hoàn tất.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable

from .config import Config
from .crawler import make_crawler
from .epub_builder import build_epub
from .storage import Chapter, Manifest, Storage
from .translator import RateLimited, make_translator

# Kiểu hàm ghi log; mặc định in ra stdout, UI truyền callback riêng để stream.
LogFn = Callable[[str], None]


def _print(msg: str) -> None:
    print(msg, flush=True)


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


def step_crawl(cfg: Config, log: LogFn = _print) -> Manifest:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    crawler = make_crawler(cfg.crawl)
    try:
        manifest = storage.load_manifest()
        
        # Thử lấy mục lục mới từ config hiện tại
        try:
            log(f"[crawl] Đọc mục lục: {cfg.crawl.toc_url}")
            page_title, chapters = crawler.fetch_toc()
            
            if manifest is None:
                manifest = Manifest(
                    slug=cfg.novel.slug,
                    title=cfg.novel.title or page_title,
                    author=cfg.novel.author,
                    chapters=chapters,
                )
            else:
                manifest.title = cfg.novel.title or manifest.title or page_title
                manifest.author = cfg.novel.author or manifest.author
                
                # Trộn danh sách chương: giữ lại title_vi của các chương đã dịch
                old_chapters_by_url = {ch.url: ch for ch in manifest.chapters}
                merged_chapters = []
                for new_ch in chapters:
                    old_ch = old_chapters_by_url.get(new_ch.url)
                    if old_ch:
                        new_ch.title_vi = old_ch.title_vi or new_ch.title_vi
                    merged_chapters.append(new_ch)
                manifest.chapters = merged_chapters
                
            storage.save_manifest(manifest)
            log(f"[crawl] Cập nhật mục lục thành công: {len(manifest.chapters)} chương.")
        except Exception as e:
            if manifest is None or not manifest.chapters:
                raise RuntimeError(f"Không thể lấy mục lục và chưa có cache cục bộ: {e}") from e
            log(f"[crawl] Không thể cập nhật mục lục mới ({e}). Sử dụng lại cache mục lục có sẵn: {len(manifest.chapters)} chương.")

        total = len(manifest.chapters)
        for i, ch in enumerate(manifest.chapters, 1):
            if storage.has_raw(ch):
                continue
            log(f"[crawl] ({i}/{total}) {ch.url}")
            content = _strip_repeated_title(crawler.fetch_chapter(ch), ch)
            if not content.strip():
                log(f"[crawl]   ! Chương {ch.stem} rỗng, bỏ qua.")
            storage.write_raw(ch, content)
            crawler.sleep()
    finally:
        crawler.close()

    log("[crawl] Hoàn tất.")
    return manifest


def step_translate(cfg: Config, log: LogFn = _print) -> Manifest:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    translator = RateLimited(make_translator(cfg.translate), cfg.translate.delay_seconds)
    is_noop = cfg.translate.type.lower() == "none"

    total = len(manifest.chapters)
    changed = False
    for i, ch in enumerate(manifest.chapters, 1):
        if not storage.has_raw(ch):
            log(f"[dịch] ({i}/{total}) chưa có raw cho {ch.stem}, bỏ qua.")
            continue
        if storage.has_translated(ch):
            continue

        log(f"[dịch] ({i}/{total}) {ch.title_zh or ch.stem}")
        raw = storage.read_raw(ch)

        # Dịch tiêu đề (nếu có) + nội dung.
        if ch.title_zh and not is_noop:
            ch.title_vi = _clean_title(translator.translate(ch.title_zh))
            changed = True
        translated = translator.translate(raw)
        storage.write_translated(ch, translated)
        storage.write_meta(ch, _build_meta(cfg, ch, translated, _quality_warnings(raw, translated)))

    if changed:
        storage.save_manifest(manifest)
    log("[dịch] Hoàn tất.")
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
) -> Manifest:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy bước 'crawl' trước.")

    translator = RateLimited(make_translator(cfg.translate), cfg.translate.delay_seconds)
    is_noop = cfg.translate.type.lower() == "none"
    selected = _chapter_range(manifest.chapters, chapter, start, end)
    total = len(selected)
    changed = False
    for i, ch in enumerate(selected, 1):
        if not storage.has_raw(ch):
            log(f"[dịch] ({i}/{total}) chưa có raw cho {ch.stem}, bỏ qua.")
            continue
        if not force and missing and storage.has_translated(ch):
            continue
        if not force and not missing and storage.has_translated(ch):
            continue
        raw = storage.read_raw(ch)
        if ch.title_zh and not is_noop:
            ch.title_vi = _clean_title(translator.translate(ch.title_zh))
            changed = True
        translated = translator.translate(raw)
        storage.write_translated(ch, translated)
        storage.write_meta(ch, _build_meta(cfg, ch, translated, _quality_warnings(raw, translated)))
    if changed:
        storage.save_manifest(manifest)
    log("[dịch] Hoàn tất.")
    return manifest


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

    out = build_epub(manifest, chapters_html, cfg.epub_path, cfg.novel.language)
    log(f"[build] Đã tạo EPUB: {out}  ({len(chapters_html)} chương)")
    return str(out)


def run_all(cfg: Config, log: LogFn = _print) -> str:
    step_crawl(cfg, log)
    step_translate(cfg, log)
    return step_build(cfg, log)
