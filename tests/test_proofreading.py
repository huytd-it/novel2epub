from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel2epub import build_validation as v, revisions
from novel2epub.proofreading import ProofreadingError, evidence_spans, fix_algorithms, validate_ai_edits
from novel2epub.proofreading_service import analyze, run, decide, snapshot, issue_confirmation, consume_confirmation
from novel2epub.storage import Storage, Chapter, Manifest
from tests.helpers.db import write_db_config


FIXTURES = json.loads((Path(__file__).parent / "fixtures/proofreading_validation.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["name"])
def test_shared_detectors(case):
    report = v.validate_chapter_detailed(case["text"], case["title"])
    assert {i["code"] for i in report["issues"]} == set(case["codes"])
    if "spans" in case:
        assert [[i["paraIndex"], i["start"], i["end"]] for i in report["issues"]] == case["spans"]


@pytest.mark.parametrize("kwargs", [{"codes": ""}, {"codes": {}}, {"codes": False}, {"drafts": []}, {"drafts": "invalid"}])
def test_analyze_rejects_invalid_input_shapes(kwargs):
    with pytest.raises(ProofreadingError):
        analyze(None, [1], **kwargs)


def test_algorithms_preserve_semantics_newlines_idempotent():
    text = "\ufeff## Đầu\r\n\r\n```\n👩‍👩‍👧‍👦 a‌b... … !!! ???\n<x>Giữ &amp;amp; chữ</x>  , lời....\n� 中 https://example.com\x00\n```\n"
    codes = list(v.ALGORITHM_CODES)
    result = fix_algorithms(text, codes, "Chương 1: Thử")
    after = result["after"]
    assert "Đầu\r\n\r\n\n" in after
    assert "👩‍👩‍👧‍👦 a‌b... … !!! ???" in after
    assert "Giữ & chữ, lời…" in after
    assert "� 中 https://example.com" in after
    assert after.endswith("\n\n")
    assert fix_algorithms(after, codes)["after"] == after
    assert fix_algorithms(text, ["url", "replacement_char", "han_remaining"])["after"] == text


def test_no_selected_codes_blocks_fix():
    with pytest.raises(ProofreadingError):
        fix_algorithms("  a", [])


def test_unknown_entities_and_acronyms_safe():
    assert fix_algorithms("<custom>Giữ &notreal; &amp;amp; nội dung</custom>", ["html_entity"])["after"] == "Giữ &notreal; & nội dung"
    assert fix_algorithms("U.S.A. A.B v.v. ThS https://example.com", ["missing_space_after"])["after"] == "U.S.A. A.B v.v. ThS https://example.com"


@pytest.mark.parametrize("data", ["", "not json", {}, {"edits": []}, {"edits": [{"start": 2, "end": 3, "original": "错", "replacement": "đúng"}]}, {"edits": [{"start": 0, "end": 1, "original": "😀", "replacement": "đúng"}]}, {"edits": [{"start": 2, "end": 3, "original": "中", "replacement": ""}]}, {"edits": [{"start": 2, "end": 3, "original": "中", "replacement": "đúng"}] * 2}])
def test_malformed_ai_never_applies(data):
    text = "😀 中 kết"
    with pytest.raises(ProofreadingError):
        validate_ai_edits(text, data, evidence_spans(text, {"han_remaining"}), title="Chương 1: Thử")


def test_offsets_codepoints_not_utf16_and_outside_unchanged():
    text = "😀 中\n\nGiữ nguyên."
    after = validate_ai_edits(text, {"edits": [{"start": 2, "end": 3, "original": "中", "replacement": "Trung"}]}, evidence_spans(text, {"han_remaining"}), title="Chương 1: Thử")["after"]
    assert after == "😀 Trung\n\nGiữ nguyên."


def test_book_exact_only_skipped_and_minmax():
    rows = [{"index": 1, "title": "Chương 101: A", "text": "a\nb"}, {"index": 2, "title": "Chương 103: B", "text": " a\nb "}, {"index": 3, "title": "Chương 102: C", "text": "a b"}, {"index": 4, "title": "Chương 103: D", "text": "A\nb"}, {"index": 5, "title": "Chương 500: E", "text": "a\nb", "skipped": True}]
    report = v.validate_book(rows)
    codes = [i["code"] for i in report["issues"]]
    assert codes.count("identical_content") == 1
    assert report["checked"] == 4
    assert all(5 not in {i["index"], *i.get("related_indexes", [])} for i in report["issues"])
    assert "number_missing" not in codes
    assert "number_duplicate" in codes and "number_descending" in codes
    gap = v.validate_book([rows[0], rows[1]])["issues"]
    assert [i for i in gap if i["code"] == "number_missing"][0]["from"] == 102


def test_duplicate_hash_collision_requires_equality(monkeypatch):
    class Hash:
        def hexdigest(self): return "collision"
    monkeypatch.setattr("hashlib.sha256", lambda _: Hash())
    report = v.validate_book([{"index": 1, "text": "é"}, {"index": 2, "text": "é"}, {"index": 3, "text": "é"}])
    assert len(report["issues"]) == 1 and report["issues"][0]["index"] == 3


@pytest.fixture
def book(tmp_path):
    write_db_config(tmp_path / "n.db", ebooks={"t": {"novel": {"title": "Thử"}}})
    storage = Storage(str(tmp_path), "t")
    chapters = [Chapter(index=i, url=f"http://test/{i}", title=f"Chương {i}: Thử") for i in range(1, 4)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        storage.write_branch_text(ch, "local_mt", "😀  中\n\nGiữ nguyên.")
        storage.write_branch_titles(ch, "local_mt", ch.title, "")
        storage.mark_branch_complete(ch, "local_mt")
    cfg = SimpleNamespace(ai=SimpleNamespace(openai=SimpleNamespace(base_url="https://mock.invalid", model="mock", api_key="never-log")))
    return storage, cfg, chapters


def ai_mock(config, prompt):
    data = json.loads(prompt[prompt.index('{"text"'):])
    span = data["evidence"][0]
    return json.dumps({"edits": [{"start": span["start"], "end": span["end"], "original": span["original"], "replacement": "Trung"}]})


def test_combined_candidate_base_after_algorithms_history_atomic(book):
    storage, cfg, chapters = book
    before = snapshot(storage, 1)
    result = run(storage, cfg, [before], ["double_space", "han_remaining"], call_ai=ai_mock)["chapters"][0]
    assert result.get("error") is None and result["candidate_id"]
    current = snapshot(storage, 1)
    assert current["text"] == "😀 中\n\nGiữ nguyên."
    cand = storage.read_ai_revision(chapters[0], result["candidate_id"])
    assert cand.status == "pending" and cand.base_rev == current["revision"] and cand.base_translated_text == current["text"]
    assert storage.publication_version(chapters[0]).text == current["text"]
    approved = decide(storage, [{"index": 1, "id": result["candidate_id"]}])["chapters"][0]
    assert approved["ok"]
    assert snapshot(storage, 1)["text"] == "😀 Trung\n\nGiữ nguyên."
    assert storage.read_ai_revision(chapters[0], result["candidate_id"]).status == "applied"
    rows = storage.conn.execute("SELECT revision_number FROM chapter_revisions WHERE ebook_slug='t' AND chapter_index=1 AND branch='local_mt' ORDER BY revision_number").fetchall()
    assert len(rows) == 3


def test_draft_never_autosaves_and_stale_rejected(book):
    storage, cfg, chapters = book
    initial = snapshot(storage, 1)
    preview = analyze(storage, [1], ["double_space", "han_remaining"], {"1": {"text": "😀  中 draft", "branch": initial["branch"], "revision": initial["revision"]}})
    result = run(storage, cfg, preview["chapters"], ["double_space", "han_remaining"], call_ai=ai_mock)["chapters"][0]
    assert result["draft"] and result["after"] == "😀 中 draft"
    assert snapshot(storage, 1) == initial
    rejected = decide(storage, [{"index": 1, "id": result["candidate_id"], "draft_text": "changed"}])["chapters"][0]
    assert not rejected["ok"]
    approved = decide(storage, [{"index": 1, "id": result["candidate_id"], "draft_text": result["after"]}])["chapters"][0]
    assert approved["ok"] and approved["after"] == "😀 Trung draft"
    assert snapshot(storage, 1) == initial


def test_batch_selected_continue_conflict_and_ai_failure(book):
    storage, cfg, chapters = book
    preview = analyze(storage, [1, 3], ["double_space", "han_remaining"])["chapters"]
    storage.write_branch_text(chapters[0], "local_mt", "concurrent")
    def fail(*args): raise RuntimeError("secret never-log")
    results = run(storage, cfg, preview, ["double_space", "han_remaining"], call_ai=fail)["chapters"]
    assert results[0]["error"]
    assert results[1]["committed"] and results[1]["unresolved"] and "secret" not in str(results)
    assert snapshot(storage, 2)["text"] == "😀  中\n\nGiữ nguyên."
    assert snapshot(storage, 3)["text"] == "😀 中\n\nGiữ nguyên."


def test_logs_cover_changed_unchanged_draft_skips_conflicts_and_no_secrets(book):
    storage, cfg, chapters = book
    captured = []
    preview = analyze(storage, [1, 2, 3], ["double_space"])["chapters"]
    storage.write_branch_text(chapters[2], "local_mt", "concurrent")
    results = run(storage, cfg, preview, ["double_space"], log=captured.append, call_ai=lambda *_: pytest.fail("Algorithm-only code must not call AI"), run_id="log-test")["chapters"]
    assert len(results) == 3
    assert results[0]["counts"]["double_space"] == {"before": 1, "after_algorithm": 0}
    assert any("ĐÃ GHI" in line and "revision=" in line for line in results[0]["audit"])
    assert any("AI BỎ QUA" in line for line in results[1]["audit"])
    assert any("TỪ CHỐI/LỖI" in line for line in results[2]["audit"])
    assert all("KẾT THÚC" in row["audit"][-1] for row in results)
    assert "TỔNG KẾT" in captured[-1] and "1 lỗi/xung đột" in captured[-1]
    unchanged = run(storage, cfg, [snapshot(storage, 1)], ["double_space"], log=captured.append)["chapters"][0]
    assert not unchanged.get("committed") and any("KHÔNG GHI" in line for line in unchanged["audit"])
    base = snapshot(storage, 1)
    draft = analyze(storage, [1], ["double_space"], {"1": {"text": "😀  中 draft", "branch": base["branch"], "revision": base["revision"]}})["chapters"]
    drafted = run(storage, cfg, draft, ["double_space"], log=captured.append)["chapters"][0]
    assert any("DRAFT" in line for line in drafted["audit"]) and snapshot(storage, 1) == base
    assert "never-log" not in str(captured) and "Giữ nguyên" not in str(captured)


def test_decision_audit_is_persisted_and_has_no_full_text(book):
    storage, cfg, chapters = book
    result = run(storage, cfg, [snapshot(storage, 1)], ["han_remaining"], call_ai=ai_mock)["chapters"][0]
    decision = decide(storage, [{"index": 1, "id": result["candidate_id"]}])["chapters"][0]
    assert decision["ok"] and any("ĐÃ ÁP AI" in line for line in decision["audit"])
    persisted = storage.read_extra_json(f"proofreading_decision:1:{result['candidate_id']}")
    assert persisted["codes"] == ["han_remaining"] and persisted["audit"] == decision["audit"]
    assert "document" not in persisted and "after" not in persisted


def test_scan_persists_partial_results_and_logs_each_issue_immediately(book, monkeypatch):
    from novel2epub import content_validation
    from novel2epub.content_validation import refresh_book, saved_report
    storage, cfg, chapters = book
    real_chapter = content_validation._chapter

    def flaky(storage, ch, publication, stamp):
        if ch.index == 2:
            raise RuntimeError("boom chapter 2")
        return real_chapter(storage, ch, publication, stamp)

    monkeypatch.setattr(content_validation, "_chapter", flaky)
    logs: list[str] = []
    report = refresh_book(storage, logs.append)
    # Chương hỏng không rollback các chương còn lại — DB vẫn cập nhật.
    assert report["checked"] == 2
    assert {row["index"] for row in report["chapters"]} == {1, 3}
    assert saved_report(storage)["checked"] == 2
    # Mọi vấn đề được log ngay khi thấy trong nhật kí job.
    assert any("boom chapter 2" in line for line in logs)
    assert any(line.startswith("[validation] Chương 1:") and "han_remaining" in line for line in logs)
    assert any(line.startswith("[validation] Toàn sách:") for line in logs)
    assert "Đã lưu lỗi 2 chương vào SQLite" in logs[-1]


def test_persisted_validation_reopens_without_parsing_or_loading_text(book, monkeypatch):
    from novel2epub.content_validation import refresh_book, saved_report
    storage, cfg, chapters = book
    report = refresh_book(storage)
    assert report["persisted"] and report["checked"] == 3
    db_file = storage.conn.execute("PRAGMA database_list").fetchone()["file"]
    reopened = Storage(str(Path(db_file).parent), "t")
    monkeypatch.setattr(reopened, "bulk_publication_versions", lambda: pytest.fail("Saved report must not load text"))
    monkeypatch.setattr(v, "scan_content", lambda *_: pytest.fail("Saved report must not parse again"))
    restored = saved_report(reopened)
    assert restored == report
    assert all("text" not in row and "translated" not in row for row in restored["chapters"])


def test_fix_refreshes_only_changed_chapter_and_cross_chapter_duplicates(book, monkeypatch):
    from novel2epub.content_validation import refresh_book, saved_report
    storage, cfg, chapters = book
    refresh_book(storage)
    calls = []
    original = v.chapter_validation_report
    def traced(ch, *args, **kwargs):
        calls.append(ch.index)
        return original(ch, *args, **kwargs)
    monkeypatch.setattr(v, "chapter_validation_report", traced)
    result = run(storage, cfg, [snapshot(storage, 1)], ["double_space"])["chapters"][0]
    assert result["committed"] and set(calls) == {1}
    rows = {row["index"]: row for row in saved_report(storage)["chapters"]}
    assert "double_space" not in {i["code"] for i in rows[1]["issues"]}
    assert "han_remaining" in {i["code"] for i in rows[1]["issues"]}
    assert "identical_content" not in {i["code"] for i in rows[1]["issues"]}
    assert "identical_content" in {i["code"] for i in rows[2]["issues"]}
    assert rows[1]["source"]["revision"] == snapshot(storage, 1)["revision"]


def test_pending_ai_draft_and_discard_do_not_clear_persisted_errors(book):
    from novel2epub.content_validation import refresh_book, saved_report
    storage, cfg, chapters = book
    initial = refresh_book(storage)
    proposal = run(storage, cfg, [snapshot(storage, 1)], ["han_remaining"], call_ai=ai_mock)["chapters"][0]
    assert [row["issues"] for row in saved_report(storage)["chapters"]] == [row["issues"] for row in initial["chapters"]]
    pending_state = saved_report(storage)
    assert decide(storage, [{"index": 1, "id": proposal["candidate_id"]}], discard=True)["chapters"][0]["ok"]
    assert saved_report(storage) == pending_state
    proposal = run(storage, cfg, [snapshot(storage, 1)], ["han_remaining"], call_ai=ai_mock)["chapters"][0]
    assert decide(storage, [{"index": 1, "id": proposal["candidate_id"]}])["chapters"][0]["ok"]
    row = saved_report(storage)["chapters"][0]
    assert "han_remaining" not in {i["code"] for i in row["issues"]}


def test_validation_failure_rolls_back_content_candidate_and_projection(book, monkeypatch):
    from novel2epub import content_validation
    storage, cfg, chapters = book
    initial = content_validation.refresh_book(storage)
    base = snapshot(storage, 1)
    proposal = run(storage, cfg, [base], ["han_remaining"], call_ai=ai_mock)["chapters"][0]
    initial = content_validation.saved_report(storage)
    def unavailable(*_): raise RuntimeError("validation unavailable")
    monkeypatch.setattr(content_validation, "refresh_chapter", unavailable)
    rejected = decide(storage, [{"index": 1, "id": proposal["candidate_id"]}])["chapters"][0]
    assert not rejected["ok"] and snapshot(storage, 1) == base
    assert storage.read_ai_revision(chapters[0], proposal["candidate_id"]).status == "pending"
    assert content_validation.saved_report(storage) == initial


def test_build_preview_and_persisted_scan_use_identical_chapter_checks(book):
    from novel2epub.content_validation import refresh_book, saved_report
    from novel2epub.config import load_config
    storage, _, chapters = book
    cfg = load_config(storage.conn.execute("PRAGMA database_list").fetchone()["file"], slug="t")
    scanned = refresh_book(storage)
    built = v.build_preview_payload(cfg, storage)
    cached = {row["index"]: row for row in saved_report(storage)["chapters"]}
    for chapter in built["validation"]["chapters"]:
        assert {i["code"] for i in chapter["issues"]} == {i["code"] for i in cached[chapter["index"]]["issues"]}
    assert "too_short" in {i["code"] for i in scanned["chapters"][0]["issues"]}
    assert cached[1]["build"]["word_count"] == scanned["chapters"][0]["build"]["word_count"]


def test_shared_checks_keep_build_title_policy_and_publication_text(book):
    from novel2epub.content_validation import refresh_book
    storage, _, chapters = book
    storage.write_branch_text(chapters[0], "ai", "AI unfinished")
    storage.write_branch_titles(chapters[0], "ai", "标题 sai", "")
    storage.write_meta(chapters[0], {"complete": False})
    row = refresh_book(storage)["chapters"][0]
    assert row["source"]["branch"] == "local_mt"
    assert row["title"] == storage.publication_title(chapters[0])
    assert "title_format" in {i["code"] for i in row["issues"]}


def test_skipped_chapters_are_not_scanned_or_shown_and_old_fix_is_rejected(book, monkeypatch):
    from novel2epub.content_validation import refresh_book, refresh_chapter, saved_report, PREFIX
    storage, cfg, chapters = book
    refresh_book(storage)
    base = snapshot(storage, 1)
    manifest = storage.load_manifest()
    manifest.chapters[0].skipped = True
    storage.save_manifest(manifest)
    # Hide previously persisted errors immediately, before another scan.
    saved = saved_report(storage)
    assert [r["index"] for r in saved["chapters"]] == [2, 3]
    assert saved["total"] == 2 and saved["skipped"] == 1 and saved["unchecked"] == 0
    assert all(1 not in {i.get("index"), *i.get("related_indexes", [])} for r in saved["chapters"] for i in r["issues"])
    original = v.chapter_validation_report
    def check(ch, *args, **kwargs):
        assert not ch.skipped
        return original(ch, *args, **kwargs)
    monkeypatch.setattr(v, "chapter_validation_report", check)
    refresh_chapter(storage, 1)
    assert storage.read_extra_json(PREFIX + "1") is None
    report = refresh_book(storage)
    assert report["checked"] == 2
    assert "Bỏ qua" in analyze(storage, [1])["chapters"][0]["error"]
    result = run(storage, cfg, [base], ["double_space"], call_ai=lambda *_: pytest.fail("No AI for skipped chapter"))
    assert "Bỏ qua" in result["chapters"][0]["error"]
    assert storage.read_branch_text(chapters[0], "local_mt") == base["text"]
    from novel2epub.config import load_config
    build = v.build_preview_payload(load_config(storage.conn.execute("PRAGMA database_list").fetchone()["file"], slug="t"), storage)
    assert all(row["index"] != 1 for row in build["validation"]["chapters"])


def test_publication_branch_changed_during_ai_rejects(book):
    storage, cfg, chapters = book
    preview = analyze(storage, [1], ["han_remaining"])["chapters"]
    def changed(config, prompt):
        storage.write_branch_text(chapters[0], "ai", "AI new")
        storage.mark_branch_complete(chapters[0], "ai")
        return ai_mock(config, prompt)
    result = run(storage, cfg, preview, ["han_remaining"], call_ai=changed)["chapters"][0]
    assert not result["candidate_id"] and result["unresolved"]
    assert snapshot(storage, 1)["text"] == "AI new"


def test_candidate_apply_branch_conflict_discard_legacy_engine_guard(book):
    storage, cfg, chapters = book
    result = run(storage, cfg, [snapshot(storage, 1)], ["han_remaining"], call_ai=ai_mock)["chapters"][0]
    storage.write_branch_text(chapters[0], "ai", "AI new")
    storage.mark_branch_complete(chapters[0], "ai")
    assert not decide(storage, [{"index": 1, "id": result["candidate_id"]}])["chapters"][0]["ok"]
    assert decide(storage, [{"index": 1, "id": result["candidate_id"]}], discard=True)["chapters"][0]["ok"]
    assert revisions.ENGINES.allows_raw("proofreading") and not revisions.ENGINES.allows_raw("fix")


def test_exact_confirmation_one_use(book):
    storage, cfg, chapters = book
    report = analyze(storage, [1, 3], ["double_space"])
    token = issue_confirmation(storage, report)
    with pytest.raises(ProofreadingError): consume_confirmation(storage, token, report["chapters"][:1], report["codes"])
    with pytest.raises(ProofreadingError): consume_confirmation(storage, token, report["chapters"], ["han_remaining"])
    consume_confirmation(storage, token, report["chapters"], report["codes"])
    with pytest.raises(ProofreadingError): consume_confirmation(storage, token, report["chapters"], report["codes"])


def test_whole_title_requires_instructions_and_stays_draft(book):
    storage, cfg, chapters = book
    base = snapshot(storage, 1)
    draft = {"1": {"text": base["text"], "title": "Tiêu đề sai", "branch": base["branch"], "revision": base["revision"]}}
    preview = analyze(storage, [1], ["title_format"], draft)["chapters"]
    calls = []
    def title_only(config, prompt):
        calls.append(prompt)
        return json.dumps({"edits": [], "title": "Chương 1: Đã sửa"})
    no_instructions = run(storage, cfg, preview, ["title_format"], call_ai=title_only)["chapters"][0]
    assert no_instructions["unresolved"] and not calls
    proposal = run(storage, cfg, preview, ["title_format"], instructions="Sửa tiêu đề thành Chương 1: Đã sửa, giữ nguyên toàn bộ nội dung.", call_ai=title_only)["chapters"][0]
    assert proposal["candidate_id"] and snapshot(storage, 1) == base
    stale = decide(storage, [{"index": 1, "id": proposal["candidate_id"], "draft_text": base["text"], "draft_title": "Vừa sửa title"}])["chapters"][0]
    assert not stale["ok"]
    approved = decide(storage, [{"index": 1, "id": proposal["candidate_id"], "draft_text": base["text"], "draft_title": "Tiêu đề sai"}])["chapters"][0]
    assert approved["ok"] and approved["title"] == "Chương 1: Đã sửa"
    assert snapshot(storage, 1) == base


def test_publication_title_fallback_change_stale(book):
    storage, cfg, chapters = book
    storage.write_branch_titles(chapters[0], "local_mt", "", "")
    preview = analyze(storage, [1], ["han_remaining"])["chapters"]
    def change_title(config, prompt):
        ch = storage.get_chapter(1)
        ch.title = "Chương 1: Đổi manifest"
        storage.save_chapter(ch)
        return ai_mock(config, prompt)
    result = run(storage, cfg, preview, ["han_remaining"], call_ai=change_title)["chapters"][0]
    assert not result["candidate_id"] and result["unresolved"]


def test_existing_schema_upgrade_keeps_raw_branches_history_candidates(book):
    from novel2epub.db import init_schema
    storage, cfg, chapters = book
    run(storage, cfg, [snapshot(storage, 1)], ["double_space", "han_remaining"], call_ai=ai_mock)
    storage.write_raw(chapters[0], "Raw preserved\n\n中")
    old_candidate = revisions.create_revision(engine="fix", idx=2, payload="legacy", base_translated_text="legacy-base", base_rev=1, has_raw=False)
    old_id = storage.create_ai_revision(old_candidate)
    columns = "idx, raw_text, translated_text, local_mt_text, active_branch, title, local_mt_title, revision, local_mt_revision"
    before = [tuple(r) for r in storage.conn.execute(f"SELECT {columns} FROM chapters WHERE ebook_slug='t' ORDER BY idx")]
    history = [tuple(r) for r in storage.conn.execute("SELECT * FROM chapter_revisions WHERE ebook_slug='t' ORDER BY id")]
    with storage.conn:
        storage.conn.execute("UPDATE _meta SET value='27' WHERE key='schema_version'")
    init_schema(storage.conn)
    assert [tuple(r) for r in storage.conn.execute(f"SELECT {columns} FROM chapters WHERE ebook_slug='t' ORDER BY idx")] == before
    assert [tuple(r) for r in storage.conn.execute("SELECT * FROM chapter_revisions WHERE ebook_slug='t' ORDER BY id")] == history
    assert storage.read_ai_revision(chapters[1], old_id).payload == "legacy"


def test_effective_ebook_ai_inheritance_and_override(tmp_path):
    from novel2epub.config import load_config
    db = write_db_config(tmp_path / "n.db", defaults={"global_ai": {"base_url": "https://mock.invalid/v1", "api_key": "inherited-secret", "assistant_model": "parent-model"}}, ebooks={"t": {"novel": {"title": "Thử"}, "ai": {"openai": {"model": "ebook-model"}}}})
    cfg = load_config(db, slug="t")
    storage = Storage(str(tmp_path), "t")
    ch = Chapter(index=1, url="http://test/1", title="Chương 1: Thử")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_branch_text(ch, "local_mt", "中")
    storage.write_branch_titles(ch, "local_mt", ch.title, "")
    storage.mark_branch_complete(ch, "local_mt")
    seen = []
    def capture(config, prompt):
        seen.append((config.base_url, config.api_key, config.model))
        return ai_mock(config, prompt)
    result = run(storage, cfg, [snapshot(storage, 1)], ["han_remaining"], call_ai=capture)
    assert seen == [("https://mock.invalid/v1", "inherited-secret", "ebook-model")]
    assert "inherited-secret" not in str(result)
