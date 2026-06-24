"""Gộp config.yaml + sources.yaml + library.yaml + configs/*.yaml -> novel2epub.yaml.

Chạy 1 lần để migrate sang file cấu hình gộp duy nhất:

    python scripts/migrate_to_single_yaml.py

Sinh ra `novel2epub.yaml` gồm 3 khối:
    defaults: phần dùng chung (lấy từ config.yaml, bỏ field đặc thù truyện)
    sources:  preset site (nguyên `sources:` của sources.yaml)
    ebooks:   mỗi ebook CHỈ giữ phần KHÁC với defaults (+ tên hiển thị)

Sau khi kiểm tra file mới đúng, có thể xóa: config.yaml, config.example.yaml,
sources.yaml, library.yaml, configs/.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

ROOT = Path(__file__).resolve().parent.parent

# Field đặc thù từng truyện -> KHÔNG để trong defaults (mỗi ebook tự khai).
EBOOK_ONLY = {
    "novel": None,  # cả khối novel
    "crawl": {"toc_url", "chapter_link_pattern"},
    "translate": {"glossary"},
    "output": {"epub_path"},
}


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _strip_ebook_only(defaults: dict) -> dict:
    out = copy.deepcopy(defaults)
    for section, keys in EBOOK_ONLY.items():
        if keys is None:
            out.pop(section, None)
        elif isinstance(out.get(section), dict):
            for k in keys:
                out[section].pop(k, None)
    return out


def _deep_diff(value: dict, base: dict) -> dict:
    """Trả về các key trong `value` khác với `base` (đệ quy theo dict)."""
    out: dict = {}
    for k, v in value.items():
        b = base.get(k)
        if isinstance(v, dict) and isinstance(b, dict):
            sub = _deep_diff(v, b)
            if sub:
                out[k] = sub
        elif b != v:
            out[k] = v
    return out


def _to_yaml(value):
    """Đệ quy chuyển sang cấu trúc ruamel; string nhiều dòng -> block literal."""
    if isinstance(value, dict):
        m = CommentedMap()
        for k, v in value.items():
            m[k] = _to_yaml(v)
        return m
    if isinstance(value, str) and "\n" in value:
        return LiteralScalarString(value.replace("\r\n", "\n").replace("\r", "\n"))
    return value


def main() -> int:
    config_raw = _load(ROOT / "config.yaml")
    sources_raw = _load(ROOT / "sources.yaml")
    library_raw = _load(ROOT / "library.yaml")

    if not config_raw:
        print("Không tìm thấy config.yaml — không có gì để migrate.", file=sys.stderr)
        return 1

    defaults = _strip_ebook_only(config_raw)

    ebooks: dict[str, dict] = {}
    entries = (library_raw.get("ebooks") or {})
    if not entries:
        # Không có library: coi config.yaml là 1 ebook mặc định.
        slug = (config_raw.get("novel") or {}).get("slug", "novel")
        entries = {slug: {"name": (config_raw.get("novel") or {}).get("title", ""),
                          "config": "config.yaml"}}

    for slug, item in entries.items():
        if isinstance(item, str):
            item = {"config": item}
        name = item.get("name", "")
        cfg_rel = item.get("config", "config.yaml")
        cfg_path = ROOT / cfg_rel
        ebook_raw = _load(cfg_path)
        if not ebook_raw:
            print(f"  ! bỏ qua {slug!r}: không đọc được {cfg_rel}", file=sys.stderr)
            continue
        override = _deep_diff(ebook_raw, defaults)
        block: dict = {}
        if name:
            block["name"] = name
        block.update(override)
        ebooks[slug] = block
        print(f"  + {slug}: {len(override)} section override "
              f"({', '.join(override.keys()) or 'none'})")

    out = CommentedMap()
    out["defaults"] = _to_yaml(defaults)
    out["sources"] = _to_yaml(sources_raw.get("sources") or {})
    out["ebooks"] = _to_yaml(ebooks)

    dest = ROOT / "novel2epub.yaml"
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    with dest.open("w", encoding="utf-8") as f:
        y.dump(out, f)

    print(f"\nĐã ghi {dest}")
    print(f"  defaults: {list(defaults.keys())}")
    print(f"  sources : {len(out['sources'])} preset")
    print(f"  ebooks  : {list(ebooks.keys())}")
    print("\nKiểm tra file rồi xóa: config.yaml, config.example.yaml, sources.yaml, "
          "library.yaml, configs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
