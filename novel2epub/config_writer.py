"""Ghi cấu hình vào bảng `settings`/`ebooks`/`sources` của DB thống nhất.

Trước đây module này ghi YAML bằng ruamel (round-trip, giữ comment người
dùng). DB không có khái niệm "comment" nên phần ruamel bị bỏ hoàn toàn —
đổi lại, ghi cấu hình giờ là UPDATE/INSERT SQL đơn giản, không cần đọc-sửa-
ghi lại toàn bộ file mỗi lần.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from .config import READER_GLOBAL_FIELDS, LibraryConfig, _deep_merge_raw
from .db import get_thread_connection

# Field deprecated — không có UI counterpart, config_writer không ghi.
# load_config vẫn đọc được (backward compat) nhưng không nên xuất hiện khi
# user tạo/sửa ebook qua web UI.
_DEPRECATED_CRAWL_FIELDS = frozenset({
    "ai_fallback", "ai_fallback_max_html", "concurrency_cap",
})
_DEPRECATED_TRANSLATE_FIELDS = frozenset({
    "glossary", "glossary_files", "profile",
})

_NOVEL_COLUMNS = frozenset({
    "title", "author", "description", "language", "publisher", "pubdate",
    "date_added", "series", "series_index", "identifier", "cover_url",
})

# Các section của bảng `settings` — thứ tự khớp cột trong _upsert_settings.
_SETTINGS_SECTIONS = ("novel", "crawl", "translate", "ai", "global_ai", "output", "queue", "reader", "api", "wireguard", "tailscale")


def clean_prompt_text(value: str) -> str:
    """Làm sạch nội dung prompt nhập từ textarea cho gọn gàng, thống nhất.

    Chỉ đụng tới khoảng trắng / ký tự xuống dòng nên an toàn với các placeholder
    `{text}`, `{glossary}`, `{tone}`... mà translator dùng qua ``str.format``:

    - Chuẩn hoá CRLF/CR về ``\\n`` (textarea web gửi xuống dùng CRLF).
    - Bỏ khoảng trắng thừa ở cuối mỗi dòng.
    - Gộp >=3 dòng trống liên tiếp thành tối đa 1 dòng trống.
    - Cắt dòng trống ở đầu và cuối.

    Giữ nguyên thụt đầu dòng (có thể là chủ ý) và mọi dấu ``{...}``.
    """
    import re

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip("\n")


def update_ebook(
    path: str | Path,
    slug: str,
    updates: dict[str, Any],
    *,
    replace_crawl: bool = False,
    replace_translate: bool = False,
    replace_ai: bool = False,
) -> None:
    """Merge `updates` (khối "novel"/"crawl"/"translate"/"ai"/"output"/
    "reader"/"source") vào row `ebooks.<slug>` — chỉ chạm đúng cột liên quan,
    ebook khác giữ nguyên.

    `replace_crawl`/`replace_translate`/`replace_ai` =True: ghi đè NGUYÊN KHỐI
    `*_overrides_json` tương ứng thay vì merge — cách duy nhất để XOÁ một
    override (merge không bỏ được key); truyền khối rỗng `{}` = reset về
    defaults (config chung).
    """
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute("INSERT OR IGNORE INTO ebooks (slug) VALUES (?)", (slug,))
        row = conn.execute("SELECT * FROM ebooks WHERE slug = ?", (slug,)).fetchone()

        set_clauses: list[str] = []
        params: list[Any] = []

        novel_updates = updates.get("novel")
        if isinstance(novel_updates, dict):
            for key, value in novel_updates.items():
                if key == "subjects":
                    set_clauses.append("subjects_json = ?")
                    params.append(json.dumps(value, ensure_ascii=False))
                elif key in _NOVEL_COLUMNS:
                    set_clauses.append(f"{key} = ?")
                    params.append(value)

        crawl_updates = updates.get("crawl")
        if isinstance(crawl_updates, dict):
            filtered = {k: v for k, v in crawl_updates.items()
                        if k not in _DEPRECATED_CRAWL_FIELDS}
            if replace_crawl:
                new_crawl = filtered
            else:
                current_crawl = json.loads(row["crawl_overrides_json"] or "{}")
                new_crawl = _deep_merge_raw(current_crawl, filtered)
            set_clauses.append("crawl_overrides_json = ?")
            params.append(json.dumps(new_crawl, ensure_ascii=False))

        translate_updates = updates.get("translate")
        if isinstance(translate_updates, dict):
            filtered = {
                k: v for k, v in translate_updates.items()
                if k not in _DEPRECATED_TRANSLATE_FIELDS and k != "openai"
            }
            if replace_translate:
                new_translate = filtered
            else:
                current_translate = json.loads(row["translate_overrides_json"] or "{}")
                new_translate = _deep_merge_raw(current_translate, filtered)
            set_clauses.append("translate_overrides_json = ?")
            params.append(json.dumps(new_translate, ensure_ascii=False))

        ai_updates = updates.get("ai")
        if isinstance(ai_updates, dict):
            # Giữ nguyên khối `openai` (provider riêng từng truyện, có thể chứa
            # api_key) — ghi đè AI config per-book được phép; credentials KHÔNG
            # còn bị lược bỏ tại đây (trước chỉ lưu được model qua override).
            filtered_ai = dict(ai_updates)
            if replace_ai:
                new_ai = filtered_ai
            else:
                current_ai = json.loads(row["ai_overrides_json"] or "{}")
                new_ai = _deep_merge_raw(current_ai, filtered_ai)
            set_clauses.append("ai_overrides_json = ?")
            params.append(json.dumps(new_ai, ensure_ascii=False))

        output_updates = updates.get("output")
        if isinstance(output_updates, dict):
            current_output = json.loads(row["output_overrides_json"] or "{}")
            merged_output = _deep_merge_raw(current_output, output_updates)
            set_clauses.append("output_overrides_json = ?")
            params.append(json.dumps(merged_output, ensure_ascii=False))
            if "epub_path" in merged_output:
                set_clauses.append("epub_path = ?")
                params.append(merged_output["epub_path"])

        reader_updates = updates.get("reader")
        if isinstance(reader_updates, dict):
            # Phần kết nối Supabase là cấu hình chung — chặn ngay ở đây để
            # `service_key` không bị nhân bản vào từng ebook (load_config cũng
            # strip, nhưng không nên ghi vào DB ngay từ đầu).
            filtered = {k: v for k, v in reader_updates.items()
                        if k not in READER_GLOBAL_FIELDS}
            current_reader = json.loads(row["reader_overrides_json"] or "{}")
            merged_reader = _deep_merge_raw(current_reader, filtered)
            set_clauses.append("reader_overrides_json = ?")
            params.append(json.dumps(merged_reader, ensure_ascii=False))

        if "source" in updates:
            set_clauses.append("source_preset = ?")
            params.append(updates["source"] or None)

        if set_clauses:
            set_clauses.append("updated_at = datetime('now')")
            params.append(slug)
            conn.execute(f"UPDATE ebooks SET {', '.join(set_clauses)} WHERE slug = ?", params)


def update_defaults(path: str | Path, updates: dict[str, Any]) -> None:
    """Merge `updates` vào bảng `settings` — CONFIG CHUNG: fallback cho ebook
    chưa cấu hình riêng + giá trị quay về khi Reset. Cấu hình riêng từng ebook
    (kể cả `translate`/`ai`) ghi qua `update_ebook`."""
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    with conn:
        current = _read_settings_sections(conn)
        for key, value in updates.items():
            if key not in current:
                current[key] = {}
            if isinstance(value, dict):
                deprecated = (
                    _DEPRECATED_CRAWL_FIELDS if key == "crawl"
                    else _DEPRECATED_TRANSLATE_FIELDS if key == "translate"
                    else frozenset()
                )
                current[key] = _deep_merge_raw(
                    current[key], {k: v for k, v in value.items() if k not in deprecated}
                )
            else:
                current[key] = value
        _upsert_settings(conn, current)


def _read_settings_sections(conn) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    return {
        s: json.loads(row[f"{s}_json"]) if row and row[f"{s}_json"] else {}
        for s in _SETTINGS_SECTIONS
    }


def _upsert_settings(conn, current: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO settings (id, novel_json, crawl_json, translate_json, ai_json, global_ai_json, output_json, queue_json, reader_json, api_json, wireguard_json, tailscale_json)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            novel_json = excluded.novel_json,
            crawl_json = excluded.crawl_json,
            translate_json = excluded.translate_json,
            ai_json = excluded.ai_json,
            global_ai_json = excluded.global_ai_json,
            output_json = excluded.output_json,
            queue_json = excluded.queue_json,
            reader_json = excluded.reader_json,
            api_json = excluded.api_json,
            wireguard_json = excluded.wireguard_json,
            tailscale_json = excluded.tailscale_json,
            updated_at = datetime('now')
        """,
        tuple(json.dumps(current.get(s, {}), ensure_ascii=False) for s in _SETTINGS_SECTIONS),
    )


