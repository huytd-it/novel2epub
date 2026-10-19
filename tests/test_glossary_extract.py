"""Regression coverage for full-book extraction; no production DB or models."""
from types import SimpleNamespace

import pytest

from novel2epub import pipeline, proper_names, translator
from novel2epub.automation import STEPS
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def extract(text, **kwargs):
    return proper_names.extract_proper_name_candidates([(1, text)], include_terms=True,
                                                       min_frequency=3, **kwargs)


def test_terms_at_unaligned_positions_and_no_sentence_fragments():
    rows = extract("他拿起灵石。" * 3)
    assert [(r["source"], r["kind"], r["frequency"]) for r in rows] == [("灵石", "term", 3)]


def test_stopwords_metadata_and_transliterated_names():
    rows = extract("世界当然问题。本章完。作者。克莱恩。" * 3)
    assert {r["source"] for r in rows} == {"克莱恩"}
    assert rows[0]["kind"] == "translit"


def test_overlap_frequency_and_cap():
    rows = extract("青云剑法。" * 3 + "灵石。" * 2)
    assert [r["source"] for r in rows] == ["青云剑法"]
    assert len(extract("青云剑法。玄天神功。" * 3, max_candidates=1)) == 1


def test_large_vocabulary_bounded_substring_filter():
    text = "。".join(chr(0x7000 + i) + chr(0x8000 + i) for i in range(1000))
    assert len(extract((text + "。") * 3, max_candidates=200)) == 200


@pytest.fixture
def book(tmp_path):
    cfg = Config(novel=NovelConfig(slug="extract"), crawl=CrawlConfig(toc_url="https://example.test"),
                 translate=TranslateConfig(type="none"),
                 output=OutputConfig(data_dir=str(tmp_path)))
    storage = Storage(tmp_path, "extract")
    storage.ensure_dirs()
    chapter = Chapter(index=1, url="https://example.test/1")
    storage.save_manifest(Manifest(slug="extract", chapters=[chapter]))
    storage.write_raw(chapter, "灵石。玄天神功。" * 3)
    return cfg, storage, chapter


def test_automation_mapping():
    from app.scheduler import _STEP_FN
    assert "glossary-extract" in STEPS
    assert callable(_STEP_FN["glossary-extract"])


def test_step_skips_existing_and_pending_before_loading_engine(book, monkeypatch):
    cfg, storage, chapter = book
    storage.upsert_glossary_entry("灵石", "linh thạch")
    calls = []
    monkeypatch.setattr(translator, "make_translator", lambda options, **kw:
                        SimpleNamespace(translate=lambda text: calls.append(text) or "Huyền Thiên Thần Công"))
    pipeline.step_glossary_extract(cfg, lambda message: None)
    assert calls == ["玄天神功"]
    assert storage.read_extra_json("glossary_pending")[0]["target"] == "Huyền Thiên Thần Công"
    calls.clear()
    monkeypatch.setattr(translator, "make_translator", lambda *a, **kw: pytest.fail("reloaded engine"))
    pipeline.step_glossary_extract(cfg, lambda message: None)
    assert storage.read_raw(chapter) == "灵石。玄天神功。" * 3


@pytest.mark.parametrize("failure", ["load", "translate"])
def test_engine_failure_keeps_han(book, monkeypatch, failure):
    cfg, storage, _ = book
    def fail(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(translator, "make_translator", fail if failure == "load" else
                        lambda *a, **kw: SimpleNamespace(translate=fail))
    pipeline.step_glossary_extract(cfg, lambda message: None)
    pending = storage.read_extra_json("glossary_pending")
    assert pending and all(row["source"] == row["target"] for row in pending)


def test_cancel_during_translation_writes_nothing(book, monkeypatch):
    cfg, storage, _ = book
    calls = []
    monkeypatch.setattr(translator, "make_translator", lambda *a, **kw:
                        SimpleNamespace(translate=lambda text: calls.append(text) or "dịch"))
    pipeline.step_glossary_extract(cfg, lambda message: None, should_cancel=lambda: bool(calls))
    assert len(calls) == 1
    assert not storage.read_extra_json("glossary_pending")


def test_no_raw_does_not_load_engine(book, monkeypatch):
    cfg, storage, chapter = book
    storage.write_raw(chapter, "")
    monkeypatch.setattr(translator, "make_translator", lambda *a, **kw: pytest.fail("loaded engine"))
    pipeline.step_glossary_extract(cfg, lambda message: None)
