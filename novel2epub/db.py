"""Kết nối + schema SQLite thống nhất — nền tảng của việc gộp toàn bộ state
(config, sources, dữ liệu ebook, sidecar workspace) vào 1 file `.db` duy nhất
để dễ backup/restore/triển khai.

Phase 0: chỉ định nghĩa schema + kết nối, CHƯA đụng tới `storage.py`/
`config.py` — các module đó vẫn đọc/ghi file như cũ cho tới các phase sau.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 9

_PRONOUN_MIGRATION_RULE = (
    "Ngôi xưng ưu tiên BẢNG NHÂN VẬT > ngôi kể thực tế > quan hệ/ngữ cảnh > "
    "gợi ý thể loại. Lời kể được dùng \"hắn\" khi tự nhiên, kể cả truyện hiện "
    "đại; không máy móc đổi thành \"anh/anh ta/anh ấy\". \"Ta/ngươi\" hợp lệ "
    "trong lời kể đúng ngôi, thoại và nội tâm khi đúng giọng, thân phận và quan "
    "hệ. Không ánh xạ máy móc 我→ta, 你→ngươi, 他→hắn."
)

_LEGACY_PRONOUN_RULES = (
    "Ngôi xưng phải theo quan hệ và ngữ cảnh, KHÔNG bê nguyên ta/ngươi. "
    "Chọn phù hợp giữa cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/nàng/ông ấy/"
    "bà ấy/ngài/người/con/cháu...",
    "Ngôi xưng theo quan hệ và ngữ cảnh, KHÔNG bê nguyên ta/ngươi. "
    "Chọn phù hợp giữa cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/nàng/ông ấy/"
    "bà ấy/ngài/người/con/cháu...",
    'Ngôi xưng theo quan hệ nhân vật và ngữ cảnh (ta/ngươi, chàng/nàng, sư '
    'phụ/đồ nhi, lão phu/tiểu hữu…). Tránh dùng "ta/ngươi" máy móc.',
)

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
        reader_json TEXT NOT NULL DEFAULT '{}',
        api_json TEXT NOT NULL DEFAULT '{}',
        -- Cấu hình WireGuard toàn cục (thư mục profile, executable, wgcf...).
        -- KHÔNG bao giờ lưu nội dung cấu hình WireGuard/private key ở đây —
        -- chỉ chứa tham chiếu đến file ngoài trong profiles_dir.
        wireguard_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── metadata profile WireGuard ─────────────────────────────────────────
    # Profile NẰM NGOÀI DB trong thư mục `wireguard.profiles_dir` (file .conf).
    # Bảng này CHỈ lưu metadata: id không rõ nguồn gốc, filename tương đối,
    # source, enabled, order, status + timestamps + error. KHÔNG lưu text cấu
    # hình hay private key. `id` là opaque (uuid hex) — không suy ra filename.
    """
    CREATE TABLE IF NOT EXISTS wireguard_profiles (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL DEFAULT 'manual',
        enabled INTEGER NOT NULL DEFAULT 1,
        position INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'inactive',
        error TEXT NOT NULL DEFAULT '',
        activated_at TEXT NOT NULL DEFAULT '',
        last_error_at TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wireguard_profiles_position ON wireguard_profiles(position, enabled)",
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
        reader_overrides_json TEXT NOT NULL DEFAULT '{}',
        translate_overrides_json TEXT NOT NULL DEFAULT '{}',
        ai_overrides_json TEXT NOT NULL DEFAULT '{}',
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
    # ── từ điển idiom/thành ngữ DÙNG CHUNG mọi ebook (global, không gắn ──
    # ebook_slug). Khác glossary per-ebook: kho thành ngữ/khẩu ngữ chung cho
    # cả LLM (tham chiếu prompt) lẫn MT 57M (hậu-chuẩn-hoá literal→natural +
    # protect zh→placeholder). `literals` = các bản máy hay ra, ngăn bằng `|`.
    """
    CREATE TABLE IF NOT EXISTS idioms (
        source TEXT PRIMARY KEY,
        target TEXT NOT NULL DEFAULT '',
        literals TEXT NOT NULL DEFAULT '',
        protect INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0
    ) WITHOUT ROWID
    """,
    # ── bảng nhân vật & ngôi xưng theo ebook ──────────────────────────────
    # Giải lỗi ngôi xưng: tiếng Trung chỉ có 我/你/他/她, tiếng Việt cần biết
    # giới tính, vai vế, alias và GIAI ĐOẠN quan hệ. `role_note` cố ý là văn
    # xuôi tự do — LLM đọc tốt hơn mọi enum ép được.
    """
    CREATE TABLE IF NOT EXISTS characters (
        ebook_slug   TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        source       TEXT NOT NULL,
        target       TEXT NOT NULL DEFAULT '',
        aliases      TEXT NOT NULL DEFAULT '',
        gender       TEXT NOT NULL DEFAULT '',
        self_pronoun TEXT NOT NULL DEFAULT '',
        narrator_ref TEXT NOT NULL DEFAULT '',
        role_note    TEXT NOT NULL DEFAULT '',
        importance   TEXT NOT NULL DEFAULT 'side',
        position     INTEGER NOT NULL DEFAULT 0,
        aliases_vi   TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (ebook_slug, source)
    ) WITHOUT ROWID
    """,
    # Quan hệ CÓ HƯỚNG (A→B khác B→A: đồ đệ gọi sư phụ khác chiều ngược lại).
    # `from_chapter` nằm trong khoá chính để một cặp có nhiều mốc xưng hô.
    # `to_chapter` NULL = còn hiệu lực tới mốc kế tiếp (hoặc mãi mãi) — chỉ điền
    # khi quan hệ chấm dứt dứt khoát mà không có mốc thay thế. `*_raw` là chữ
    # Hán gốc làm căn cứ (khác `a_calls_b`/`a_self` vốn đã là bản Việt hoá).
    """
    CREATE TABLE IF NOT EXISTS character_relations (
        ebook_slug    TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        a_source      TEXT NOT NULL,
        b_source      TEXT NOT NULL,
        from_chapter  INTEGER NOT NULL DEFAULT 0,
        a_calls_b     TEXT NOT NULL DEFAULT '',
        a_self        TEXT NOT NULL DEFAULT '',
        note          TEXT NOT NULL DEFAULT '',
        to_chapter    INTEGER,
        a_calls_b_raw TEXT NOT NULL DEFAULT '',
        a_self_raw    TEXT NOT NULL DEFAULT '',
        evidence      TEXT NOT NULL DEFAULT '',
        inferred      INTEGER NOT NULL DEFAULT 0,
        confidence    TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (ebook_slug, a_source, b_source, from_chapter)
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
        last_run_stats_json TEXT NOT NULL DEFAULT '{}',
        crawl_workers INTEGER NOT NULL DEFAULT 4,
        translate_workers INTEGER NOT NULL DEFAULT 4,
        created_at TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_automations_ebook ON automations(ebook)",
]

# Cột thêm vào bảng ĐÃ TỒN TẠI ở các phiên bản schema sau. `_SCHEMA_STATEMENTS`
# chỉ chạy `CREATE TABLE IF NOT EXISTS` nên DB cũ sẽ không có các cột này —
# `_ensure_columns` vá bằng ALTER TABLE. DB tạo mới đã có sẵn (khai báo trong
# CREATE TABLE ở trên), nên danh sách này là no-op với chúng.
_ADDED_COLUMNS = [
    # v2: đẩy chương lên app đọc (novel-reader / Supabase)
    ("settings", "reader_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("ebooks", "reader_overrides_json", "TEXT NOT NULL DEFAULT '{}'"),
    # v3: lịch cron — base tính "đến hạn" cho automation chưa từng chạy
    ("automations", "created_at", "TEXT NOT NULL DEFAULT ''"),
    ("automations", "crawl_workers", "INTEGER NOT NULL DEFAULT 4"),
    ("automations", "translate_workers", "INTEGER NOT NULL DEFAULT 4"),
    # v3: translate/ai per-ebook — mỗi ebook một config AI riêng, defaults
    # (bảng settings) chỉ còn là fallback + nguồn khi Reset.
    ("ebooks", "translate_overrides_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("ebooks", "ai_overrides_json", "TEXT NOT NULL DEFAULT '{}'"),
    # v6: AI trích nhân vật — chữ Hán gốc, bằng chứng, độ tin cậy, mốc kết thúc
    ("characters", "aliases_vi", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "to_chapter", "INTEGER"),
    ("character_relations", "a_calls_b_raw", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "a_self_raw", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "evidence", "TEXT NOT NULL DEFAULT ''"),
    ("character_relations", "inferred", "INTEGER NOT NULL DEFAULT 0"),
    ("character_relations", "confidence", "TEXT NOT NULL DEFAULT ''"),
    # v8: token + CORS cho OPDS/API ngoài localhost (tích hợp readest GĐ1).
    # KHÔNG gộp vào `reader_json` — khối đó thuộc app novel-reader (Supabase).
    ("settings", "api_json", "TEXT NOT NULL DEFAULT '{}'"),
    # v9: cấu hình WireGuard toàn cục (settings.wireguard_json) — chỉ tham
    # chiếu file ngoài, không phải nội dung cấu hình/private key.
    ("settings", "wireguard_json", "TEXT NOT NULL DEFAULT '{}'"),
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


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Thêm các cột của `_ADDED_COLUMNS` còn thiếu vào DB cũ (ALTER TABLE).

    SQLite không có `ADD COLUMN IF NOT EXISTS` nên phải tự dò bằng
    `PRAGMA table_info`. Idempotent; bảng chưa tồn tại thì bỏ qua (vòng
    `_SCHEMA_STATEMENTS` ở trên đã tạo rồi nên trường hợp này không xảy ra).
    """
    for table, column, decl in _ADDED_COLUMNS:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            continue
        if column not in {r["name"] for r in rows}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _upgrade_prompt_text(prompt: str) -> str:
    """Thay đúng luật xưng hô legacy đã phát hành; prompt khác giữ nguyên."""
    out = prompt
    for legacy in _LEGACY_PRONOUN_RULES:
        out = out.replace(legacy, _PRONOUN_MIGRATION_RULE)
    return out


def _upgrade_prompt_json(raw: str, *, settings: bool) -> str | None:
    """Nâng prompt trong JSON; trả None nếu hỏng, thiếu hoặc không thay đổi."""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    translate = data.get("translate") if settings else data
    if not isinstance(translate, dict):
        return None
    openai = translate.get("openai")
    if not isinstance(openai, dict):
        return None
    prompt = openai.get("prompt_template")
    if not isinstance(prompt, str):
        return None
    upgraded = _upgrade_prompt_text(prompt)
    if upgraded == prompt:
        return None
    openai["prompt_template"] = upgraded
    return json.dumps(data, ensure_ascii=False)


def _migrate_legacy_prompts(conn: sqlite3.Connection) -> None:
    """Nâng prompt global và từng ebook, an toàn gọi lại nhiều lần."""
    for row in conn.execute("SELECT id, translate_json FROM settings").fetchall():
        upgraded = _upgrade_prompt_json(row["translate_json"], settings=False)
        if upgraded is not None:
            conn.execute(
                "UPDATE settings SET translate_json = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (upgraded, row["id"]),
            )
    for row in conn.execute(
        "SELECT slug, translate_overrides_json FROM ebooks"
    ).fetchall():
        upgraded = _upgrade_prompt_json(
            row["translate_overrides_json"], settings=False
        )
        if upgraded is not None:
            conn.execute(
                "UPDATE ebooks SET translate_overrides_json = ?, "
                "updated_at = datetime('now') WHERE slug = ?",
                (upgraded, row["slug"]),
            )


def init_schema(conn: sqlite3.Connection) -> None:
    """Tạo toàn bộ bảng nếu chưa có — idempotent, an toàn gọi mỗi lần khởi
    động app/CLI (không xóa/động tới dữ liệu đã có)."""
    with conn:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        _ensure_columns(conn)
        _migrate_legacy_prompts(conn)
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
