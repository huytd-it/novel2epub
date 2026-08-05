"""CORS chỉ bật khi được cấu hình, và không bao giờ là '*'."""
from __future__ import annotations

from app.main import _cors_origins


def test_khong_cau_hinh_thi_khong_co_origin_nao(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.WORKSPACE_PATH", str(tmp_path / "khong-ton-tai.db"))
    assert _cors_origins() == []


def test_doc_duoc_origin_tu_config(tmp_path):
    from novel2epub.config_writer import update_defaults

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    update_defaults(db, {"api": {"cors_origins": ["http://localhost:3000"]}})
    from app import main

    assert main._cors_origins(str(db)) == ["http://localhost:3000"]


def test_sao_bi_loai_bo(tmp_path):
    from novel2epub.config_writer import update_defaults

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    update_defaults(db, {"api": {"cors_origins": ["*", "http://a"]}})
    from app import main

    assert main._cors_origins(str(db)) == ["http://a"]
