"""Giao diện dòng lệnh cho novel2epub."""
from __future__ import annotations

import argparse
import sys

import os

from .config import load_config, load_library, CrawlConfig
from .pipeline import (
    run_all,
    step_build,
    step_clean_toc_titles,
    step_cleanup_han_selected,
    step_crawl,
    step_crawl_selected,
    step_evaluate_translation,
    step_fetch_toc,
    step_reindex,
    step_translate,
    step_translate_selected,
)
from .storage import Storage
from .toc import apply_chapter_query, chapter_rows, parse_filter, parse_range, select_visible_range


DEFAULT_CONFIG_PATH = os.environ.get(
    "NOVEL2EPUB_DB",
    os.environ.get("NOVEL2EPUB_FILE", os.environ.get("NOVEL2EPUB_CONFIG", "novel2epub.db")),
)


def _coerce_wg_value(value: str):
    """Ép kiểu giá trị CLI `wireguard set` — số/bool tự nhận, còn lại là chuỗi."""
    low = value.strip().lower()
    if low in ("true", "yes", "on", "1"):
        return True
    if low in ("false", "no", "off", "0"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _wireguard_main(config: str, args) -> int:
    """Xử lý các lệnh con của `wireguard` — KHÔNG cần ebook, không lưu key."""
    from . import wireguard as wg_mod
    from .config import load_config

    if not os.path.exists(config):
        print(f"Lỗi: không tìm thấy DB {config}", file=sys.stderr)
        return 1
    try:
        wgcfg = load_config(config).wireguard
        action = args.wg_action

        if action == "config":
            for key, value in wg_mod.describe_config(wgcfg).items():
                display = repr(value) if isinstance(value, list) else value
                print(f"{key} = {display}")
            return 0

        if action == "status":
            print(f"wireguard.enabled = {wgcfg.enabled}")
            print(f"profiles_dir = {wgcfg.profiles_dir}")
            active = wg_mod.get_active(config)
            if active is None:
                print("active = (không có)")
            else:
                print(f"active = {active['filename']} ({active['id']})")
            rows = wg_mod.list_profiles(config)
            if not rows:
                print("(chưa có profile — dùng wireguard import hoặc wireguard provision)")
            for r in rows:
                print(f"  {r['filename']}\t{r['source']}\t{'on' if r['enabled'] else 'off'}\t"
                      f"{r['status'] or 'inactive'}\t{r['id']}")
            return 0

        if action == "set":
            if args.key.endswith("argv"):
                value = [v.strip() for v in args.value.split(",") if v.strip()]
            else:
                value = _coerce_wg_value(args.value)
            wg_mod.write_config(config, wg_mod.nested_update(args.key, value))
            print(f"Đã đặt wireguard.{args.key} = {value!r}")
            return 0

        if action == "list":
            if args.scan:
                wg_mod.discover_profiles(config, wgcfg.profiles_dir)
            rows = wg_mod.list_profiles(config)
            if not rows:
                print("(chưa có profile nào — dùng `wireguard import` hoặc `wireguard provision`)")
            for r in rows:
                print(f"{r['filename']}\t{r['source']}\t{'on' if r['enabled'] else 'off'}\t"
                      f"{r['status'] or 'inactive'}\t{r['id']}")
            return 0

        if action == "import":
            prof = wg_mod.import_profile(
                config, wgcfg.profiles_dir, args.path,
                source=args.source, name=args.name or None,
            )
            print(f"Đã nhập profile {prof['filename']} (id={prof['id']}).")
            return 0

        if action == "remove":
            ok = wg_mod.remove_profile(config, wgcfg.profiles_dir, args.selector)
            if not ok:
                print(f"Lỗi: không tìm thấy profile {args.selector!r}.", file=sys.stderr)
                return 1
            print("Đã xóa profile.")
            return 0

        if action in ("enable", "disable"):
            ok = wg_mod.set_enabled(config, args.selector, action == "enable")
            if not ok:
                print(f"Lỗi: không tìm thấy profile {args.selector!r}.", file=sys.stderr)
                return 1
            print(f"Đã {'bật' if action == 'enable' else 'tắt'} profile {args.selector!r}.")
            return 0

        if action == "activate":
            prof = wg_mod.activate_profile(config, wgcfg, args.selector)
            print(f"Đã kích hoạt profile {prof['filename']} (tunnel service thật).")
            return 0

        if action == "rotate":
            prof = wg_mod.rotate_profile(config, wgcfg)
            print(f"Đã rotate sang profile {prof['filename']} (tunnel service thật).")
            return 0

        if action == "provision":
            prof = wg_mod.provision_wgcf_profile(config, wgcfg, label=args.label)
            print(f"Đã cung cấp wgcf và nhập profile {prof['filename']} (id={prof['id']}).")
            return 0
    except wg_mod.WireGuardProfileError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
    return 1


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
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH, help="Đường dẫn file DB gộp (novel2epub.db)")
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
    sub.add_parser("toc", help="Lấy mục lục, không crawl nội dung chương")
    clean_toc_parser = sub.add_parser("clean-toc", help="Dọn từ rác kêu gọi độc giả (cầu nguyệt phiếu, 求月票…) khỏi tiêu đề chương")
    clean_toc_parser.add_argument("--apply", action="store_true", help="Ghi thay đổi (mặc định chỉ preview, không sửa)")
    chapters_parser = sub.add_parser("chapters", help="Liệt kê chương với sort/search/filter")
    chapters_parser.add_argument("--sort", default="source", choices=["source", "title", "raw", "translated"], help="Khóa sắp xếp")
    chapters_parser.add_argument("--desc", action="store_true", help="Đảo chiều sort")
    chapters_parser.add_argument("--search", default="", help="Tìm trong tiêu đề hiển thị hoặc URL chương")
    chapters_parser.add_argument("--filter", dest="filters", action="append", default=[], help="Lọc chương: raw:yes/no, translated:yes/no, missing:yes/no")
    evaluate_parser = sub.add_parser("evaluate", help="AI đánh giá glossary + bản dịch (chỉ xem, không sửa)")
    evaluate_parser.add_argument("--from", dest="start", type=int, default=None, help="Đánh giá từ chương số")
    evaluate_parser.add_argument("--to", dest="end", type=int, default=None, help="Đánh giá đến chương số")
    search_parser = sub.add_parser("search", help="Tìm kiếm tiểu thuyết trên các source")
    search_parser.add_argument("query", help="Tên tiểu thuyết cần tìm")
    search_parser.add_argument("--sources", default="", help="Chỉ tìm trên các source cụ thể (phân tách bằng dấu phẩy)")
    search_parser.add_argument("--limit", type=int, default=5, help="Số kết quả tối đa mỗi source (mặc định: 5)")
    search_parser.add_argument("--format", dest="output_format", default="text", choices=["text", "json"], help="Định dạng output")
    search_parser.add_argument("--select", type=int, default=None, help="Chọn kết quả theo số thứ tự (1-based) để tạo ebook")
    sub.add_parser("reindex", help="Đánh lại index theo thứ tự chapters trong manifest")
    sub.add_parser("build", help="Đóng gói EPUB từ các chương đã dịch")
    sub.add_parser("run", help="Chạy toàn bộ: crawl -> translate -> build")
    cleanup_parser = sub.add_parser("cleanup-han", help="Phát hiện và sửa chữ Hán còn sót trong bản dịch (mặc định Local MT)")
    cleanup_parser.add_argument("--engine", default="", choices=["", "local_mt", "openai"], help="Engine dọn Hán: local_mt (mặc định) hoặc openai. Trống = theo cấu hình ebook")
    cleanup_parser.add_argument("--force", action="store_true", help="Chạy lại dù chương đã được cleanup trước đó")
    cleanup_parser.add_argument("--chapter", type=int, default=None, help="Cleanup một chương cụ thể")
    cleanup_parser.add_argument("--from", dest="start", type=int, default=None, help="Cleanup từ chương số")
    cleanup_parser.add_argument("--to", dest="end", type=int, default=None, help="Cleanup đến chương số")
    cleanup_parser.add_argument("--sort", default="source", choices=["source", "title", "raw", "translated"], help="Sắp xếp danh sách chương trước khi chọn range")
    cleanup_parser.add_argument("--desc", action="store_true", help="Đảo chiều sort danh sách chương")
    cleanup_parser.add_argument("--search", default="", help="Tìm trong tiêu đề hiển thị hoặc URL chương")
    cleanup_parser.add_argument("--filter", dest="filters", action="append", default=[], help="Lọc chương: raw:yes/no, translated:yes/no, missing:yes/no")
    cleanup_parser.add_argument("--range", dest="visible_range", default="", help="Chọn range theo danh sách đang sort/filter, ví dụ 1:3")
    sub.add_parser("list", help="Liệt kê các ebook trong library")
    models_parser = sub.add_parser(
        "models",
        help="Liệt kê model khả dụng từ translate.openai.base_url (hỗ trợ OmniRoute, OpenAI, v.v.)",
    )
    models_parser.add_argument("--free", action="store_true", help="Chỉ hiện model free (chỉ áp dụng khi endpoint trả pricing info)")
    models_parser.add_argument("--format", dest="output_format", default="text", choices=["text", "json"], help="Định dạng output")
    backup_parser = sub.add_parser("backup", help="Sao lưu toàn bộ DB ra 1 file .db (nhất quán, an toàn khi đang chạy)")
    backup_parser.add_argument("--out", default="", help="Đường dẫn file backup (mặc định backups/<db>-<timestamp>.db)")
    restore_parser = sub.add_parser("restore", help="Phục hồi DB từ 1 file backup .db (ghi đè DB hiện tại)")
    restore_parser.add_argument("--from", dest="from_path", required=True, help="File backup .db nguồn")
    restore_parser.add_argument("--yes", action="store_true", help="Không hỏi xác nhận trước khi ghi đè")
    service_parser = sub.add_parser(
        "service",
        help="Đăng ký web server chạy nền khi khởi động máy (Windows Task Scheduler / Linux systemd)",
    )
    service_parser.add_argument("action", choices=["install", "uninstall", "status"])
    service_parser.add_argument("--host", default="127.0.0.1", help="Host uvicorn (mặc định 127.0.0.1)")
    service_parser.add_argument("--port", type=int, default=8010, help="Port uvicorn (mặc định 8010)")

    # ── WireGuard / wgcf — hoạt động ĐỘC LẬP, không cần ebook ─────────────
    wg = sub.add_parser(
        "wireguard",
        help="Quản lý profile WireGuard/wgcf (không cần ebook; KHÔNG lưu key trong DB)",
    )
    wg_sub = wg.add_subparsers(dest="wg_action", required=True)
    wg_sub.add_parser("config", help="Hiển thị cấu hình wireguard toàn cục (không chứa key)")
    wg_sub.add_parser("status", help="Trạng thái wireguard: active + danh sách profile (không chứa key)")
    set_parser = wg_sub.add_parser("set", help="Đặt 1 field cấu hình wireguard (không có key)")
    set_parser.add_argument("key", help="Ví dụ: enabled, profiles_dir, wgcf.output, wgcf.argv")
    set_parser.add_argument("value", help="Giá trị; với wgcf.argv dùng danh sách cách nhau bởi dấu phẩy")
    list_parser = wg_sub.add_parser("list", help="Liệt kê profile")
    list_parser.add_argument("--scan", action="store_true", help="Đăng ký các file .conf hợp lệ chưa có trong DB")
    import_parser = wg_sub.add_parser("import", help="Nhập profile từ file (xác thực + copy vào profiles_dir)")
    import_parser.add_argument("path", help="File cấu hình .conf nguồn")
    import_parser.add_argument("--name", default="", help="Tên file ưu tiên trong profiles_dir")
    import_parser.add_argument("--source", default="manual", help="Gắn nhãn nguồn")
    remove_parser = wg_sub.add_parser("remove", help="Xóa profile theo id hoặc filename")
    remove_parser.add_argument("selector")
    enable_parser = wg_sub.add_parser("enable", help="Bật profile")
    enable_parser.add_argument("selector")
    disable_parser = wg_sub.add_parser("disable", help="Tắt profile")
    disable_parser.add_argument("selector")
    activate_parser = wg_sub.add_parser("activate", help="Kích hoạt 1 profile (metadata active)")
    activate_parser.add_argument("selector")
    wg_sub.add_parser("rotate", help="Kích hoạt profile kế tiếp (round-robin xác định)")
    provision_parser = wg_sub.add_parser("provision", help="Chạy wgcf trong cwd tạm rồi nhập profile sinh ra")
    provision_parser.add_argument("--label", default="", help="Tên file ưu tiên cho profile sinh ra")

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

    if args.command == "service":
        from .service import service_main

        return service_main(args.action, args.host, args.port)

    if args.command == "backup":
        from .backup import backup_db, timestamped_backup

        db_path = args.config
        if not os.path.exists(db_path):
            print(f"Lỗi: không tìm thấy DB {db_path}", file=sys.stderr)
            return 1
        try:
            if args.out:
                out = backup_db(db_path, args.out)
            else:
                out = timestamped_backup(db_path, os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups"))
        except (OSError, RuntimeError) as e:
            print(f"Lỗi backup: {e}", file=sys.stderr)
            return 1
        print(f"Đã sao lưu -> {out}")
        return 0

    if args.command == "restore":
        from .backup import restore_db, validate_backup_file

        ok, message = validate_backup_file(args.from_path)
        if not ok:
            print(f"Lỗi: {message}", file=sys.stderr)
            return 1
        if not args.yes:
            print(f"Sắp GHI ĐÈ {args.config} bằng {args.from_path} ({message}).")
            print("DB hiện tại sẽ được tự sao lưu ra <db>.pre-restore-<timestamp> trước.")
            resp = input("Tiếp tục? [y/N] ").strip().lower()
            if resp not in ("y", "yes"):
                print("Đã hủy.")
                return 1
        try:
            restore_db(args.from_path, args.config)
        except (OSError, ValueError) as e:
            print(f"Lỗi restore: {e}", file=sys.stderr)
            return 1
        print(f"Đã phục hồi {args.config} từ {args.from_path}.")
        return 0

    if args.command == "search":
        from .search import search_all
        from .sources import load_presets

        # Sources nay nằm trong chính DB gộp (không còn sources.yaml riêng).
        presets = load_presets(args.config)
        source_names = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None

        response = search_all(
            presets,
            args.query,
            source_names=source_names,
            enrich=args.select is not None,
            max_workers=5,
        )

        if response.errors:
            for err in response.errors:
                print(f"[{err.source_name}] Lỗi: {err.message}", file=sys.stderr)

        if not response.results:
            print("Không tìm thấy kết quả nào.")
            return 1

        if args.output_format == "json":
            import json
            results = []
            for r in response.results:
                results.append({
                    "title": r.title,
                    "author": r.author,
                    "url": r.url,
                    "source_name": r.source_name,
                    "cover_url": r.cover_url,
                    "chapter_count": r.chapter_count,
                    "description": r.description,
                })
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0

        for i, r in enumerate(response.results, 1):
            author = f" — {r.author}" if r.author else ""
            chapters = f" ({r.chapter_count} ch)" if r.chapter_count else ""
            print(f"[{r.source_name}] {r.title}{author}{chapters} — {r.url}")

        if args.select is not None:
            idx = args.select - 1
            if idx < 0 or idx >= len(response.results):
                print(f"Lỗi: --select {args.select} không hợp lệ (có {len(response.results)} kết quả).", file=sys.stderr)
                return 1

            selected = response.results[idx]
            print(f"\nĐã chọn: {selected.title} ({selected.source_name})")

            print(f"  URL: {selected.url}")
            print(f"  Tác giả: {selected.author or 'N/A'}")
            print(f"  Số chương: {selected.chapter_count or 'N/A'}")
            print("\nĐể tạo ebook mới, hãy thêm vào novel2epub.yaml:")
            print(f"  ebooks:")
            print(f"    <slug>:")
            print(f"      novel:")
            print(f"        title: \"{selected.title}\"")
            print(f"        author: \"{selected.author}\"")
            print(f"      crawl:")
            print(f"        toc_url: \"{selected.url}\"")

        return 0

    if args.command == "models":
        from . import openai_client
        from .config import load_config

        try:
            cfg = load_config(args.config, args.ebook)
        except (FileNotFoundError, KeyError) as e:
            print(f"Lỗi: {e}", file=sys.stderr)
            return 1
        oa = cfg.translate.openai
        if not oa.base_url:
            print("Lỗi: translate.openai.base_url chưa được cấu hình.", file=sys.stderr)
            return 1
        try:
            model_ids = openai_client.list_models(oa.base_url, oa.api_key)
        except Exception as e:
            print(f"Lỗi gọi GET {oa.base_url}/models: {e}", file=sys.stderr)
            return 1

        # Best-effort filter "--free": model id chứa "free/" hoặc nằm trong
        # list known free providers của OmniRoute. Không chính xác 100% nếu
        # endpoint không trả pricing — dùng như gợi ý.
        free_prefixes = ("kr/", "kf/", "qdr/", "pollinations/", "longcat/", "kiro/", "qoder/")
        if args.free:
            model_ids = [
                m for m in model_ids
                if m.startswith("free/") or any(m.startswith(p) for p in free_prefixes)
            ]

        if args.output_format == "json":
            import json
            print(json.dumps({"models": model_ids, "count": len(model_ids)}, ensure_ascii=False, indent=2))
        else:
            print(f"# {len(model_ids)} model từ {oa.base_url}")
            for m in model_ids:
                print(m)
        return 0

    if args.command == "wireguard":
        return _wireguard_main(args.config, args)

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
        elif args.command == "cleanup-han":
            selected_indexes = _selected_indexes_from_args(cfg, args)
            step_cleanup_han_selected(
                cfg,
                chapter=args.chapter,
                start=args.start,
                end=args.end,
                force=args.force,
                selected_indexes=selected_indexes,
                engine=(args.engine or None),
            )
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
        elif args.command == "toc":
            step_fetch_toc(cfg)
        elif args.command == "clean-toc":
            result = step_clean_toc_titles(cfg, apply=args.apply)
            for c in result["changes"]:
                print(f"  [{c['index']}] {c['old']!r} -> {c['new']!r}")
            verb = "Đã ghi" if args.apply else "Preview (dùng --apply để ghi)"
            print(f"{verb}: {result['changed']}/{result['scanned']} tiêu đề dính từ rác.")
        elif args.command == "chapters":
            _print_chapters(cfg, args)
        elif args.command == "evaluate":
            step_evaluate_translation(cfg, start=args.start, end=args.end)
        elif args.command == "reindex":
            step_reindex(cfg)
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
