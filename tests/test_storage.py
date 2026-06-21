from novel2epub.storage import Chapter, Manifest, Storage


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
        title="原书名",
        author="某作者",
        description="简介",
        cover_url="http://x/c.jpg",
        cover_file="cover.jpg",
        title_vi="Tên Việt",
        author_vi="Tác giả Việt",
        description_vi="Giới thiệu",
        chapters=[Chapter(index=1, url="http://x/1", title_zh="第一章")],
    )
    storage.save_manifest(manifest)

    loaded = storage.load_manifest()
    assert loaded.description == "简介"
    assert loaded.cover_url == "http://x/c.jpg"
    assert loaded.cover_file == "cover.jpg"
    assert loaded.title_vi == "Tên Việt"
    assert loaded.author_vi == "Tác giả Việt"
    assert loaded.description_vi == "Giới thiệu"
    assert loaded.chapters[0].title_zh == "第一章"


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


def test_cover_helpers(tmp_path):
    storage = Storage(tmp_path, "slug")
    name = storage.write_cover(b"\x89PNG", "png")
    assert name == "cover.png"
    manifest = Manifest(slug="slug", cover_file=name)
    assert storage.cover_fs_path(manifest).read_bytes() == b"\x89PNG"
    assert storage.cover_fs_path(Manifest(slug="slug")) is None
    assert storage.cover_fs_path(Manifest(slug="slug", cover_file="missing.jpg")) is None
