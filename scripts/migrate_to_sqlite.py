"""Di chuyển cài đặt CŨ (file rời) sang DB SQLite thống nhất — chạy 1 lần.

Đọc TRỰC TIẾP layout file cũ (không qua Storage/load_config đã viết lại để
dùng DB) rồi ghi tất cả vào 1 file `novel2epub.db`:

    novel2epub.yaml        -> settings + sources + ebooks
    sources.yaml           -> sources (nếu tách riêng)
    data/<slug>/
        manifest.json      -> ebooks + chapters
        raw/NNNN.md        -> chapters.raw_text
        translated/NNNN.md -> chapters.translated_text
        translated_mt/NNNN.md -> chapters.translated_mt_text
        translation_meta/NNNN.json -> chapters.meta_json (+ _cost_summary/_glossary_conflicts -> ebook_extra_json)
        glossary/*.txt     -> glossary_entries
        notes.json         -> notes
        cover.*            -> ebook_covers
    workspace/.n2e/
        queue_history.json -> job_queue_history
        automations.yaml   -> automations
        library_state.json -> ebooks.archived

Chạy:
    python scripts/migrate_to_sqlite.py [--yaml novel2epub.yaml] [--db novel2epub.db]
                                        [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novel2epub.db import get_connection, init_schema  # noqa: E402

_SETTINGS_SECTIONS = ("novel", "crawl", "translate", "ai", "output", "queue")
_NOVEL_SCALAR = (
    "title", "author", "description", "language", "publisher", "pubdate",
    "date_added", "series", "series_index", "identifier", "cover_url",
)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_glossary_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    source, rest = line.split("=", 1)
    source = source.strip()
    if "|" in rest:
        target, note = rest.split("|", 1)
        target, note = target.strip(), note.strip()
    else:
        target, note = rest.strip(), ""
    if not source or not target:
        return None
    return source, target, note


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", default="novel2epub.yaml", help="File config gộp cũ")
    parser.add_argument("--sources", default="sources.yaml", help="File sources cũ (nếu tách riêng)")
    parser.add_argument("--data-dir", default="", help="Ghi đè output.data_dir (mặc định đọc từ config)")
    parser.add_argument("--db", default="novel2epub.db", help="File DB đích")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ đếm, không ghi DB")
    parser.add_argument("--force", action="store_true", help="Ghi đè DB đích nếu đã tồn tại")
    args = parser.parse_args()

    yaml_path = Path(args.yaml)
    db_path = Path(args.db)

    if not yaml_path.exists():
        print(f"Không tìm thấy {yaml_path} — không có gì để migrate.", file=sys.stderr)
        return 1
    if db_path.exists() and not args.force and not args.dry_run:
        print(f"{db_path} đã tồn tại — dùng --force để ghi đè (hoặc backup trước).", file=sys.stderr)
        return 1

    raw = _load_yaml(yaml_path)
    defaults = raw.get("defaults") or {}
    sources = dict(raw.get("sources") or {})
    ebooks_raw = raw.get("ebooks") or {}

    # sources.yaml tách riêng (nếu có) — merge vào, ưu tiên khối trong file gộp.
    sources_path = Path(args.sources)
    if sources_path.exists() and sources_path != yaml_path:
        standalone = _load_yaml(sources_path)
        standalone = standalone.get("sources") or standalone
        for name, item in standalone.items():
            sources.setdefault(name, item)

    base_dir = yaml_path.resolve().parent
    data_dir_name = args.data_dir or (defaults.get("output") or {}).get("data_dir", "data")
    data_dir = Path(data_dir_name)
    if not data_dir.is_absolute():
        data_dir = (base_dir / data_dir).resolve()
    workspace_dir = base_dir / ".n2e"
    if not workspace_dir.exists():
        workspace_dir = base_dir / "workspace" / ".n2e"

    counts = {"ebooks": 0, "chapters": 0, "glossary": 0, "notes": 0, "covers": 0, "automations": 0, "history": 0, "sources": len(sources)}
    mismatches: list[str] = []

    # Backup toàn bộ nguồn TRƯỚC khi động vào gì (belt-and-suspenders — transaction
    # chỉ bảo vệ phía DB, không bảo vệ khỏi bug đọc sai file nguồn).
    if not args.dry_run:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_root = base_dir / f"pre-sqlite-migration-backup-{stamp}"
        backup_root.mkdir(parents=True, exist_ok=True)
        for src in (yaml_path, sources_path, data_dir, workspace_dir):
            if src.exists():
                dest = backup_root / src.name
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest)
        print(f"Đã backup nguồn -> {backup_root}")
        if db_path.exists():
            db_path.unlink()

    conn = get_connection(str(db_path)) if not args.dry_run else get_connection(":memory:")
    try:
        init_schema(conn)
        with conn:
            # settings
            conn.execute(
                """
                INSERT INTO settings (id, novel_json, crawl_json, translate_json, ai_json, output_json, queue_json)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    novel_json=excluded.novel_json, crawl_json=excluded.crawl_json,
                    translate_json=excluded.translate_json, ai_json=excluded.ai_json,
                    output_json=excluded.output_json, queue_json=excluded.queue_json
                """,
                tuple(json.dumps(defaults.get(s) or {}, ensure_ascii=False) for s in _SETTINGS_SECTIONS),
            )
            # sources
            for name, item in sources.items():
                data = dict(item or {})
                data.pop("name", None)
                conn.execute(
                    "INSERT OR REPLACE INTO sources (name, data_json) VALUES (?, ?)",
                    (name, json.dumps(data, ensure_ascii=False)),
                )
            # archived slugs
            archived = set()
            ls_path = workspace_dir / "library_state.json"
            if ls_path.exists():
                try:
                    archived = set((json.loads(ls_path.read_text(encoding="utf-8")) or {}).get("archived", []))
                except (OSError, json.JSONDecodeError):
                    archived = set()

            # ebooks + chapters + glossary + notes + covers
            for slug, block in ebooks_raw.items():
                block = dict(block or {})
                novel = dict(block.get("novel") or {})
                crawl_over = dict(block.get("crawl") or {})
                output_over = dict(block.get("output") or {})
                storage_root = data_dir / slug
                manifest = {}
                mpath = storage_root / "manifest.json"
                if mpath.exists():
                    try:
                        manifest = json.loads(mpath.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        manifest = {}

                def mv(key, default=""):
                    return manifest.get(key) or novel.get(key) or default

                conn.execute(
                    """
                    INSERT INTO ebooks
                        (slug, source_preset, archived, title, author, description, language,
                         publisher, pubdate, date_added, subjects_json, series, series_index,
                         identifier, cover_url, source_url, cover_file, title_note,
                         metadata_missing_json, curated_fields_json,
                         crawl_overrides_json, output_overrides_json, epub_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        source_preset=excluded.source_preset, archived=excluded.archived,
                        title=excluded.title, author=excluded.author, description=excluded.description
                    """,
                    (
                        slug, block.get("source") or None,
                        1 if slug in archived else 0,
                        mv("title") or block.get("name", ""), mv("author"), mv("description"),
                        novel.get("language", "vi"), novel.get("publisher", ""), novel.get("pubdate", ""),
                        novel.get("date_added", ""), json.dumps(novel.get("subjects", []), ensure_ascii=False),
                        novel.get("series", ""), novel.get("series_index", ""),
                        novel.get("identifier", ""), mv("cover_url"),
                        manifest.get("source_url", ""), manifest.get("cover_file", ""),
                        manifest.get("title_note", ""),
                        json.dumps(manifest.get("metadata_missing", []), ensure_ascii=False),
                        json.dumps(manifest.get("curated_fields", []), ensure_ascii=False),
                        json.dumps(crawl_over, ensure_ascii=False),
                        json.dumps(output_over, ensure_ascii=False),
                        output_over.get("epub_path", ""),
                    ),
                )
                counts["ebooks"] += 1

                # chapters + content
                for ch in manifest.get("chapters", []):
                    idx = ch.get("index", 0)
                    stem = f"{idx:04d}"
                    raw_text = _read_file(storage_root / "raw" / f"{stem}.md")
                    tr_text = _read_file(storage_root / "translated" / f"{stem}.md")
                    mt_text = _read_file(storage_root / "translated_mt" / f"{stem}.md")
                    meta_json = "{}"
                    mp = storage_root / "translation_meta" / f"{stem}.json"
                    if mp.exists():
                        try:
                            meta_json = json.dumps(json.loads(mp.read_text(encoding="utf-8")), ensure_ascii=False)
                        except (OSError, json.JSONDecodeError):
                            meta_json = "{}"
                    conn.execute(
                        """
                        INSERT INTO chapters
                            (ebook_slug, idx, url, title, title_zh, title_note, missing_fields_json,
                             duplicate_of, last_action_status, skipped, raw_text, translated_text,
                             translated_mt_text, meta_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            slug, idx, ch.get("url", ""), ch.get("title", ""), ch.get("title_zh", ""),
                            ch.get("title_note", ""), json.dumps(ch.get("missing_fields", []), ensure_ascii=False),
                            ch.get("duplicate_of"), ch.get("last_action_status", ""),
                            1 if ch.get("skipped") else 0, raw_text, tr_text, mt_text, meta_json,
                        ),
                    )
                    counts["chapters"] += 1
                    # checksum spot-check
                    if raw_text is not None:
                        disk = (storage_root / "raw" / f"{stem}.md").read_text(encoding="utf-8")
                        if _sha(disk) != _sha(raw_text):
                            mismatches.append(f"{slug}/raw/{stem}")

                # glossary
                for list_name in ("names.txt", "vietphrase.txt"):
                    gpath = storage_root / "glossary" / list_name
                    if not gpath.exists():
                        continue
                    seen = {}
                    order = []
                    for line in gpath.read_text(encoding="utf-8").splitlines():
                        parsed = _parse_glossary_line(line)
                        if not parsed:
                            continue
                        s, t, n = parsed
                        if s not in seen:
                            order.append(s)
                        seen[s] = (t, n)
                    for pos, s in enumerate(order):
                        t, n = seen[s]
                        conn.execute(
                            "INSERT OR REPLACE INTO glossary_entries (ebook_slug, list_name, source, target, note, position) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (slug, list_name, s, t, n, pos),
                        )
                        counts["glossary"] += 1

                # notes
                npath = storage_root / "notes.json"
                if npath.exists():
                    try:
                        notes = json.loads(npath.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        notes = []
                    for note in notes if isinstance(notes, list) else []:
                        conn.execute(
                            "INSERT INTO notes (ebook_slug, data_json) VALUES (?, ?)",
                            (slug, json.dumps(note, ensure_ascii=False)),
                        )
                        counts["notes"] += 1

                # extra json (cost summary / glossary conflicts)
                for fname, key in (("_cost_summary.json", "cost_summary"), ("_glossary_conflicts.json", "glossary_conflicts")):
                    xp = storage_root / "translation_meta" / fname
                    if xp.exists():
                        try:
                            data = json.loads(xp.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            continue
                        conn.execute(
                            "INSERT OR REPLACE INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, ?, ?)",
                            (slug, key, json.dumps(data, ensure_ascii=False)),
                        )

                # cover
                for cover in sorted(storage_root.glob("cover.*")):
                    if cover.is_file():
                        ext = cover.suffix.lstrip(".").lower() or "jpg"
                        conn.execute(
                            "INSERT OR REPLACE INTO ebook_covers (ebook_slug, ext, content) VALUES (?, ?, ?)",
                            (slug, ext, cover.read_bytes()),
                        )
                        counts["covers"] += 1
                        break

            # automations
            apath = workspace_dir / "automations.yaml"
            if apath.exists():
                autos = (_load_yaml(apath) or {}).get("automations") or {}
                for aid, item in autos.items():
                    item = dict(item or {})
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO automations
                            (id, ebook, steps_json, schedule, enabled, last_run_at,
                             last_run_outcome, last_run_error, last_run_stats_json,
                             crawl_workers, translate_workers, created_at,
                             translate_threshold, cleanup_threshold, publish_threshold, build_threshold)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            aid, item.get("ebook", ""),
                            json.dumps(item.get("steps", ["build"]), ensure_ascii=False),
                            item.get("schedule", "manual"), 1 if item.get("enabled", True) else 0,
                            item.get("last_run_at", ""), item.get("last_run_outcome", ""),
                            item.get("last_run_error", ""),
                            json.dumps(item.get("last_run_stats", {}), ensure_ascii=False),
                            int(item.get("crawl_workers", 4) or 4), int(item.get("translate_workers", 4) or 4),
                            item.get("created_at", ""),
                            int(item.get("translate_threshold", 0) or 0), int(item.get("cleanup_threshold", 0) or 0),
                            int(item.get("publish_threshold", 0) or 0), int(item.get("build_threshold", 0) or 0),
                        ),
                    )
                    counts["automations"] += 1

            # queue history (chỉ history, KHÔNG migrate pending — job dở dang qua
            # cutover storage engine rất rủi ro; để chúng chạy xong/hủy trước khi migrate).
            hpath = workspace_dir / "queue_history.json"
            if hpath.exists():
                try:
                    hist = json.loads(hpath.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    hist = []
                for item in hist if isinstance(hist, list) else []:
                    conn.execute(
                        "INSERT OR REPLACE INTO job_queue_history (id, data_json, ended_at) VALUES (?, ?, ?)",
                        (item.get("id", ""), json.dumps(item, ensure_ascii=False), item.get("ended_at")),
                    )
                    counts["history"] += 1

            if mismatches:
                raise RuntimeError(
                    f"Checksum lệch ở {len(mismatches)} chương (vd {mismatches[:3]}) — HỦY migrate."
                )
    finally:
        if args.dry_run:
            conn.close()

    if args.dry_run:
        print("[dry-run] Không ghi DB. Số liệu sẽ migrate:")
    else:
        conn.close()
        print(f"Đã ghi {db_path}. Số liệu:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if not args.dry_run:
        pending = workspace_dir / "queue_pending.json"
        if pending.exists():
            print("\nCẢNH BÁO: có queue_pending.json — job đang dở KHÔNG được migrate.")
            print("Hãy để chúng chạy xong hoặc hủy trước khi dùng DB mới.")
        print("\nKiểm tra DB rồi mới xóa: novel2epub.yaml, sources.yaml, data/, workspace/.n2e/")
    return 0


def _read_file(path: Path) -> str | None:
    """Đọc file text; trả None nếu KHÔNG tồn tại (phân biệt "chưa có" với rỗng)."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
