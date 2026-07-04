"""Test route export/import biên tập hàng loạt (POST /api/ebooks/{slug}/batch/...)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub import openai_client
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path, batch_size=10):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0, batch_size=batch_size),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Bản dịch chương 1")
    storage.write_translated(chapters[1], "Bản dịch chương 2")
    storage.write_translated_mt(chapters[0], "MT 1")
    storage.write_translated_mt(chapters[1], "MT 2")
    return storage, chapters


def test_export_returns_text_with_prompt_and_chapters(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, _ = _seed(tmp_path)
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["skipped"] == []
    assert "## Chương 1" in data["text"]
    assert "Bản dịch chương 1" in data["text"]
    assert "萧炎 = Tiêu Viêm" in data["text"]


def test_export_skips_untranslated(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Chỉ chương 1")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["skipped"] == [2]


def test_export_raw_returns_translate_prompt_and_raw_text(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1", title="第一章")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "原文内容")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1", "source": "raw"})
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "raw"
    assert data["total"] == 1
    assert "Yêu cầu dịch truyện" in data["text"]
    assert "BIÊN TẬP LẠI" not in data["text"]
    assert "原文内容" in data["text"]
    assert "## Chương 1: 第一章" in data["text"]


def test_export_raw_skips_chapters_without_raw(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "只有章节一")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2", "source": "raw"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["skipped"] == [2]


def test_export_invalid_source_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1", "source": "bogus"})
    assert res.status_code == 400


def test_export_no_indexes_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/batch/export", data={"indexes": ""})
    assert res.status_code == 400


def test_import_preview_does_not_write(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    text = (
        "========== CHƯƠNG 1 ==========\nĐã sửa chương 1\n"
        "========== CHƯƠNG 2 ==========\nBản dịch chương 2\n"
        "========== GLOSSARY ==========\n[NAMES]\n林动 = Lâm Động\n"
    )
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1,2", "mode": "preview"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "preview"
    # Chương 1 đổi, chương 2 không đổi.
    by_idx = {c["index"]: c for c in data["chapters"]}
    assert by_idx[1]["changed"] is True
    assert by_idx[2]["changed"] is False
    assert data["glossary_names"] == {"林动": "Lâm Động"}
    # Preview KHÔNG ghi.
    assert storage.read_translated(chapters[0]) == "Bản dịch chương 1"
    assert storage.read_glossary_file("names.txt") == {}


def test_import_confirm_writes_and_merges_glossary(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    text = (
        "========== CHƯƠNG 1 ==========\nĐã sửa chương 1\n"
        "========== GLOSSARY ==========\n[NAMES]\n林动 = Lâm Động\n[VIETPHRASE]\n斗气 = Đấu khí\n"
    )
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1", "mode": "confirm"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["written"] == [1]
    assert data["glossary_added"] == 2
    # Ghi đè translated/ đúng chương.
    assert storage.read_translated(chapters[0]) == "Đã sửa chương 1"
    # KHÔNG đụng translated_mt/.
    assert storage.read_translated_mt(chapters[0]) == "MT 1"
    # Glossary đã merge.
    assert storage.read_glossary_file("names.txt") == {"林动": "Lâm Động"}
    assert storage.read_glossary_file("vietphrase.txt") == {"斗气": "Đấu khí"}


def test_import_confirm_backfills_translated_mt_when_missing(tmp_path, monkeypatch):
    """Chương chưa từng có translated_mt (vd vừa dịch lần đầu qua luồng 'xuất
    raw để dịch') — confirm phải ghi cả translated_mt lẫn translated."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "原文")
    client = _client(cfg, monkeypatch)

    text = "## Chương 1\nBản dịch đầu tiên\n"
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1", "mode": "confirm"},
    )
    assert res.status_code == 200
    assert storage.read_translated(chapters[0]) == "Bản dịch đầu tiên"
    assert storage.has_translated_mt(chapters[0])
    assert storage.read_translated_mt(chapters[0]) == "Bản dịch đầu tiên"


def test_import_no_marker_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": "không có marker", "indexes": "1", "mode": "preview"},
    )
    assert res.status_code == 400


