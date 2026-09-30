"""Chuẩn hoá HOA/THƯỜNG cho cột Việt của glossary theo quy ước Hán Việt:
viết hoa TỪNG chữ (vd: `Tào Tinh`, `Kỵ Sĩ Cực Quang`, `Xà Nhân Cuồng Hóa`).

Vì sao cần: glossary sinh theo nhiều đợt (dịch máy, NER, AI) nên cột Việt
bị trộn ba phong cách — Hán Việt hoa từng chữ, dịch nghĩa viết thường, và
"Title Case cả câu" (`Cha Của Chư Thần`). Bản dịch đã sinh ra cũng tra
glossary nên style lẫn lộn làm câu chữ đọc lệch. Quy ước này đúng với prompt
AI sẵn có của repo (`novel2epub.glossary_ai.RETRANSLATE_PROMPT`: "viết hoa
từng chữ").

Script chỉ đổi HOA/THƯỜNG — không đổi từ ngữ, không thêm/xoá mục. Mục không
an toàn (cột Hán không có chữ Trung, tức nguồn đã hỏng: đảo cột, lọt văn bản
AI, handle diễn đàn) được BỎ QUA và chỉ báo cáo, không tự sửa.

    python -m scripts.normalize_glossary_case --slug <slug> --dry-run
    python -m scripts.normalize_glossary_case --slug <slug>
    python -m scripts.normalize_glossary_case --slug <slug> --restore <file.json>

Lần đầu LUÔN chạy kèm `--dry-run`; lần ghi thật tự backup các dòng sắp đổi
vào `.n2e/backups/` để `--restore` hoàn nguyên.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from novel2epub.db import get_thread_connection
from novel2epub.han_cleanup import count_han

# Giống `novel2epub/cli.py` và `app/deps.py`: operator chỉ set NOVEL2EPUB_FILE
# (env override chính của repo) vẫn trỏ đúng DB thật.
DEFAULT_DB_PATH = os.environ.get(
    "NOVEL2EPUB_DB",
    os.environ.get("NOVEL2EPUB_FILE", os.environ.get("NOVEL2EPUB_CONFIG", "novel2epub.db")),
)

BACKUP_DIR = Path(".n2e") / "backups"

# Dấu bao quanh/ngăn cách không phải chữ hay số — tách ra khỏi "lõi" từ để
# `(Lục)` không bị hạ chữ thành `(lục)`.
_LEAD = re.compile(r"^[^\w]+", re.UNICODE)
_TRAIL = re.compile(r"[^\w]+$", re.UNICODE)


def _split_edges(token: str) -> tuple[str, str, str]:
    """Tách một token trắng-tách được thành (dấu đầu, lõi, dấu cuối)."""
    lead = _LEAD.match(token)
    head = lead.group(0) if lead else ""
    rest = token[len(head) :]
    trail = _TRAIL.search(rest)
    tail = trail.group(0) if trail else ""
    return head, rest[: len(rest) - len(tail)], tail


def _fix_core(core: str) -> str:
    """Viết hoa chữ đầu lõi, hạ phần còn lại — trừ khi lõi KHÔNG nên đổi:
    chữ viết tắt ALL-CAPS (NPC, HP), tên có hoa bên trong (McDonald, O'Brien,
    iPhone) hoặc chữ Trung (hoa/thường không mang nghĩa)."""
    if not core:
        return core
    letters = [c for c in core if c.isalpha()]
    if not letters:
        return core  # "174", "-", "·" — không có chữ cái để đổi
    if count_han(core):
        return core
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return core  # NPC, HP, AOE — chữ viết tắt
    if any(c.isupper() for c in core[1:]):
        return core  # McDonald, O'Brien, iPhone — hoa bên trong là cố ý
    return core[0].upper() + core[1:].lower()


def title_case_vi(text: str) -> str:
    """Chuẩn hoá HOA/THƯỜNG cột Việt: hoa từng chữ, giữ nguyên khoảng trắng.

    Idempotent: gọi lại trên output không đổi gì.
    """
    if not text:
        return text
    out = []
    for token in re.split(r"(\s+)", text):
        if not token.strip():
            out.append(token)
            continue
        head, core, tail = _split_edges(token)
        out.append(head + _fix_core(core) + tail)
    return "".join(out)


# ── Quét & lập kế hoạch ──────────────────────────────────────────────

SKIP_NO_HAN = "source-khong-co-chu-Trung"


def plan_changes(conn, slug: str) -> dict:
    """Đọc glossary của `slug`, trả kế hoạch sửa + danh sách mục bỏ qua."""
    rows = conn.execute(
        "SELECT list_name, source, target, note, position FROM glossary_entries "
        "WHERE ebook_slug = ? ORDER BY list_name, position",
        (slug,),
    ).fetchall()

    changes: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        source, target = row["source"], row["target"]
        # Cột Hán không có chữ Trung nghĩa là nguồn đã hỏng (đảo cột, lọt văn
        # bản suy luận của AI, handle diễn đàn). Chuẩn hoá HOA/THƯỜNG không
        # cứu được mục đó — giữ nguyên và đưa ra báo cáo cho người dùng.
        if count_han(source) == 0:
            skipped.append(
                {
                    "list_name": row["list_name"],
                    "source": source,
                    "target": target,
                    "reason": SKIP_NO_HAN,
                }
            )
            continue
        new_target = title_case_vi(target)
        if new_target != target:
            changes.append(
                {
                    "list_name": row["list_name"],
                    "source": source,
                    "old_target": target,
                    "new_target": new_target,
                    "note": row["note"],
                }
            )
    return {"total": len(rows), "changes": changes, "skipped": skipped}


def apply_changes(conn, slug: str, changes: list[dict]) -> int:
    """Ghi cột Việt mới. Chỉ UPDATE `target` — `note`/`position` giữ nguyên."""
    with conn:
        conn.executemany(
            "UPDATE glossary_entries SET target = ? "
            "WHERE ebook_slug = ? AND list_name = ? AND source = ?",
            [(c["new_target"], slug, c["list_name"], c["source"]) for c in changes],
        )
    return len(changes)


def backup_payload(slug: str, plan: dict) -> dict:
    """Gói đủ để hoàn nguyên: mọi dòng SẼ đổi, kèm giá trị cũ."""
    return {
        "slug": slug,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "script": "normalize_glossary_case",
        "rows": list(plan["changes"]),
    }


def write_backup(db_path: Path, slug: str, plan: dict) -> Path:
    out_dir = db_path.parent / BACKUP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"glossary_case_{slug}_{stamp}.json"
    path.write_text(
        json.dumps(backup_payload(slug, plan), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return path


def restore(conn, path: Path) -> int:
    """Hoàn nguyên cột Việt về đúng giá trị trước khi script chạy."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    slug = payload["slug"]
    rows = payload.get("rows") or []
    with conn:
        conn.executemany(
            "UPDATE glossary_entries SET target = ? "
            "WHERE ebook_slug = ? AND list_name = ? AND source = ?",
            [(r["old_target"], slug, r["list_name"], r["source"]) for r in rows],
        )
    return len(rows)


