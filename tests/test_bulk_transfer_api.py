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


def _cfg(tmp_path, batch_size=10, glossary_filter=True):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(
            type="cli", delay_seconds=0, batch_size=batch_size,
            glossary_filter=glossary_filter,
        ),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    # batch/translate giờ chạy nền qua job queue (không block request) — thay
    # app.state.job bằng stub chạy target NGAY (sync trong request) để test
    # assert được kết quả ghi file/log mà không cần chờ worker thread thật
    # (xem _FakeJob, cùng pattern với tests/test_batch_delete_translation.py).
    app.state.job = _FakeJob()
    return TestClient(app)


class _FakeJob:
    """Stub cho app.state.job — start_custom chạy target NGAY (sync), bắt
    exception giống JobQueue._execute() thật (không để lộ ra HTTP response,
    chỉ ghi vào .error) và gom log lại (.logs) để test kiểm tra nội dung
    thông báo kết quả/lỗi — trước đây các nội dung này nằm trong JSON response
    lúc endpoint còn chạy đồng bộ."""

    def __init__(self):
        self.started: list[dict] = []
        self.logs: list[str] = []
        self.error: str = ""

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }

    def start_custom(self, name, target, *, category, ebook="", spec=None):
        self.started.append({"name": name, "category": category, "ebook": ebook, "spec": spec})
        self.logs = []
        self.error = ""
        try:
            target(self.logs.append)
        except Exception as e:
            self.error = str(e)
        return True


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
    # glossary_filter tắt: test này kiểm tra khối glossary được nhúng nguyên
    # vào export, không phải hành vi lọc (nội dung không chứa từ glossary).
    cfg = _cfg(tmp_path, glossary_filter=False)
    storage, _ = _seed(tmp_path)
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["skipped"] == []
    assert "## idx:1" in data["text"]
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
    assert "## idx:1: 第一章" in data["text"]


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
    """Happy path: chọn 2 chương có raw → job nền (chạy sync qua _FakeJob
    trong test) → AI trả về → ghi translated/ + glossary."""
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
    # Response trả ngay lúc enqueue — kết quả chi tiết nằm trong log của job.
    assert data["started"] is True
    assert data["pending"] == 2

    fake = client.app.state.job
    assert fake.error == ""
    log_text = "\n".join(fake.logs)
    assert "2/2 chương" in log_text
    assert "1 mục glossary mới" in log_text

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
    # Phải có marker chương (idx:N — không dùng "Chương N" để tránh AI nhầm
    # N với số chương thật)
    assert "## idx:1: 第1章" in p
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


def test_batch_translate_ai_error(tmp_path, monkeypatch):
    """AI lỗi cả 2 lần retry → batch bị SKIP, job vẫn hoàn tất (không raise).
    Log phải ghi nhận cả 2 lần lỗi + cảnh báo "bỏ qua", và chương KHÔNG được
    ghi translated/ — caller sẽ thấy nó trong danh sách `all_skipped`.
    """
    cfg = _cfg(tmp_path)
    storage, chapters = _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)

    call_count = {"n": 0}

    def _raise(*_a, **_k):
        call_count["n"] += 1
        raise RuntimeError("connection refused")

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _raise)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    assert res.status_code == 200
    assert res.json()["started"] is True
    # Job hoàn tất (không raise) — error rỗng, retry đúng 2 lần
    assert client.app.state.job.error == ""
    assert call_count["n"] == 2
    # Chương không được ghi translated/
    assert not storage.has_translated(chapters[0])
    # Log phải có cả 2 lần lỗi + cảnh báo bỏ qua
    log_text = "\n".join(client.app.state.job.logs)
    assert "lần 1" in log_text
    assert "lần 2" in log_text
    assert "bỏ qua" in log_text
    assert "connection refused" in log_text


def test_batch_translate_ai_retries_once_then_succeeds(tmp_path, monkeypatch):
    """AI lỗi lần 1 nhưng lần 2 thành công (round-robin đổi node) → batch vẫn
    được ghi translated/ bình thường, không có log "bỏ qua"."""
    cfg = _cfg(tmp_path)
    storage, chapters = _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)

    call_count = {"n": 0}

    def _maybe_fail(*_a, **_k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("timeout lần 1")
        return ("## Chương 1: 第1章\nBản dịch chương 1\n", {})

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _maybe_fail)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1"},
    )
    assert res.status_code == 200
    # Retry đúng 2 lần (fail + success)
    assert call_count["n"] == 2
    # Job không raise, chương được ghi
    assert client.app.state.job.error == ""
    assert storage.read_translated(chapters[0]) == "Bản dịch chương 1"
    # Log có thông báo retry + KHÔNG có "bỏ qua"
    log_text = "\n".join(client.app.state.job.logs)
    assert "thử lại" in log_text
    assert "bỏ qua" not in log_text