def reset_defaults(path: str | Path, sections: list[str] | tuple[str, ...]) -> list[str]:
    """Xoá trắng các section trong bảng `settings` (config chung) — load_config
    quay về default của dataclass (novel2epub/config.py). Lưu ý: nút Reset ở
    trang Settings ebook KHÔNG gọi hàm này — nó xoá override RIÊNG của ebook
    (`update_ebook(..., replace_translate/ai=True)`) để quay VỀ config chung;
    hàm này dành cho việc đưa chính config chung về mặc định.

    Trả về danh sách section thật sự được reset (section không hợp lệ bị bỏ qua).
    """
    targets = [s for s in sections if s in _SETTINGS_SECTIONS]
    if not targets:
        return []
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    with conn:
        current = _read_settings_sections(conn)
        for s in targets:
            current[s] = {}
        _upsert_settings(conn, current)
    return targets


def add_ebook(
    path: str | Path,
    slug: str,
    *,
    title: str = "",
    author: str = "",
    toc_url: str = "",
    preset: dict[str, Any] | None = None,
    source_name: str = "",
) -> None:
    """Thêm 1 ebook với CHỈ phần override tối thiểu.

    Phần dùng chung (prompt, style, output...) do `settings` lo, không lặp lại.
    Nếu ``source_name`` được cung cấp, ghi `source_preset` thay vì copy preset
    fields vào `crawl_overrides_json` (preset resolve tự động khi load config).
    """
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)

    crawl_over: dict[str, Any] = {}
    if toc_url:
        crawl_over["toc_url"] = toc_url
    if not source_name and preset:
        for k, v in preset.items():
            if k in {"name", "url", "domains", "engine"}:
                continue
            crawl_over[k] = v

    with conn:
        conn.execute(
            """
            INSERT INTO ebooks (slug, title, author, date_added, identifier, source_preset, crawl_overrides_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title,
                author = excluded.author,
                source_preset = excluded.source_preset,
                crawl_overrides_json = excluded.crawl_overrides_json
            """,
            (
                slug, title, author, date.today().isoformat(),
                f"urn:uuid:{uuid.uuid4()}", source_name or None,
                json.dumps(crawl_over, ensure_ascii=False),
            ),
        )
        from .codes import backfill_codes
        backfill_codes(conn)


