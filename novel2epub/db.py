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

SCHEMA_VERSION = 22

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
        global_ai_json TEXT NOT NULL DEFAULT '{}',
        oidc_json TEXT NOT NULL DEFAULT '{}',
        session_epoch INTEGER NOT NULL DEFAULT 0,
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
        code TEXT NOT NULL DEFAULT '',
        data_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── ebook (thay khối `ebooks:` + library_state.json) ─────────────────
    """
    CREATE TABLE IF NOT EXISTS ebooks (
        slug TEXT PRIMARY KEY,
        code TEXT NOT NULL DEFAULT '',
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
        raw_title TEXT NOT NULL DEFAULT '',
        raw_author TEXT NOT NULL DEFAULT '',
        raw_description TEXT NOT NULL DEFAULT '',
        raw_subjects_json TEXT NOT NULL DEFAULT '[]',
        raw_source_hash TEXT NOT NULL DEFAULT '',
        raw_updated_at TEXT NOT NULL DEFAULT '',
        translated_metadata_source_hash TEXT NOT NULL DEFAULT '',
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
        revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ebooks_archived ON ebooks(archived)",
    # ── chương: manifest fields + nội dung raw/translated/translated_mt ──
    # `translated_text`/`translated_mt_text`/`revision`/`title`/`title_zh` là
    # nhánh AI (ai_translation); `local_mt_*` là nhánh Local NMT độc lập. Mỗi
    # chương có `active_branch` — bản dịch của nhánh đang hoạt động là thứ đi
    # vào EPUB/Reader. Hai nhánh có revision/tiêu đề/workspace RIÊNG.
    """
    CREATE TABLE IF NOT EXISTS chapters (
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        code TEXT NOT NULL DEFAULT '',
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
        active_branch TEXT NOT NULL DEFAULT 'ai',
        local_mt_text TEXT,
        local_mt_revision INTEGER NOT NULL DEFAULT 1,
        local_mt_title TEXT NOT NULL DEFAULT '',
        local_mt_title_zh TEXT NOT NULL DEFAULT '',
        local_mt_mt_snapshot TEXT,
        meta_json TEXT NOT NULL DEFAULT '{}',
        revision INTEGER NOT NULL DEFAULT 1,
        updated_by_issuer TEXT NOT NULL DEFAULT '',
        updated_by_subject TEXT NOT NULL DEFAULT '',
        translated_updated_at REAL,
        ai_content_hash TEXT NOT NULL DEFAULT '',
        local_mt_content_hash TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (ebook_slug, idx)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapters_skipped ON chapters(ebook_slug, skipped)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_status ON chapters(ebook_slug, last_action_status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_code ON sources(code) WHERE code <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ebooks_code ON ebooks(code) WHERE code <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapters_code ON chapters(code) WHERE code <> ''",
    # Trạng thái hẹp cho các màn hình tổng quan.  Không đọc blob raw/dịch từ
    # `chapters` chỉ để vẽ tiến độ: bảng chapters có thể lớn hàng GB.
    """
    CREATE TABLE IF NOT EXISTS chapter_ui_state (
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        active_branch TEXT NOT NULL DEFAULT 'ai',
        has_raw INTEGER NOT NULL DEFAULT 0,
        has_ai_translation INTEGER NOT NULL DEFAULT 0,
        has_local_mt_translation INTEGER NOT NULL DEFAULT 0,
        has_translated INTEGER NOT NULL DEFAULT 0,
        raw_len INTEGER NOT NULL DEFAULT 0,
        translated_len INTEGER NOT NULL DEFAULT 0,
        edit_state TEXT NOT NULL DEFAULT '',
        han_fixed_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (ebook_slug, idx)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapter_ui_state_ebook ON chapter_ui_state(ebook_slug, idx)",
    """
    CREATE TRIGGER IF NOT EXISTS chapters_ui_state_after_insert
    AFTER INSERT ON chapters
    BEGIN
        INSERT INTO chapter_ui_state (
            ebook_slug, idx, active_branch, has_raw, has_ai_translation,
            has_local_mt_translation, has_translated, raw_len, translated_len,
            edit_state, han_fixed_count
        ) VALUES (
            NEW.ebook_slug, NEW.idx, COALESCE(NEW.active_branch, 'ai'),
            CASE WHEN COALESCE(NEW.raw_text, '') != '' THEN 1 ELSE 0 END,
            CASE WHEN COALESCE(NEW.translated_text, '') != '' AND
                (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete') IS NULL OR
                 COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete'), 0) != 0) THEN 1 ELSE 0 END,
            CASE WHEN COALESCE(NEW.local_mt_text, '') != '' AND
                (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete') IS NULL OR
                 COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete'), 0) != 0) THEN 1 ELSE 0 END,
            CASE WHEN COALESCE(NEW.active_branch, 'ai') = 'local_mt' THEN
                CASE WHEN COALESCE(NEW.local_mt_text, '') != '' AND
                    (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete') IS NULL OR COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete'), 0) != 0) THEN 1 ELSE 0 END
            ELSE CASE WHEN COALESCE(NEW.translated_text, '') != '' AND
                    (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete') IS NULL OR COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete'), 0) != 0) THEN 1 ELSE 0 END END,
            LENGTH(COALESCE(NEW.raw_text, '')),
            CASE WHEN COALESCE(NEW.active_branch, 'ai') = 'local_mt' THEN LENGTH(COALESCE(NEW.local_mt_text, '')) ELSE LENGTH(COALESCE(NEW.translated_text, '')) END,
            CASE WHEN json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.ai_rewrite') NOT IN ('null') AND json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.ai_rewrite') IS NOT NULL THEN 'draft'
                 WHEN json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.before_rewrite') NOT IN ('null') AND json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.before_rewrite') IS NOT NULL THEN 'edited_ai'
                 WHEN json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_ai_edited') NOT IN ('null') AND json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_ai_edited') IS NOT NULL THEN 'edited_local_mt'
                 ELSE '' END,
            COALESCE(CAST(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.han_cleanup.fixed_count') AS INTEGER), 0)
        );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chapters_ui_state_after_update
    AFTER UPDATE OF active_branch, raw_text, translated_text, local_mt_text, meta_json ON chapters
    BEGIN
        DELETE FROM chapter_ui_state WHERE ebook_slug=NEW.ebook_slug AND idx=NEW.idx;
        INSERT INTO chapter_ui_state (ebook_slug, idx, active_branch, has_raw, has_ai_translation, has_local_mt_translation, has_translated, raw_len, translated_len, edit_state, han_fixed_count)
        SELECT NEW.ebook_slug, NEW.idx, COALESCE(NEW.active_branch, 'ai'),
            COALESCE(NEW.raw_text, '') != '',
            COALESCE(NEW.translated_text, '') != '' AND (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete') IS NULL OR COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete'), 0) != 0),
            COALESCE(NEW.local_mt_text, '') != '' AND (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete') IS NULL OR COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete'), 0) != 0),
            CASE WHEN COALESCE(NEW.active_branch, 'ai') = 'local_mt' THEN COALESCE(NEW.local_mt_text, '') != '' AND (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete') IS NULL OR COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_complete'), 0) != 0) ELSE COALESCE(NEW.translated_text, '') != '' AND (json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete') IS NULL OR COALESCE(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.complete'), 0) != 0) END,
            LENGTH(COALESCE(NEW.raw_text, '')), CASE WHEN COALESCE(NEW.active_branch, 'ai') = 'local_mt' THEN LENGTH(COALESCE(NEW.local_mt_text, '')) ELSE LENGTH(COALESCE(NEW.translated_text, '')) END,
            CASE WHEN json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.ai_rewrite') NOT IN ('null') AND json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.ai_rewrite') IS NOT NULL THEN 'draft' WHEN json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.before_rewrite') NOT IN ('null') AND json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.before_rewrite') IS NOT NULL THEN 'edited_ai' WHEN json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_ai_edited') NOT IN ('null') AND json_type(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.local_mt_ai_edited') IS NOT NULL THEN 'edited_local_mt' ELSE '' END,
            COALESCE(CAST(json_extract(CASE WHEN json_valid(NEW.meta_json) THEN NEW.meta_json ELSE '{}' END, '$.han_cleanup.fixed_count') AS INTEGER), 0);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chapters_ui_state_after_identity_update
    AFTER UPDATE OF ebook_slug, idx ON chapters
    BEGIN
        UPDATE chapter_ui_state SET ebook_slug=NEW.ebook_slug, idx=NEW.idx
        WHERE ebook_slug=OLD.ebook_slug AND idx=OLD.idx;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chapters_ui_state_after_delete
    AFTER DELETE ON chapters
    BEGIN
        DELETE FROM chapter_ui_state WHERE ebook_slug=OLD.ebook_slug AND idx=OLD.idx;
    END
    """,
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
        revision INTEGER NOT NULL DEFAULT 1,
        actor_issuer TEXT NOT NULL DEFAULT '',
        actor_subject TEXT NOT NULL DEFAULT '',
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
        actor_issuer TEXT NOT NULL DEFAULT '',
        actor_subject TEXT NOT NULL DEFAULT '',
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
        spec_json TEXT NOT NULL DEFAULT '{}',
        position INTEGER NOT NULL DEFAULT 0,
        actor_issuer TEXT NOT NULL DEFAULT '',
        actor_subject TEXT NOT NULL DEFAULT ''
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
    # ── API v2 / OIDC foundation (v10) ───────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS identities (
        issuer TEXT NOT NULL,
        subject TEXT NOT NULL,
        role TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (issuer, subject)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_identities_role ON identities(role, disabled)",
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL,
        actor_issuer TEXT NOT NULL DEFAULT '',
        actor_subject TEXT NOT NULL DEFAULT '',
        actor_role TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT 'success',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_request_action ON audit_events(request_id, action, resource_type, resource_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_cursor ON audit_events(created_at DESC, id DESC)",
    # ── candidate revisions — hộp bản nháp AI (v11) ──────────────────────
    # Mỗi bản nháp AI (rewrite/han-cleanup/fix) là một hàng, luôn bắt đầu ở
    # `status='pending'` (candidate CHƯA kích hoạt). `base_rev` + 
    # `base_translated_text` là snapshot "exact set" lúc sinh — dùng làm
    # optimistic lock khi người dùng "chấp nhận" (áp). `has_raw` cho biết engine
    # đó có được cấp raw_text không (chống rò rỉ raw vào AI edit). `expires_at`
    # là hạn để refresh snapshot: quá hạn thì không còn áp được nữa.
    """
    CREATE TABLE IF NOT EXISTS ai_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        branch TEXT NOT NULL DEFAULT 'ai',
        engine TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        base_rev INTEGER NOT NULL DEFAULT 1,
        base_translated_text TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        has_raw INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL DEFAULT '',
        applied_at TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ai_revisions_ebook_status ON ai_revisions(ebook_slug, idx, status)",
    "CREATE INDEX IF NOT EXISTS idx_ai_revisions_status_expiry ON ai_revisions(status, expires_at)",
    # `idx_ai_revisions_branch_status` KHÔNG được đặt ở đây dù cùng bảng: cột
    # `branch` không nằm trong CREATE TABLE ai_revisions phía trên — nó chỉ
    # được thêm qua `_ADDED_COLUMNS`/ALTER TABLE. Trên database MỚI, bảng vừa
    # được CREATE TABLE ở đây chưa có cột đó, nên index này phải đợi tới sau
    # khi `_ensure_columns` chạy LẦN HAI (xem `init_schema`) mới được tạo —
    # xem `_POST_COLUMN_INDEXES` bên dưới.
    # ── từ điển entity (v11 mở rộng) ─────────────────────────────────────
    # Entity (tên riêng nhân vật, địa danh, ...) được bảo vệ trong AI edit:
    # `protect=1` ⇒ AI chỉ được nhìn `ENT<prefix>` placeholder chứ không thấy
    # literal; sau khi AI trả kết quả ta khôi phục literal từ placeholder.
    # Bảng này là toàn cục; per-ebook override nằm ở `ebook_entity_overrides`.
    """
    CREATE TABLE IF NOT EXISTS entity_dictionary (
        source TEXT NOT NULL PRIMARY KEY,
        target TEXT NOT NULL DEFAULT '',
        protect INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ebook_entity_overrides (
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        source TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',
        protect INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (ebook_slug, source)
    )
    """,
    # ── preview token chính xác (v11 mở rộng) ────────────────────────────────────
    # Token phát ra để review "bản nháp sắp áp" — xác thực bằng chính snapshot
    # nội dung tại thời điểm cấp token (base_rev + base_text), nên UI không thể
    # nhầm lẫn bản khác với bản được duyệt. Một token chỉ dùng được 1 lần,
    # có hạn, và bị vô hiệu hoá khi chương thay đổi.
    """
    CREATE TABLE IF NOT EXISTS preview_tokens (
        token TEXT NOT NULL PRIMARY KEY,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        branch TEXT NOT NULL DEFAULT 'ai',
        revision_id INTEGER NOT NULL,
        base_rev INTEGER NOT NULL DEFAULT 1,
        base_text TEXT NOT NULL DEFAULT '',
        expires_at TEXT NOT NULL DEFAULT '',
        consumed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_preview_tokens_ebook ON preview_tokens(ebook_slug, idx, branch)",
    # ── trạng thái build artifact (v11 mở rộng) ──────────────────────────────────
    # 1 hàng mỗi ebook. `lock_owner` ghi chủ đang build (blocker — không cho
    # build chồng); `manifest_snapshot` là fingerprint các nhánh đang hoạt
    # động lúc build — thay đổi bản dịch sau đó ⇒ build stale. `finished_at`
    # phân biệt "đang chạy" (đang build) với "xong".
    """
    CREATE TABLE IF NOT EXISTS build_artifacts (
        ebook_slug TEXT NOT NULL PRIMARY KEY REFERENCES ebooks(slug) ON DELETE CASCADE,
        lock_owner TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL DEFAULT '',
        finished_at TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'none',
        error TEXT NOT NULL DEFAULT '',
        manifest_snapshot TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── bulk preview token (hợp đồng bulk-preview / bulk-confirm) ─────────────────
    # Token phát ra khi user preview hành động hàng loạt chương. Confirm xác
    # thực bằng chính snapshot đánh giá (config_hash + fingerprint workspace
    # từng chương) nên hành động chỉ chạy đúng trên trạng thái đã được duyệt.
    # Một token chỉ dùng được 1 lần và có hạn.
    """
    CREATE TABLE IF NOT EXISTS bulk_tokens (
        token TEXT NOT NULL PRIMARY KEY,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        action TEXT NOT NULL DEFAULT '',
        options_json TEXT NOT NULL DEFAULT '{}',
        config_hash TEXT NOT NULL DEFAULT '',
        chapters_json TEXT NOT NULL DEFAULT '[]',
        eligibility_json TEXT NOT NULL DEFAULT '{}',
        estimates_json TEXT NOT NULL DEFAULT '{}',
        expires_at TEXT NOT NULL DEFAULT '',
        consumed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bulk_tokens_ebook ON bulk_tokens(ebook_slug, action)",
    # ── chapter_operations / chapter_revisions — ledger hai chiều (v13) ─────
    # Nhật ký append-only các thao tác thay đổi nội dung chương (translate,
    # ai-edit, pull-edits, ...) và mỗi revision nội dung theo nhánh. Baseline
    # migration (kind='migration_baseline') là snapshot nguyên trạng của từng
    # nhánh được khởi tạo — nền để sau này "dựng lại trạng thái" và đối chiếu
    # với bản hiện hành. `client_operation_id` NULL-free để idempotency theo
    # client (gửi lại không sinh trùng).
    """
    CREATE TABLE IF NOT EXISTS chapter_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        actor_issuer TEXT NOT NULL DEFAULT '',
        actor_subject TEXT NOT NULL DEFAULT '',
        client_operation_id TEXT NOT NULL DEFAULT '',
        request_hash TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_operations_client_id ON chapter_operations(client_operation_id)",
    "CREATE INDEX IF NOT EXISTS idx_chapter_operations_ebook ON chapter_operations(ebook_slug)",
    # `content_hash` là full SHA-256 (64 ký tự hex) của canonical `title` +
    # `content_blob` đã giải nén — bất biến sản phẩm, không cắt gọn. Baseline
    # có `parent_revision_id` NULL và `base_content_hash` NULL (mốc gốc).
    """
    CREATE TABLE IF NOT EXISTS chapter_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES chapter_operations(id) ON DELETE CASCADE,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        branch TEXT NOT NULL CHECK (branch IN ('ai', 'local_mt')),
        revision_number INTEGER NOT NULL,
        parent_revision_id INTEGER REFERENCES chapter_revisions(id),
        title TEXT NOT NULL DEFAULT '',
        content_blob BLOB,
        content_encoding TEXT NOT NULL DEFAULT 'zlib',
        content_hash TEXT NOT NULL DEFAULT '' CHECK (
            content_hash = '' OR (length(content_hash) = 64)
        ),
        base_content_hash TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapter_revisions_unique ON chapter_revisions(ebook_slug, chapter_index, branch, revision_number)",
    "CREATE INDEX IF NOT EXISTS idx_chapter_revisions_branch ON chapter_revisions(ebook_slug, chapter_index, branch, revision_number DESC)",
    "CREATE INDEX IF NOT EXISTS idx_chapter_revisions_operation ON chapter_revisions(operation_id)",
    # ── Kho dữ liệu canonical cho fine-tune (v18) ──────────────────────────
    """
    CREATE TABLE IF NOT EXISTS chapter_source_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES chapter_operations(id) ON DELETE RESTRICT,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
        parent_revision_id INTEGER REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT,
        source_url TEXT NOT NULL DEFAULT '',
        fetched_at TEXT NOT NULL DEFAULT '',
        fetcher_kind TEXT NOT NULL DEFAULT '',
        fetch_metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(fetch_metadata_json)),
        title TEXT NOT NULL DEFAULT '',
        content_blob BLOB NOT NULL,
        content_encoding TEXT NOT NULL DEFAULT 'zlib' CHECK (content_encoding = 'zlib'),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        base_content_hash TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (ebook_slug, chapter_index, revision_number),
        UNIQUE (ebook_slug, chapter_index, content_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_source_revisions_head ON chapter_source_revisions(ebook_slug, chapter_index, revision_number DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_source_revisions_operation ON chapter_source_revisions(operation_id)",
    """
    CREATE TABLE IF NOT EXISTS chapter_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        stable_key TEXT NOT NULL,
        created_from_source_revision_id INTEGER NOT NULL REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT,
        parent_segment_id INTEGER REFERENCES chapter_segments(id) ON DELETE RESTRICT,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','merged','split')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (ebook_slug, chapter_index, stable_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_revision_segments (
        source_revision_id INTEGER NOT NULL REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT,
        segment_id INTEGER NOT NULL REFERENCES chapter_segments(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        char_start INTEGER NOT NULL CHECK (char_start >= 0),
        char_end INTEGER NOT NULL CHECK (char_end >= char_start),
        content_text TEXT NOT NULL,
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        splitter TEXT NOT NULL DEFAULT 'nonempty_line_v1',
        splitter_version INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (source_revision_id, segment_id),
        UNIQUE (source_revision_id, ordinal)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS translation_revision_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        translation_revision_id INTEGER NOT NULL REFERENCES chapter_revisions(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        char_start INTEGER NOT NULL CHECK (char_start >= 0),
        char_end INTEGER NOT NULL CHECK (char_end >= char_start),
        content_text TEXT NOT NULL,
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        splitter TEXT NOT NULL DEFAULT 'nonempty_line_v1',
        splitter_version INTEGER NOT NULL DEFAULT 1,
        UNIQUE (translation_revision_id, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS segment_alignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_revision_id INTEGER NOT NULL REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT,
        translation_revision_id INTEGER NOT NULL REFERENCES chapter_revisions(id) ON DELETE RESTRICT,
        alignment_set TEXT NOT NULL DEFAULT 'default',
        method TEXT NOT NULL CHECK (method IN ('ordinal_backfill','exact','model','human')),
        confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','accepted','rejected','superseded')),
        operation_id INTEGER NOT NULL REFERENCES chapter_operations(id) ON DELETE RESTRICT,
        metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (source_revision_id, translation_revision_id, alignment_set)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS segment_alignment_members (
        alignment_id INTEGER NOT NULL REFERENCES segment_alignments(id) ON DELETE RESTRICT,
        group_ordinal INTEGER NOT NULL DEFAULT 0 CHECK (group_ordinal >= 0),
        side TEXT NOT NULL CHECK (side IN ('source','translation')),
        source_segment_id INTEGER REFERENCES chapter_segments(id) ON DELETE RESTRICT,
        translation_segment_id INTEGER REFERENCES translation_revision_segments(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
        PRIMARY KEY (alignment_id, group_ordinal, side, ordinal),
        CHECK ((side='source' AND source_segment_id IS NOT NULL AND translation_segment_id IS NULL)
            OR (side='translation' AND source_segment_id IS NULL AND translation_segment_id IS NOT NULL))
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES chapter_operations(id) ON DELETE RESTRICT,
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        source_revision_id INTEGER REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT,
        translation_revision_id INTEGER REFERENCES chapter_revisions(id) ON DELETE RESTRICT,
        source_segment_id INTEGER REFERENCES chapter_segments(id) ON DELETE RESTRICT,
        translation_segment_id INTEGER REFERENCES translation_revision_segments(id) ON DELETE RESTRICT,
        evidence_type TEXT NOT NULL,
        code TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','error','blocking')),
        verdict TEXT NOT NULL DEFAULT 'observed' CHECK (verdict IN ('observed','pass','fail','needs_review','accepted','rejected')),
        score REAL,
        confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        value_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(value_json)),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        CHECK (source_revision_id IS NOT NULL OR translation_revision_id IS NOT NULL)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_evidence_review ON chapter_evidence(ebook_slug, verdict, severity, chapter_index)",
    """
    CREATE TABLE IF NOT EXISTS chapter_eligibility_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id INTEGER NOT NULL REFERENCES chapter_operations(id) ON DELETE RESTRICT,
        translation_revision_id INTEGER NOT NULL REFERENCES chapter_revisions(id) ON DELETE RESTRICT,
        purpose TEXT NOT NULL CHECK (purpose IN ('publication','reader','review','mt_parallel','mt_post_edit','llm_translate','llm_post_edit','llm_critic','preference','dataset_eval')),
        policy_name TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        policy_hash TEXT NOT NULL CHECK (length(policy_hash) = 64),
        eligible INTEGER NOT NULL CHECK (eligible IN (0,1)),
        reason_codes_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(reason_codes_json)),
        evidence_snapshot_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_snapshot_json)),
        supersedes_id INTEGER REFERENCES chapter_eligibility_decisions(id) ON DELETE RESTRICT,
        decided_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (translation_revision_id, purpose, policy_name, policy_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapter_pointers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        namespace TEXT NOT NULL,
        pointer_key TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK (purpose IN ('reading','review','dataset')),
        ebook_slug TEXT NOT NULL REFERENCES ebooks(slug) ON DELETE CASCADE,
        chapter_index INTEGER NOT NULL,
        translation_revision_id INTEGER NOT NULL REFERENCES chapter_revisions(id) ON DELETE RESTRICT,
        source_revision_id INTEGER REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT,
        source_segment_id INTEGER REFERENCES chapter_segments(id) ON DELETE RESTRICT,
        translation_segment_id INTEGER REFERENCES translation_revision_segments(id) ON DELETE RESTRICT,
        alignment_id INTEGER REFERENCES segment_alignments(id) ON DELETE RESTRICT,
        selector_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(selector_json)),
        created_by_operation_id INTEGER REFERENCES chapter_operations(id) ON DELETE RESTRICT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (namespace, pointer_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapter_pointers_chapter ON chapter_pointers(ebook_slug, chapter_index, purpose)",
    # ── nhật ký ứng dụng (v22) — thay logs/app.log xoay vòng theo dung lượng ──
    # Mọi dòng log của novel2epub.* (crawler, translator, queue, scheduler...)
    # ghi 1 hàng vào đây thay vì file text: lọc được theo mức/logger/thời gian
    # ngay trong SQL, sống cùng bản backup `.db`, và bị giới hạn số hàng bởi
    # retention (novel2epub/logstore.py). `job_id` nối dòng log với job trong
    # job_queue_history khi dòng được ghi trong phạm vi job đó.
    """
    CREATE TABLE IF NOT EXISTS app_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        level TEXT NOT NULL,
        logger TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL,
        job_id TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_app_logs_ts ON app_logs(ts DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_app_logs_level ON app_logs(level, ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_app_logs_job ON app_logs(job_id) WHERE job_id <> ''",
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
    # v10: nền API v2/OIDC, optimistic concurrency và actor metadata.
    ("settings", "oidc_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("settings", "session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    ("ebooks", "revision", "INTEGER NOT NULL DEFAULT 1"),
    ("chapters", "revision", "INTEGER NOT NULL DEFAULT 1"),
    ("chapters", "updated_by_issuer", "TEXT NOT NULL DEFAULT ''"),
    ("chapters", "updated_by_subject", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "revision", "INTEGER NOT NULL DEFAULT 1"),
    ("notes", "actor_issuer", "TEXT NOT NULL DEFAULT ''"),
    ("notes", "actor_subject", "TEXT NOT NULL DEFAULT ''"),
    ("job_queue_history", "actor_issuer", "TEXT NOT NULL DEFAULT ''"),
    ("job_queue_history", "actor_subject", "TEXT NOT NULL DEFAULT ''"),
    ("job_queue_pending", "position", "INTEGER NOT NULL DEFAULT 0"),
    ("job_queue_pending", "actor_issuer", "TEXT NOT NULL DEFAULT ''"),
    ("job_queue_pending", "actor_subject", "TEXT NOT NULL DEFAULT ''"),
    # v11 (mở rộng): nhánh local_mt + ai_translation độc lập (title/workspace/
    # revisions riêng) và `ai_revisions.branch` đánh dấu nhánh mà candidate
    # thuộc về. `_SCHEMA_STATEMENTS`/`_ensure_columns` chạy trên MỌI lần mở DB
    # nên bảng/column mới cũng xuất hiện trên DB v11 đã tồn tại.
    ("chapters", "active_branch", "TEXT NOT NULL DEFAULT 'ai'"),
    ("chapters", "local_mt_text", "TEXT"),
    ("chapters", "local_mt_revision", "INTEGER NOT NULL DEFAULT 1"),
    ("chapters", "local_mt_title", "TEXT NOT NULL DEFAULT ''"),
    ("chapters", "local_mt_title_zh", "TEXT NOT NULL DEFAULT ''"),
    ("chapters", "local_mt_mt_snapshot", "TEXT"),
    ("ai_revisions", "branch", "TEXT NOT NULL DEFAULT 'ai'"),
    ("chapter_operations", "request_hash", "TEXT NOT NULL DEFAULT ''"),
    # v18: provenance truy vấn thường xuyên của immutable translation revision.
    ("chapter_revisions", "source_revision_id", "INTEGER REFERENCES chapter_source_revisions(id) ON DELETE RESTRICT"),
    ("chapter_revisions", "stage", "TEXT NOT NULL DEFAULT 'edited'"),
    ("chapter_revisions", "generator_kind", "TEXT NOT NULL DEFAULT ''"),
    ("chapter_revisions", "generator_name", "TEXT NOT NULL DEFAULT ''"),
    ("chapter_revisions", "generator_version", "TEXT NOT NULL DEFAULT ''"),
    ("chapter_revisions", "prompt_hash", "TEXT NOT NULL DEFAULT ''"),
    ("chapter_revisions", "config_hash", "TEXT NOT NULL DEFAULT ''"),
    ("chapter_revisions", "input_snapshot_hash", "TEXT NOT NULL DEFAULT ''"),
    ("chapter_revisions", "provenance_json", "TEXT NOT NULL DEFAULT '{}'"),
    # v13: per-branch content hash — mốc đối chiếu "bản hiện hành" của nhánh
    # với revision gần nhất (bất biến sản phẩm: full SHA-256 canonical).
    ("chapters", "ai_content_hash", "TEXT NOT NULL DEFAULT ''"),
    ("chapters", "local_mt_content_hash", "TEXT NOT NULL DEFAULT ''"),
    # v14: human-readable operational identity (SRC-EBOOK-0001).
    ("sources", "code", "TEXT NOT NULL DEFAULT ''"),
    ("ebooks", "code", "TEXT NOT NULL DEFAULT ''"),
    ("chapters", "code", "TEXT NOT NULL DEFAULT ''"),
    # v15: Global AI provider + raw metadata for curated/stale tracking.
    ("settings", "global_ai_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("ebooks", "raw_title", "TEXT NOT NULL DEFAULT ''"),
    ("ebooks", "raw_author", "TEXT NOT NULL DEFAULT ''"),
    ("ebooks", "raw_description", "TEXT NOT NULL DEFAULT ''"),
    ("ebooks", "raw_subjects_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("ebooks", "raw_source_hash", "TEXT NOT NULL DEFAULT ''"),
    ("ebooks", "raw_updated_at", "TEXT NOT NULL DEFAULT ''"),
    ("ebooks", "translated_metadata_source_hash", "TEXT NOT NULL DEFAULT ''"),
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
    `PRAGMA table_info`. Idempotent; bảng chưa tồn tại thì bỏ qua — gọi hàm
    này LẦN HAI sau khi `_SCHEMA_STATEMENTS` chạy (xem `init_schema`) mới
    thật sự vá được cột trên các bảng vừa được CREATE TABLE ở đó.
    """
    for table, column, decl in _ADDED_COLUMNS:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            continue
        if column not in {r["name"] for r in rows}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# Index tham chiếu cột chỉ tồn tại nhờ `_ADDED_COLUMNS`/ALTER TABLE (không nằm
# trong CREATE TABLE gốc của bảng trong `_SCHEMA_STATEMENTS`) — phải tạo SAU
# lần `_ensure_columns` thứ hai, nếu không CREATE INDEX sẽ thất bại trên
# database MỚI (bảng vừa CREATE TABLE chưa có cột đó cho tới khi ALTER chạy).
_POST_COLUMN_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ai_revisions_branch_status ON ai_revisions(ebook_slug, branch, status)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_ai_content_hash ON chapters(ebook_slug, ai_content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_local_mt_content_hash ON chapters(ebook_slug, local_mt_content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_chapter_revisions_source ON chapter_revisions(source_revision_id) WHERE source_revision_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_chapter_revisions_stage ON chapter_revisions(ebook_slug, chapter_index, branch, stage, revision_number DESC)",
]


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


class SchemaVersionError(RuntimeError):
    """DB được tạo bởi phiên bản mới hơn, không được tự động hạ schema."""


def _record_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO _meta (key, value) VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(version),),
    )


