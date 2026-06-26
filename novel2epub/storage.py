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


def parse_glossary_line(line: str) -> tuple[str, str, str] | None:
    """Tách 1 dòng glossary `Hán = Việt | ghi chú` thành (source, target, note).

    - Phần `| ghi chú` là tùy chọn (tương thích ngược dòng cũ `Hán = Việt`).
    - Trả None nếu dòng rỗng, là comment (`#`) hoặc không có dấu `=`.
    """
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


@dataclass
class Chapter:
    index: int
    url: str
    title_zh: str = ""
    title_vi: str = ""
    title_note: str = ""
    missing_fields: list[str] = field(default_factory=list)
    duplicate_of: int | None = None
    last_action_status: str = ""

    @property
    def stem(self) -> str:
        return f"{self.index:04d}"


@dataclass
class Manifest:
    slug: str
    source_url: str = ""
    title: str = ""
    author: str = ""
    # Metadata bản gốc (tiếng Trung) crawl từ trang mục lục.
    description: str = ""
    cover_url: str = ""
    # Tên file ảnh bìa đã tải về (nằm trong thư mục <data_dir>/<slug>/).
    cover_file: str = ""
    # Metadata đã dịch sang tiếng Việt (dùng cho EPUB).
    title_vi: str = ""
    title_note: str = ""
    author_vi: str = ""
    description_vi: str = ""
    metadata_missing: list[str] = field(default_factory=list)
    curated_fields: list[str] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "slug": self.slug,
                "source_url": self.source_url,
                "title": self.title,
                "author": self.author,
                "description": self.description,
                "cover_url": self.cover_url,
                "cover_file": self.cover_file,
                "title_vi": self.title_vi,
                "title_note": self.title_note,
                "author_vi": self.author_vi,
                "description_vi": self.description_vi,
                "metadata_missing": self.metadata_missing,
                "curated_fields": self.curated_fields,
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
        # Snapshot bản dịch máy (cột "VI" trong editor 3 cột), bất biến để đối
        # chiếu — tách khỏi `translated` (cột "Biên tập", bản lưu cuối vào EPUB).
        self.translated_mt_dir = self.root / "translated_mt"
        self.meta_dir = self.root / "translation_meta"
        self.glossary_dir = self.root / "glossary"
        self.manifest_path = self.root / "manifest.json"
        self.slug = slug

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.translated_dir.mkdir(parents=True, exist_ok=True)
        self.translated_mt_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.glossary_dir.mkdir(parents=True, exist_ok=True)

    # ----- manifest -----
    def load_manifest(self) -> Manifest | None:
        if not self.manifest_path.exists():
            return None
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        chapters = []
        for c in data.get("chapters", []):
            chapters.append(Chapter(
                index=c.get("index", 0),
                url=c.get("url", ""),
                title_zh=c.get("title_zh", ""),
                title_vi=c.get("title_vi", ""),
                title_note=c.get("title_note", ""),
                missing_fields=list(c.get("missing_fields", []) or []),
                duplicate_of=c.get("duplicate_of"),
                last_action_status=c.get("last_action_status", ""),
            ))
        return Manifest(
            slug=data.get("slug", self.slug),
            source_url=data.get("source_url", ""),
            title=data.get("title", ""),
            author=data.get("author", ""),
            description=data.get("description", ""),
            cover_url=data.get("cover_url", ""),
            cover_file=data.get("cover_file", ""),
            title_vi=data.get("title_vi", ""),
            title_note=data.get("title_note", ""),
            author_vi=data.get("author_vi", ""),
            description_vi=data.get("description_vi", ""),
            metadata_missing=list(data.get("metadata_missing", []) or []),
            curated_fields=list(data.get("curated_fields", []) or []),
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

    def translated_mt_path(self, ch: Chapter) -> Path:
        return self.translated_mt_dir / f"{ch.stem}.md"

    def meta_path(self, ch: Chapter) -> Path:
        return self.meta_dir / f"{ch.stem}.json"

    def has_raw(self, ch: Chapter) -> bool:
        p = self.raw_path(ch)
        return p.exists() and p.stat().st_size > 0

    def has_translated(self, ch: Chapter) -> bool:
        p = self.translated_path(ch)
        if not (p.exists() and p.stat().st_size > 0):
            return False
        # Phân biệt bản dịch hoàn tất với bản dịch dở (job bị crash giữa chunk).
        # Back-compat: meta cũ (không có key `complete`) được coi là hoàn tất để
        # không ép người dùng dịch lại thư viện EPUB đã build. Meta mới chỉ được
        # ghi kèm `complete: true` ở cuối `_translate_one` (xem
        # `translate-chunk-streaming` spec).
        meta_path = self.meta_path(ch)
        if not meta_path.exists():
            return True
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return bool(meta.get("complete", True))

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

    def has_translated_mt(self, ch: Chapter) -> bool:
        p = self.translated_mt_path(ch)
        return p.exists() and p.stat().st_size > 0

    def write_translated_mt(self, ch: Chapter, content: str) -> None:
        """Ghi snapshot bản dịch máy (cột VI). Gọi ở bước dịch, độc lập với
        `write_translated` (cột Biên tập sửa tay/AI)."""
        self.ensure_dirs()
        self.translated_mt_path(ch).write_text(content, encoding="utf-8")

    def read_translated_mt(self, ch: Chapter) -> str:
        """Đọc snapshot bản dịch máy; fallback về `translated` (degrade an toàn)
        cho chương cũ dịch trước khi có snapshot."""
        p = self.translated_mt_path(ch)
        if p.exists():
            return p.read_text(encoding="utf-8")
        tp = self.translated_path(ch)
        return tp.read_text(encoding="utf-8") if tp.exists() else ""

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

    def mark_translated_complete(self, ch: Chapter, *, meta_extra: dict | None = None) -> None:
        """Đánh dấu chương đã dịch xong (set `complete: true` trong meta).

        Đọc meta hiện tại (nếu có) để không phá các key đã có (warnings,
        generated_at, ...), merge thêm `meta_extra` (vd. length_raw) rồi
        set `complete=True` và ghi lại. Pipeline gọi đúng một lần ở cuối
        `_translate_one` (xem `translate-chunk-streaming` spec).
        """
        meta = self.read_meta(ch) if self.has_meta(ch) else {}
        if meta_extra:
            meta.update(meta_extra)
        meta["complete"] = True
        self.write_meta(ch, meta)

    def append_translated_chunk(
        self, ch: Chapter, chunk_text: str, *, is_first: bool
    ) -> None:
        """Ghi 1 chunk của bản dịch: chunk đầu tạo file, các chunk sau append.

        Chèn `\n` ngăn cách giữa 2 chunk để tránh dính ký tự cuối chunk
        trước với đầu chunk sau khi `_split_into_chunks` cắt ở ranh giới
        đoạn văn (xem `translate-chunk-streaming` spec).
        """
        self.ensure_dirs()
        path = self.translated_path(ch)
        if is_first:
            path.write_text(chunk_text, encoding="utf-8")
        else:
            with path.open("a", encoding="utf-8") as f:
                f.write("\n")
                f.write(chunk_text)

    # ----- ảnh bìa -----
    def write_cover(self, content: bytes, ext: str) -> str:
        """Lưu ảnh bìa vào <root>/cover.<ext>, trả về tên file (để ghi vào manifest)."""
        self.ensure_dirs()
        ext = (ext or "jpg").lstrip(".").lower() or "jpg"
        name = f"cover.{ext}"
        (self.root / name).write_bytes(content)
        return name

    def cover_fs_path(self, manifest: "Manifest") -> Path | None:
        """Đường dẫn tuyệt đối tới ảnh bìa nếu manifest có khai báo và file tồn tại."""
        if not manifest.cover_file:
            return None
        path = self.root / manifest.cover_file
        return path if path.exists() else None

    def glossary_path(self, name: str) -> Path:
        return self.glossary_dir / name

    def read_glossary_file(self, name: str) -> dict[str, str]:
        """Trả về dict source→target (bỏ ghi chú nếu có)."""
        path = self.glossary_path(name)
        if not path.exists():
            return {}
        glossary: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_glossary_line(line)
            if parsed:
                source, target, _note = parsed
                glossary[source] = target
        return glossary

    def read_glossary_notes(self) -> dict[str, str]:
        """Gộp names.txt + vietphrase.txt, trả {target: note} cho mục có ghi chú.

        Target (từ tiếng Việt) là chuỗi dùng để dò trong bản dịch khi sinh footnote.
        """
        notes: dict[str, str] = {}
        for name in ("names.txt", "vietphrase.txt"):
            path = self.glossary_path(name)
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                parsed = parse_glossary_line(line)
                if not parsed:
                    continue
                _source, target, note = parsed
                if note:
                    notes[target] = note
        return notes

    def write_glossary_file(self, name: str, content: str) -> None:
        self.ensure_dirs()
        self.glossary_path(name).write_text(content, encoding="utf-8")