def test_batch_translate_continues_to_next_batch_after_ai_error(tmp_path, monkeypatch):
    """Batch 1 fail cả 2 lần (skip) → batch 2 vẫn chạy bình thường. Chỉ chương
    thuộc batch fail mới bị bỏ qua, các chương batch sau vẫn được dịch."""
    cfg = _cfg(tmp_path, batch_size=2)
    storage, chapters = _seed_with_raw(tmp_path, n=4)
    client = _client(cfg, monkeypatch)

    # batch_size=2 + 4 chương = 2 batch: [1,2] và [3,4]
    call_count = {"batch": 0}

    def _maybe_fail(*_a, **_k):
        call_count["batch"] += 1
        if call_count["batch"] == 1:
            raise RuntimeError("timeout lần 1")
        if call_count["batch"] == 2:
            raise RuntimeError("timeout lần 2")
        # Từ call thứ 3 trở đi (batch 2): trả về content cho cả 3 và 4
        return (
            "## Chương 3: 第3章\nDịch 3\n\n"
            "## Chương 4: 第4章\nDịch 4\n",
            {},
        )

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _maybe_fail)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1,2,3,4"},
    )
    assert res.status_code == 200
    # Job hoàn tất (không raise)
    assert client.app.state.job.error == ""
    # Batch 1 gọi AI 2 lần (đều fail) + Batch 2 gọi 1 lần (success) = 3 calls
    assert call_count["batch"] == 3
    # Batch 1 bị skip → chương 1,2 KHÔNG có translated/
    assert not storage.has_translated(chapters[0])
    assert not storage.has_translated(chapters[1])
    # Batch 2 chạy bình thường → chương 3,4 CÓ translated/
    assert storage.read_translated(chapters[2]) == "Dịch 3"
    assert storage.read_translated(chapters[3]) == "Dịch 4"
    # Log có cảnh báo skip + danh sách chương bị bỏ qua
    log_text = "\n".join(client.app.state.job.logs)
    assert "Bỏ qua do AI lỗi 2 lần liên tiếp" in log_text
    assert "[1, 2]" in log_text


def test_batch_translate_ai_no_marker_error(tmp_path, monkeypatch):
    """AI trả về nhưng không có marker chương nào → job ghi nhận lỗi rõ ràng."""
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
    assert res.status_code == 200
    assert "marker" in client.app.state.job.error


def test_batch_translate_ai_missing_chapter_reported(tmp_path, monkeypatch):
    """AI bỏ sót 1 chương → chỉ ghi chương có, log báo cáo phần bị bỏ sót."""
    cfg = _cfg(tmp_path)
    storage, chapters = _seed_with_raw(tmp_path, n=2)
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
    assert res.status_code == 200
    assert storage.read_translated(chapters[0]) == "Chỉ có 1"
    assert not storage.has_translated(chapters[1])
    log_text = "\n".join(client.app.state.job.logs)
    assert "bỏ sót" in log_text
    assert "[2]" in log_text