def _migration_v10(conn: sqlite3.Connection) -> None:
    """Thêm nền identity/audit/revision; ALTER giữ nguyên toàn bộ dữ liệu v9."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def _migration_v11(conn: sqlite3.Connection) -> None:
    """Thêm hộp bản nháp AI (`ai_revisions`), nhánh local_mt/ai_translation,
    từ điển entity, preview token và trạng thái build artifact; ALTER giữ
    nguyên dữ liệu v10."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def _migration_noop(conn: sqlite3.Connection) -> None:
    """Stub cho các phiên bản cũ đã được xử lý bằng _ensure_columns + CREATE TABLE IF NOT EXISTS."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


# Ánh xạ đổi tên/gỡ engine dịch: google/libretranslate (đã gỡ) → openai;
# hachimimt/moxhimt → localmt (tên chính thức của Local MT).
_TRANSLATE_TYPE_REWRITE = {
    "google": "openai",
    "libretranslate": "openai",
    "hachimimt": "localmt",
    "moxhimt": "localmt",
}


def _rewrite_translate_type(json_text: str | None) -> str | None:
    """Rewrite khoá `type` trong một khối translate JSON. Trả JSON mới nếu có
    thay đổi, ngược lại trả None (caller bỏ qua để không ghi thừa)."""
    if not json_text:
        return None
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    old = data.get("type")
    new = _TRANSLATE_TYPE_REWRITE.get(str(old or "").lower())
    changed = False
    if new and new != old:
        data["type"] = new
        changed = True
    # `libretranslate` sub-block cũng đã gỡ khỏi config — dọn luôn nếu còn.
    if data.pop("libretranslate", None) is not None:
        changed = True
    return json.dumps(data, ensure_ascii=False) if changed else None


def _migration_v12(conn: sqlite3.Connection) -> None:
    """Đổi tên engine dịch đã lưu: google/libretranslate → openai,
    hachimimt/moxhimt → localmt. Rewrite `settings.translate_json` (id=1) và
    `ebooks.translate_overrides_json`. Giữ nguyên mọi field khác."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)

    row = conn.execute("SELECT translate_json FROM settings WHERE id = 1").fetchone()
    if row is not None:
        new_text = _rewrite_translate_type(row["translate_json"] if hasattr(row, "keys") else row[0])
        if new_text is not None:
            conn.execute("UPDATE settings SET translate_json = ? WHERE id = 1", (new_text,))

    for r in conn.execute("SELECT slug, translate_overrides_json FROM ebooks").fetchall():
        slug = r["slug"] if hasattr(r, "keys") else r[0]
        current = r["translate_overrides_json"] if hasattr(r, "keys") else r[1]
        new_text = _rewrite_translate_type(current)
        if new_text is not None:
            conn.execute(
                "UPDATE ebooks SET translate_overrides_json = ? WHERE slug = ?",
                (new_text, slug),
            )