def test_import_unknown_index_not_written(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    text = "========== CHƯƠNG 99 ==========\nChương không thuộc truyện\n"
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1", "mode": "confirm"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["written"] == []
    assert data["unknown"] == [99]


# ── Tests cho POST /api/ebooks/{slug}/batch/translate ─────────────────
# Endpoint mới: Dịch = Export RAW → gọi AI → parse_import → ghi translated/


def _seed_with_raw(tmp_path, n=2):
    """Seed 2 chương CHỈ có raw (chưa dịch) — mô phỏng flow vừa Crawl xong."""
    storage = Storage(tmp_path, "t")
    chapters = [
        Chapter(index=i, url=f"http://x/{i}", title=f"第{i}章") for i in range(1, n + 1)
    ]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        storage.write_raw(ch, f"原文内容 chương {ch.index}")
    return storage, chapters


class _FakeResp:
    """Mock response từ openai_client.run_chat_with_meta."""
    def __init__(self, content: str, status_code: int = 200, headers: dict | None = None):
        self._data = {
            "choices": [{"message": {"content": content}}]
        }
        self.status_code = status_code
        self.text = content if status_code != 200 else ""
        self.headers = headers or {}
        # Make it json-serializable for resp.json()
        self._json = self._data

    def json(self):
        return self._json


def test_batch_translate_happy_path(tmp_path, monkeypatch):
    """Happy path: chọn 2 chương có raw → AI trả về → ghi translated/ + glossary."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    storage, chapters = _seed_with_raw(tmp_path, n=2)
    client = _client(cfg, monkeypatch)

    ai_response = (
        "## Chương 1: 第1章\nBản dịch chương 1\n\n"
        "## Chương 2: 第2章\nBản dịch chương 2\n\n"
        "## GLOSSARY\n\n"
        "### NAMES\n"
        "- 林动 = Lâm Động\n"
    )

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda openai_cfg, prompt: (
            ai_response,
            {
                "version": "3.8.40",
                "cost_usd": 0.001,
                "tokens_in": 100,
                "tokens_out": 50,
                "latency_ms": 1500,
            },
        ),
    )

    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1,2"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["written"] == [1, 2]
    assert data["glossary_added"] == 1
    assert data["missing"] == []
    assert data["unknown"] == []
    # Cost meta pass-through từ run_chat_with_meta
    assert data["ai_meta"]["cost_usd"] == 0.001
    assert data["ai_meta"]["version"] == "3.8.40"

    # Ghi translated/ đúng nội dung
    assert storage.read_translated(chapters[0]) == "Bản dịch chương 1"
    assert storage.read_translated(chapters[1]) == "Bản dịch chương 2"
    # Backfill translated_mt/ (chưa có sẵn)
    assert storage.has_translated_mt(chapters[0])
    assert storage.read_translated_mt(chapters[0]) == "Bản dịch chương 1"
    # Glossary merged
    assert storage.read_glossary_file("names.txt") == {"林动": "Lâm Động"}


def test_batch_translate_uses_TRANSLATE_PROMPT(tmp_path, monkeypatch):
    """Verify rằng prompt gửi cho AI khớp 100% với "Xuất RAW để dịch" (TRANSLATE_PROMPT)."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)

    captured_prompt: dict = {}

    def _capture(openai_cfg, prompt):
        captured_prompt["text"] = prompt
        return ("## Chương 1\nDịch xong\n", {})

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    p = captured_prompt["text"]
    # Prompt phải chứa yêu cầu dịch (không phải biên tập)
    assert "Yêu cầu dịch truyện" in p
    assert "BIÊN TẬP LẠI" not in p
    # Phải có marker chương
    assert "## Chương 1: 第1章" in p
    # Phải có raw text
    assert "原文内容 chương 1" in p


def test_batch_translate_no_indexes_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": ""})
    assert res.status_code == 400


def test_batch_translate_no_raw_400(tmp_path, monkeypatch):
    """Không có chương nào có raw → 400."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1")]))
    client = _client(cfg, monkeypatch)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    assert res.status_code == 400
    assert "raw" in res.json()["detail"]


def test_batch_translate_ai_error_502(tmp_path, monkeypatch):
    """AI lỗi → 502 với message."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)

    def _raise(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _raise)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    assert res.status_code == 502
    assert "connection refused" in res.json()["detail"]


def test_batch_translate_ai_no_marker_502(tmp_path, monkeypatch):
    """AI trả về nhưng không có marker chương nào → 502 với message rõ ràng."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("AI nói linh tinh không có marker nào", {}),
    )
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    assert res.status_code == 502
    assert "marker" in res.json()["detail"]


def test_batch_translate_ai_missing_chapter_reported(tmp_path, monkeypatch):
    """AI bỏ sót 1 chương → written chỉ chứa chương có, missing báo cáo."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    _seed_with_raw(tmp_path, n=2)
    client = _client(cfg, monkeypatch)

    # AI chỉ trả chương 1, bỏ sót chương 2
    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 1\nChỉ có 1\n", {}),
    )
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1,2"},
    )
    data = res.json()
    assert data["written"] == [1]
    assert data["missing"] == [2]
    assert data["unknown"] == []


