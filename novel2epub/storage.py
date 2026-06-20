"""Lưu trữ & cache: manifest chương + nội dung raw/đã dịch trên đĩa.

Cấu trúc:
    <data_dir>/<slug>/
        manifest.json        danh sách chương + trạng thái
        raw/0001.md          nội dung tiếng Trung đã crawl
        translated/0001.md   nội dung tiếng Việt đã dịch
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Chapter:
    index: int
    url: str
    title_zh: str = ""
    title_vi: str = ""

    @property
    def stem(self) -> str:
        return f"{self.index:04d}"


@dataclass
class Manifest:
    slug: str
    title: str = ""
    author: str = ""
    chapters: list[Chapter] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "slug": self.slug,
                "title": self.title,
                "author": self.author,
                "chapters": [asdict(c) for c in self.chapters],
            },
            ensure_ascii=False,
            indent=2,
        )


class Storage:
    def __init__(self, data_dir: str | Path, slug: str):
        self.root = Path(data_dir) / slug
        self.raw_dir = self.root / "raw"
        self.translated_dir = self.root / "translated"
        self.meta_dir = self.root / "translation_meta"
        self.glossary_dir = self.root / "glossary"
        self.manifest_path = self.root / "manifest.json"
        self.slug = slug

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.translated_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.glossary_dir.mkdir(parents=True, exist_ok=True)

    # ----- manifest -----
    def load_manifest(self) -> Manifest | None:
        if not self.manifest_path.exists():
            return None
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        chapters = [Chapter(**c) for c in data.get("chapters", [])]
        return Manifest(
            slug=data.get("slug", self.slug),
            title=data.get("title", ""),
            author=data.get("author", ""),
            chapters=chapters,
        )

    def save_manifest(self, manifest: Manifest) -> None:
        self.ensure_dirs()
        self.manifest_path.write_text(manifest.to_json(), encoding="utf-8")

    # ----- nội dung chương -----
    def raw_path(self, ch: Chapter) -> Path:
        return self.raw_dir / f"{ch.stem}.md"

    def translated_path(self, ch: Chapter) -> Path:
        return self.translated_dir / f"{ch.stem}.md"

    def meta_path(self, ch: Chapter) -> Path:
        return self.meta_dir / f"{ch.stem}.json"

    def has_raw(self, ch: Chapter) -> bool:
        p = self.raw_path(ch)
        return p.exists() and p.stat().st_size > 0

    def has_translated(self, ch: Chapter) -> bool:
        p = self.translated_path(ch)
        return p.exists() and p.stat().st_size > 0

    def write_raw(self, ch: Chapter, content: str) -> None:
        self.ensure_dirs()
        self.raw_path(ch).write_text(content, encoding="utf-8")

    def read_raw(self, ch: Chapter) -> str:
        return self.raw_path(ch).read_text(encoding="utf-8")

    def write_translated(self, ch: Chapter, content: str) -> None:
        self.ensure_dirs()
        self.translated_path(ch).write_text(content, encoding="utf-8")

    def read_translated(self, ch: Chapter) -> str:
        return self.translated_path(ch).read_text(encoding="utf-8")

    def has_meta(self, ch: Chapter) -> bool:
        return self.meta_path(ch).exists()

    def read_meta(self, ch: Chapter) -> dict:
        path = self.meta_path(ch)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_meta(self, ch: Chapter, meta: dict) -> None:
        self.ensure_dirs()
        self.meta_path(ch).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def glossary_path(self, name: str) -> Path:
        return self.glossary_dir / name

    def read_glossary_file(self, name: str) -> dict[str, str]:
        path = self.glossary_path(name)
        if not path.exists():
            return {}
        glossary: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            zh, vi = line.split("=", 1)
            zh = zh.strip()
            vi = vi.strip()
            if zh and vi:
                glossary[zh] = vi
        return glossary

    def write_glossary_file(self, name: str, content: str) -> None:
        self.ensure_dirs()
        self.glossary_path(name).write_text(content, encoding="utf-8")