def _migration_v13(conn: sqlite3.Connection) -> None:
    """Thêm ledger hai chiều (`chapter_operations`/`chapter_revisions`) và cột
    hash theo nhánh (`chapters.ai_content_hash`/`local_mt_content_hash`);
    ALTER giữ nguyên toàn bộ dữ liệu v12."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def _migration_v14(conn: sqlite3.Connection) -> None:
    """Add and backfill stable source/ebook/chapter operational codes."""
    from .codes import backfill_codes

    _ensure_columns(conn)
    backfill_codes(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def _json_object(raw: str | dict | None) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _first_nonempty(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _migration_v15(conn: sqlite3.Connection) -> None:
    """Create the global AI provider and raw-metadata tracking fields."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)

    row = conn.execute(
        "SELECT translate_json, ai_json, global_ai_json FROM settings WHERE id = 1"
    ).fetchone()
    if row is not None:
        translate = _json_object(row["translate_json"])
        assistant = _json_object(row["ai_json"])
        global_ai = _json_object(row["global_ai_json"])
        translate_openai = _json_object(translate.get("openai"))
        assistant_openai = _json_object(assistant.get("openai"))
        migrated = {
            "base_url": _first_nonempty(
                translate_openai.get("base_url"), assistant_openai.get("base_url")
            ),
            "api_key": _first_nonempty(
                translate_openai.get("api_key"), assistant_openai.get("api_key")
            ),
            "translation_model": translate_openai.get("model"),
            "assistant_model": assistant_openai.get("model"),
            "timeout_seconds": _first_nonempty(
                translate_openai.get("timeout_seconds"),
                assistant_openai.get("timeout_seconds"),
            ),
            "temperature": _first_nonempty(
                translate_openai.get("temperature"), assistant_openai.get("temperature")
            ),
        }
        for key, value in migrated.items():
            if key not in global_ai and value not in (None, ""):
                global_ai[key] = value
        conn.execute(
            "UPDATE settings SET global_ai_json = ?, updated_at = datetime('now') WHERE id = 1",
            (json.dumps(global_ai, ensure_ascii=False),),
        )

    for ebook in conn.execute(
        "SELECT slug, translate_overrides_json, ai_overrides_json FROM ebooks"
    ).fetchall():
        translate = _json_object(ebook["translate_overrides_json"])
        assistant = _json_object(ebook["ai_overrides_json"])
        translation_openai = _json_object(translate.get("openai"))
        assistant_openai = _json_object(assistant.get("openai"))
        changed = False
        if "translation_model" not in translate and translation_openai.get("model"):
            translate["translation_model"] = translation_openai["model"]
            changed = True
        if "assistant_model" not in assistant and assistant_openai.get("model"):
            assistant["assistant_model"] = assistant_openai["model"]
            changed = True
        if changed:
            conn.execute(
                "UPDATE ebooks SET translate_overrides_json = ?, ai_overrides_json = ?, "
                "updated_at = datetime('now') WHERE slug = ?",
                (
                    json.dumps(translate, ensure_ascii=False),
                    json.dumps(assistant, ensure_ascii=False),
                    ebook["slug"],
                ),
            )


