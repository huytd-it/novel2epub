"""Kết nối + schema SQLite thống nhất — nền tảng của việc gộp toàn bộ state
(config, sources, dữ liệu ebook, sidecar workspace) vào 1 file `.db` duy nhất
để dễ backup/restore/triển khai.

Phase 0: chỉ định nghĩa schema + kết nối, CHƯA đụng tới `storage.py`/
`config.py` — các module đó vẫn đọc/ghi file như cũ cho tới các phase sau.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS _meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # ── config toàn cục (thay novel2epub.yaml khối `defaults:`) ─────────
    """
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        novel_json TEXT NOT NULL DEFAULT '{}',
        crawl_json TEXT NOT NULL DEFAULT '{}',
        translate_json TEXT NOT NULL DEFAULT '{}',
        ai_json TEXT NOT NULL DEFAULT '{}',
        output_json TEXT NOT NULL DEFAULT '{}',
        queue_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── preset site (thay sources.yaml) ──────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS sources (
        name TEXT PRIMARY KEY,
        data_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── ebook (thay khối `ebooks:` + library_state.json) ─────────────────
    """
    CREATE TABLE IF NOT EXISTS ebooks (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        -- KHÔNG dùng FOREIGN KEY tới sources(name): ebook có thể tham chiếu
        -- 1 preset đã bị xóa (cố ý — _resolve_source_overrides xử lý bằng
        -- warning graceful, không phải lỗi cứng, xem novel2epub/config.py).
        source_preset TEXT,
        archived INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT 'vi',
        publisher TEXT NOT NULL DEFAULT '',
        pubdate TEXT NOT NULL DEFAULT '',
        date_added TEXT NOT NULL DEFAULT '',
        subjects_json TEXT NOT NULL DEFAULT '[]',
        series TEXT NOT NULL DEFAULT '',
        series_index TEXT NOT NULL DEFAULT '',
        identifier TEXT NOT NULL DEFAULT '',
        cover_url TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        cover_file TEXT NOT NULL DEFAULT '',
        title_note TEXT NOT NULL DEFAULT '',
        metadata_missing_json TEXT NOT NULL DEFAULT '[]',
        curated_fields_json TEXT NOT NULL DEFAULT '[]',
        crawl_overrides_json TEXT NOT NULL DEFAULT '{}',
        output_overrides_json TEXT NOT NULL DEFAULT '{}',
        epub_path TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ebooks_archived ON ebooks(archived)",
    # ── chương: manifest fields + nội dung raw/translated/translated_mt ──
    """
    CREATE TABLE IF NOT EXISTS chapters (
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        url TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        title_zh TEXT NOT NULL DEFAULT '',
        title_note TEXT NOT NULL DEFAULT '',
        missing_fields_json TEXT NOT NULL DEFAULT '[]',
        duplicate_of INTEGER,
        last_action_status TEXT NOT NULL DEFAULT '',
        skipped INTEGER NOT NULL DEFAULT 0,
        raw_text TEXT,
        translated_text TEXT,
        translated_mt_text TEXT,
        meta_json TEXT NOT NULL DEFAULT '{}',
        translated_updated_at REAL,
        PRIMARY KEY (ebook_slug, idx)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapters_skipped ON chapters(ebook_slug, skipped)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_status ON chapters(ebook_slug, last_action_status)",
    # ── glossary (names.txt / vietphrase.txt) ────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS glossary_entries (
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        list_name TEXT NOT NULL,
        source TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (ebook_slug, list_name, source)
    ) WITHOUT ROWID
    """,
    # ── ghi chú lỗi dịch (trang đọc) ──────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        data_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notes_ebook ON notes(ebook_slug)",
    # ── ảnh bìa ───────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS ebook_covers (
        ebook_slug TEXT PRIMARY KEY REFERENCES ebooks(slug) ON DELETE CASCADE,
        ext TEXT NOT NULL DEFAULT 'jpg',
        content BLOB NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── kho JSON phụ theo ebook (cost summary, glossary conflicts, ...) ──
    """
    CREATE TABLE IF NOT EXISTS ebook_extra_json (
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        key TEXT NOT NULL,
        data_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (ebook_slug, key)
    ) WITHOUT ROWID
    """,
    # ── hàng đợi job (thay queue_history.json / queue_pending.json) ──────
    """
    CREATE TABLE IF NOT EXISTS job_queue_history (
        id TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        ended_at REAL,
        inserted_at REAL NOT NULL DEFAULT (unixepoch('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jqh_ended ON job_queue_history(ended_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS job_queue_pending (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        step TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        ebook TEXT NOT NULL DEFAULT '',
        spec_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    # ── automation (thay automations.yaml) ───────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS automations (
        id TEXT PRIMARY KEY,
        ebook TEXT NOT NULL,
        steps_json TEXT NOT NULL DEFAULT '["build"]',
        schedule TEXT NOT NULL DEFAULT 'manual',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_run_at TEXT NOT NULL DEFAULT '',
        last_run_outcome TEXT NOT NULL DEFAULT '',
        last_run_error TEXT NOT NULL DEFAULT '',
        last_run_stats_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_automations_ebook ON automations(ebook)",
]


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Mở 1 kết nối SQLite mới với PRAGMA cần thiết cho an toàn dữ liệu +
    concurrency (WAL, foreign_keys, busy_timeout). Mỗi thread nên tự gọi hàm
    này để lấy kết nối riêng (không share 1 Connection giữa nhiều thread) —
    xem phần concurrency của kế hoạch SQLite unification.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def resolve_db_path(data_dir: str | Path) -> Path:
    """Đường dẫn file `.db` thống nhất cho 1 `data_dir` (`<data_dir>/
    novel2epub.db`). `app/deps.py` derive `DB_PATH` bằng CHÍNH hàm này (cùng
    `data_dir` đọc từ config) để queue/automations/library_state trỏ vào
    đúng file `.db` mà `Storage(cfg.output.data_dir, slug)` cũng dùng —
    không dùng biến môi trường global vì sẽ rò rỉ giữa các test/tiến trình
    dùng `data_dir` khác nhau trong cùng 1 process."""
    path = Path(data_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path / "novel2epub.db"


_thread_local = threading.local()


def get_thread_connection(db_path: str | Path) -> sqlite3.Connection:
    """Kết nối SQLite của THREAD HIỆN TẠI cho `db_path` — an toàn gọi từ
    nhiều thread khác nhau (mỗi thread tự có 1 Connection riêng, xem phần
    concurrency của kế hoạch SQLite unification)."""
    key = str(db_path)
    conns: dict[str, sqlite3.Connection] = getattr(_thread_local, "conns", None)
    if conns is None:
        conns = {}
        _thread_local.conns = conns
    conn = conns.get(key)
    if conn is None:
        conn = get_connection(key)
        init_schema(conn)
        conns[key] = conn
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Tạo toàn bộ bảng nếu chưa có — idempotent, an toàn gọi mỗi lần khởi
    động app/CLI (không xóa/động tới dữ liệu đã có)."""
    with conn:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.execute(
            """
            INSERT INTO _meta (key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )


def schema_version(conn: sqlite3.Connection) -> int | None:
    """Trả schema_version hiện tại của DB, hoặc None nếu chưa init_schema."""
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row["value"]) if row else None