def test_batch_translate_preserves_existing_translated_mt(tmp_path, monkeypatch):
    """Chương có sẵn translated_mt/ (vd từ 1 lần dịch máy trước) nhưng CHƯA có
    translated/ (chưa tính là "đã dịch") → job vẫn chạy, và KHÔNG được đụng
    vào snapshot máy cũ khi ghi bản dịch mới."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "raw text")
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
    # translated/ được ghi
    assert storage.read_translated(ch) == "Bản dịch mới"
    # translated_mt/ KHÔNG bị đụng
    assert storage.read_translated_mt(ch) == "MT snapshot giữ nguyên"


def test_batch_translate_skips_chapters_without_raw(tmp_path, monkeypatch):
    """Tick 1 chương có raw + 1 chương chưa có raw → chỉ dịch chương có raw."""
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
    assert res.status_code == 200
    assert storage.read_translated(chapters[0]) == "Bản dịch 1"
    assert not storage.has_translated(chapters[1])
    log_text = "\n".join(client.app.state.job.logs)
    assert "chưa có raw" in log_text


def test_batch_translate_skips_already_translated(tmp_path, monkeypatch):
    """Chương đã có bản dịch (has_translated) → tự động bỏ qua, KHÔNG gọi AI
    lại và KHÔNG ghi đè — muốn dịch lại phải xoá bản dịch cũ trước."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "raw 1")
    storage.write_raw(chapters[1], "raw 2")
    storage.write_translated(chapters[0], "Đã dịch từ trước")
    client = _client(cfg, monkeypatch)

    call_count = {"n": 0}

    def _capture(openai_cfg, prompt):
        call_count["n"] += 1
        assert "raw 1" not in prompt  # chương 1 không được đưa vào prompt
        return ("## Chương 2\nBản dịch 2\n", {})

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    res = client.post(
        "/api/ebooks/t/batch/translate",
        data={"indexes": "1,2"},
    )
    assert res.status_code == 200
    assert res.json()["pending"] == 1
    assert call_count["n"] == 1
    assert storage.read_translated(chapters[0]) == "Đã dịch từ trước"
    assert storage.read_translated(chapters[1]) == "Bản dịch 2"
    log_text = "\n".join(client.app.state.job.logs)
    assert "1 chương đã dịch" in log_text


def test_batch_translate_all_already_translated_400(tmp_path, monkeypatch):
    """Tất cả chương đã chọn đều đã dịch rồi → 400, không enqueue job."""
    cfg = _cfg(tmp_path)
    storage, chapters = _seed_with_raw(tmp_path, n=1)
    storage.write_translated(chapters[0], "Đã dịch rồi")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1"})
    assert res.status_code == 400
    assert client.app.state.job.started == []


def test_batch_translate_includes_glossary_in_prompt(tmp_path, monkeypatch):
    """Glossary có sẵn phải được nhúng vào prompt gửi cho AI."""
    # glossary_filter tắt: kiểm tra nhúng glossary, không phải lọc theo nội dung.
    cfg = _cfg(tmp_path, glossary_filter=False)
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


# ── Tests cập nhật tiêu đề chương vào manifest ────────────────────────


def test_batch_translate_updates_manifest_titles(tmp_path, monkeypatch):
    """Tiêu đề AI dịch trong heading `## idx:N: <title>` ghi đè manifest.title,
    backfill title_zh (đang rỗng) bằng title cũ."""
    cfg = _cfg(tmp_path)
    storage, _ = _seed_with_raw(tmp_path, n=2)
    client = _client(cfg, monkeypatch)

    ai_response = (
        "## Chương 1: Khởi đầu\nBản dịch 1\n\n"
        "## Chương 2: Trở về\nBản dịch 2\n"
    )
    monkeypatch.setattr(
        openai_client, "run_chat_with_meta", lambda *_: (ai_response, {})
    )
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1,2"})
    assert res.status_code == 200
    assert "2 tiêu đề cập nhật" in "\n".join(client.app.state.job.logs)

    manifest = storage.load_manifest()
    by_idx = {c.index: c for c in manifest.chapters}
    # Tiêu đề gốc mở đầu 第N章 → ensure_title_number gắn lại "Chương N: ".
    assert by_idx[1].title == "Chương 1: Khởi đầu"
    assert by_idx[1].title_zh == "第1章"  # title cũ backfill vào title_zh
    assert by_idx[2].title == "Chương 2: Trở về"
    assert by_idx[2].title_zh == "第2章"


def test_batch_translate_keeps_existing_title_zh(tmp_path, monkeypatch):
    """title_zh đã có sẵn → KHÔNG bị ghi đè khi cập nhật title mới."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="Tiêu đề cũ VI", title_zh="第一章")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文")
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 1: Tiêu đề mới VI\nDịch\n", {}),
    )
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1"})
    assert res.status_code == 200

    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title == "Tiêu đề mới VI"
    assert ch2.title_zh == "第一章"


def test_batch_translate_heading_without_title_keeps_manifest_title(tmp_path, monkeypatch):
    """Heading không kèm tiêu đề (`## Chương 1`) → giữ title cũ, không nằm trong titles_updated."""
    cfg = _cfg(tmp_path)
    storage, _ = _seed_with_raw(tmp_path, n=1)
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 1\nDịch xong\n", {}),
    )
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1"})
    assert res.status_code == 200
    assert "0 tiêu đề cập nhật" in "\n".join(client.app.state.job.logs)
    assert storage.load_manifest().chapters[0].title == "第1章"


def test_batch_translate_title_number_differs_from_index(tmp_path, monkeypatch):
    """Marker N là index VỊ TRÍ trong manifest; số chương trong tiêu đề có thể
    khác (vd vị trí 928 nhưng truyện đánh số 918) — match theo N của marker,
    title giữ nguyên văn."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=928, url="http://x/928", title="第918章 少年归来")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文")
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 928: Chương 918: Thiếu niên trở về\nDịch\n", {}),
    )
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "928"})
    assert res.status_code == 200
    assert storage.read_translated(ch) == "Dịch"
    assert "1 tiêu đề cập nhật" in "\n".join(client.app.state.job.logs)

    ch2 = storage.load_manifest().chapters[0]
    assert ch2.index == 928
    assert ch2.title == "Chương 918: Thiếu niên trở về"
    assert ch2.title_zh == "第918章 少年归来"