def _migration_v16(conn: sqlite3.Connection) -> None:
    """Activate completed legacy Local MT rows whose default AI branch is empty.

    The branch columns originally defaulted to ``ai`` before the translation
    pipeline started activating the branch it had just completed.  Restrict the
    backfill to unambiguous rows so an existing AI translation or an incomplete
    Local MT job is never overridden.
    """
    _ensure_columns(conn)
    conn.execute(
        """
        UPDATE chapters
        SET active_branch = 'local_mt'
        WHERE active_branch = 'ai'
          AND trim(COALESCE(translated_text, '')) = ''
          AND trim(COALESCE(local_mt_text, '')) != ''
          AND json_valid(COALESCE(meta_json, '{}'))
          AND COALESCE(json_extract(meta_json, '$.local_mt_complete'), 0) = 1
        """
    )


def _migration_v18(conn: sqlite3.Connection) -> None:
    """Thêm kho dữ liệu canonical additive; không tự backfill dữ liệu lớn."""
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)
    _ensure_columns(conn)
    for stmt in _POST_COLUMN_INDEXES:
        conn.execute(stmt)


def _migration_v19(conn: sqlite3.Connection) -> None:
    """Backfill projection trạng thái UI hẹp từ chapters một lần khi nâng cấp."""
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)
    # Trigger biến phép UPDATE no-op này thành projection cho từng chương.  Chỉ
    # chạy trong migration; các lần ghi sau được trigger đồng bộ cùng transaction.
    conn.execute("UPDATE chapters SET meta_json=meta_json")