# ── CLI ──────────────────────────────────────────────────────────────

def _print_preview(plan: dict, limit: int) -> None:
    changes = plan["changes"]
    print(f"Glossary: {plan['total']} mục → sửa {len(changes)}, bỏ qua {len(plan['skipped'])}")
    if changes:
        print("\n--- SẼ đổi ---")
        for c in changes[:limit]:
            print(f"  {c['source']}\n      {c['old_target']}  ->  {c['new_target']}")
        if len(changes) > limit:
            print(f"  … và {len(changes) - limit} mục nữa")
    if plan["skipped"]:
        print(f"\n--- BỎ QUA (không có chữ Trung ở cột Hán) — {len(plan['skipped'])} mục ---")
        for s in plan["skipped"][:limit]:
            print(f"  {s['source']!r} = {s['target']!r}")
        if len(plan["skipped"]) > limit:
            print(f"  … và {len(plan['skipped']) - limit} mục nữa")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Chuẩn hoá hoa/thường cột Việt của glossary (quy ước Hán Việt)."
    )
    parser.add_argument("-c", "--config", default=DEFAULT_DB_PATH, help="Đường dẫn file DB.")
    parser.add_argument("--slug", required=True, help="Slug ebook cần chuẩn hoá.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in ra thay đổi, không ghi DB.")
    parser.add_argument("--restore", metavar="FILE", help="Hoàn nguyên từ file backup JSON.")
    parser.add_argument("--limit", type=int, default=30, help="Số dòng mẫu in ra (mặc định 30).")
    args = parser.parse_args(argv)

    path = Path(args.config).resolve()
    if not path.exists():
        print(f"Không tìm thấy DB: {path}", file=sys.stderr)
        raise SystemExit(1)

    conn = get_thread_connection(path)

    if args.restore:
        n = restore(conn, Path(args.restore))
        print(f"Đã hoàn nguyên {n} mục từ {args.restore}")
        return

    ebook = conn.execute("SELECT slug FROM ebooks WHERE slug = ?", (args.slug,)).fetchone()
    if ebook is None:
        print(f"Không tìm thấy ebook: {args.slug}", file=sys.stderr)
        raise SystemExit(1)

    plan = plan_changes(conn, args.slug)
    if not plan["changes"]:
        _print_preview(plan, args.limit)
        print("\nKhông có mục nào lệch quy ước. Không cần làm gì.")
        return

    _print_preview(plan, args.limit)

    if args.dry_run:
        print("\n[dry-run] Chưa ghi gì cả. Bỏ --dry-run để áp dụng.")
        return

    backup = write_backup(path, args.slug, plan)
    apply_changes(conn, args.slug, plan["changes"])
    print(f"\nĐã chuẩn hoá {len(plan['changes'])} mục. Backup: {backup}")
    print(f"Hoàn nguyên: python -m scripts.normalize_glossary_case --slug {args.slug} --restore {backup}")


if __name__ == "__main__":
    main()
