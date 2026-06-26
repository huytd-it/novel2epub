from novel2epub.storage import Chapter, Manifest, Storage, parse_glossary_line


def test_parse_glossary_line_variants():
    assert parse_glossary_line("庄国 = Trang Quốc") == ("庄国", "Trang Quốc", "")
    assert parse_glossary_line("庄国 = Trang Quốc | nước hư cấu") == (
        "庄国",
        "Trang Quốc",
        "nước hư cấu",
    )
    # khoảng trắng thừa được strip
    assert parse_glossary_line("  道元  =  Đạo Nguyên  |  ghi chú  ") == (
        "道元",
        "Đạo Nguyên",
        "ghi chú",
    )
    # comment / không có '=' / rỗng -> None
    assert parse_glossary_line("# comment") is None
    assert parse_glossary_line("dòng không có dấu bằng") is None
    assert parse_glossary_line("   ") is None
    # thiếu source hoặc target -> None
    assert parse_glossary_line(" = Trang Quốc") is None
    assert parse_glossary_line("庄国 = ") is None


def test_read_glossary_file_strips_note(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.write_glossary_file(
        "names.txt",
        "庄国 = Trang Quốc | nước hư cấu\n道元 = Đạo Nguyên\n",
    )
    # read_glossary_file vẫn trả source->target, bỏ note
    assert storage.read_glossary_file("names.txt") == {
        "庄国": "Trang Quốc",
        "道元": "Đạo Nguyên",
    }


def test_read_glossary_notes_merges_only_entries_with_note(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.write_glossary_file("names.txt", "庄国 = Trang Quốc | nước hư cấu\n")
    storage.write_glossary_file(
        "vietphrase.txt", "元气 = nguyên khí\n猫虎 = miêu hổ | tàn nhẫn, khốc liệt\n"
    )
    assert storage.read_glossary_notes() == {
        "Trang Quốc": "nước hư cấu",
        "miêu hổ": "tàn nhẫn, khốc liệt",
    }


def test_read_glossary_file_parses_lines_and_skips_invalid(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    storage.write_glossary_file(
        "names.txt",
        "# comment\n"
        "庄国 = Trang Quốc\n"
        "\n"
        "dòng không có dấu bằng\n"
        "  道元  =  Đạo Nguyên  \n",
    )

    glossary = storage.read_glossary_file("names.txt")

    assert glossary == {"庄国": "Trang Quốc", "道元": "Đạo Nguyên"}


def test_read_glossary_file_missing_returns_empty(tmp_path):
    storage = Storage(tmp_path, "slug")
    assert storage.read_glossary_file("names.txt") == {}


def test_write_then_read_roundtrip(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.write_glossary_file("vietphrase.txt", "元气 = nguyên khí\n")
    assert storage.read_glossary_file("vietphrase.txt") == {"元气": "nguyên khí"}


def test_manifest_roundtrip_keeps_metadata(tmp_path):
    storage = Storage(tmp_path, "slug")
    manifest = Manifest(
        slug="slug",
        source_url="http://x/book",
        title="原书名",
        author="某作者",
        description="简介",
        cover_url="http://x/c.jpg",
        cover_file="cover.jpg",
        title_vi="Tên Việt",
        author_vi="Tác giả Việt",
        description_vi="Giới thiệu",
        metadata_missing=["author"],
        curated_fields=["title_vi"],
        chapters=[Chapter(index=1, url="http://x/1", title_zh="第一章", missing_fields=["title"], duplicate_of=1, last_action_status="skipped")],
    )
    storage.save_manifest(manifest)

    loaded = storage.load_manifest()
    assert loaded.description == "简介"
    assert loaded.cover_url == "http://x/c.jpg"
    assert loaded.cover_file == "cover.jpg"
    assert loaded.title_vi == "Tên Việt"
    assert loaded.author_vi == "Tác giả Việt"
    assert loaded.description_vi == "Giới thiệu"
    assert loaded.source_url == "http://x/book"
    assert loaded.metadata_missing == ["author"]
    assert loaded.curated_fields == ["title_vi"]
    assert loaded.chapters[0].title_zh == "第一章"
    assert loaded.chapters[0].missing_fields == ["title"]
    assert loaded.chapters[0].duplicate_of == 1
    assert loaded.chapters[0].last_action_status == "skipped"


def test_old_manifest_without_metadata_loads(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.root.mkdir(parents=True, exist_ok=True)
    storage.manifest_path.write_text(
        '{"slug": "slug", "title": "T", "chapters": []}', encoding="utf-8"
    )
    loaded = storage.load_manifest()
    assert loaded.title == "T"
    assert loaded.description == ""
    assert loaded.cover_file == ""
    assert loaded.source_url == ""
    assert loaded.metadata_missing == []


def test_cover_helpers(tmp_path):
    storage = Storage(tmp_path, "slug")
    name = storage.write_cover(b"\x89PNG", "png")
    assert name == "cover.png"
    manifest = Manifest(slug="slug", cover_file=name)
    assert storage.cover_fs_path(manifest).read_bytes() == b"\x89PNG"
    assert storage.cover_fs_path(Manifest(slug="slug")) is None
    assert storage.cover_fs_path(Manifest(slug="slug", cover_file="missing.jpg")) is None


# --- has_translated cache contract (xem spec translate-chunk-streaming) ---


def test_has_translated_false_when_file_missing(tmp_path):
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    assert storage.has_translated(ch) is False


def test_has_translated_true_when_file_exists_but_meta_missing(tmp_path):
    """Back-compat: meta cũ (không có `complete` key) coi như complete."""
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    storage.write_translated(ch, "bản dịch")
    assert not storage.has_meta(ch)  # confirm meta missing
    assert storage.has_translated(ch) is True


def test_has_translated_false_when_file_exists_and_meta_complete_false(tmp_path):
    """Partial: file có nhưng meta chưa đánh dấu complete (job bị crash)."""
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    storage.write_translated(ch, "đoạn 1")
    storage.write_meta(ch, {"complete": False, "warnings": []})
    assert storage.has_translated(ch) is False


def test_has_translated_true_when_meta_complete_true(tmp_path):
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    storage.write_translated(ch, "đầy đủ")
    storage.mark_translated_complete(ch, meta_extra={"warnings": [], "length_raw": 100})
    assert storage.has_translated(ch) is True


def test_mark_translated_complete_preserves_existing_meta_keys(tmp_path):
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    storage.write_translated(ch, "x")
    storage.write_meta(ch, {"warnings": ["warn 1"], "length_raw": 42})
    storage.mark_translated_complete(ch, meta_extra={"length_raw": 99})
    meta = storage.read_meta(ch)
    assert meta["complete"] is True
    assert meta["warnings"] == ["warn 1"]  # giữ key cũ
    assert meta["length_raw"] == 99  # bị override bởi meta_extra


def test_append_translated_chunk_creates_then_appends(tmp_path):
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    storage.append_translated_chunk(ch, "đoạn 1", is_first=True)
    storage.append_translated_chunk(ch, "đoạn 2", is_first=False)
    storage.append_translated_chunk(ch, "đoạn 3", is_first=False)
    assert storage.read_translated(ch) == "đoạn 1\nđoạn 2\nđoạn 3"


# --- snapshot bản dịch máy (editor 3 cột: cột VI tách khỏi cột Biên tập) ---


def test_mt_snapshot_independent_from_edited_copy(tmp_path):
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=1, url="x")
    storage.write_translated_mt(ch, "BẢN MÁY")
    storage.write_translated(ch, "BẢN MÁY")
    # Sửa cột Biên tập KHÔNG đụng tới snapshot máy.
    storage.write_translated(ch, "BẢN ĐÃ SỬA")
    assert storage.has_translated_mt(ch) is True
    assert storage.read_translated_mt(ch) == "BẢN MÁY"
    assert storage.read_translated(ch) == "BẢN ĐÃ SỬA"


def test_read_mt_snapshot_falls_back_to_translated(tmp_path):
    """Chương cũ chưa có snapshot máy → đọc fallback bản dịch hiện có."""
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=2, url="x")
    storage.write_translated(ch, "chỉ có bản dịch")
    assert storage.has_translated_mt(ch) is False
    assert storage.read_translated_mt(ch) == "chỉ có bản dịch"


def test_read_mt_snapshot_empty_when_nothing(tmp_path):
    storage = Storage(tmp_path, "slug")
    ch = Chapter(index=3, url="x")
    assert storage.read_translated_mt(ch) == ""
