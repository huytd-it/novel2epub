"""Giao diện dòng lệnh cho novel2epub."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config, load_library
from .pipeline import (
    run_all,
    step_build,
    step_crawl,
    step_crawl_selected,
    step_evaluate_translation,
    step_translate,
    step_translate_meta,
    step_translate_selected,
)


DEFAULT_LIBRARY_PATH = "library.yaml"


def _force_utf8() -> None:
    """Console Windows mặc định cp1252 -> in tiếng Việt bị lỗi. Ép về UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _resolve_config_path(config_path: str, library_path: str, ebook_slug: str) -> str:
    if not ebook_slug:
        return config_path
    library = load_library(library_path)
    entry = library.ebooks.get(ebook_slug)
    if entry is None:
        raise KeyError(f"không tìm thấy ebook {ebook_slug!r}")
    if not entry.config:
        return config_path
    p = Path(entry.config)
    if p.is_absolute():
        return entry.config
    return str((Path(library_path).resolve().parent / p).resolve())


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="novel2epub",
        description="Crawl truyện tiếng Trung -> dịch tiếng Việt -> đóng gói EPUB.",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="Đường dẫn file cấu hình YAML")
    parser.add_argument("-e", "--ebook", default="", help="Slug ebook trong library.yaml")
    parser.add_argument("--library", default=DEFAULT_LIBRARY_PATH, help="Đường dẫn file library.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    crawl_parser = sub.add_parser("crawl", help="Crawl mục lục + nội dung chương")
    crawl_parser.add_argument("--from", dest="start", type=int, default=None, help="Crawl từ chương số")
    crawl_parser.add_argument("--to", dest="end", type=int, default=None, help="Crawl đến chương số")
    crawl_parser.add_argument("--force", action="store_true", help="Tải lại cả chương đã có raw")
    crawl_parser.add_argument("--retries", type=int, default=0, help="Số lần thử lại khi tải chương lỗi")
    sub.add_parser("translate", help="Dịch các chương đã crawl sang tiếng Việt")
    sub.add_parser("meta", help="Dịch metadata truyện (tên, tác giả, mô tả) sang tiếng Việt")
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

    args = parser.parse_args(argv)

    if args.command == "list":
        library = load_library(args.library)
        if not library.ebooks:
            print("Chưa có ebook nào trong library.yaml")
            return 0
        for slug, entry in library.ebooks.items():
            print(f"{slug}\t{entry.name or slug}\t{entry.config}")
        return 0

    config_path = args.config
    if args.ebook:
        try:
            config_path = _resolve_config_path(args.config, args.library, args.ebook)
        except KeyError as e:
            print(f"Lỗi: {e} trong {args.library}", file=sys.stderr)
            return 1

    try:
        cfg = load_config(config_path)
    except FileNotFoundError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        print("Gợi ý: copy config.example.yaml thành config.yaml rồi chỉnh sửa.",
              file=sys.stderr)
        return 1

    try:
        if args.command == "crawl":
            if args.force or args.retries or args.start is not None or args.end is not None:
                step_crawl_selected(
                    cfg,
                    start=args.start,
                    end=args.end,
                    force=args.force,
                    retries=args.retries,
                )
            else:
                step_crawl(cfg)
        elif args.command == "translate":
            if args.force or args.missing or args.chapter is not None or args.start is not None or args.end is not None:
                step_translate_selected(
                    cfg,
                    chapter=args.chapter,
                    start=args.start,
                    end=args.end,
                    force=args.force,
                    missing=args.missing,
                )
            else:
                step_translate(cfg)
        elif args.command == "meta":
            step_translate_meta(cfg, force=True)
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
