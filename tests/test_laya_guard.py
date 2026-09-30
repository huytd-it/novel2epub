"""PoC Laya guard: mặc định tắt, log-only, mọi lỗi bị nuốt. Test không cần
model thật — transport HTTP được mock."""
from novel2epub import laya_guard
from novel2epub.laya_guard import LayaGuardConfig, chunk_items, merge_opinions


def test_disabled_by_default():
    assert LayaGuardConfig.from_env({}).enabled is False
    assert LayaGuardConfig.from_env({"LAYA_BASE_URL": "  "}).enabled is False


def test_from_env_parses_threshold_and_bad_values():
    cfg = LayaGuardConfig.from_env({"LAYA_BASE_URL": "http://x:8000/", "LAYA_THRESHOLD": "0.9"})
    assert cfg.enabled is True
    assert cfg.base_url == "http://x:8000"  # rstrip "/"
    assert cfg.threshold == 0.9
    bad = LayaGuardConfig.from_env({"LAYA_THRESHOLD": "abc", "LAYA_TIMEOUT": "abc"})
    assert (bad.threshold, bad.timeout_seconds) == (0.8, 30)


def test_chunk_items_respects_size():
    items = [{"source": f"s{i}", "target": "t"} for i in range(45)]
    chunks = chunk_items(items)
    assert [len(c) for c in chunks] == [20, 20, 5]
    assert chunk_items([], size=0) == []


def test_merge_opinions_annotates_and_measures_agreement():
    gate = {
        "approved": [{"source": "叶凡", "target": "Diệp Phàm"}],
        "held": [{"source": "叶番", "target": "Diệp 凡", "reason": "cờ"}],
    }
    opinions = [
        {"source": "叶凡", "verdict": "A", "confidence": 0.95},  # đồng ý duyệt
        {"source": "叶番", "verdict": "B", "confidence": 0.6},  # đồng ý giữ
    ]
    out = merge_opinions(gate, opinions, threshold=0.8)
    assert out["approved"][0]["laya"] == {"verdict": "A", "confidence": 0.95, "agrees": True}
    assert out["held"][0]["laya"]["agrees"] is True
    assert out["agreement"] == 1.0


def test_merge_opinions_flags_disagreement_and_missing():
    gate = {
        "approved": [{"source": "叶凡", "target": "Diệp Phàm"}, {"source": "林动", "target": "Lâm Động"}],
        "held": [],
    }
    opinions = [{"source": "叶凡", "verdict": "B", "confidence": 0.9}]  # Laya phản đối duyệt
    out = merge_opinions(gate, opinions, threshold=0.8)
    assert out["approved"][0]["laya"]["agrees"] is False
    assert out["approved"][1]["laya"] is None  # không có ý kiến
    assert out["agreement"] == 0.0


def test_merge_opinions_low_confidence_approval_is_not_agreement():
    gate = {"approved": [{"source": "叶凡", "target": "Diệp Phàm"}], "held": []}
    out = merge_opinions(gate, [{"source": "叶凡", "verdict": "A", "confidence": 0.5}], threshold=0.8)
    assert out["approved"][0]["laya"]["agrees"] is False


def test_score_terms_posts_systemone_shape_and_parses(monkeypatch):
    import json as _json

    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"answers": {"q0": {"choice": "A", "confidence": 0.9}}}

    def _post(url, json=None, headers=None, timeout=None):
        seen.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "post", _post)
    cfg = LayaGuardConfig(base_url="http://x:8000")
    out = laya_guard.score_terms(cfg, [{"source": "叶凡", "target": "Diệp Phàm"}])

    assert seen["url"] == "http://x:8000/v1/systemone"
    body = seen["json"]
    assert "- 叶凡 = Diệp Phàm" in body["state"]["terms"]
    assert set(body["questions"]) == {"q0"}
    assert body["questions"]["q0"]["type"] == "choice"
    assert out == [{"source": "叶凡", "verdict": "A", "confidence": 0.9}]


def test_score_terms_skips_failed_chunk_without_raising(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise RuntimeError("server chưa chạy")

    monkeypatch.setattr(requests, "post", _boom)
    logs: list[str] = []
    cfg = LayaGuardConfig(base_url="http://x:8000")
    assert laya_guard.score_terms(cfg, [{"source": "a", "target": "b"}], log=logs.append) == []
    assert any("lỗi" in line for line in logs)
