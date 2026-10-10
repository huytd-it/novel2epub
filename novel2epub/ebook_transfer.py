"""Xuat/nhap ebook giua hai app novel2epub (chuyen app).

Package la file `.zip` (duoi goi y `.n2e.zip`) chua JSON thuan + bia + EPUB
tuy chon, du de dung lai ebook tren app khac va tiep tuc crawl/dich/build:

- `package.json`: metadata package + thong tin ebook (novel fields, source
  preset, cac khoi overrides, counts)
- `chapters.json`: full noi dung chuong (raw, ca hai nhanh dich, tieu de
  nhanh, snapshot MT, meta, active_branch...)
- `glossary.json`, `characters.json`, `relations.json`, `notes.json`,
  `entity_overrides.json`, `extra_json.json`: du lieu phu theo ebook
- `automations.json`: workflow automation (tao id moi khi nhap)
- `cover.bin` + `cover.json`: anh bia
- `book.epub`: EPUB da build (chi khi export voi `include_epub=True`)

Co y KHONG mang theo: job queue, log, session, secret Reader (nam trong
global settings), cac bang dataset canonical (`chapter_revisions`,
`chapter_source_revisions`, segments...) — chay `dataset-backfill` tren app
dich de dung lai. `translated_updated_at` khong khoi phuc chinh xac (nhan
lai moc hien tai khi ghi).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_FORMAT = "novel2epub-ebook-transfer"
PACKAGE_VERSION = 1

_EXTRA_KEYS = (
    "glossary_pending",
    "glossary_conflicts",
    "characters_pending",
    "cost_summary",
)


def _storage(data_dir: str | Path, slug: str):
    from .storage import Storage

    return Storage(data_dir, slug)


def export_ebook_dict(data_dir: str | Path, slug: str) -> dict[str, Any]:
    """Doc toan bo du lieu per-ebook cua `slug` thanh dict thuan JSON."""
    storage = _storage(data_dir, slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise KeyError(f"Khong co ebook {slug!r}.")
    conn = storage.conn
    row = conn.execute("SELECT * FROM ebooks WHERE slug = ?", (slug,)).fetchone()

    def _j(value: Any, default: Any):
        if not value:
            return default
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default

    ebook = {
        "slug": manifest.slug,
        "title": manifest.title,
        "author": manifest.author,
        "description": manifest.description,
        "cover_url": manifest.cover_url,
        "cover_file": manifest.cover_file,
        "title_note": manifest.title_note,
        "metadata_missing": list(manifest.metadata_missing or []),
        "curated_fields": list(manifest.curated_fields or []),
        "source_url": manifest.source_url,
        "source_preset": (row["source_preset"] if row else None) or "",
        "language": (row["language"] if row else None) or "vi",
        "publisher": (row["publisher"] if row else None) or "",
        "pubdate": (row["pubdate"] if row else None) or "",
        "series": (row["series"] if row else None) or "",
        "series_index": (row["series_index"] if row else None) or "",
        "identifier": (row["identifier"] if row else None) or "",
        "raw_title": (row["raw_title"] if row else None) or "",
        "raw_author": (row["raw_author"] if row else None) or "",
        "raw_description": (row["raw_description"] if row else None) or "",
        "crawl_overrides": _j(row["crawl_overrides_json"], {}) if row else {},
        "output_overrides": _j(row["output_overrides_json"], {}) if row else {},
        "reader_overrides": _j(row["reader_overrides_json"], {}) if row else {},
        "translate_overrides": _j(row["translate_overrides_json"], {}) if row else {},
        "ai_overrides": _j(row["ai_overrides_json"], {}) if row else {},
    }

    from .storage import Chapter

    chapters: list[dict[str, Any]] = []
    for ch in manifest.chapters:
        probe = Chapter(index=ch.index, url=ch.url)
        chapters.append({
            "index": ch.index,
            "url": ch.url,
            "title": ch.title,
            "title_zh": ch.title_zh,
            "title_note": ch.title_note,
            "missing_fields": list(ch.missing_fields or []),
            "duplicate_of": ch.duplicate_of,
            "last_action_status": ch.last_action_status,
            "skipped": bool(ch.skipped),
            "crawl_pages": storage.crawl_pages(probe),
            "raw": storage.read_raw(probe),
            "ai_text": storage.read_branch_text(probe, "ai"),
            "ai_title": storage.read_branch_title(probe, "ai"),
            "ai_title_zh": storage.read_branch_title_zh(probe, "ai"),
            "ai_mt": storage.read_branch_mt_snapshot(probe, "ai"),
            "localmt_text": storage.read_branch_text(probe, "local_mt"),
            "localmt_title": storage.read_branch_title(probe, "local_mt"),
            "localmt_title_zh": storage.read_branch_title_zh(probe, "local_mt"),
            "localmt_mt": storage.read_branch_mt_snapshot(probe, "local_mt"),
            "active_branch": storage.active_branch(probe),
            "meta": storage.read_meta(probe) if storage.has_meta(probe) else {},
        })

    glossary = {
        name: [[s, t, n] for s, t, n in storage.read_glossary_entries(name)]
        for name in ("names.txt", "vietphrase.txt")
    }
    characters = [list(c) for c in storage.read_character_entries()]
    relations = [list(r) for r in storage.read_relation_entries()]
    notes = storage.read_notes()
    entity_overrides = storage.export_entity_overrides()
    extra = {k: storage.read_extra_json(k) for k in _EXTRA_KEYS}
    extra = {k: v for k, v in extra.items() if v is not None}
    automations = [
        dict(r)
        for r in conn.execute(
            "SELECT steps_json, schedule, enabled, crawl_workers, translate_workers, "
            "translate_threshold, cleanup_threshold, publish_threshold, "
            "build_threshold FROM automations WHERE ebook = ?",
            (slug,),
        ).fetchall()
    ]
    cover = storage.read_cover_bytes()

    has_raw = sum(1 for c in chapters if c["raw"])
    has_translated = sum(1 for c in chapters if c["ai_text"] or c["localmt_text"])
    return {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_slug": slug,
        "ebook": ebook,
        "chapters": chapters,
        "glossary": glossary,
        "characters": characters,
        "relations": relations,
        "notes": notes,
        "entity_overrides": entity_overrides,
        "extra_json": extra,
        "automations": automations,
        "cover": {"ext": cover[1], "size": len(cover[0])} if cover else None,
        "_cover_bytes": cover[0] if cover else None,
        "counts": {
            "chapters": len(chapters),
            "has_raw": has_raw,
            "has_translated": has_translated,
            "glossary": sum(len(v) for v in glossary.values()),
            "characters": len(characters),
            "relations": len(relations),
            "notes": len(notes),
            "entity_overrides": len(entity_overrides),
            "has_cover": cover is not None,
        },
    }


def build_transfer_zip(
    data_dir: str | Path,
    slug: str,
    *,
    include_epub: bool = False,
    epub_path: str | Path | None = None,
) -> bytes:
    """Goi ebook thanh bytes `.zip` de tai ve / sang app khac."""
    data = export_ebook_dict(data_dir, slug)
    cover_bytes = data.pop("_cover_bytes")
    cover_meta = data.pop("cover")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("package.json", json.dumps(data, ensure_ascii=False, indent=2))
        if cover_bytes is not None and cover_meta is not None:
            zf.writestr("cover.json", json.dumps(cover_meta, ensure_ascii=False))
            zf.writestr("cover.bin", cover_bytes)
        if include_epub and epub_path:
            p = Path(epub_path)
            if p.exists() and p.is_file():
                zf.write(p, arcname="book.epub")
    return buf.getvalue()


def _read_package(zip_bytes: bytes) -> tuple[dict[str, Any], set[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("File khong phai package ebook (.zip) hop le.") from exc
    names = set(zf.namelist())
    if "package.json" not in names:
        raise ValueError("Thieu package.json — khong phai file xuat tu novel2epub.")
    try:
        data = json.loads(zf.read("package.json").decode("utf-8"))
    except Exception as exc:
        raise ValueError("package.json hong, khong doc duoc.") from exc
    if data.get("format") != PACKAGE_FORMAT:
        raise ValueError("File .zip nay khong phai package ebook cua novel2epub.")
    if int(data.get("version", 0)) != PACKAGE_VERSION:
        raise ValueError(
            f"Phien ban package {data.get('version')!r} khong duoc ho tro "
            f"(can v{PACKAGE_VERSION})."
        )
    return data, names


def preview_transfer_zip(zip_bytes: bytes) -> dict[str, Any]:
    """Doc summary tu package ma khong cham DB — cho UI duyet truoc khi nhap."""
    data, names = _read_package(zip_bytes)
    ebook = data.get("ebook") or {}
    counts = data.get("counts") or {}
    chapters = data.get("chapters") or []
    return {
        "slug": str(ebook.get("slug") or data.get("source_slug") or ""),
        "title": str(ebook.get("title") or ""),
        "author": str(ebook.get("author") or ""),
        "source_preset": ebook.get("source_preset") or "",
        "source_url": str(ebook.get("source_url") or ""),
        "chapters": int(counts.get("chapters", len(chapters))),
        "has_raw": int(counts.get("has_raw", 0)),
        "has_translated": int(counts.get("has_translated", 0)),
        "glossary": int(counts.get("glossary", 0)),
        "characters": int(counts.get("characters", 0)),
        "relations": int(counts.get("relations", 0)),
        "notes": int(counts.get("notes", 0)),
        "entity_overrides": int(counts.get("entity_overrides", 0)),
        "has_cover": bool(counts.get("has_cover", False) or "cover.bin" in names),
        "has_epub": "book.epub" in names,
        "exported_at": data.get("exported_at") or "",
    }


def import_transfer_zip(
    db_path: str | Path,
    data_dir: str | Path,
    zip_bytes: bytes,
    *,
    slug: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Nhap package vao DB. Tra `{slug, counts, warnings}`.

    - `slug` trong: giu slug goc trong package.
    - Slug da ton tai + `overwrite=False`: raise FileExistsError.
    - `overwrite=True`: xoa sach du lieu cu cua slug dich roi ghi de.
    """
    import zipfile as _zf

    zf = _zf.ZipFile(io.BytesIO(zip_bytes))
    data, names = _read_package(zip_bytes)
    ebook: dict[str, Any] = data.get("ebook") or {}
    target = (slug or str(ebook.get("slug") or "")).strip()
    if not target:
        raise ValueError("Package thieu slug — hay nhap slug thu cong.")
    if not target.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Slug {target!r} khong hop le.")

    from .config_writer import add_ebook, update_ebook
    from .db import get_thread_connection
    from .storage import Chapter, Manifest

    conn = get_thread_connection(db_path)
    exists = conn.execute("SELECT 1 FROM ebooks WHERE slug = ?", (target,)).fetchone()
    if exists is not None and not overwrite:
        raise FileExistsError(f"Ebook '{target}' da ton tai.")

    warnings: list[str] = []
    source_preset = (ebook.get("source_preset") or "").strip() or None
    if source_preset:
        has_preset = conn.execute(
            "SELECT 1 FROM sources WHERE name = ?", (source_preset,)
        ).fetchone()
        if has_preset is None:
            warnings.append(
                f"Nguon '{source_preset}' chua co tren app nay — ebook van duoc nhap, "
                "crawl se dung cau hinh mac dinh cho toi khi tao preset."
            )
            # DB legacy còn FK ebooks→sources (xem config_writer): giữ liên
            # kết bằng stub rỗng thay vì để add_ebook nổ IntegrityError.
            # DB mới không FK → no-op, ref treo được giữ nguyên.
            from .config_writer import _ensure_source_stub_for_legacy_fk

            with conn:
                _ensure_source_stub_for_legacy_fk(conn, source_preset)

    if exists is not None:
        # Ghi de: xoa sach du lieu cu (khong phu thuoc FK cascade).
        with conn:
            for table, col in (
                ("chapters", "ebook_slug"),
                ("glossary_entries", "ebook_slug"),
                ("characters", "ebook_slug"),
                ("character_relations", "ebook_slug"),
                ("notes", "ebook_slug"),
                ("ebook_covers", "ebook_slug"),
                ("ebook_extra_json", "ebook_slug"),
                ("ebook_entity_overrides", "ebook_slug"),
                ("ai_revisions", "ebook_slug"),
            ):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (target,))
                except Exception:
                    pass
            conn.execute("DELETE FROM automations WHERE ebook = ?", (target,))

    toc_url = str((ebook.get("crawl_overrides") or {}).get("toc_url", ""))
    add_ebook(
        db_path, target,
        title=str(ebook.get("title") or ""),
        author=str(ebook.get("author") or ""),
        toc_url=toc_url,
        source_name=source_preset or "",
    )
    novel_extra: dict[str, Any] = {}
    for key in (
        "description", "language", "publisher", "pubdate", "series",
        "series_index", "identifier", "cover_url", "raw_title", "raw_author",
        "raw_description",
    ):
        value = ebook.get(key)
        if value:
            novel_extra[key] = value
    if novel_extra:
        update_ebook(db_path, target, {"novel": novel_extra})
    for section, payload in (
        ("crawl", ebook.get("crawl_overrides") or {}),
        ("output", ebook.get("output_overrides") or {}),
        ("reader", ebook.get("reader_overrides") or {}),
        ("translate", ebook.get("translate_overrides") or {}),
        ("ai", ebook.get("ai_overrides") or {}),
    ):
        payload = {k: v for k, v in payload.items() if k != "toc_url" or section != "crawl"}
        if payload:
            update_ebook(db_path, target, {section: payload})
    # Metadata phu cua manifest (cover_url mo ta them, ghi chu...).
    update_ebook(db_path, target, {"novel": {
        "description": str(ebook.get("description") or ""),
        "cover_url": str(ebook.get("cover_url") or ""),
    }})

    storage = _storage(data_dir, target)
    storage.ensure_dirs()

    chapters_in: list[dict[str, Any]] = data.get("chapters") or []
    manifest = Manifest(
        slug=target,
        source_url=str(ebook.get("source_url") or ""),
        title=str(ebook.get("title") or ""),
        author=str(ebook.get("author") or ""),
        description=str(ebook.get("description") or ""),
        cover_url=str(ebook.get("cover_url") or ""),
        cover_file=str(ebook.get("cover_file") or ""),
        title_note=str(ebook.get("title_note") or ""),
        metadata_missing=list(ebook.get("metadata_missing") or []),
        curated_fields=list(ebook.get("curated_fields") or []),
        chapters=[
            Chapter(
                index=int(c.get("index", 0)),
                url=str(c.get("url") or ""),
                title=str(c.get("title") or ""),
                title_zh=str(c.get("title_zh") or ""),
                title_note=str(c.get("title_note") or ""),
                missing_fields=list(c.get("missing_fields") or []),
                duplicate_of=c.get("duplicate_of"),
                last_action_status=str(c.get("last_action_status") or ""),
                skipped=bool(c.get("skipped", False)),
            )
            for c in chapters_in
            if int(c.get("index", 0)) >= 1
        ],
    )
    storage.save_manifest(manifest)

    for c in chapters_in:
        idx = int(c.get("index", 0))
        if idx < 1:
            continue
        ch = Chapter(index=idx, url=str(c.get("url") or ""))
        if c.get("raw"):
            try:
                storage.write_raw(ch, c["raw"], crawl_pages=int(c.get("crawl_pages") or 0))
            except Exception:
                storage.write_raw(ch, c["raw"])
        if c.get("ai_text"):
            storage.write_branch_text(ch, "ai", c["ai_text"])
        if c.get("ai_title") or c.get("ai_title_zh"):
            storage.write_branch_titles(
                ch, "ai", str(c.get("ai_title") or ""), str(c.get("ai_title_zh") or ""))
        if c.get("ai_mt"):
            storage.write_branch_mt_snapshot(ch, "ai", c["ai_mt"])
        if c.get("localmt_text"):
            storage.write_branch_text(ch, "local_mt", c["localmt_text"])
        if c.get("localmt_title") or c.get("localmt_title_zh"):
            storage.write_branch_titles(
                ch, "local_mt", str(c.get("localmt_title") or ""),
                str(c.get("localmt_title_zh") or ""))
        if c.get("localmt_mt"):
            storage.write_branch_mt_snapshot(ch, "local_mt", c["localmt_mt"])
        if (c.get("active_branch") or "ai") == "local_mt":
            storage.set_active_branch(ch, "local_mt")
        if c.get("meta"):
            try:
                storage.write_meta(ch, dict(c["meta"]))
            except Exception:
                pass

    glossary_in = data.get("glossary") or {}
    for name in ("names.txt", "vietphrase.txt"):
        entries = [(e[0], e[1], e[2] if len(e) > 2 else "")
                   for e in (glossary_in.get(name) or []) if e and e[0] and e[1]]
        if entries:
            storage.write_glossary_entries(name, entries)

    for c in data.get("characters") or []:
        if not c or not c[0]:
            continue
        storage.upsert_character(
            source=c[0], target=c[1] if len(c) > 1 else "",
            aliases=c[2] if len(c) > 2 else "", gender=c[3] if len(c) > 3 else "",
            self_pronoun=c[4] if len(c) > 4 else "",
            narrator_ref=c[5] if len(c) > 5 else "",
            role_note=c[6] if len(c) > 6 else "",
            importance=c[7] if len(c) > 7 else "side",
            aliases_vi=c[8] if len(c) > 8 else "",
        )
    for r in data.get("relations") or []:
        if not r or not r[0] or not r[1]:
            continue
        storage.upsert_relation(
            a_source=r[0], b_source=r[1],
            from_chapter=int(r[2]) if len(r) > 2 and r[2] is not None else 0,
            a_calls_b=r[3] if len(r) > 3 else "", a_self=r[4] if len(r) > 4 else "",
            note=r[5] if len(r) > 5 else "",
            to_chapter=r[6] if len(r) > 6 else None,
            a_calls_b_raw=r[7] if len(r) > 7 else "",
            a_self_raw=r[8] if len(r) > 8 else "",
            evidence=r[9] if len(r) > 9 else "",
            inferred=bool(r[10]) if len(r) > 10 else False,
            confidence=r[11] if len(r) > 11 else "",
        )
    if data.get("notes"):
        storage.write_notes(list(data["notes"]))
    if data.get("entity_overrides"):
        storage.import_entity_overrides(list(data["entity_overrides"]), merge=False)
    for key, value in (data.get("extra_json") or {}).items():
        try:
            storage.write_extra_json(str(key), value)
        except Exception:
            pass

    if "cover.bin" in names:
        try:
            cover_bytes = zf.read("cover.bin")
            try:
                ext = str(json.loads(zf.read("cover.json").decode()).get("ext") or "jpg")
            except Exception:
                ext = "jpg"
            storage.write_cover(cover_bytes, ext)
        except Exception as exc:
            warnings.append(f"Khong nhap duoc bia: {exc}")

    automation_count = 0
    for a in data.get("automations") or []:
        try:
            import json as _json

            steps = _json.loads(a.get("steps_json", '["build"]'))
            from .automation import add_automation

            add_automation(
                db_path, target, list(steps),
                schedule=str(a.get("schedule") or "manual"),
                crawl_workers=int(a.get("crawl_workers") or 4),
                translate_workers=int(a.get("translate_workers") or 4),
                translate_threshold=int(a.get("translate_threshold") or 0),
                cleanup_threshold=int(a.get("cleanup_threshold") or 0),
                publish_threshold=int(a.get("publish_threshold") or 0),
                build_threshold=int(a.get("build_threshold") or 0),
            )
            automation_count += 1
        except Exception:
            continue

    counts = {
        "chapters": len(manifest.chapters),
        "glossary": sum(len(storage.read_glossary_entries(n)) for n in ("names.txt", "vietphrase.txt")),
        "characters": len(storage.read_character_entries()),
        "relations": len(storage.read_relation_entries()),
        "notes": len(storage.read_notes()),
        "automations": automation_count,
    }
    return {"slug": target, "counts": counts, "warnings": warnings}
