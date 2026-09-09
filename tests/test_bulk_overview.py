"""Các màn hình liệt kê (Thư viện, Dashboard) phải lấy trạng thái chương từ
projection hẹp `chapter_ui_state` — không dựng Manifest cho từng ebook, không
chạm bảng `chapters` (nơi chứa blob raw/dịch)."""
from __future__ import annotations

from types import SimpleNamespace

from app.overview import chapter_states_by_slug
from app.routes import webui
from novel2epub.progress import progress_from_states
from novel2epub.storage import Chapter, Manifest, Storage, bulk_chapter_states


def _seed(data_dir, slug: str, *, total=4, raw=(), translated=(), edited=(), skipped=()):
    storage = Storage(data_dir, slug)
    chapters = [Chapter(index=i, url=f"http://x/{slug}/{i}") for i in range(1, total + 1)]
    for ch in chapters:
        ch.skipped = ch.index in skipped
    storage.save_manifest(Manifest(slug=slug, chapters=chapters))
    for ch in chapters:
        if ch.index in raw:
            storage.write_raw(ch, "你好世界" * 5)
        if ch.index in translated:
            storage.write_translated(ch, "Xin chào thế giới")
            storage.mark_translated_complete(ch)
        if ch.index in edited:
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            meta["before_rewrite"] = {"text": "cũ"}
            storage.write_meta(ch, meta)
    return storage


def _cfg(data_dir, slug):
    return SimpleNamespace(
        output=SimpleNamespace(data_dir=str(data_dir)),
        novel=SimpleNamespace(slug=slug, title=slug, author=""),
        crawl=SimpleNamespace(toc_url=""),
        translate=SimpleNamespace(type="openai"),
        epub_path=str(data_dir / f"{slug}.epub"),
    )


def test_bulk_chapter_states_covers_every_ebook_in_one_pass(tmp_path):
    _seed(tmp_path, "a", total=3, raw=(1, 2), translated=(1,), skipped=(3,))
    _seed(tmp_path, "b", total=2, raw=(1,))

    states = bulk_chapter_states(tmp_path, ["a", "b"])

    assert [s["index"] for s in states["a"]] == [1, 2, 3]
    assert [s["has_raw"] for s in states["a"]] == [True, True, False]
    assert [s["has_translated"] for s in states["a"]] == [True, False, False]
    assert [s["skipped"] for s in states["a"]] == [False, False, True]
    assert states["a"][0]["raw_len"] > 0
    assert len(states["b"]) == 2


def test_bulk_chapter_states_handles_empty_and_unknown_slugs(tmp_path):
    _seed(tmp_path, "a", total=1)

    assert bulk_chapter_states(tmp_path, []) == {}
    assert bulk_chapter_states(tmp_path, ["khong-ton-tai"]) == {"khong-ton-tai": []}


def test_progress_from_states_matches_manifest_counting(tmp_path):
    _seed(tmp_path, "a", total=4, raw=(1, 2, 3), translated=(1, 2))

    progress = progress_from_states(bulk_chapter_states(tmp_path, ["a"])["a"])

    assert progress == {
        "total": 4, "raw_count": 3, "translated_count": 2,
        "raw_pct": 75, "translated_pct": 50,
    }


def test_chapter_states_by_slug_keeps_ebooks_on_separate_dbs_apart(tmp_path):
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _seed(dir_a, "truyen", total=3, raw=(1, 2, 3))
    _seed(dir_b, "truyen", total=1)

    states = chapter_states_by_slug([("x", _cfg(dir_a, "truyen")), ("y", _cfg(dir_b, "truyen"))])

    assert len(states["x"]) == 3
    assert len(states["y"]) == 1


def test_library_summary_reports_progress_and_run_length_strip(tmp_path, monkeypatch):
    _seed(tmp_path, "a", total=5, raw=(1, 2, 3, 4), translated=(1, 2), edited=(2,), skipped=(5,))
    monkeypatch.setattr(webui.deps, "DB_PATH", tmp_path / "novel2epub.db")
    monkeypatch.setattr(webui.deps, "resolved_cfg", lambda slug: _cfg(tmp_path, slug))

    result = webui.library_list(limit=10)

    card = next(item for item in result["ebooks"] if item["slug"] == "a")
    assert card["total"] == 5
    assert card["raw_count"] == 4
    assert card["translated_count"] == 2
    # chương 1 đã dịch, 2 đã biên tập, 3-4 mới có raw, 5 bỏ qua.
    assert card["strip"] == "m1,e1,r2,s1"
    assert card["counts"] == {"n": 0, "r": 2, "m": 1, "e": 1, "s": 1}