def test_batch_translate_preserves_existing_translated_mt(tmp_path, monkeypatch):
    """Nếu đã có translated_mt/ (đang biên tập dịch cũ) → KHÔNG đụng snapshot máy."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "raw text")
    storage.write_translated(ch, "bản dịch cũ")
    storage.write_translated_mt(ch, "MT snapshot giữ nguyên")
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 1\nBản dịch mới\n", {}),
    )
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    assert res.status_code == 200
    # translated/ được ghi đè
    assert storage.read_translated(ch) == "Bản dịch mới"
    # translated_mt/ KHÔNG bị đụng
    assert storage.read_translated_mt(ch) == "MT snapshot giữ nguyên"


def test_batch_translate_skips_chapters_without_raw(tmp_path, monkeypatch):
    """Tick 1 chương có raw + 1 chương chưa có raw → chỉ dịch chương có raw."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "raw 1")
    # Chương 2 không có raw
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 1\nBản dịch 1\n", {}),
    )
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1,2"},
    )
    data = res.json()
    assert data["written"] == [1]
    assert data["skipped"] == [2]


def test_batch_translate_includes_glossary_in_prompt(tmp_path, monkeypatch):
    """Glossary có sẵn phải được nhúng vào prompt gửi cho AI."""
    from app.routes import chapters as chapters_routes

    cfg = _cfg(tmp_path)
    storage, _ = _seed_with_raw(tmp_path, n=1)
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n")
    storage.write_glossary_file("vietphrase.txt", "斗气 = Đấu khí\n")
    client = _client(cfg, monkeypatch)

    captured: dict = {}

    def _capture(openai_cfg, prompt):
        captured["text"] = prompt
        return ("## Chương 1\nOK\n", {})

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    p = captured["text"]
    assert "萧炎 = Tiêu Viêm" in p
    assert "斗气 = Đấu khí" in p
    assert "## Glossary tham khảo" in p


# ── Tests cho batch splitting ──────────────────────────────────────────


def test_batch_translate_splits_into_batches(tmp_path, monkeypatch):
    """Với batch_size=2 và 5 chapters → AI được gọi 3 lần."""
    cfg = _cfg(tmp_path, batch_size=2)
    storage, _ = _seed_with_raw(tmp_path, n=5)
    client = _client(cfg, monkeypatch)

    call_count = {"n": 0}

    def _capture(openai_cfg, prompt):
        call_count["n"] += 1
        # Trả về 1 chương bất kỳ trong batch
        return ("## Chương 1: 第1章\nDịch OK\n", {})

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1,2,3,4,5"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["batches"] == 3  # ceil(5/2) = 3
    assert call_count["n"] == 3


def test_batch_translate_glossary_merges_across_batches(tmp_path, monkeypatch):
    """Glossary từ batch 1 phải xuất hiện trong prompt batch 2."""
    cfg = _cfg(tmp_path, batch_size=1)
    storage, _ = _seed_with_raw(tmp_path, n=2)
    client = _client(cfg, monkeypatch)

    prompts: list[str] = []

    def _capture(openai_cfg, prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            # Batch 1: trả glossary mới
            return (
                "## Chương 1: 第1章\nDịch 1\n\n"
                "## GLOSSARY\n\n### NAMES\n- 萧炎 = Tiêu Viêm\n",
                {},
            )
        # Batch 2: chỉ trả dịch
        return ("## Chương 2: 第2章\nDịch 2\n", {})

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1,2"})
    assert res.status_code == 200

    # Prompt batch 2 phải chứa glossary từ batch 1
    assert len(prompts) == 2
    assert "萧炎 = Tiêu Viêm" in prompts[1]
    assert "## Glossary tham khảo" in prompts[1]


def test_batch_translate_meta_aggregated(tmp_path, monkeypatch):
    """ai_meta phải tổng hợp cost/tokens từ tất cả batch."""
    cfg = _cfg(tmp_path, batch_size=1)
    storage, _ = _seed_with_raw(tmp_path, n=2)
    client = _client(cfg, monkeypatch)

    def _capture(openai_cfg, prompt):
        return (
            "## Chương 1: 第1章\nDịch 1\n",
            {"cost_usd": 0.001, "tokens_in": 100, "tokens_out": 50, "latency_ms": 1000},
        )

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1,2"})
    data = res.json()

    assert data["ai_meta"]["cost_usd"] == 0.002  # 0.001 * 2 batches
    assert data["ai_meta"]["tokens_in"] == 200
    assert data["ai_meta"]["tokens_out"] == 100
    assert data["ai_meta"]["latency_ms"] == 2000
    assert data["ai_meta"]["batches"] == 2
