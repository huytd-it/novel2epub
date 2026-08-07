from pathlib import Path


TEMPLATE = (Path(__file__).parents[1] / "app" / "templates" / "glossary.html").read_text(
    encoding="utf-8"
)


def test_glossary_table_exposes_pending_and_entry_controls():
    required_ids = {
        "btn-approve-selected",
        "btn-approve-all",
        "btn-pending-clear",
        "btn-add",
    }
    for control_id in required_ids:
        assert f'id="{control_id}"' in TEMPLATE
    assert "Đề xuất mới" in TEMPLATE
    assert "Việt hiện tại" in TEMPLATE
    assert 'data-kind="pending"' in TEMPLATE
    assert 'data-kind="entry"' in TEMPLATE
    # Conflicts cũ đã gỡ — không còn điều khiển/checkbox loại conflict.
    assert "data-kind=\"conflict\"" not in TEMPLATE
    assert "btn-conflict-take" not in TEMPLATE
    assert "btn-conflict-keep" not in TEMPLATE


def test_glossary_loader_fetches_all_sources_in_parallel():
    assert "Promise.all" in TEMPLATE
    assert "/glossary/list?" in TEMPLATE
    assert "/glossary/pending" in TEMPLATE
    assert "/glossary/replace/preview" in TEMPLATE
    assert "PENDING_ROWS" in TEMPLATE
    assert "CONFLICT_ROWS" not in TEMPLATE


def test_glossary_bulk_payloads_use_explicit_snapshots():
    assert "source: row.source.trim()" in TEMPLATE
    assert "target: row.target.trim()" in TEMPLATE
    assert "/glossary/replace/approve" in TEMPLATE
    assert "/glossary/pending/clear" in TEMPLATE
    assert "/glossary/conflicts/bulk-resolve" not in TEMPLATE


def test_glossary_ui_rejects_non_han_sources_before_saving():
    assert "HAN_SOURCE_RE" in TEMPLATE
    assert "Source phải chứa chữ Hán, không nhập tiếng Việt." in TEMPLATE
    assert "validateSource(source" in TEMPLATE