def _migration_v20(conn: sqlite3.Connection) -> None:
    """Sửa trigger đổi khóa chapter để projection di chuyển không tự ghi lại chapter."""
    conn.execute("DROP TRIGGER IF EXISTS chapters_ui_state_after_identity_update")
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)


def _migration_v21(conn: sqlite3.Connection) -> None:
    """Giữ thứ tự queue qua restart và đổi category `both` sang `automation`."""
    _ensure_columns(conn)
    conn.execute("UPDATE job_queue_pending SET category = 'automation' WHERE category = 'both'")


def _migration_v22(conn: sqlite3.Connection) -> None:
    """Thêm bảng nhật ký ứng dụng `app_logs` (thay logs/app.log xoay vòng).

    Thuần additive — không đụng dữ liệu cũ, log file cũ còn lại nguyên vẹn
    trên đĩa để đối chiếu khi cần."""
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)



def _migration_v17(conn: sqlite3.Connection) -> None:
    """Gỡ cột `ebooks.name` — chỉ còn `title`.

    Ebook cũ có `name` nhưng chưa có `title` (tạo từ YAML/library chỉ khai
    `name`) được backfill `title = name` TRƯỚC khi xoá cột, rồi mới
    ALTER TABLE DROP COLUMN (SQLite >= 3.35; cột không nằm trong index/PK
    nên drop an toàn).
    """
    _ensure_columns(conn)
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)

    columns = {r["name"] for r in conn.execute("PRAGMA table_info(ebooks)")}
    if "name" not in columns:
        return
    conn.execute(
        """
        UPDATE ebooks
        SET title = name
        WHERE trim(COALESCE(title, '')) = '' AND trim(COALESCE(name, '')) != ''
        """
    )
    conn.execute("ALTER TABLE ebooks DROP COLUMN name")


