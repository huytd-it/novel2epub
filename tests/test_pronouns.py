from __future__ import annotations

import pytest

from novel2epub.chapter_versions import ChapterVersionError, ChapterVersionService
from novel2epub.db import get_thread_connection, init_schema
from novel2epub.ops_baseline import initialize_branch_revisions
from novel2epub.pronouns import normalize_book_pronouns, normalize_pronouns
from novel2epub.storage import Storage


@pytest.mark.parametrize("opening,closing", [('"', '"'), ('“', '”'), ('«', '»'), ('「', '」'), ('『', '』')])
def test_only_quoted_dialogue(opening, closing):
    text = f'Tôi nhìn hắn. {opening}Tôi biết mày. Tao đợi tớ.{closing} Nàng nhìn tôi.'
    result = normalize_pronouns(text)
    assert result.text == f'Tôi nhìn hắn. {opening}Ta biết ngươi. Ta đợi ta.{closing} Nàng nhìn tôi.'
    assert len(result.changes) == 4
    for change in result.changes:
        assert text[change.start:change.end] == change.before
    assert not normalize_pronouns(result.text).changes


def test_plural_and_case_preserve_number_and_exclusivity():
    result = normalize_pronouns('“CHÚNG TÔI chờ chúng mày, bọn tao và tụi tớ. Chúng ta đi!”')
    assert result.text == '“BỌN TA chờ các ngươi, bọn ta và bọn ta. Chúng ta đi!”'
    assert len(result.changes) == 4


def test_whitespace_and_exact_offsets():
    text = 'Mở\r\n“Tôi nói với chúng\t\tmày.”\r\nCuối\r\n'
    result = normalize_pronouns(text)
    assert result.text == 'Mở\r\n“Ta nói với các ngươi.”\r\nCuối\r\n'
    assert all(text[c.start:c.end] == c.before for c in result.changes)


@pytest.mark.parametrize("text", [
    '“Anh, em, bạn, mình, mi, hắn, nàng, y, sư phụ, đệ tử, huynh, muội.”',
    '“Cái tôi, đầy tớ, tôi tớ, thanh tao, tao nhã, tao đàn, tao nhân, tao phùng.”',
    '“Tôi luyện, tôi thép, tôi kim loại; lông mày, nhíu mày, cau mày, nhướng mày.”',
    '“Chân mày, đôi mày, hàng mày, cặp mày, nhướn mày, rướn mày, mày kiếm, mày liễu.”',
    '“atôi tôi2 _tôi mày_.”',
    'Tôi kể rằng mày đã đi.',
    '- Tôi đợi mày.',
    '“Tôi đợi mày.',
    '“Tôi đợi\nmày.”',
    '“Tôi đợi\n"Tao chờ mày."\nmày.”',
    '“Tôi nói 「mày」 rồi đi.”',
    '“Tôi về.” “mày còn ở',
])
def test_ambiguous_or_non_pronoun_text_unchanged(text):
    assert normalize_pronouns(text).text == text
    assert not normalize_pronouns(text).changes


def test_protected_names_preserve_literal_not_entity_target():
    result = normalize_pronouns(
        '“Tôi gặp Tớ và Mày Đen. Tôi chờ mày.”', protected_terms=['Tớ', 'Mày Đen'],
    )
    assert result.text == '“Ta gặp Tớ và Mày Đen. Ta chờ ngươi.”'


def test_multiple_dialogues_escaped_quote_and_empty_text():
    text = '“Tôi về.” Hắn nhìn tôi. "Tao nói \\"mày\\" đấy."'
    result = normalize_pronouns(text)
    assert result.text == '“Ta về.” Hắn nhìn tôi. "Ta nói \\"ngươi\\" đấy."'
    assert normalize_pronouns("").text == ""


def test_dialogue_after_multiline_quote_is_processed():
    text = '“Tôi đợi\nmày.”\n“Tôi về.”'
    assert normalize_pronouns(text).text == '“Tôi đợi\nmày.”\n“Ta về.”'


@pytest.fixture
def storage(tmp_path):
    db_path = tmp_path / "novel2epub.db"
    conn = get_thread_connection(str(db_path))
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        for index in range(1, 4):
            conn.execute(
                "INSERT INTO chapters (ebook_slug, idx, title, translated_text, translated_mt_text, "
                "raw_text, local_mt_title, local_mt_text, local_mt_mt_snapshot, active_branch, skipped) "
                "VALUES ('demo', ?, 'Title', ?, 'AI snapshot', 'Raw', 'MT title', ?, 'MT snapshot', 'ai', ?)",
                (index, '“Tôi chờ mày.”', '“Tớ chờ mày.”', int(index == 3)),
            )
    store = Storage(tmp_path, "demo")
    yield store
    conn.close()


