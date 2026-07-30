from pathlib import Path


TEMPLATE = (Path(__file__).parents[1] / "app" / "templates" / "glossary.html").read_text(
    encoding="utf-8"
)


def test_glossary_table_exposes_pending_and_conflict_controls():
    required_ids = {
        "btn-approve-selected",
        "btn-approve-all",
        "btn-pending-clear",
        "btn-conflict-take",
        "btn-conflict-keep",
    }
    for control_id in required_ids:
        assert f'id="{control_id}"' in TEMPLATE
    assert "AI đề xuất mới" in TEMPLATE
    assert 'data-kind="pending"' in TEMPLATE
    assert 'data-kind="conflict"' in TEMPLATE
    assert 'data-kind="entry"' in TEMPLATE


def test_glossary_loader_fetches_all_three_sources_in_parallel():
    assert "Promise.all" in TEMPLATE
    assert "/glossary/list?" in TEMPLATE
    assert "/glossary/pending" in TEMPLATE
    assert "/glossary/suspects" in TEMPLATE
    assert "PENDING_ROWS" in TEMPLATE
    assert "CONFLICT_ROWS" in TEMPLATE


def test_glossary_bulk_payloads_use_explicit_snapshots():
    assert "original_source" in TEMPLATE
    assert "original_new" in TEMPLATE
    assert "/glossary/pending/approve" in TEMPLATE
    assert "/glossary/pending/clear" in TEMPLATE
    assert "/glossary/conflicts/bulk-resolve" in TEMPLATE
    assert '"take"' in TEMPLATE
    assert '"keep"' in TEMPLATE