_MIGRATIONS = {

    8: _migration_noop,
    9: _migration_noop,
    10: _migration_v10,
    11: _migration_v11,
    12: _migration_v12,
    13: _migration_v13,
    14: _migration_v14,
    15: _migration_v15,
    16: _migration_v16,
    17: _migration_v17,
    18: _migration_v18,
    19: _migration_v19,
    20: _migration_v20,
    21: _migration_v21,
    22: _migration_v22,
}


def init_schema(conn: sqlite3.Connection) -> None:
    """Tạo/nâng schema tuần tự và atomic, an toàn gọi lại nhiều lần.

    DB chưa có metadata được bootstrap bằng schema hiện tại. DB v9 trở lên chạy
    từng migration theo version; chỉ ghi version sau khi migration thành công.
    """
    current = schema_version(conn)
    if current is not None and current > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database schema v{current} is newer than supported v{SCHEMA_VERSION}"
        )

    with conn:
        # Giữ khả năng nâng các DB rất cũ vốn chưa có migration ledger.
        # `_ensure_columns` chạy TRƯỚC `_SCHEMA_STATEMENTS` để vá cột cho các
        # bảng ĐÃ TỒN TẠI từ phiên bản trước khi index của chúng chạy.
        _ensure_columns(conn)
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        # Gọi lại LẦN HAI: bảng nào vừa được CREATE TABLE ở vòng trên (database
        # hoàn toàn mới) chưa có mặt lúc lần gọi đầu nên bị bỏ qua — giờ bảng
        # đã tồn tại, `_ensure_columns` mới vá được cột `_ADDED_COLUMNS` của
        # nó. Phải chạy trước `_POST_COLUMN_INDEXES` vì index đó cần đúng cột
        # này (`ai_revisions.branch`, không nằm trong CREATE TABLE gốc).
        _ensure_columns(conn)
        from .codes import backfill_codes
        backfill_codes(conn)
        for stmt in _POST_COLUMN_INDEXES:
            conn.execute(stmt)
        _migrate_legacy_prompts(conn)

        start = current if current is not None else SCHEMA_VERSION
        for version in range(start + 1, SCHEMA_VERSION + 1):
            migration = _MIGRATIONS.get(version)
            if migration is None:
                raise SchemaVersionError(f"missing migration for schema v{version}")
            migration(conn)
            _record_schema_version(conn, version)
        if current is None:
            _record_schema_version(conn, SCHEMA_VERSION)


def schema_version(conn: sqlite3.Connection) -> int | None:
    """Trả schema_version hiện tại, kể cả trước khi `_meta` được tạo."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_meta'"
    ).fetchone()
    if not exists:
        return None
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row["value"]) if row else None
