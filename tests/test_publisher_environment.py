from novel2epub.config import load_config
from novel2epub.environment import publisher_override
from tests.helpers.db import write_db_config


def test_publisher_env_applies_to_all_existing_ebooks(tmp_path, monkeypatch):
    path = write_db_config(tmp_path / "n.db", ebooks={
        "one": {"novel": {"title": "Một", "publisher": "Cũ"}},
        "two": {"novel": {"title": "Hai"}},
    })
    monkeypatch.setenv("NOVEL2EPUB_PUBLISHER", "NXB Chung")
    assert load_config(path, "one").novel.publisher == "NXB Chung"
    assert load_config(path, "two").novel.publisher == "NXB Chung"
    monkeypatch.setenv("NOVEL2EPUB_PUBLISHER", "")
    assert load_config(path, "one").novel.publisher == "Cũ"


def test_publisher_reads_dotenv_and_preserves_quoted_hash(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVEL2EPUB_PUBLISHER", raising=False)
    (tmp_path / ".env").write_text('export NOVEL2EPUB_PUBLISHER="Nhà xuất bản #1" # ghi chú\n', encoding="utf-8-sig")
    assert publisher_override(tmp_path) == "Nhà xuất bản #1"
    monkeypatch.setenv("NOVEL2EPUB_PUBLISHER", "Environment wins")
    assert publisher_override(tmp_path) == "Environment wins"


def test_dotenv_publisher_applies_during_load(tmp_path, monkeypatch):
    monkeypatch.delenv("NOVEL2EPUB_PUBLISHER", raising=False)
    (tmp_path / ".env").write_text('NOVEL2EPUB_PUBLISHER="Nhà xuất bản chung"\n', encoding="utf-8")
    path = write_db_config(tmp_path / "n.db", ebooks={"old": {"novel": {"title": "Truyện cũ"}}})
    assert load_config(path, "old").novel.publisher == "Nhà xuất bản chung"