def test_preview_has_no_database_writes(storage):
    conn = storage.conn
    old = conn.total_changes
    messages = []
    result = normalize_book_pronouns(storage, branch="local_mt", log=messages.append)
    assert result == {"scanned": 2, "changed": 2, "replacements": 4, "applied": 0}
    assert conn.total_changes == old
    assert conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0] == 0
    assert any('-“Tớ chờ mày.”' in line and '+“Ta chờ ngươi.”' in line for line in messages)


def test_apply_history_branch_isolation_range_and_idempotency(storage):
    conn = storage.conn
    initialize_branch_revisions(storage)
    old = tuple(conn.execute("SELECT * FROM chapters WHERE idx=1").fetchone())
    result = normalize_book_pronouns(storage, branch="local_mt", start=2, end=2, apply=True, log=lambda _: None)
    assert result == {"scanned": 1, "changed": 1, "replacements": 2, "applied": 1}
    row = conn.execute("SELECT * FROM chapters WHERE idx=2").fetchone()
    assert row["local_mt_text"] == '“Ta chờ ngươi.”'
    assert row["translated_text"] == '“Tôi chờ mày.”'
    assert (row["raw_text"], row["translated_mt_text"], row["local_mt_mt_snapshot"], row["active_branch"]) == ("Raw", "AI snapshot", "MT snapshot", "ai")
    assert tuple(conn.execute("SELECT * FROM chapters WHERE idx=1").fetchone()) == old
    service = ChapterVersionService(storage)
    assert service.validate_integrity(chapter_index=2).valid
    operation = conn.execute("SELECT * FROM chapter_operations WHERE kind='normalize_pronouns'").fetchone()
    assert operation is not None
    count = conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0]
    again = normalize_book_pronouns(storage, branch="local_mt", start=2, end=2, apply=True, log=lambda _: None)
    assert again["applied"] == 0
    assert conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0] == count


def test_apply_ai_branch_and_entity_protection(storage):
    with storage.conn:
        storage.conn.execute("INSERT INTO entity_dictionary (source, target, protect) VALUES ('mày', 'Tên khác', 1)")
    normalize_book_pronouns(storage, branch="ai", start=1, end=1, apply=True, log=lambda _: None)
    row = storage.conn.execute("SELECT * FROM chapters WHERE idx=1").fetchone()
    assert row["translated_text"] == '“Ta chờ mày.”'
    assert row["local_mt_text"] == '“Tớ chờ mày.”'


def test_concurrent_edit_is_not_overwritten(storage):
    def concurrent_edit(diff):
        if diff.startswith("---"):
            service = ChapterVersionService(storage)
            base = service.read_document(1, "local_mt")
            service.commit_document(
                chapter_index=1, branch="local_mt", expected_revision=base.revision,
                expected_content_hash=base.content_hash, title=base.title,
                translated="Concurrent text", client_operation_id="other-edit",
            )

    with pytest.raises(ChapterVersionError) as error:
        normalize_book_pronouns(storage, branch="local_mt", start=1, end=1, apply=True, log=concurrent_edit)
    assert error.value.code == "document_conflict"
    assert storage.conn.execute("SELECT local_mt_text FROM chapters WHERE idx=1").fetchone()[0] == "Concurrent text"


@pytest.mark.parametrize("kwargs", [{"branch": "other"}, {"branch": "ai", "start": -1}, {"branch": "ai", "start": 3, "end": 1}])
def test_invalid_scope(storage, kwargs):
    with pytest.raises(ValueError):
        normalize_book_pronouns(storage, **kwargs)


def test_cli_preview_routes_to_selected_book(storage, monkeypatch, capsys):
    from types import SimpleNamespace
    from novel2epub import cli

    calls = []

    def load_config(path, slug):
        calls.append((path, slug))
        return SimpleNamespace(output=SimpleNamespace(data_dir=storage.data_dir), novel=SimpleNamespace(slug=slug))

    monkeypatch.setattr(cli, "load_config", load_config)
    assert cli.main(["-c", "test.db", "-e", "demo", "normalize-pronouns", "--branch", "ai", "--from", "1", "--to", "1"]) == 0
    assert calls == [("test.db", "demo")]
    assert "1/1" in capsys.readouterr().out
    assert storage.conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0] == 0


@pytest.mark.parametrize("args", [
    ["-e", "demo", "normalize-pronouns"],
    ["normalize-pronouns", "--branch", "ai"],
])
def test_cli_requires_explicit_branch_and_book(args):
    from novel2epub.cli import main

    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_incomplete_branch_is_skipped(storage):
    with storage.conn:
        storage.conn.execute("UPDATE chapters SET meta_json=? WHERE idx=1", ('{"complete": false}',))
    result = normalize_book_pronouns(storage, branch="ai", start=1, end=1, log=lambda _: None)
    assert result["scanned"] == 0