def ensure_identifier(path: str | Path, slug: str, current: str) -> str:
    """Trả `current` nếu đã có, ngược lại sinh + lưu 1 urn:uuid mới (ổn định
    qua các lần build sau — xem spec ebook-metadata 'Identifier stable
    across rebuilds'). Dùng cho ebook tạo trước khi field này tồn tại."""
    if current:
        return current
    new_id = f"urn:uuid:{uuid.uuid4()}"
    update_ebook(path, slug, {"novel": {"identifier": new_id}})
    return new_id


def remove_ebook(path: str | Path, slug: str) -> None:
    """Xóa hẳn ebook (row `ebooks.<slug>`) — CASCADE xóa luôn chapters/
    glossary/notes/cover của ebook này (khác hành vi cũ chỉ xóa khối config
    YAML, giữ nguyên dữ liệu đã crawl/dịch trên đĩa)."""
    db_path = Path(path).resolve()
    if not db_path.exists():
        return
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute("DELETE FROM ebooks WHERE slug = ?", (slug,))


def save_library(path: str | Path, library: LibraryConfig) -> None:
    """Đồng bộ danh sách ebook: thêm slug chưa có, xóa ebook đã gỡ khỏi `library`."""
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    with conn:
        existing = {r["slug"] for r in conn.execute("SELECT slug FROM ebooks")}
        for slug in existing - set(library.ebooks):
            conn.execute("DELETE FROM ebooks WHERE slug = ?", (slug,))
        for slug in library.ebooks:
            conn.execute(
                "INSERT OR IGNORE INTO ebooks (slug) VALUES (?)",
                (slug,),
            )