def test_batch_translate_reprefixes_real_chapter_number_when_ai_drops_it(tmp_path, monkeypatch):
    """AI dịch tiêu đề làm rơi 第911章 (số chương THẬT, khác index vị trí 961)
    → ensure_title_number gắn lại 'Chương 911: ' từ tiêu đề gốc."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=961, url="http://x/961", title="第911章 我要冻结所有法条！")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文")
    client = _client(cfg, monkeypatch)

    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda *_: ("## Chương 961: Ta muốn đóng băng tất cả pháp điều!\nDịch\n", {}),
    )
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "961"})
    assert res.status_code == 200
    assert "1 tiêu đề cập nhật" in "\n".join(client.app.state.job.logs)

    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title == "Chương 911: Ta muốn đóng băng tất cả pháp điều!"
    assert ch2.title_zh == "第911章 我要冻结所有法条！"


def test_batch_translate_idx_marker_end_to_end(tmp_path, monkeypatch):
    """Export dùng `## idx:N` (N = vị trí manifest, ở đây 1353) tách biệt với
    số chương thật nằm trong tiêu đề gốc (1338 — vd truyện đăng phiên ngoại,
    số thứ tự lệch số chương thật). AI giữ nguyên idx, chỉ dịch phần tiêu đề
    → import phải khớp đúng theo idx và ensure_title_number giữ số chương
    thật 1338, không lẫn với idx 1353."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    zh_title = "第1338章 番外一（就是先前把完本感言发错了，直接全盘修改重写成番外了）"
    ch = Chapter(index=1353, url="http://x/1353", title=zh_title)
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "正文")
    client = _client(cfg, monkeypatch)

    captured_prompt: dict = {}

    def _capture(openai_cfg, prompt):
        captured_prompt["text"] = prompt
        return (
            "## idx:1353: Chương 1338: Phiên ngoại 1 (...)\nBản dịch\n",
            {},
        )

    monkeypatch.setattr(openai_client, "run_chat_with_meta", _capture)
    res = client.post("/api/ebooks/t/batch/translate", data={"indexes": "1353"})
    assert res.status_code == 200

    # Export gửi AI phải dùng idx:1353, KHÔNG phải "Chương 1353" (tránh AI
    # nhầm 1353 là số chương thật khi tiêu đề cũng chứa 第1338章).
    assert f"## idx:1353: {zh_title}" in captured_prompt["text"]
    assert "## Chương 1353" not in captured_prompt["text"]

    ch2 = storage.load_manifest().chapters[0]
    assert ch2.index == 1353
    assert ch2.title == "Chương 1338: Phiên ngoại 1 (...)"
    assert ch2.title_zh == zh_title


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
    assert call_count["n"] == 3  # ceil(5/2) = 3
    assert "chia 3 batch" in "\n".join(client.app.state.job.logs)


def test_batch_translate_glossary_merges_across_batches(tmp_path, monkeypatch):
    """Glossary từ batch 1 phải xuất hiện trong prompt batch 2."""
    # glossary_filter tắt: kiểm tra merge glossary xuyên batch, không phải lọc.
    cfg = _cfg(tmp_path, batch_size=1, glossary_filter=False)
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
    """Log tổng kết phải tổng hợp cost/tokens từ tất cả batch."""
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
    assert res.status_code == 200

    log_text = "\n".join(client.app.state.job.logs)
    assert "0.0020 USD" in log_text  # cost_usd 0.001 * 2 batches
    assert "300 tokens" in log_text  # (100+50) * 2 batches
