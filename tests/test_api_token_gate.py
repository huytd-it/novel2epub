"""Middleware chặn token cho `/api/*` — lớp bảo vệ khi SPA chạy trên host khác.

Trước đây chỉ `/opds` và `/api/v1` đòi token; phần còn lại của `/api` dựa vào
giả định "chỉ localhost gọi". Đưa giao diện lên Vercel/Cloudflare Pages với
backend sau Tailscale phá vỡ giả định đó, nên nhóm test này khoá lại hành vi:
API điều khiển crawler/queue KHÔNG được mở cho client từ xa không có token.

Mọi test dùng đường dẫn KHÔNG tồn tại (`/api/__probe__`). Chủ đích: câu hỏi ở
đây là "middleware có cho request đi tiếp không", nên 404 (đã tới bảng route)
là câu trả lời "có" sạch nhất — không phụ thuộc vào bất kỳ route thật nào,
tránh cả việc test khác trong suite thay `app.state.job.queue` bằng stub.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel2epub.config import ApiConfig

PROBE = "/api/__probe__"
BLOCKED = (401, 503)
ORIGIN = "https://xuong.vercel.app"


@pytest.fixture
def make_app(monkeypatch):
    from app import deps
    from app.main import app

    def _make(token: str = "tok", origins: list[str] | None = None):
        class _Cfg:
            api = ApiConfig(token=token, cors_origins=origins or [])

        monkeypatch.setattr(deps, "cfg", lambda: _Cfg())
        # `_cors_origins` đọc DB thẳng qua `load_config`, không đi qua
        # `deps.cfg`, nên phải vá riêng để test không đụng DB thật.
        monkeypatch.setattr("app.main._cors_origins", lambda *a, **k: list(origins or []))
        return app

    return _make


def _client(app, host: str) -> TestClient:
    return TestClient(app, client=(host, 12345))


def test_localhost_khong_can_token(make_app):
    r = _client(make_app(), "127.0.0.1").get(PROBE)
    assert r.status_code not in BLOCKED


def test_may_khac_khong_token_bi_chan(make_app):
    r = _client(make_app(), "100.64.0.5").get(PROBE)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_dung_token_thi_qua(make_app):
    r = _client(make_app(), "100.64.0.5").get(
        PROBE, headers={"Authorization": "Bearer tok"}
    )
    assert r.status_code not in BLOCKED


def test_may_khac_sai_token_bi_chan(make_app):
    r = _client(make_app(), "100.64.0.5").get(
        PROBE, headers={"Authorization": "Bearer sai"}
    )
    assert r.status_code == 401


def test_endpoint_ghi_cung_bi_chan(make_app):
    """Endpoint đổi trạng thái mới là thứ đáng lo, không chỉ endpoint đọc."""
    r = _client(make_app(), "100.64.0.5").post(PROBE, json="all")
    assert r.status_code == 401


def test_chua_cau_hinh_token_tra_503(make_app):
    r = _client(make_app(token=""), "100.64.0.5").get(PROBE)
    assert r.status_code == 503
    assert "WWW-Authenticate" not in r.headers


def test_trang_html_khong_bi_middleware_dong_vao(make_app):
    """Chỉ `/api` và `/opds` bị chặn — route web UI giữ nguyên hành vi cũ."""
    r = _client(make_app(), "100.64.0.5").get("/khong-ton-tai")
    assert r.status_code not in BLOCKED


def test_preflight_di_qua_de_trinh_duyet_kip_gui_token(make_app):
    """Trình duyệt không đính `Authorization` vào preflight.

    Chặn OPTIONS thì request chéo chết trước khi kịp gửi token, và lỗi hiện ra
    là "CORS error" mơ hồ chứ không phải 401.
    """
    r = _client(make_app(origins=[ORIGIN]), "100.64.0.5").options(
        PROBE,
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == ORIGIN


def test_401_van_kem_header_cors_de_frontend_doc_duoc_loi(make_app):
    """CORS phải bọc NGOÀI auth.

    Nếu 401 không đi qua lớp CORS, trình duyệt nuốt response và frontend chỉ
    thấy lỗi mạng chung chung — người dùng không biết là sai token.
    """
    r = _client(make_app(origins=[ORIGIN]), "100.64.0.5").get(
        PROBE, headers={"Origin": ORIGIN}
    )
    assert r.status_code == 401
    assert r.headers["Access-Control-Allow-Origin"] == ORIGIN


def test_origin_khong_duoc_cap_thi_khong_co_header_cors(make_app):
    r = _client(make_app(origins=[ORIGIN]), "127.0.0.1").get(
        PROBE, headers={"Origin": "https://ke-la.example"}
    )
    assert "Access-Control-Allow-Origin" not in r.headers


def test_settings_api_van_nam_ngoai_pham_vi_cors():
    """Token hiện cleartext trong HTML trang này — mở CORS cho nó là để lộ.

    Kiểm ở tầng hàm thuần: mở rộng `_CORS_PREFIXES` từ `/api/v1` lên `/api`
    không được kéo theo bất kỳ route web UI nào.
    """
    from app.main import _cors_eligible_path

    assert _cors_eligible_path("/api/ui/library")
    assert _cors_eligible_path("/api/v1/ebooks/x/chapters/1")
    assert _cors_eligible_path("/opds/books")
    assert not _cors_eligible_path("/settings/api")
    assert not _cors_eligible_path("/ebooks/x/settings")
    assert not _cors_eligible_path("/")
