"""Giao diện dòng lệnh cho novel2epub."""
from __future__ import annotations

import argparse
import sys

import os

from .config import load_config, load_library
from .pipeline import (
    run_all,
    step_build,
    step_crawl,
    step_crawl_selected,
    step_evaluate_translation,
    step_fetch_toc,
    step_translate,
    step_translate_meta,
    step_translate_selected,
)
from .storage import Storage
from .toc import apply_chapter_query, chapter_rows, parse_filter, parse_range, select_visible_range


DEFAULT_CONFIG_PATH = os.environ.get(
    "NOVEL2EPUB_FILE", os.environ.get("NOVEL2EPUB_CONFIG", "novel2epub.yaml")
)


def _force_utf8() -> None:
    """Console Windows mặc định cp1252 -> in tiếng Việt bị lỗi. Ép về UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _selected_indexes_from_args(cfg, args) -> list[int] | None:
    if not (getattr(args, "sort", None) or getattr(args, "desc", False) or getattr(args, "search", "") or getattr(args, "filters", None) or getattr(args, "visible_range", "")):
        return None
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy 'toc' hoặc 'crawl' trước.")
    filters = parse_filter(getattr(args, "filters", None))
    rows = apply_chapter_query(
        chapter_rows(manifest.chapters, storage),
        sort=getattr(args, "sort", "source") or "source",
        direction="desc" if getattr(args, "desc", False) else "asc",
        search=getattr(args, "search", ""),
        filter_raw=filters["raw"],
        filter_translated=filters["translated"],
        filter_missing=filters["missing"],
    )
    start, end = parse_range(getattr(args, "visible_range", ""))
    return select_visible_range(rows, start, end)


def _print_chapters(cfg, args) -> None:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Chưa có manifest. Hãy chạy 'toc' hoặc 'crawl' trước.")
    filters = parse_filter(args.filters)
    rows = apply_chapter_query(
        chapter_rows(manifest.chapters, storage),
        sort=args.sort,
        direction="desc" if args.desc else "asc",
        search=args.search,
        filter_raw=filters["raw"],
        filter_translated=filters["translated"],
        filter_missing=filters["missing"],
    )
    for row in rows:
        missing = ",".join(row.missing_fields) or "-"
        print(f"{row.index}\t{row.visible_title}\t{row.url}\traw={row.has_raw}\ttranslated={row.has_translated}\tmissing={missing}")


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="novel2epub",
        description="Crawl truyện tiếng Trung -> dịch tiếng Việt -> đóng gói EPUB.",
    )
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH, help="Đường dẫn file cấu hình gộp (novel2epub.yaml)")
    parser.add_argument("-e", "--ebook", default="", help="Slug ebook trong khối ebooks: của file gộp")
    sub = parser.add_subparsers(dest="command", required=True)
    crawl_parser = sub.add_parser("crawl", help="Crawl mục lục + nội dung chương")
    crawl_parser.add_argument("--from", dest="start", type=int, default=None, help="Crawl từ chương số")
    crawl_parser.add_argument("--to", dest="end", type=int, default=None, help="Crawl đến chương số")
    crawl_parser.add_argument("--force", action="store_true", help="Tải lại cả chương đã có raw")
    crawl_parser.add_argument("--retries", type=int, default=None, help="Ghi đè số lần thử lại khi tải chương lỗi (mặc định lấy từ crawl.retry trong config)")
    crawl_parser.add_argument("--sort", default="source", choices=["source", "title", "raw", "translated"], help="Sắp xếp danh sách chương trước khi chọn range")
    crawl_parser.add_argument("--desc", action="store_true", help="Đảo chiều sort danh sách chương")
    crawl_parser.add_argument("--search", default="", help="Tìm trong tiêu đề hiển thị hoặc URL chương")
    crawl_parser.add_argument("--filter", dest="filters", action="append", default=[], help="Lọc chương: raw:yes/no, translated:yes/no, missing:yes/no")
    crawl_parser.add_argument("--range", dest="visible_range", default="", help="Chọn range theo danh sách đang sort/filter, ví dụ 1:3")
    sub.add_parser("translate", help="Dịch các chương đã crawl sang tiếng Việt")
    meta_parser = sub.add_parser("meta", help="Dịch metadata truyện (tên, tác giả, mô tả) sang tiếng Việt")
    meta_parser.add_argument("--force", action="store_true", help="Dịch lại metadata dù đã có bản dịch")
    toc_parser = sub.add_parser("toc", help="Lấy mục lục + metadata, không crawl nội dung chương")
    toc_parser.add_argument("--force", action="store_true", help="Làm mới metadata nguồn dù manifest đã có giá trị")
    chapters_parser = sub.add_parser("chapters", help="Liệt kê chương với sort/search/filter")
    chapters_parser.add_argument("--sort", default="source", choices=["source", "title", "raw", "translated"], help="Khóa sắp xếp")
    chapters_parser.add_argument("--desc", action="store_true", help="Đảo chiều sort")
    chapters_parser.add_argument("--search", default="", help="Tìm trong tiêu đề hiển thị hoặc URL chương")
    chapters_parser.add_argument("--filter", dest="filters", action="append", default=[], help="Lọc chương: raw:yes/no, translated:yes/no, missing:yes/no")
    evaluate_parser = sub.add_parser("evaluate", help="AI đánh giá glossary + bản dịch (chỉ xem, không sửa)")
    evaluate_parser.add_argument("--from", dest="start", type=int, default=None, help="Đánh giá từ chương số")
    evaluate_parser.add_argument("--to", dest="end", type=int, default=None, help="Đánh giá đến chương số")
    sub.add_parser("build", help="Đóng gói EPUB từ các chương đã dịch")
    sub.add_parser("run", help="Chạy toàn bộ: crawl -> translate -> build")
    sub.add_parser("list", help="Liệt kê các ebook trong library")

    translate_parser = sub.choices["translate"]
    translate_parser.add_argument("--force", action="store_true", help="Dịch lại dù đã có bản dịch")
    translate_parser.add_argument("--missing", action="store_true", help="Chỉ dịch chương chưa có bản dịch")
    translate_parser.add_argument("--chapter", type=int, default=None, help="Dịch một chương cụ thể")
    translate_parser.add_argument("--from", dest="start", type=int, default=None, help="Dịch từ chương số")
    translate_parser.add_argument("--to", dest="end", type=int, default=None, help="Dịch đến chương số")
    translate_parser.add_argument("--sort", default="source", choices=["source", "title", "raw", "translated"], help="Sắp xếp danh sách chương trước khi chọn range")
    translate_parser.add_argument("--desc", action="store_true", help="Đảo chiều sort danh sách chương")
    translate_parser.add_argument("--search", default="", help="Tìm trong tiêu đề hiển thị hoặc URL chương")
    translate_parser.add_argument("--filter", dest="filters", action="append", default=[], help="Lọc chương: raw:yes/no, translated:yes/no, missing:yes/no")
    translate_parser.add_argument("--range", dest="visible_range", default="", help="Chọn range theo danh sách đang sort/filter, ví dụ 1:3")

    args = parser.parse_args(argv)

    if args.command == "list":
        library = load_library(args.config)
        if not library.ebooks:
            print("Chưa có ebook nào trong file gộp (khối ebooks:)")
            return 0
        for slug, entry in library.ebooks.items():
            print(f"{slug}\t{entry.name or slug}")
        return 0

    try:
        cfg = load_config(args.config, args.ebook)
    except FileNotFoundError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        print("Gợi ý: copy novel2epub.example.yaml thành novel2epub.yaml rồi chỉnh sửa.",
              file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1

    try:
        if args.command == "crawl":
            selected_indexes = _selected_indexes_from_args(cfg, args)
            if args.force or args.retries is not None or args.start is not None or args.end is not None or selected_indexes is not None:
                step_crawl_selected(
                    cfg,
                    start=args.start,
                    end=args.end,
                    force=args.force,
                    retries=args.retries,
                    selected_indexes=selected_indexes,
                )
            else:
                step_crawl(cfg)
        elif args.command == "translate":
            selected_indexes = _selected_indexes_from_args(cfg, args)
            if args.force or args.missing or args.chapter is not None or args.start is not None or args.end is not None or selected_indexes is not None:
                step_translate_selected(
                    cfg,
                    chapter=args.chapter,
                    start=args.start,
                    end=args.end,
                    force=args.force,
                    missing=args.missing,
                    selected_indexes=selected_indexes,
                )
            else:
                step_translate(cfg)
        elif args.command == "meta":
            step_translate_meta(cfg, force=args.force)
        elif args.command == "toc":
            step_fetch_toc(cfg, force=args.force)
        elif args.command == "chapters":
            _print_chapters(cfg, args)
        elif args.command == "evaluate":
            step_evaluate_translation(cfg, start=args.start, end=args.end)
        elif args.command == "build":
            step_build(cfg)
        elif args.command == "run":
            run_all(cfg)
    except (RuntimeError, ValueError, ImportError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