def test_entity_target_is_protected_too(storage):
    with storage.conn:
        storage.conn.execute("INSERT INTO entity_dictionary (source, target, protect) VALUES ('某名', 'Tôi', 1)")
    messages = []
    result = normalize_book_pronouns(storage, branch="ai", start=1, end=1, log=messages.append)
    assert result["replacements"] == 1
    assert any('+“Tôi chờ ngươi.”' in text for text in messages)


def test_apply_noop_does_not_create_history(storage):
    with storage.conn:
        storage.conn.execute("UPDATE chapters SET translated_text='Không có thoại' WHERE idx=1")
    before = storage.conn.total_changes
    result = normalize_book_pronouns(storage, branch="ai", start=1, end=1, apply=True, log=lambda _: None)
    assert result["applied"] == 0
    assert storage.conn.total_changes == before


@pytest.mark.parametrize("opening,closing", [("'", "'"), ("‘", "’"), ("“", "”"), ("「", "」"), ("『", "』")])
def test_single_chinese_mode_only_changes_selected_wrappers(opening, closing):
    text = f'Tôi kể. "Tôi về với mày." (Tôi đợi mày.) {opening}Tôi tìm mày.{closing} Tôi đi.'
    result = normalize_pronouns(text, dialogue_marks="single_chinese")
    assert result.text == f'Tôi kể. "Tôi về với mày." (Tôi đợi mày.) {opening}Ta tìm ngươi.{closing} Tôi đi.'
    assert len(result.changes) == 2
    assert all(text[c.start:c.end] == c.before for c in result.changes)
    assert not normalize_pronouns(result.text, dialogue_marks="single_chinese").changes


@pytest.mark.parametrize("opening,closing", [("(", ")"), ("（", "）")])
def test_parentheses_mode_is_separate_and_preserves_other_quotes(opening, closing):
    text = f'Tôi kể. "Tôi về." ‘Tôi đi.’ “Tôi chạy.” {opening}Tôi chờ mày.{closing}'
    assert normalize_pronouns(text, dialogue_marks="parentheses").text == f'Tôi kể. "Tôi về." ‘Tôi đi.’ “Tôi chạy.” {opening}Ta chờ ngươi.{closing}'


@pytest.mark.parametrize("mode,text", [
    ("single_chinese", "'Tôi nhìn mày"),
    ("single_chinese", "'Tôi nhìn\nmày'"),
    ("single_chinese", "'Tôi nhìn 「mày」.'"),
    ("single_chinese", '"Tôi nhìn ‘mày’."'),
    ("single_chinese", "(‘Tôi nhìn mày.’)"),
    ("single_chinese", "‘Tôi nhìn mày.'"),
    ("single_chinese", "'Tôi nhìn mày.' (thiếu"),
    ("single_chinese", "Don't gọi tôi, O’Connor bảo mày đấy. James' book."),
    ("single_chinese", "«Tôi chờ mày.»"),
    ("parentheses", "(Tôi nhìn\nmày)"),
    ("parentheses", "(Tôi nhìn mày."),
    ("parentheses", "(Tôi nhìn （mày）.)"),
    ("parentheses", '"(Tôi nhìn mày.)"'),
    ("parentheses", "(Tôi nhìn mày.）"),
])
def test_strict_modes_abstain_on_ambiguous_or_unselected_regions(mode, text):
    assert normalize_pronouns(text, dialogue_marks=mode).text == text


def test_single_quotes_inside_words_and_escaped_quotes_do_not_break_boundaries():
    text = "O’Connor nói: 'Tôi don't gọi mày.' Tôi ở ngoài."
    assert normalize_pronouns(text, dialogue_marks="single_chinese").text == "O’Connor nói: 'Ta don't gọi ngươi.' Tôi ở ngoài."
    text = "'Tôi nói \\'mày\\' đấy.' Tôi ở ngoài."
    assert normalize_pronouns(text, dialogue_marks="single_chinese").text == "'Ta nói \\'ngươi\\' đấy.' Tôi ở ngoài."


def test_unknown_dialogue_marks_are_rejected():
    with pytest.raises(ValueError):
        normalize_pronouns("", dialogue_marks="all_text")


def test_cli_dialogue_marks_applied_to_selected_scope(storage, monkeypatch, capsys):
    from types import SimpleNamespace
    from novel2epub import cli

    monkeypatch.setattr(cli, "load_config", lambda path, slug: SimpleNamespace(output=SimpleNamespace(data_dir=storage.data_dir), novel=SimpleNamespace(slug=slug)))
    assert cli.main(["-e", "demo", "normalize-pronouns", "--branch", "ai", "--from", "1", "--to", "1", "--dialogue-marks", "parentheses"]) == 0
    assert "0/1" in capsys.readouterr().out
    assert storage.conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0] == 0
