"""Regression: import preset chấp nhận cả định dạng phẳng (sources.yaml cũ)
lẫn định dạng bọc `sources:` (file export)."""
import io

from fastapi.testclient import TestClient

from app import deps
import app.routes.sources as sources_route


FLAT_YAML = """\
biquge:
  engine: scrapling
  url: https://www.biquge.co/
  domains: biquge,bqg
  content_selector: '#content'
shuhaige:
  engine: scrapling
  url: https://www.shuhaige.net/
  domains: shuhaige.net
  content_selector: '#content'
"""

WRAPPED_YAML = """\
sources:
  aixdzs:
    engine: scrapling
    url: https://www.aixdzs.com/
    domains: aixdzs.com
    content_selector: .content
"""


def _client(monkeypatch):
    saved = {}

    def _fake_save(path, presets):
        saved["presets"] = presets

    monkeypatch.setattr(deps, "presets", lambda: {})
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(sources_route, "save_presets", _fake_save)
    from app.main import app

    return TestClient(app, follow_redirects=False), saved


def test_import_flat_sources_yaml(monkeypatch):
    client, saved = _client(monkeypatch)
    resp = client.post(
        "/sources/import",
        files={"file": ("sources.yaml", io.BytesIO(FLAT_YAML.encode()), "application/x-yaml")},
        data={"on_collision": "rename"},
    )
    assert resp.status_code == 303
    assert set(saved["presets"].keys()) == {"biquge", "shuhaige"}
    assert saved["presets"]["biquge"].content_selector == "#content"


def test_import_wrapped_sources_yaml(monkeypatch):
    client, saved = _client(monkeypatch)
    resp = client.post(
        "/sources/import",
        files={"file": ("export.yaml", io.BytesIO(WRAPPED_YAML.encode()), "application/x-yaml")},
        data={"on_collision": "rename"},
    )
    assert resp.status_code == 303
    assert set(saved["presets"].keys()) == {"aixdzs"}
    assert saved["presets"]["aixdzs"].content_selector == ".content"


def test_import_empty_rejected(monkeypatch):
    client, _ = _client(monkeypatch)
    resp = client.post(
        "/sources/import",
        files={"file": ("empty.yaml", io.BytesIO(b"just_a_string\n"), "application/x-yaml")},
        data={"on_collision": "rename"},
    )
    assert resp.status_code == 400
