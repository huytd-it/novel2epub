from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub import idioms as idioms_mod


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeJob:
    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": [], "running_ebooks": []},
        }


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob()
    return TestClient(app)


def test_idioms_page_seeds_and_lists(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    # GET trang seed bộ mẫu khi trống
    r = client.get("/idioms")
    assert r.status_code == 200
    data = client.get("/api/idioms/list").json()
    assert data["total"] == len(idioms_mod.DEFAULT_IDIOM_SEED)
    sources = {e["source"] for e in data["entries"]}
    assert "千方百计" in sources


def test_idioms_crud_and_protect(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    client.get("/idioms")  # seed
    # add mới
    r = client.post("/api/idioms/entry", data={
        "source": "画蛇添足", "target": "Vẽ rắn thêm chân", "literals": "Thêm chân cho rắn", "protect": "",
    })
    assert r.json()["ok"]
    # protect entry
    r = client.post("/api/idioms/entry", data={
        "source": "势不可挡", "target": "Thế như chẻ tre", "protect": "1",
    })
    assert r.json()["ok"]
    entries = {e["source"]: e for e in client.get("/api/idioms/list?per_page=500").json()["entries"]}
    assert entries["画蛇添足"]["literals"] == "Thêm chân cho rắn"
    assert entries["势不可挡"]["protect"] is True
    # delete
    client.post("/api/idioms/entry/delete", data={"source": "画蛇添足"})
    assert "画蛇添足" not in {e["source"] for e in client.get("/api/idioms/list?per_page=500").json()["entries"]}


def test_idioms_export_import_roundtrip(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    client.get("/idioms")
    text = client.post("/api/idioms/export").json()["text"]
    assert "千方百计 = Trăm phương nghìn kế | Ngàn phương trăm kế" in text
    # import bản mới đè + thêm
    r = client.post("/api/idioms/import", data={
        "text": "千方百计 = Bản mới\n刻舟求剑 = Khắc thuyền tìm kiếm | @protect\n",
    })
    body = r.json()
    assert body["updated"] == 1 and body["added"] == 1
    entries = {e["source"]: e for e in client.get("/api/idioms/list?per_page=500").json()["entries"]}
    assert entries["千方百计"]["target"] == "Bản mới"
    assert entries["刻舟求剑"]["protect"] is True
