from novel2epub.storage import Storage


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
