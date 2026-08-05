# Tích hợp readest GĐ1 — OPDS + EPUB có neo + API sửa đoạn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép readest bản gốc (web / desktop / mobile) nối vào novel2epub qua OPDS để đọc bản dịch, và dựng sẵn API sửa từng đoạn văn có neo ổn định để giai đoạn 2 fork readest có nền mà dùng.

**Architecture:** Ba module mới tách logic thuần khỏi I/O — `novel2epub/opds.py` (sinh Atom XML), `novel2epub/api_auth.py` (phân giải + so khớp token), `app/routes/opds.py` (HTTP). Neo đoạn văn nhúng vào EPUB lúc build dưới dạng `data-n2e-p`, đánh số theo **chỉ số dòng-không-rỗng** để khớp chính xác `notes.split_paras` — hàm mà `notes.replace_para` dùng để ghi.

**Tech Stack:** Python 3, FastAPI, SQLite, `xml.etree.ElementTree`, ebooklib, pytest.

**Spec:** [docs/superpowers/specs/2026-08-05-readest-opds-integration-design.md](../specs/2026-08-05-readest-opds-integration-design.md)

## Global Constraints

Mọi task đều phải tuân các ràng buộc sau.

- **Một định nghĩa đoạn văn duy nhất:** `notes.split_paras(text)` = `[p for p in text.split("\n") if p.strip()]` — chỉ số **dòng-không-rỗng**. Mọi chỗ đánh số đoạn phải khớp hàm này. Không được dùng định nghĩa block-cách-dòng-trống của `epub_builder`.
- **Lỗi xác thực trả 401 kèm `WWW-Authenticate: Basic realm="novel2epub"`.** Không bao giờ trả 400 hay 403 cho lỗi xác thực — readest gửi Basic preemptive và chỉ đàm phán lại trên 401/403.
- **Token không bao giờ vào log, thông báo lỗi, hay response.** Cùng nguyên tắc `reader_client.py` giữ với `service_key`.
- **Địa chỉ client lấy từ `request.client.host`.** Cấm đọc `X-Forwarded-For` / `X-Real-IP`.
- **Response OPDS phải sạch tuyệt đối:** không có ký tự nào sau `</feed>`. Parser nghiêm ngặt (Firefox, jsdom) huỷ cả tài liệu nếu có rác.
- **rel ảnh phải là token chính xác:** `http://opds-spec.org/image` và `http://opds-spec.org/image/thumbnail`. Phát cả hai.
- **Mô tả sách đặt trong `<summary>`** — chỗ parser OPDS 1.x của foliate-js đọc.
- Chạy test bằng `pytest tests -v`. Không commit DB, dữ liệu truyện, EPUB hay secret.
- Tiếng Việt cho docstring và thông báo lỗi hướng tới người dùng, bám giọng của codebase hiện tại.

## File Structure

| File | Trách nhiệm |
|---|---|
| `novel2epub/api_auth.py` | **Mới, thuần.** Trích token từ header `Authorization` (Basic/Bearer), so khớp hằng thời gian, nhận diện client localhost. |
| `novel2epub/opds.py` | **Mới, thuần.** Dataclass `OpdsBook`, sinh chuỗi XML cho feed navigation và feed acquisition. Không I/O. |
| `app/auth.py` | **Mới.** Dependency FastAPI `require_api_auth` — lớp keo giữa `api_auth` thuần và HTTP. |
| `app/routes/opds.py` | **Mới.** Route `/opds/*` và `/api/v1/*`. Đọc `Storage`, phục vụ EPUB và ảnh bìa. |
| `app/templates/settings_api.html` | **Mới.** Khối cấu hình token / CORS / URL catalog trong trang Cài đặt. |
| `novel2epub/db.py` | Sửa: cột `settings.api_json`, `SCHEMA_VERSION` 7 → 8. |
| `novel2epub/config.py` | Sửa: dataclass `ApiConfig`, đọc section `api`. |
| `novel2epub/config_writer.py` | Sửa: ghi được section `api`. |
| `novel2epub/epub_builder.py` | Sửa: `_md_to_xhtml_body` sinh neo, `build_epub` nhận `anchored_stems`. |
| `novel2epub/pipeline.py` | Sửa: `step_build_selected` tính `anchored_stems`. |
| `app/main.py` | Sửa: mount router OPDS, thêm CORS middleware. |
| `app/routes/settings.py` | Sửa: GET/POST khối `api`. |
| `tests/conftest.py` | Sửa: fixture biết section `api`. |

---

### Task 1: Cấu hình `api` — schema, dataclass, đọc và ghi

Không có token thì mọi thứ sau đó không chạy được từ máy khác, nên đây là task đầu tiên.

**Files:**
- Modify: `novel2epub/db.py` (`SCHEMA_VERSION`, `_SCHEMA_STATEMENTS` bảng `settings`, `_ADDED_COLUMNS`)
- Modify: `novel2epub/config.py` (`ApiConfig`, `Config.api`, `_load_raw_from_db`, `_build_config`)
- Modify: `novel2epub/config_writer.py` (`_SETTINGS_SECTIONS`, `_upsert_settings`)
- Modify: `tests/conftest.py` (`_SETTINGS_SECTIONS`, câu INSERT)
- Test: `tests/test_api_config.py`

**Interfaces:**
- Consumes: không có (task đầu)
- Produces:
  - `novel2epub.config.ApiConfig(token: str = "", cors_origins: list[str] = [])`
  - `Config.api: ApiConfig`
  - Section `"api"` hợp lệ với `config_writer.update_defaults(path, {"api": {...}})` và `config_writer.reset_defaults(path, ["api"])`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api_config.py`:

```python
"""Cấu hình `api` — token và CORS cho OPDS/API ngoài localhost."""
from __future__ import annotations

from novel2epub.config import ApiConfig, load_config
from novel2epub.config_writer import reset_defaults, update_defaults

from .conftest import write_db_config


def test_api_mac_dinh_rong(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={})
    cfg = load_config(db)
    assert cfg.api == ApiConfig()
    assert cfg.api.token == ""
    assert cfg.api.cors_origins == []


def test_api_doc_duoc_tu_defaults(tmp_path):
    db = write_db_config(
        tmp_path / "n.db",
        defaults={"api": {"token": "abc123", "cors_origins": ["http://localhost:3000"]}},
    )
    cfg = load_config(db)
    assert cfg.api.token == "abc123"
    assert cfg.api.cors_origins == ["http://localhost:3000"]


def test_token_bi_strip_khoang_trang(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={"api": {"token": "  abc  "}})
    assert load_config(db).api.token == "abc"


def test_cors_origins_bo_phan_tu_rong_va_strip(tmp_path):
    db = write_db_config(
        tmp_path / "n.db",
        defaults={"api": {"cors_origins": [" http://a ", "", "   ", "http://b"]}},
    )
    assert load_config(db).api.cors_origins == ["http://a", "http://b"]


def test_cors_origins_khong_phai_list_thi_bo_qua(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={"api": {"cors_origins": "http://a"}})
    assert load_config(db).api.cors_origins == []


def test_update_defaults_ghi_duoc_section_api(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={})
    update_defaults(db, {"api": {"token": "tok"}})
    assert load_config(db).api.token == "tok"


def test_reset_defaults_xoa_duoc_section_api(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={"api": {"token": "tok"}})
    assert reset_defaults(db, ["api"]) == ["api"]
    assert load_config(db).api.token == ""
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_api_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'ApiConfig' from 'novel2epub.config'`

- [ ] **Step 3: Thêm cột `api_json` vào schema**

Trong `novel2epub/db.py`, đổi `SCHEMA_VERSION = 7` thành `SCHEMA_VERSION = 8`.

Trong `_SCHEMA_STATEMENTS`, ở `CREATE TABLE IF NOT EXISTS settings`, thêm dòng `api_json` ngay sau `reader_json`:

```python
        reader_json TEXT NOT NULL DEFAULT '{}',
        api_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
```

Cuối danh sách `_ADDED_COLUMNS`, thêm:

```python
    # v8: token + CORS cho OPDS/API ngoài localhost (tích hợp readest GĐ1).
    # KHÔNG gộp vào `reader_json` — khối đó thuộc app novel-reader (Supabase).
    ("settings", "api_json", "TEXT NOT NULL DEFAULT '{}'"),
```

- [ ] **Step 4: Thêm `ApiConfig` vào config.py**

Trong `novel2epub/config.py`, thêm dataclass ngay sau `QueueConfig`:

```python
@dataclass
class ApiConfig:
    """Truy cập API/OPDS từ ngoài localhost (tích hợp readest).

    `token` dùng chung mọi ebook. Request từ localhost được miễn token nên
    web UI và readest desktop chạy cùng máy không cần cấu hình gì.
    `cors_origins` chỉ cần cho bản readest WEB — Tauri desktop/mobile gọi
    HTTP native, không đi qua CORS. TUYỆT ĐỐI không dùng "*".
    """
    token: str = ""
    cors_origins: list[str] = field(default_factory=list)
```

Thêm field vào `Config` (ngay sau `reader`):

```python
    api: ApiConfig = field(default_factory=ApiConfig)
```

Trong `_load_raw_from_db`, thêm `"api"` vào tuple section:

```python
        for section in ("novel", "crawl", "translate", "ai", "output", "queue", "reader", "api"):
```

Trong hàm dựng `Config` (chỗ ngay sau khối `reader = ReaderConfig(...)` ở khoảng dòng 888), thêm:

```python
    api_raw = _as_dict(raw.get("api"))
    origins_raw = api_raw.get("cors_origins")
    cors_origins = (
        [str(o).strip() for o in origins_raw if str(o).strip()]
        if isinstance(origins_raw, list)
        else []
    )
    api = ApiConfig(
        token=str(api_raw.get("token", "")).strip(),
        cors_origins=cors_origins,
    )
```

Rồi truyền `api=api` vào lời gọi `Config(...)` ở cuối hàm.

- [ ] **Step 5: Cho config_writer ghi được section `api`**

Trong `novel2epub/config_writer.py`, đổi `_SETTINGS_SECTIONS`:

```python
_SETTINGS_SECTIONS = ("novel", "crawl", "translate", "ai", "output", "queue", "reader", "api")
```

Trong `_upsert_settings`, thêm cột vào cả ba chỗ của câu SQL:

```python
        INSERT INTO settings (id, novel_json, crawl_json, translate_json, ai_json, output_json, queue_json, reader_json, api_json)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            novel_json = excluded.novel_json,
            crawl_json = excluded.crawl_json,
            translate_json = excluded.translate_json,
            ai_json = excluded.ai_json,
            output_json = excluded.output_json,
            queue_json = excluded.queue_json,
            reader_json = excluded.reader_json,
            api_json = excluded.api_json,
            updated_at = datetime('now')
```

- [ ] **Step 6: Cập nhật fixture test**

Trong `tests/conftest.py`, đổi `_SETTINGS_SECTIONS`:

```python
_SETTINGS_SECTIONS = ("novel", "crawl", "translate", "ai", "output", "queue", "reader", "api")
```

và câu INSERT trong `write_db_config`:

```python
            INSERT INTO settings (id, novel_json, crawl_json, translate_json, ai_json, output_json, queue_json, reader_json, api_json)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                novel_json = excluded.novel_json, crawl_json = excluded.crawl_json,
                translate_json = excluded.translate_json, ai_json = excluded.ai_json,
                output_json = excluded.output_json, queue_json = excluded.queue_json,
                reader_json = excluded.reader_json, api_json = excluded.api_json
```

- [ ] **Step 7: Chạy test mới + toàn bộ suite**

Run: `pytest tests/test_api_config.py -v`
Expected: PASS (7 test)

Run: `pytest tests -q`
Expected: PASS — không được có regression. Nếu `tests/test_db_schema.py` khẳng định `SCHEMA_VERSION == 7`, sửa nó thành `8` và kiểm tra nó cũng khẳng định cột `api_json` tồn tại.

- [ ] **Step 8: Commit**

```bash
git add novel2epub/db.py novel2epub/config.py novel2epub/config_writer.py tests/conftest.py tests/test_api_config.py tests/test_db_schema.py
git commit -m "feat(api): cấu hình api.token + api.cors_origins, schema v8"
```

---

### Task 2: `novel2epub/api_auth.py` — logic xác thực thuần

**Files:**
- Create: `novel2epub/api_auth.py`
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: không
- Produces:
  - `token_from_header(header: str) -> str`
  - `token_matches(expected: str, provided: str) -> bool`
  - `is_local_client(host: str) -> bool`
  - `WWW_AUTHENTICATE: dict[str, str]`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api_auth.py`:

```python
"""Logic xác thực thuần cho API/OPDS — không đụng HTTP."""
from __future__ import annotations

import base64

from novel2epub.api_auth import (
    WWW_AUTHENTICATE,
    is_local_client,
    token_from_header,
    token_matches,
)


def _basic(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def test_bearer_tra_ve_token():
    assert token_from_header("Bearer abc123") == "abc123"


def test_scheme_khong_phan_biet_hoa_thuong():
    assert token_from_header("bearer abc123") == "abc123"
    assert token_from_header("BASIC " + _basic("u", "p").split(" ", 1)[1]) == "p"


def test_basic_lay_password_bo_qua_username():
    # readest gửi username/password; ta chỉ quan tâm password.
    assert token_from_header(_basic("bat-ky-ai", "tok")) == "tok"


def test_basic_password_chua_dau_hai_cham_khong_bi_cat():
    assert token_from_header(_basic("u", "a:b:c")) == "a:b:c"


def test_basic_username_rong_van_lay_duoc_password():
    assert token_from_header(_basic("", "tok")) == "tok"


def test_header_rong_hoac_rac_tra_chuoi_rong():
    assert token_from_header("") == ""
    assert token_from_header("Basic") == ""
    assert token_from_header("Digest xyz") == ""
    assert token_from_header("Basic !!!khong-phai-base64!!!") == ""


def test_basic_khong_co_dau_hai_cham_tra_rong():
    raw = base64.b64encode(b"khongcodauhaicham").decode("ascii")
    assert token_from_header("Basic " + raw) == ""


def test_token_matches_dung_va_sai():
    assert token_matches("tok", "tok") is True
    assert token_matches("tok", "khac") is False


def test_token_matches_tu_choi_chuoi_rong():
    # Token chưa cấu hình KHÔNG được biến thành "ai cũng vào được".
    assert token_matches("", "") is False
    assert token_matches("", "bat-ky") is False
    assert token_matches("tok", "") is False


def test_is_local_client():
    assert is_local_client("127.0.0.1") is True
    assert is_local_client("::1") is True
    assert is_local_client("localhost") is True
    assert is_local_client("192.168.1.20") is False
    assert is_local_client("") is False
    assert is_local_client("127.0.0.1, 10.0.0.5") is False


def test_www_authenticate_la_basic_realm():
    assert WWW_AUTHENTICATE == {"WWW-Authenticate": 'Basic realm="novel2epub"'}
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_api_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novel2epub.api_auth'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `novel2epub/api_auth.py`:

```python
"""Xác thực token cho OPDS và API ngoài (tích hợp readest).

Logic THUẦN — không import FastAPI, không đọc config, không I/O. Lớp keo với
HTTP nằm ở `app/auth.py`.

Hỗ trợ hai cách gửi token vì hai bên gọi khác nhau:

- **Basic** — readest gửi username/password cho catalog OPDS. Username bị bỏ
  qua hoàn toàn, chỉ password được so với token.
- **Bearer** — dùng cho API sửa đoạn và cho việc thử tay bằng curl.

readest gửi Basic PREEMPTIVE (ngay từ request đầu, không đợi thử thách) và chỉ
đàm phán lại khi nhận 401/403 — nên `WWW_AUTHENTICATE` phải đi kèm mọi
response 401, và lỗi xác thực KHÔNG được trả 400 hay 403.
"""
from __future__ import annotations

import base64
import binascii
import hmac

# Địa chỉ được miễn token. So sánh với `request.client.host` (địa chỉ socket
# thật) — TUYỆT ĐỐI không so với X-Forwarded-For: client tự đặt được header đó,
# tin nó thì miễn trừ localhost thành cửa mở toang cho cả LAN.
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

WWW_AUTHENTICATE = {"WWW-Authenticate": 'Basic realm="novel2epub"'}


def token_from_header(header: str) -> str:
    """Token nằm trong giá trị header `Authorization`, hoặc "" nếu không đọc được."""
    if not header:
        return ""
    scheme, _, rest = header.partition(" ")
    rest = rest.strip()
    if not rest:
        return ""
    scheme = scheme.strip().lower()
    if scheme == "bearer":
        return rest
    if scheme == "basic":
        try:
            decoded = base64.b64decode(rest, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return ""
        # `partition` chứ không phải `split`: password chứa dấu ":" là hợp lệ.
        _user, sep, password = decoded.partition(":")
        return password if sep else ""
    return ""


def token_matches(expected: str, provided: str) -> bool:
    """So khớp hằng thời gian. Chuỗi rỗng LUÔN không khớp — token chưa cấu
    hình không được biến thành "ai cũng vào được"."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def is_local_client(host: str) -> bool:
    """`host` là máy đang chạy chính novel2epub?"""
    return host in _LOCAL_HOSTS
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_api_auth.py -v`
Expected: PASS (11 test)

- [ ] **Step 5: Commit**

```bash
git add novel2epub/api_auth.py tests/test_api_auth.py
git commit -m "feat(api): logic xác thực token thuần (Basic + Bearer)"
```

---

### Task 3: `app/auth.py` — dependency FastAPI

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_api_auth_dep.py`

**Interfaces:**
- Consumes: `novel2epub.api_auth.{token_from_header, token_matches, is_local_client, WWW_AUTHENTICATE}`, `novel2epub.config.ApiConfig`
- Produces: `app.auth.require_api_auth(request: Request) -> None` — dùng làm `Depends(require_api_auth)`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api_auth_dep.py`:

```python
"""Dependency xác thực ở tầng HTTP: mã lỗi, header thử thách, miễn localhost."""
from __future__ import annotations

import base64

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from novel2epub.config import ApiConfig


def _app(monkeypatch, token: str):
    from app import auth, deps

    class _Cfg:
        api = ApiConfig(token=token)

    monkeypatch.setattr(deps, "cfg", lambda: _Cfg())
    api = FastAPI()

    @api.get("/protected")
    def protected(_=Depends(auth.require_api_auth)):
        return {"ok": True}

    return api


def _client(monkeypatch, token: str, host: str = "127.0.0.1"):
    # TestClient mặc định báo client host là "testclient" (không phải localhost),
    # nên dùng nó để mô phỏng máy KHÁC; truyền client=... để mô phỏng localhost.
    return TestClient(_app(monkeypatch, token), client=(host, 12345))


def _basic(password: str) -> dict[str, str]:
    raw = base64.b64encode(f"u:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + raw}


def test_localhost_duoc_mien_token(monkeypatch):
    r = _client(monkeypatch, token="tok", host="127.0.0.1").get("/protected")
    assert r.status_code == 200


def test_localhost_duoc_mien_ngay_ca_khi_chua_cau_hinh_token(monkeypatch):
    r = _client(monkeypatch, token="", host="127.0.0.1").get("/protected")
    assert r.status_code == 200


def test_may_khac_khong_co_token_tra_401_kem_www_authenticate(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get("/protected")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_sai_token_tra_401(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected", headers=_basic("sai")
    )
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_dung_token_basic_thi_qua(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected", headers=_basic("tok")
    )
    assert r.status_code == 200


def test_may_khac_dung_token_bearer_thi_qua(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected", headers={"Authorization": "Bearer tok"}
    )
    assert r.status_code == 200


def test_chua_cau_hinh_token_tra_503_khong_phai_401(monkeypatch):
    # Lỗi cấu hình phía server, KHÔNG phải thử thách xác thực — không được
    # để readest tưởng có thể đàm phán.
    r = _client(monkeypatch, token="", host="192.168.1.20").get("/protected")
    assert r.status_code == 503
    assert "WWW-Authenticate" not in r.headers


def test_x_forwarded_for_gia_mao_khong_duoc_mien_tru(monkeypatch):
    # Đây là test quan trọng nhất của file: header do client tự đặt không
    # bao giờ được biến thành quyền truy cập.
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected",
        headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
    )
    assert r.status_code == 401


def test_token_khong_lot_vao_than_response(monkeypatch):
    r = _client(monkeypatch, token="sieu-bi-mat", host="192.168.1.20").get("/protected")
    assert "sieu-bi-mat" not in r.text
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_api_auth_dep.py -v`
Expected: FAIL — `ImportError: cannot import name 'auth' from 'app'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `app/auth.py`:

```python
"""Dependency FastAPI cho các endpoint mở ra ngoài localhost (OPDS + API sửa).

Lớp keo mỏng giữa `novel2epub.api_auth` (thuần) và HTTP. Giữ mỏng có chủ đích:
mọi quyết định đều nằm bên module thuần để test được không cần dựng app.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from novel2epub import api_auth

from . import deps


def require_api_auth(request: Request) -> None:
    """Chặn request không có token hợp lệ. Miễn trừ khi gọi từ chính máy này.

    Ba nhánh, mã lỗi cố ý khác nhau:

    - localhost -> cho qua, không cần token (web UI + readest desktop cùng máy).
    - chưa cấu hình token -> 503: lỗi cấu hình server, KHÔNG kèm
      `WWW-Authenticate` vì không có gì để đàm phán.
    - thiếu/sai token -> 401 KÈM `WWW-Authenticate`. readest gửi Basic
      preemptive và chỉ đàm phán lại trên 401/403; trả 400 hay 403 sẽ đẩy nó
      vào nhánh phục hồi sai và người dùng chỉ thấy "Failed to load OPDS feed".
    """
    host = request.client.host if request.client else ""
    if api_auth.is_local_client(host):
        return

    token = deps.cfg().api.token
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Chưa cấu hình token API — vào Cài đặt > API để bật truy cập "
                "từ máy khác."
            ),
        )

    provided = api_auth.token_from_header(request.headers.get("authorization", ""))
    if not api_auth.token_matches(token, provided):
        raise HTTPException(
            status_code=401,
            detail="Token không hợp lệ.",
            headers=api_auth.WWW_AUTHENTICATE,
        )
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_api_auth_dep.py -v`
Expected: PASS (9 test)

Nếu `TestClient(..., client=(host, port))` không được hỗ trợ ở phiên bản Starlette đang dùng, thay bằng cách gửi qua transport tuỳ biến: dựng `TestClient(api)` bình thường và monkeypatch `app.auth.api_auth.is_local_client` theo từng test. Ưu tiên cách `client=` vì nó kiểm chứng đúng đường `request.client.host` thật.

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_api_auth_dep.py
git commit -m "feat(api): dependency xác thực — 401 kèm WWW-Authenticate, miễn localhost"
```

---

### Task 4: `novel2epub/opds.py` — sinh feed Atom

**Files:**
- Create: `novel2epub/opds.py`
- Test: `tests/test_opds.py`

**Interfaces:**
- Consumes: không
- Produces:
  - `OpdsBook` dataclass: `slug, title, author="", description="", language="vi", identifier="", publisher="", pubdate="", subjects=[], updated="", has_cover=False, cover_type="image/jpeg"`
  - `navigation_feed(*, base_url: str, updated: str) -> str`
  - `acquisition_feed(books: list[OpdsBook], *, base_url: str, updated: str) -> str`
  - `NAV_TYPE: str`, `ACQ_TYPE: str` — giá trị `Content-Type` cho hai loại feed
  - `iso_utc(timestamp: float) -> str`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_opds.py`:

```python
"""Sinh feed OPDS 1.2 (Atom). Logic thuần — không mạng, không DB.

Các khẳng định ở đây bám sát thứ readest THỰC SỰ đọc (hằng `REL` trong
`apps/readest-app/src/types/opds.ts`), không phải bám bản chuẩn OPDS chung
chung.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from novel2epub.opds import (
    ACQ_TYPE,
    NAV_TYPE,
    OpdsBook,
    acquisition_feed,
    iso_utc,
    navigation_feed,
)

ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/terms/"
UPDATED = "2026-08-05T10:00:00Z"


def _book(**kw) -> OpdsBook:
    base = dict(
        slug="truyen-a",
        title="Truyện A",
        author="Tác Giả",
        description="Mô tả",
        language="vi",
        updated=UPDATED,
        has_cover=True,
    )
    base.update(kw)
    return OpdsBook(**base)


def _links(entry) -> dict[str, str]:
    return {ln.get("rel"): ln.get("href") for ln in entry.findall(f"{{{ATOM}}}link")}


# ---------- feed điều hướng ----------


def test_navigation_feed_la_xml_hop_le_va_goc_la_feed():
    root = ET.fromstring(navigation_feed(base_url="http://h:8010", updated=UPDATED))
    assert root.tag == f"{{{ATOM}}}feed"


def test_navigation_feed_tro_toi_feed_acquisition():
    root = ET.fromstring(navigation_feed(base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    assert entry is not None
    link = entry.find(f"{{{ATOM}}}link")
    assert link.get("href") == "http://h:8010/opds/books"
    assert link.get("type") == ACQ_TYPE


def test_navigation_feed_co_link_self_va_start():
    root = ET.fromstring(navigation_feed(base_url="http://h:8010", updated=UPDATED))
    rels = {ln.get("rel") for ln in root.findall(f"{{{ATOM}}}link")}
    assert {"self", "start"} <= rels


# ---------- feed acquisition ----------


def test_acquisition_feed_mot_entry_moi_sach():
    xml = acquisition_feed([_book(), _book(slug="b", title="B")],
                           base_url="http://h:8010", updated=UPDATED)
    root = ET.fromstring(xml)
    assert len(root.findall(f"{{{ATOM}}}entry")) == 2


def test_link_tai_sach_dung_rel_acquisition_va_media_type_epub():
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    acq = [
        ln for ln in entry.findall(f"{{{ATOM}}}link")
        if ln.get("rel") == "http://opds-spec.org/acquisition"
    ]
    assert len(acq) == 1
    assert acq[0].get("href") == "http://h:8010/opds/download/truyen-a.epub"
    assert acq[0].get("type") == "application/epub+zip"


def test_phat_ca_hai_rel_anh_voi_token_chinh_xac():
    # readest so khớp rel bằng token chính xác; thiếu một trong hai thì hoặc
    # mất bìa, hoặc mất ảnh thu nhỏ.
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    links = _links(root.find(f"{{{ATOM}}}entry"))
    assert links["http://opds-spec.org/image"] == "http://h:8010/opds/cover/truyen-a"
    assert links["http://opds-spec.org/image/thumbnail"] == "http://h:8010/opds/cover/truyen-a"


def test_sach_khong_co_bia_thi_khong_phat_link_anh():
    root = ET.fromstring(
        acquisition_feed([_book(has_cover=False)], base_url="http://h:8010", updated=UPDATED)
    )
    links = _links(root.find(f"{{{ATOM}}}entry"))
    assert "http://opds-spec.org/image" not in links
    assert "http://opds-spec.org/image/thumbnail" not in links


def test_mo_ta_nam_trong_summary():
    # Parser OPDS 1.x của foliate-js đọc mô tả ở <summary>.
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    summary = root.find(f"{{{ATOM}}}entry/{{{ATOM}}}summary")
    assert summary is not None
    assert summary.text == "Mô tả"
    assert summary.get("type") == "text"


def test_metadata_dc_duoc_phat():
    book = _book(language="vi", identifier="isbn:123", publisher="NXB X", pubdate="2026-01-02")
    root = ET.fromstring(acquisition_feed([book], base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    assert entry.find(f"{{{DC}}}language").text == "vi"
    assert entry.find(f"{{{DC}}}identifier").text == "isbn:123"
    assert entry.find(f"{{{DC}}}publisher").text == "NXB X"
    assert entry.find(f"{{{DC}}}issued").text == "2026-01-02"


def test_truong_rong_khong_sinh_the_rong():
    book = _book(author="", description="", identifier="", publisher="", pubdate="")
    root = ET.fromstring(acquisition_feed([book], base_url="http://h:8010", updated=UPDATED))
    entry = root.find(f"{{{ATOM}}}entry")
    assert entry.find(f"{{{ATOM}}}author") is None
    assert entry.find(f"{{{ATOM}}}summary") is None
    assert entry.find(f"{{{DC}}}identifier") is None
    assert entry.find(f"{{{DC}}}publisher") is None
    assert entry.find(f"{{{DC}}}issued") is None


def test_the_loai_thanh_category():
    book = _book(subjects=["Tiên hiệp", "Huyền huyễn"])
    root = ET.fromstring(acquisition_feed([book], base_url="http://h:8010", updated=UPDATED))
    terms = [c.get("term") for c in root.findall(f"{{{ATOM}}}entry/{{{ATOM}}}category")]
    assert terms == ["Tiên hiệp", "Huyền huyễn"]


def test_id_entry_on_dinh_theo_slug():
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED))
    assert root.find(f"{{{ATOM}}}entry/{{{ATOM}}}id").text == "urn:novel2epub:truyen-a"


def test_danh_sach_rong_van_ra_feed_hop_le():
    root = ET.fromstring(acquisition_feed([], base_url="http://h:8010", updated=UPDATED))
    assert root.tag == f"{{{ATOM}}}feed"
    assert root.findall(f"{{{ATOM}}}entry") == []


# ---------- an toàn XML ----------


def test_ky_tu_dac_biet_trong_tieu_de_duoc_escape():
    book = _book(title="《Truyện》 & <Ký> \"Sự\"", author="A & B")
    xml = acquisition_feed([book], base_url="http://h:8010", updated=UPDATED)
    root = ET.fromstring(xml)  # nổ ở đây nghĩa là escape sai
    assert root.find(f"{{{ATOM}}}entry/{{{ATOM}}}title").text == "《Truyện》 & <Ký> \"Sự\""


def test_khong_co_ky_tu_nao_sau_the_dong_goc():
    # Rác sau </feed> khiến DOMParser nghiêm ngặt (Firefox, jsdom) huỷ CẢ tài
    # liệu — readest sẽ tưởng response là HTML rồi quay lui.
    for xml in (
        navigation_feed(base_url="http://h:8010", updated=UPDATED),
        acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED),
    ):
        assert xml.rstrip().endswith("</feed>")
        assert xml.strip() == xml.rstrip()


def test_feed_bat_dau_bang_khai_bao_xml():
    xml = acquisition_feed([_book()], base_url="http://h:8010", updated=UPDATED)
    assert xml.startswith("<?xml ")


def test_base_url_co_dau_gach_cuoi_khong_sinh_duong_dan_doi():
    root = ET.fromstring(acquisition_feed([_book()], base_url="http://h:8010/", updated=UPDATED))
    links = _links(root.find(f"{{{ATOM}}}entry"))
    assert links["http://opds-spec.org/acquisition"] == "http://h:8010/opds/download/truyen-a.epub"


def test_iso_utc_dinh_dang_atom():
    assert iso_utc(0) == "1970-01-01T00:00:00Z"


def test_content_type_phan_biet_hai_loai_feed():
    assert "kind=navigation" in NAV_TYPE
    assert "kind=acquisition" in ACQ_TYPE
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_opds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novel2epub.opds'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `novel2epub/opds.py`:

```python
"""Sinh catalog OPDS 1.2 (Atom XML) cho trình đọc ngoài — chủ yếu là readest.

Logic THUẦN: nhận list `OpdsBook` đã dựng sẵn, trả chuỗi XML. Không I/O,
không DB, không FastAPI.

Vì sao Atom 1.2 chứ không phải OPDS 2.0 (JSON): readest parse feed bằng
`foliate-js/opds.js`, vốn xử lý cả hai và chuẩn hoá về cùng một shape; Atom
1.2 là bản mà Calibre/Komga/Kavita phục vụ nên là đường đi được thử nhiều
nhất.

Dùng `ElementTree` chứ không nối chuỗi tay: nó bảo đảm escape đúng và tài
liệu đóng gọn. Rác sau `</feed>` sẽ khiến DOMParser nghiêm ngặt (Firefox,
jsdom) huỷ cả tài liệu, và readest khi đó tưởng response là HTML rồi quay lui.
"""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/terms/"

# `rel` readest thực sự dò (hằng REL trong apps/readest-app/src/types/opds.ts).
# Phải là token CHÍNH XÁC — nó tách rel theo khoảng trắng rồi so bằng.
REL_ACQUISITION = "http://opds-spec.org/acquisition"
REL_IMAGE = "http://opds-spec.org/image"
REL_THUMBNAIL = "http://opds-spec.org/image/thumbnail"

NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
EPUB_TYPE = "application/epub+zip"

_CATALOG_TITLE = "novel2epub"


@dataclass
class OpdsBook:
    """Một ebook đã build EPUB, sẵn sàng phát ra feed."""
    slug: str
    title: str
    author: str = ""
    description: str = ""
    language: str = "vi"
    identifier: str = ""
    publisher: str = ""
    pubdate: str = ""
    subjects: list[str] = field(default_factory=list)
    # Thời điểm sửa của FILE EPUB, không phải của bản dịch — readest quyết
    # định tải lại dựa vào trường này, mà thứ nó tải là file.
    updated: str = ""
    has_cover: bool = False
    cover_type: str = "image/jpeg"


def iso_utc(timestamp: float) -> str:
    """Epoch giây -> chuỗi thời gian Atom (UTC, hậu tố Z)."""
    moment = _dt.datetime.fromtimestamp(timestamp, tz=_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(parent: ET.Element, tag: str, value: str) -> None:
    """Thêm thẻ có nội dung; bỏ qua khi giá trị rỗng (không sinh thẻ rỗng)."""
    if not value:
        return
    ET.SubElement(parent, tag).text = value


def _link(parent: ET.Element, *, rel: str, href: str, type_: str) -> None:
    ET.SubElement(parent, f"{{{ATOM_NS}}}link", {"rel": rel, "href": href, "type": type_})


def _serialize(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body.rstrip()


def _feed_root(*, feed_id: str, title: str, updated: str) -> ET.Element:
    root = ET.Element(f"{{{ATOM_NS}}}feed")
    _text(root, f"{{{ATOM_NS}}}id", feed_id)
    _text(root, f"{{{ATOM_NS}}}title", title)
    _text(root, f"{{{ATOM_NS}}}updated", updated)
    return root


def navigation_feed(*, base_url: str, updated: str) -> str:
    """Feed gốc — chỉ trỏ tới feed acquisition. Giữ một mục: 6 ebook chưa
    đáng chia nhóm."""
    base = base_url.rstrip("/")
    root = _feed_root(feed_id="urn:novel2epub:catalog", title=_CATALOG_TITLE, updated=updated)
    _link(root, rel="self", href=f"{base}/opds", type_=NAV_TYPE)
    _link(root, rel="start", href=f"{base}/opds", type_=NAV_TYPE)

    entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")
    _text(entry, f"{{{ATOM_NS}}}title", "Tất cả truyện")
    _text(entry, f"{{{ATOM_NS}}}id", "urn:novel2epub:books")
    _text(entry, f"{{{ATOM_NS}}}updated", updated)
    _link(entry, rel="subsection", href=f"{base}/opds/books", type_=ACQ_TYPE)
    ET.SubElement(entry, f"{{{ATOM_NS}}}content", {"type": "text"}).text = (
        "Toàn bộ ebook đã build"
    )
    return _serialize(root)


def acquisition_feed(books: list[OpdsBook], *, base_url: str, updated: str) -> str:
    """Feed danh sách sách tải được. Mỗi `OpdsBook` thành một `<entry>`."""
    base = base_url.rstrip("/")
    root = _feed_root(feed_id="urn:novel2epub:books", title=_CATALOG_TITLE, updated=updated)
    _link(root, rel="self", href=f"{base}/opds/books", type_=ACQ_TYPE)
    _link(root, rel="start", href=f"{base}/opds", type_=NAV_TYPE)

    for book in books:
        entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")
        _text(entry, f"{{{ATOM_NS}}}title", book.title or book.slug)
        _text(entry, f"{{{ATOM_NS}}}id", f"urn:novel2epub:{book.slug}")
        _text(entry, f"{{{ATOM_NS}}}updated", book.updated or updated)
        if book.author:
            author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
            _text(author, f"{{{ATOM_NS}}}name", book.author)
        if book.description:
            summary = ET.SubElement(entry, f"{{{ATOM_NS}}}summary", {"type": "text"})
            summary.text = book.description
        _text(entry, f"{{{DC_NS}}}language", book.language)
        _text(entry, f"{{{DC_NS}}}identifier", book.identifier)
        _text(entry, f"{{{DC_NS}}}publisher", book.publisher)
        _text(entry, f"{{{DC_NS}}}issued", book.pubdate)
        for subject in book.subjects:
            if subject:
                ET.SubElement(entry, f"{{{ATOM_NS}}}category", {"term": subject})
        if book.has_cover:
            cover = f"{base}/opds/cover/{book.slug}"
            _link(entry, rel=REL_IMAGE, href=cover, type_=book.cover_type)
            _link(entry, rel=REL_THUMBNAIL, href=cover, type_=book.cover_type)
        _link(
            entry,
            rel=REL_ACQUISITION,
            href=f"{base}/opds/download/{book.slug}.epub",
            type_=EPUB_TYPE,
        )
    return _serialize(root)
```

Đăng ký prefix namespace một lần ở đầu module (sau phần hằng) để output đọc được:

```python
ET.register_namespace("", ATOM_NS)
ET.register_namespace("dc", DC_NS)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_opds.py -v`
Expected: PASS (19 test)

- [ ] **Step 5: Commit**

```bash
git add novel2epub/opds.py tests/test_opds.py
git commit -m "feat(opds): sinh feed OPDS 1.2 Atom (navigation + acquisition)"
```

---

### Task 5: Route OPDS — feed, tải EPUB, ảnh bìa

**Files:**
- Create: `app/routes/opds.py`
- Modify: `app/main.py`
- Test: `tests/test_opds_routes.py`

**Interfaces:**
- Consumes: `novel2epub.opds.{OpdsBook, navigation_feed, acquisition_feed, iso_utc, NAV_TYPE, ACQ_TYPE}`, `app.auth.require_api_auth`, `app.deps.{library, resolved_cfg}`, `novel2epub.storage.Storage`
- Produces: `app.routes.opds.router` — `GET /opds`, `GET /opds/books`, `GET /opds/download/{slug}.epub`, `GET /opds/cover/{slug}`; helper `_epub_path(cfg) -> Path`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_opds_routes.py`:

```python
"""Route OPDS: chỉ liệt kê sách đã build, mã lỗi đúng, xác thực đúng chỗ."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from novel2epub.config import (
    ApiConfig,
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage

ATOM = "http://www.w3.org/2005/Atom"


def _cfg(tmp_path, slug: str, *, epub_name: str = "", token: str = "") -> Config:
    return Config(
        novel=NovelConfig(slug=slug, title=f"Tên {slug}", author="Tác Giả"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path), epub_path=epub_name),
        api=ApiConfig(token=token),
    )


def _seed_ebook(tmp_path, slug: str, *, with_epub: bool, cover: bytes | None = None):
    storage = Storage(tmp_path, slug)
    storage.save_manifest(
        Manifest(slug=slug, title=f"Tên {slug}", author="Tác Giả",
                 chapters=[Chapter(index=1, url="http://x/1", title="C1")])
    )
    if cover is not None:
        storage.save_cover_bytes(cover, "jpg")
    if with_epub:
        (tmp_path / f"{slug}.epub").write_bytes(b"PK\x03\x04gia-lap-epub")
    return storage


def _client(monkeypatch, tmp_path, slugs: list[str], *, token: str = "", host: str = "127.0.0.1"):
    from app import deps
    from app.main import app
    from novel2epub.config import LibraryConfig

    cfgs = {s: _cfg(tmp_path, s, epub_name=str(tmp_path / f"{s}.epub"), token=token)
            for s in slugs}
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig(ebooks={s: object() for s in slugs}))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfgs[slug])
    monkeypatch.setattr(deps, "cfg", lambda: next(iter(cfgs.values())))
    monkeypatch.setattr("app.routes.opds.archived_slugs", lambda _p: set())
    return TestClient(app, client=(host, 12345))


def test_feed_goc_tra_atom_va_content_type_navigation(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds")
    assert r.status_code == 200
    assert "kind=navigation" in r.headers["content-type"]
    assert ET.fromstring(r.text).tag == f"{{{ATOM}}}feed"


def test_feed_books_liet_ke_sach_da_build(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/books")
    assert r.status_code == 200
    assert "kind=acquisition" in r.headers["content-type"]
    titles = [e.text for e in ET.fromstring(r.text).findall(f"{{{ATOM}}}entry/{{{ATOM}}}title")]
    assert titles == ["Tên a"]


def test_sach_chua_build_epub_khong_xuat_hien(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    _seed_ebook(tmp_path, "b", with_epub=False)
    r = _client(monkeypatch, tmp_path, ["a", "b"]).get("/opds/books")
    titles = [e.text for e in ET.fromstring(r.text).findall(f"{{{ATOM}}}entry/{{{ATOM}}}title")]
    assert titles == ["Tên a"]


def test_sach_da_archive_khong_xuat_hien(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    _seed_ebook(tmp_path, "b", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a", "b"])
    monkeypatch.setattr("app.routes.opds.archived_slugs", lambda _p: {"b"})
    titles = [e.text for e in ET.fromstring(client.get("/opds/books").text)
              .findall(f"{{{ATOM}}}entry/{{{ATOM}}}title")]
    assert titles == ["Tên a"]


def test_tai_epub_tra_dung_byte_va_media_type(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/download/a.epub")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    assert r.content == b"PK\x03\x04gia-lap-epub"


def test_tai_epub_chua_build_tra_404(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=False)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/download/a.epub")
    assert r.status_code == 404


def test_bia_tra_dung_byte(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True, cover=b"\xff\xd8\xff-gia-lap-jpg")
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/cover/a")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff-gia-lap-jpg"


def test_khong_co_bia_tra_404_va_feed_khong_phat_link_anh(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True, cover=None)
    client = _client(monkeypatch, tmp_path, ["a"])
    assert client.get("/opds/cover/a").status_code == 404
    entry = ET.fromstring(client.get("/opds/books").text).find(f"{{{ATOM}}}entry")
    rels = {ln.get("rel") for ln in entry.findall(f"{{{ATOM}}}link")}
    assert "http://opds-spec.org/image" not in rels


def test_ebook_khong_ton_tai_tra_404(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/download/khong-co.epub")
    assert r.status_code == 404


# ---------- xác thực ----------


def test_may_khac_khong_co_token_tra_401(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    r = client.get("/opds")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_chua_cau_hinh_token_tra_503(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a"], token="", host="192.168.1.20")
    assert client.get("/opds").status_code == 503


def test_moi_endpoint_opds_deu_duoc_bao_ve(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True, cover=b"x")
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    for path in ("/opds", "/opds/books", "/opds/download/a.epub", "/opds/cover/a"):
        assert client.get(path).status_code == 401, path


def test_url_trong_feed_dung_host_ma_client_da_goi(monkeypatch, tmp_path):
    # readest trên điện thoại gọi bằng IP LAN — link trong feed phải là IP đó,
    # không phải localhost, nếu không nó tải về chính cái điện thoại.
    _seed_ebook(tmp_path, "a", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a"])
    r = client.get("/opds/books", headers={"Host": "192.168.1.9:8010"})
    assert "http://192.168.1.9:8010/opds/download/a.epub" in r.text
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_opds_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routes.opds'`

- [ ] **Step 3: Viết implementation tối thiểu**

Tạo `app/routes/opds.py`:

```python
"""Catalog OPDS cho trình đọc ngoài (readest) + phục vụ file EPUB và ảnh bìa.

Chỉ liệt kê ebook ĐÃ BUILD EPUB. Ebook chưa build thì vắng mặt hẳn — thà
không thấy còn hơn thấy rồi bấm tải về báo lỗi. EPUB cũ hơn bản dịch vẫn
được phục vụ nguyên trạng: build lại là việc của trang Tự động hoá, không
phải của một request HTTP (ebook lớn nhất 2907 chương, build trong request
sẽ treo).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from novel2epub import opds
from novel2epub.library_state import archived_slugs
from novel2epub.storage import Storage

from .. import deps
from ..auth import require_api_auth

router = APIRouter(dependencies=[Depends(require_api_auth)])

_MEDIA_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _epub_path(cfg) -> Path:
    """Đường dẫn tuyệt đối tới file EPUB của một ebook."""
    return Path(cfg.epub_path).resolve()


def _xml(body: str, media_type: str) -> Response:
    return Response(content=body, media_type=media_type)


def _cover_media_type(ext: str) -> str:
    return _MEDIA_BY_EXT.get(ext.lower().lstrip("."), "image/jpeg")


def _ebook_or_404(slug: str):
    """(cfg, storage) của ebook, hoặc 404."""
    if slug not in deps.library().ebooks:
        raise HTTPException(status_code=404, detail="Không tìm thấy ebook.")
    cfg = deps.resolved_cfg(slug)
    return cfg, Storage(cfg.output.data_dir, cfg.novel.slug)


def _collect_books() -> list[opds.OpdsBook]:
    """Các ebook đủ điều kiện lên feed: chưa archive VÀ đã có file EPUB."""
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    books: list[opds.OpdsBook] = []
    for slug in deps.library().ebooks:
        if slug in archived:
            continue
        cfg = deps.resolved_cfg(slug)
        epub = _epub_path(cfg)
        if not epub.exists():
            continue
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        cover = storage.read_cover_bytes()
        novel = cfg.novel
        books.append(
            opds.OpdsBook(
                slug=slug,
                title=novel.title or (manifest.title if manifest else "") or slug,
                author=novel.author or (manifest.author if manifest else ""),
                description=novel.description or (manifest.description if manifest else ""),
                language=novel.language or "vi",
                identifier=novel.identifier,
                publisher=novel.publisher,
                pubdate=novel.pubdate,
                subjects=list(novel.subjects or []),
                # mtime của FILE, không phải của bản dịch — readest tải lại
                # dựa vào trường này và thứ nó tải là file.
                updated=opds.iso_utc(epub.stat().st_mtime),
                has_cover=cover is not None,
                cover_type=_cover_media_type(cover[1]) if cover else "image/jpeg",
            )
        )
    return books


@router.get("/opds")
def opds_root(request: Request) -> Response:
    """Feed điều hướng gốc — URL người dùng dán vào readest."""
    base = str(request.base_url).rstrip("/")
    body = opds.navigation_feed(base_url=base, updated=opds.iso_utc(_now()))
    return _xml(body, opds.NAV_TYPE)


@router.get("/opds/books")
def opds_books(request: Request) -> Response:
    """Feed acquisition — mỗi ebook đã build một entry."""
    base = str(request.base_url).rstrip("/")
    books = _collect_books()
    updated = max((b.updated for b in books), default=opds.iso_utc(_now()))
    body = opds.acquisition_feed(books, base_url=base, updated=updated)
    return _xml(body, opds.ACQ_TYPE)


@router.get("/opds/download/{slug}.epub")
def opds_download(slug: str) -> Response:
    cfg, _storage = _ebook_or_404(slug)
    epub = _epub_path(cfg)
    if not epub.exists():
        raise HTTPException(status_code=404, detail="Chưa build EPUB cho ebook này.")
    return Response(
        content=epub.read_bytes(),
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.epub"'},
    )


@router.get("/opds/cover/{slug}")
def opds_cover(slug: str) -> Response:
    _cfg, storage = _ebook_or_404(slug)
    cover = storage.read_cover_bytes()
    if cover is None:
        raise HTTPException(status_code=404, detail="Ebook chưa có ảnh bìa.")
    content, ext = cover
    return Response(content=content, media_type=_cover_media_type(ext))
```

Thêm helper thời gian ở đầu module (sau phần import):

```python
import time


def _now() -> float:
    return time.time()
```

Kiểm tra tên thật của hàm đọc danh sách ebook đã archive trước khi viết import — chạy:

```bash
grep -rn "def archived_slugs" novel2epub/
```

Nếu nó không nằm ở `novel2epub/library_state.py`, sửa dòng import cho khớp. Nếu dự án không có hàm đó, thay `_collect_books` bằng cách đọc cột `ebooks.archived` qua `deps.library()`.

Trong `app/main.py`, thêm `opds` vào khối import router và thêm dòng mount:

```python
app.include_router(opds.router)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_opds_routes.py -v`
Expected: PASS (13 test)

- [ ] **Step 5: Commit**

```bash
git add app/routes/opds.py app/main.py tests/test_opds_routes.py
git commit -m "feat(opds): route catalog, tải EPUB và ảnh bìa"
```

---

### Task 6: Neo đoạn văn trong EPUB

Đây là task khó nhất. Thứ duy nhất chứng minh nó đúng là so trực tiếp với `notes.split_paras`.

**Files:**
- Modify: `novel2epub/epub_builder.py` (`_md_to_xhtml_body`, `build_epub`)
- Modify: `novel2epub/pipeline.py` (`step_build_selected`)
- Test: `tests/test_epub_anchors.py`

**Interfaces:**
- Consumes: `novel2epub.notes.split_paras`
- Produces:
  - `epub_builder._md_to_xhtml_body(md: str, *, anchored: bool = False) -> str`
  - `epub_builder.build_epub(..., anchored_stems: set[str] | None = None) -> Path`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_epub_anchors.py`:

```python
"""Neo đoạn văn trong EPUB — `data-n2e-p` phải khớp CHÍNH XÁC notes.split_paras.

Đây là bất biến nền của cả tính năng sửa từ readest: neo cho biết ĐOẠN NÀO,
còn `notes.replace_para` ghi theo đúng chỉ số đó. Lệch một bậc là sửa nhầm đoạn.
"""
from __future__ import annotations

import re

from novel2epub.epub_builder import _md_to_xhtml_body
from novel2epub.notes import split_paras


def _anchors(html: str) -> list[int]:
    return [int(n) for n in re.findall(r'data-n2e-p="(\d+)"', html)]


def _anchored_text(html: str, index: int) -> str:
    m = re.search(rf'data-n2e-p="{index}"[^>]*>(.*?)<', html, re.S)
    return m.group(1) if m else ""


def test_khong_bat_thi_khong_co_neo_nao():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    assert _anchors(_md_to_xhtml_body(md)) == []
    assert "data-n2e-p" not in _md_to_xhtml_body(md, anchored=False)


def test_neo_danh_so_lien_tuc_tu_0():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    assert _anchors(_md_to_xhtml_body(md, anchored=True)) == [0, 1, 2]


def test_so_luong_neo_bang_so_doan_cua_split_paras():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai.\n\nĐoạn ba."
    html = _md_to_xhtml_body(md, anchored=True)
    assert _anchors(html) == list(range(len(split_paras(md))))


def test_heading_cung_duoc_dem_vao_chi_so():
    # split_paras GIỮ dòng heading, nên bộ đếm phải tính nó — bỏ qua là lệch
    # toàn bộ chương một bậc.
    md = "# Chương 1\n\nĐoạn một."
    html = _md_to_xhtml_body(md, anchored=True)
    assert 'data-n2e-p="0"' in html
    assert "<h2" in html
    assert split_paras(md)[0] == "# Chương 1"


def test_block_nhieu_dong_moi_dong_mot_neo():
    # ĐÂY là ca đã làm hai định nghĩa đoạn lệch nhau trong dữ liệu thật
    # (161 dòng-không-rỗng vs 160 block). Đếm theo DÒNG mới đúng.
    md = "Dòng một\nDòng hai\n\nĐoạn sau"
    html = _md_to_xhtml_body(md, anchored=True)
    assert len(split_paras(md)) == 3
    assert _anchors(html) == [0, 1, 2]
    assert html.count("<p>") == 2  # hình thức hiển thị KHÔNG đổi
    assert "<br/>" in html


def test_giu_nguyen_cach_hien_thi_khi_bat_neo():
    md = "Dòng một\nDòng hai\n\nĐoạn sau"
    plain = _md_to_xhtml_body(md)
    anchored = _md_to_xhtml_body(md, anchored=True)
    assert re.sub(r'<span data-n2e-p="\d+">|</span>|\sdata-n2e-p="\d+"', "", anchored) == plain


def test_neo_khop_split_paras_tren_moi_kieu_xuong_dong():
    for md in (
        "# T\n\nA\n\nB",
        "# T\nA\nB",
        "A\n\n\n\nB",
        "A\n  \nB",
        "Dòng một\nDòng hai\n\nC\nD\n\nE",
        "  \n\n# T\n\nA\n\n  ",
    ):
        html = _md_to_xhtml_body(md, anchored=True)
        assert _anchors(html) == list(range(len(split_paras(md)))), md


def test_noi_dung_tai_neo_khop_doan_tuong_ung():
    md = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai."
    html = _md_to_xhtml_body(md, anchored=True)
    paras = split_paras(md)
    assert _anchored_text(html, 1) == paras[1]
    assert _anchored_text(html, 2) == paras[2]


def test_ky_tu_dac_biet_van_duoc_escape_khi_co_neo():
    md = "A & B < C"
    html = _md_to_xhtml_body(md, anchored=True)
    assert "&amp;" in html and "&lt;" in html
    assert 'data-n2e-p="0"' in html


def test_footnote_khong_lam_lech_chi_so():
    from novel2epub import footnotes

    md = "# Chương 1\n\nTrang Quốc là nơi đó.\n\nĐoạn sau."
    marked, fns = footnotes.annotate(md, {"Trang Quốc": "nước hư cấu"})
    assert fns  # phải có footnote thì test mới có ý nghĩa
    # annotate chỉ CHÈN ký tự inline, không thêm/bớt dòng.
    assert len(split_paras(marked)) == len(split_paras(md))
    assert _anchors(_md_to_xhtml_body(marked, anchored=True)) == [0, 1, 2]
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_epub_anchors.py -v`
Expected: FAIL — `TypeError: _md_to_xhtml_body() got an unexpected keyword argument 'anchored'`

- [ ] **Step 3: Sửa `_md_to_xhtml_body`**

Trong `novel2epub/epub_builder.py`, thay toàn bộ hàm:

```python
def _md_to_xhtml_body(md: str, *, anchored: bool = False) -> str:
    """Chuyển markdown đơn giản -> các đoạn <p>/<h2> (escape an toàn).

    Placeholder footnote (ký tự PUA) được giữ qua html.escape rồi đổi thành <sup>.

    `anchored=True` gắn thêm `data-n2e-p="<chỉ số>"` cho từng đoạn, để trình
    đọc ngoài (readest) định vị được đoạn mà gọi API sửa. Chỉ số đếm theo
    DÒNG-KHÔNG-RỖNG xuyên suốt cả chương, kể cả heading — khớp chính xác
    `notes.split_paras`, tức là thứ `notes.replace_para` dùng để ghi. Đếm theo
    block cách-dòng-trống (cách hàm này tách khối) sẽ lệch ở chương có block
    nhiều dòng, và mọi lần sửa sau đó ghi nhầm đoạn.

    Hình thức hiển thị KHÔNG đổi khi bật neo: vẫn một <p> cho mỗi block, các
    dòng trong block vẫn nối bằng <br/>. Neo bọc trong <span> chứ không tách
    thành nhiều <p> để không đổi thụt đầu dòng và giãn cách của mọi EPUB cũ.
    """
    blocks: list[str] = []
    para_index = 0
    for block in re.split(r"\n\s*\n", md.strip()):
        block = block.strip()
        if not block:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", block)
        if heading:
            inner = _markers_to_html(html.escape(heading.group(1).strip()))
            attr = f' data-n2e-p="{para_index}"' if anchored else ""
            blocks.append(f"<h2{attr}>{inner}</h2>")
            para_index += 1
            continue
        # Gộp các dòng trong cùng đoạn, xuống dòng -> <br/>
        rendered: list[str] = []
        for line in block.splitlines():
            if not line.strip():
                continue
            inner = _markers_to_html(html.escape(line.strip()))
            if anchored:
                inner = f'<span data-n2e-p="{para_index}">{inner}</span>'
            rendered.append(inner)
            para_index += 1
        blocks.append("<p>" + "<br/>".join(rendered) + "</p>")
    return "\n".join(blocks)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_epub_anchors.py -v`
Expected: PASS (10 test)

- [ ] **Step 5: Cho `build_epub` nhận `anchored_stems`**

Trong `novel2epub/epub_builder.py`, thêm tham số vào chữ ký `build_epub` (ngay sau `metadata`):

```python
    metadata: NovelConfig | None = None,
    anchored_stems: set[str] | None = None,
) -> Path:
```

Bổ sung vào docstring:

```
    `anchored_stems` (tùy chọn): tập `ch.stem` được gắn neo `data-n2e-p`.
    CHỈ truyền stem của chương có BẢN DỊCH — chương rơi về `raw_text` chứa
    văn bản Hán gốc, mà API sửa lại ghi vào `translated_text`; gắn neo cho
    chúng là mời người dùng sửa nhầm cột.
```

Ngay dưới `footnotes_by_stem = footnotes_by_stem or {}`, thêm:

```python
    anchored_stems = anchored_stems or set()
```

Trong vòng lặp chương, đổi dòng dựng body:

```python
        body = _md_to_xhtml_body(md, anchored=ch.stem in anchored_stems)
```

- [ ] **Step 6: Cho pipeline tính `anchored_stems`**

Trong `novel2epub/pipeline.py`, hàm `step_build_selected`: khai báo tập rỗng cạnh `footnotes_by_stem`:

```python
    footnotes_by_stem: dict[str, list[dict]] = {}
    anchored_stems: set[str] = set()
```

Trong vòng lặp chương, ở nhánh `if storage.has_translated(ch):`, thêm ngay sau `md = storage.read_translated(ch)`:

```python
            anchored_stems.add(ch.stem)
```

Truyền vào lời gọi `build_epub`:

```python
        footnotes_by_stem=footnotes_by_stem,
        metadata=cfg.novel,
        anchored_stems=anchored_stems,
    )
```

- [ ] **Step 7: Thêm test cho quy tắc "chương chưa dịch không có neo"**

Thêm vào cuối `tests/test_epub_anchors.py`:

```python
def test_chi_chuong_da_dich_moi_duoc_gan_neo(tmp_path):
    """Chương rơi về raw_text (Hán gốc) tuyệt đối không được có neo — API sửa
    ghi vào translated_text, gắn neo là mời sửa nhầm cột."""
    import zipfile

    from novel2epub.pipeline import step_build_selected
    from novel2epub.storage import Chapter, Manifest, Storage
    from tests.test_opds_routes import _cfg  # dựng Config tối thiểu

    storage = Storage(tmp_path, "t")
    da_dich = Chapter(index=1, url="http://x/1", title="Đã dịch")
    chua_dich = Chapter(index=2, url="http://x/2", title="Chưa dịch")
    storage.save_manifest(Manifest(slug="t", title="T", chapters=[da_dich, chua_dich]))
    storage.write_translated(da_dich, "# Đã dịch\n\nĐoạn tiếng Việt.")
    storage.mark_translated_complete(da_dich)
    storage.write_raw(chua_dich, "# 第二章\n\n这是中文。")

    cfg = _cfg(tmp_path, "t", epub_name=str(tmp_path / "t.epub"))
    step_build_selected(cfg, log=lambda _m: None)

    with zipfile.ZipFile(tmp_path / "t.epub") as z:
        names = [n for n in z.namelist() if n.endswith(".xhtml")]
        bodies = {n: z.read(n).decode("utf-8") for n in names}

    co_neo = [n for n, b in bodies.items() if "data-n2e-p" in b]
    assert any("0001" in n for n in co_neo)
    assert not any("0002" in n for n in co_neo)
```

Nếu `Storage` không có `write_raw`/`mark_translated_complete` với đúng tên đó, chạy `grep -n "def write_raw\|def mark_translated_complete" novel2epub/storage.py` và sửa lời gọi cho khớp.

- [ ] **Step 8: Chạy test + toàn bộ suite**

Run: `pytest tests/test_epub_anchors.py -v`
Expected: PASS (11 test)

Run: `pytest tests -q`
Expected: PASS — `tests/test_pipeline_meta.py` phải chạy nguyên trạng vì `anchored_stems` có giá trị mặc định.

- [ ] **Step 9: Commit**

```bash
git add novel2epub/epub_builder.py novel2epub/pipeline.py tests/test_epub_anchors.py
git commit -m "feat(epub): neo data-n2e-p theo chỉ số split_paras cho chương đã dịch"
```

---

### Task 7: API đọc và sửa đoạn văn

**Files:**
- Modify: `app/routes/opds.py`
- Test: `tests/test_paragraph_api.py`

**Interfaces:**
- Consumes: `novel2epub.notes.{split_paras, replace_para}`, `app.routes.opds._ebook_or_404`
- Produces:
  - `GET /api/v1/ebooks/{slug}/chapters/{idx}` → `{"slug", "index", "title", "paragraphs": [{"index", "text"}]}`
  - `PATCH /api/v1/ebooks/{slug}/chapters/{idx}/paragraphs/{para_index}` body `{"text", "expected"}` → `{"ok", "index", "text"}`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_paragraph_api.py`:

```python
"""API đọc/sửa đoạn văn — nền cho việc sửa từ readest ở giai đoạn 2."""
from __future__ import annotations

from novel2epub.storage import Chapter, Manifest, Storage

from .test_opds_routes import _client

MD = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai.\n\nĐoạn ba."


def _seed(tmp_path, slug: str = "a", *, translated: str = MD):
    storage = Storage(tmp_path, slug)
    ch = Chapter(index=1, url="http://x/1", title="C1")
    storage.save_manifest(Manifest(slug=slug, title=f"Tên {slug}", chapters=[ch]))
    if translated:
        storage.write_translated(ch, translated)
        storage.mark_translated_complete(ch)
    return storage, ch


def test_get_tra_ve_danh_sach_doan_kem_chi_so(monkeypatch, tmp_path):
    _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/api/v1/ebooks/a/chapters/1")
    assert r.status_code == 200
    data = r.json()
    assert data["index"] == 1
    assert [p["index"] for p in data["paragraphs"]] == [0, 1, 2, 3]
    assert data["paragraphs"][1]["text"] == "Đoạn một."


def test_get_chuong_khong_ton_tai_tra_404(monkeypatch, tmp_path):
    _seed(tmp_path)
    assert _client(monkeypatch, tmp_path, ["a"]).get(
        "/api/v1/ebooks/a/chapters/99"
    ).status_code == 404


def test_patch_sua_dung_doan_va_khong_dong_doan_khac(monkeypatch, tmp_path):
    storage, ch = _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/2",
        json={"text": "Đoạn hai đã sửa.", "expected": "Đoạn hai."},
    )
    assert r.status_code == 200
    from novel2epub.notes import split_paras

    paras = split_paras(storage.read_translated(ch))
    assert paras == ["# Chương 1", "Đoạn một.", "Đoạn hai đã sửa.", "Đoạn ba."]


def test_patch_sai_expected_tra_409_kem_noi_dung_hien_tai(monkeypatch, tmp_path):
    storage, ch = _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/2",
        json={"text": "X", "expected": "Nội dung cũ đã lỗi thời."},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["current"] == "Đoạn hai."
    # KHÔNG được ghi gì
    assert "Đoạn hai." in storage.read_translated(ch)


def test_patch_chi_so_vuot_pham_vi_tra_409(monkeypatch, tmp_path):
    _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/99",
        json={"text": "X", "expected": "Y"},
    )
    assert r.status_code == 409


def test_patch_text_rong_tra_400_va_khong_xoa_doan(monkeypatch, tmp_path):
    # replace_para khi nhận rỗng sẽ XOÁ dòng rồi đánh lại chỉ số các đoạn sau —
    # client giữ chỉ số cũ sẽ sửa nhầm ở lần gọi kế tiếp.
    storage, ch = _seed(tmp_path)
    for payload in ({"text": "", "expected": "Đoạn hai."},
                    {"text": "   ", "expected": "Đoạn hai."}):
        r = _client(monkeypatch, tmp_path, ["a"]).patch(
            "/api/v1/ebooks/a/chapters/1/paragraphs/2", json=payload
        )
        assert r.status_code == 400
    assert "Đoạn hai." in storage.read_translated(ch)


def test_patch_chuong_chua_dich_tra_404(monkeypatch, tmp_path):
    _seed(tmp_path, translated="")
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/0",
        json={"text": "X", "expected": "Y"},
    )
    assert r.status_code == 404


def test_api_sua_duoc_bao_ve_boi_token(monkeypatch, tmp_path):
    _seed(tmp_path)
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    assert client.get("/api/v1/ebooks/a/chapters/1").status_code == 401
    assert client.patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/1",
        json={"text": "X", "expected": "Y"},
    ).status_code == 401


def test_bearer_token_dung_thi_sua_duoc(monkeypatch, tmp_path):
    storage, ch = _seed(tmp_path)
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    r = client.patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/1",
        json={"text": "Đoạn một đã sửa.", "expected": "Đoạn một."},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    assert "Đoạn một đã sửa." in storage.read_translated(ch)
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_paragraph_api.py -v`
Expected: FAIL — 404 trên mọi route `/api/v1/...` vì chưa đăng ký

- [ ] **Step 3: Viết implementation tối thiểu**

Thêm vào `app/routes/opds.py` — import ở đầu file:

```python
from pydantic import BaseModel

from novel2epub.notes import replace_para, split_paras
```

Rồi thêm ở cuối file:

```python
class ParagraphPatch(BaseModel):
    """Thân request sửa một đoạn.

    `expected` PHẢI lấy từ `GET .../chapters/{idx}`, KHÔNG được lấy từ DOM của
    trang đang đọc: văn bản trong EPUB đã qua html.escape và marker footnote đã
    thành <sup>, nên không bao giờ khớp bản trong DB.
    """
    text: str
    expected: str


def _chapter_or_404(slug: str, idx: int):
    """(storage, chapter) của một chương, hoặc 404."""
    _cfg, storage = _ebook_or_404(slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == idx), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return storage, ch


@router.get("/api/v1/ebooks/{slug}/chapters/{idx}")
def api_chapter(slug: str, idx: int) -> dict:
    """Các đoạn của một chương kèm chỉ số — nguồn `expected` cho PATCH."""
    storage, ch = _chapter_or_404(slug, idx)
    translated = storage.read_translated(ch)
    paras = split_paras(translated)
    return {
        "slug": slug,
        "index": idx,
        "title": ch.title or f"Chương {idx}",
        "paragraphs": [{"index": i, "text": p} for i, p in enumerate(paras)],
    }


@router.patch("/api/v1/ebooks/{slug}/chapters/{idx}/paragraphs/{para_index}")
def api_patch_paragraph(slug: str, idx: int, para_index: int, body: ParagraphPatch) -> dict:
    """Thay toàn bộ một đoạn. Chống ghi đè bằng `expected`.

    Không cho `text` rỗng: `replace_para` khi nhận rỗng sẽ xoá hẳn dòng rồi
    đánh lại chỉ số mọi đoạn phía sau, mà client vẫn giữ chỉ số cũ. Xoá đoạn
    chỉ làm ở web UI, nơi trang tự tải lại sau mỗi thao tác.
    """
    storage, ch = _chapter_or_404(slug, idx)
    if not body.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Không xoá đoạn qua API — dùng trang biên tập trên web.",
        )
    if not storage.has_translated(ch):
        raise HTTPException(status_code=404, detail="Chương chưa có bản dịch.")

    translated = storage.read_translated(ch)
    updated, error = replace_para(translated, para_index, body.expected, body.text)
    if updated is None:
        paras = split_paras(translated)
        current = paras[para_index] if 0 <= para_index < len(paras) else ""
        raise HTTPException(status_code=409, detail={"error": error, "current": current})

    storage.write_translated(ch, updated)
    return {"ok": True, "index": para_index, "text": split_paras(updated)[para_index]}
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_paragraph_api.py -v`
Expected: PASS (9 test)

- [ ] **Step 5: Commit**

```bash
git add app/routes/opds.py tests/test_paragraph_api.py
git commit -m "feat(api): đọc và sửa từng đoạn văn qua /api/v1"
```

---

### Task 8: Test khứ hồi — chứng minh neo thật sự hoạt động

Các test trước chỉ chứng minh từng mảnh rời. Đây là test duy nhất chứng minh cả chuỗi.

**Files:**
- Test: `tests/test_opds_roundtrip.py`

**Interfaces:**
- Consumes: `pipeline.step_build_selected`, `app.routes.opds` API, `novel2epub.notes.split_paras`

- [ ] **Step 1: Viết test khứ hồi**

Tạo `tests/test_opds_roundtrip.py`:

```python
"""Khứ hồi: build EPUB -> đọc neo từ XHTML -> PATCH qua API -> soi lại DB.

Test quan trọng nhất của cả tính năng. Nó bắt đúng lớp lỗi mà các test đơn lẻ
bỏ sót: neo đúng trong EPUB nhưng lệch so với chỉ số mà `replace_para` dùng.
Phải bao cả chương có block nhiều dòng và chương có footnote — hai chỗ mà hai
định nghĩa đoạn từng lệch nhau.
"""
from __future__ import annotations

import re
import zipfile

from novel2epub.notes import split_paras
from novel2epub.pipeline import step_build_selected
from novel2epub.storage import Chapter, Manifest, Storage

from .test_opds_routes import _cfg, _client

# Chương cố ý có block nhiều dòng (đoạn 2 và 3 dính chung một block) — đúng
# hình dạng đã làm dòng-không-rỗng (161) lệch khỏi block (160) trong dữ liệu thật.
MD = (
    "# Chương 1\n\n"
    "Đoạn mở đầu.\n\n"
    "Dòng thoại một\nDòng thoại hai\n\n"
    "Trang Quốc là nơi đó.\n\n"
    "Đoạn kết."
)


def _build(tmp_path):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="Chương 1")
    storage.save_manifest(Manifest(slug="t", title="Truyện T", chapters=[ch]))
    storage.write_translated(ch, MD)
    storage.mark_translated_complete(ch)
    storage.write_glossary_file("names.txt", "Trang Quốc = Trang Quốc | nước hư cấu\n")
    cfg = _cfg(tmp_path, "t", epub_name=str(tmp_path / "t.epub"))
    step_build_selected(cfg, log=lambda _m: None)
    return storage, ch


def _chapter_xhtml(epub_path) -> str:
    with zipfile.ZipFile(epub_path) as z:
        name = next(n for n in z.namelist() if n.endswith("chap_0001.xhtml"))
        return z.read(name).decode("utf-8")


def test_neo_trong_epub_khop_chi_so_cua_split_paras(tmp_path):
    _build(tmp_path)
    xhtml = _chapter_xhtml(tmp_path / "t.epub")
    anchors = [int(n) for n in re.findall(r'data-n2e-p="(\d+)"', xhtml)]
    assert anchors == list(range(len(split_paras(MD))))


def test_sua_theo_neo_lay_tu_epub_doi_dung_doan_do(monkeypatch, tmp_path):
    storage, ch = _build(tmp_path)
    xhtml = _chapter_xhtml(tmp_path / "t.epub")

    # Đường đi của client thật: tìm neo trong EPUB, rồi lấy `expected` từ API
    # (KHÔNG lấy từ EPUB — bản trong EPUB đã escape và có <sup> footnote).
    target = int(re.search(r'data-n2e-p="(\d+)"[^>]*>Dòng thoại hai<', xhtml).group(1))

    client = _client(monkeypatch, tmp_path, ["t"])
    paragraphs = client.get("/api/v1/ebooks/t/chapters/1").json()["paragraphs"]
    expected = paragraphs[target]["text"]
    assert expected == "Dòng thoại hai"

    r = client.patch(
        f"/api/v1/ebooks/t/chapters/1/paragraphs/{target}",
        json={"text": "Dòng thoại hai ĐÃ SỬA", "expected": expected},
    )
    assert r.status_code == 200

    truoc = split_paras(MD)
    sau = split_paras(storage.read_translated(ch))
    assert sau[target] == "Dòng thoại hai ĐÃ SỬA"
    # Không đoạn nào khác động.
    assert len(sau) == len(truoc)
    for i, (a, b) in enumerate(zip(truoc, sau)):
        if i != target:
            assert a == b, f"đoạn {i} bị đổi ngoài ý muốn"


def test_neo_van_dung_o_doan_co_footnote(monkeypatch, tmp_path):
    storage, ch = _build(tmp_path)
    xhtml = _chapter_xhtml(tmp_path / "t.epub")
    assert "<sup" in xhtml  # footnote đã được chèn, test mới có ý nghĩa

    client = _client(monkeypatch, tmp_path, ["t"])
    paragraphs = client.get("/api/v1/ebooks/t/chapters/1").json()["paragraphs"]
    target = next(p["index"] for p in paragraphs if "Trang Quốc" in p["text"])

    r = client.patch(
        f"/api/v1/ebooks/t/chapters/1/paragraphs/{target}",
        json={"text": "Đã sửa đoạn có footnote.", "expected": paragraphs[target]["text"]},
    )
    assert r.status_code == 200
    assert split_paras(storage.read_translated(ch))[target] == "Đã sửa đoạn có footnote."


def test_sua_xong_build_lai_thi_neo_van_lien_tuc(tmp_path, monkeypatch):
    storage, ch = _build(tmp_path)
    client = _client(monkeypatch, tmp_path, ["t"])
    paragraphs = client.get("/api/v1/ebooks/t/chapters/1").json()["paragraphs"]
    client.patch(
        "/api/v1/ebooks/t/chapters/1/paragraphs/1",
        json={"text": "Mở đầu mới.", "expected": paragraphs[1]["text"]},
    )
    cfg = _cfg(tmp_path, "t", epub_name=str(tmp_path / "t.epub"))
    step_build_selected(cfg, log=lambda _m: None)

    xhtml = _chapter_xhtml(tmp_path / "t.epub")
    anchors = [int(n) for n in re.findall(r'data-n2e-p="(\d+)"', xhtml)]
    assert anchors == list(range(len(split_paras(storage.read_translated(ch)))))


def test_epub_tai_qua_opds_chinh_la_file_co_neo(monkeypatch, tmp_path):
    _build(tmp_path)
    client = _client(monkeypatch, tmp_path, ["t"])
    r = client.get("/opds/download/t.epub")
    assert r.status_code == 200
    assert r.content == (tmp_path / "t.epub").read_bytes()
```

- [ ] **Step 2: Chạy test**

Run: `pytest tests/test_opds_roundtrip.py -v`
Expected: PASS (5 test)

Nếu `test_neo_van_dung_o_doan_co_footnote` fail vì không có `<sup>`, kiểm tra định dạng dòng glossary bằng `grep -n "def read_glossary_notes" -A 15 novel2epub/storage.py` — chỉ entry CÓ ghi chú (phần sau dấu `|`) mới sinh footnote.

- [ ] **Step 3: Commit**

```bash
git add tests/test_opds_roundtrip.py
git commit -m "test: khứ hồi build EPUB -> neo -> PATCH -> soi DB"
```

---

### Task 9: CORS cho bản readest web

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api_cors.py`

**Interfaces:**
- Consumes: `Config.api.cors_origins`
- Produces: không có API mới

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api_cors.py`:

```python
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
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_api_cors.py -v`
Expected: FAIL — `ImportError: cannot import name '_cors_origins' from 'app.main'`

- [ ] **Step 3: Viết implementation tối thiểu**

Trong `app/main.py`, thêm sau hàm `_load_queue_workers`:

```python
def _cors_origins(path: str | None = None) -> list[str]:
    """Origin được phép gọi chéo — chỉ bản readest WEB cần (Tauri desktop và
    mobile gọi HTTP native, không đi qua CORS).

    "*" bị loại thẳng: kết hợp với credential nó phá luôn ý nghĩa của token,
    và không có tình huống nào ở đây cần nó.
    """
    from novel2epub.config import load_config

    try:
        cfg = load_config(path or WORKSPACE_PATH)
    except Exception:
        return []
    return [o for o in cfg.api.cors_origins if o and o != "*"]
```

Rồi ngay sau `app.add_middleware(GZipMiddleware, minimum_size=500)`:

```python
_ALLOWED_ORIGINS = _cors_origins()
if _ALLOWED_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
```

Lưu ý thứ tự: `_cors_origins` phải được định nghĩa TRƯỚC chỗ gọi. Nếu `_load_queue_workers` nằm dưới `add_middleware`, đặt cả hai hàm lên trên khối middleware.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_api_cors.py -v`
Expected: PASS (3 test)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api_cors.py
git commit -m "feat(api): CORS theo cấu hình cho bản readest web"
```

---

### Task 10: Khối Cài đặt — token, CORS, URL catalog

**Files:**
- Create: `app/templates/settings_api.html`
- Modify: `app/routes/settings.py`
- Modify: `app/templates/settings.html`
- Test: `tests/test_settings_api_block.py`

**Interfaces:**
- Consumes: `config_writer.update_defaults`, `Config.api`
- Produces: `GET /settings/api`, `POST /settings/api`, `POST /settings/api/token` (sinh token mới)

- [ ] **Step 1: Đọc khuôn của khối Reader để bắt chước**

Run:

```bash
sed -n '1,60p' app/templates/settings_reader.html
grep -n "settings_reader\|reader" app/routes/settings.py | head -30
```

Khối `api` là config TOÀN CỤC nên đi qua `config_writer.update_defaults`, giống khối kết nối Reader — không phải `update_ebook`. Bám đúng khuôn route và template đã có ở đó: cùng cách bind form, cùng cách hiện thông báo lưu, cùng cách đánh dấu giá trị mặc định.

- [ ] **Step 2: Viết test thất bại**

Tạo `tests/test_settings_api_block.py`:

```python
"""Khối Cài đặt > API: lưu token/CORS, sinh token, không rò token ra HTML."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app
    from novel2epub.config import LibraryConfig

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    return TestClient(app), db


def test_luu_duoc_token_va_cors(monkeypatch, tmp_path):
    from novel2epub.config import load_config

    client, db = _client(monkeypatch, tmp_path)
    r = client.post(
        "/settings/api",
        data={"token": "tok-moi", "cors_origins": "http://localhost:3000\nhttp://b"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303)
    cfg = load_config(db)
    assert cfg.api.token == "tok-moi"
    assert cfg.api.cors_origins == ["http://localhost:3000", "http://b"]


def test_sinh_token_tao_chuoi_du_dai_va_khac_nhau(monkeypatch, tmp_path):
    from novel2epub.config import load_config

    client, db = _client(monkeypatch, tmp_path)
    client.post("/settings/api/token", follow_redirects=False)
    first = load_config(db).api.token
    client.post("/settings/api/token", follow_redirects=False)
    second = load_config(db).api.token
    assert len(first) >= 32
    assert first != second


def test_trang_cai_dat_hien_url_catalog_opds(monkeypatch, tmp_path):
    client, _db = _client(monkeypatch, tmp_path)
    r = client.get("/settings/api")
    assert r.status_code == 200
    assert "/opds" in r.text


def test_token_khong_nhung_vao_url_catalog(monkeypatch, tmp_path):
    # Bí mật trong URL là bí mật đã lọt vào lịch sử duyệt và log.
    from novel2epub.config_writer import update_defaults

    client, db = _client(monkeypatch, tmp_path)
    update_defaults(db, {"api": {"token": "sieu-bi-mat"}})
    html = client.get("/settings/api").text
    assert "sieu-bi-mat" not in html.split("/opds")[0].split("value=")[-1] or True
    for line in html.splitlines():
        if "/opds" in line:
            assert "sieu-bi-mat" not in line
```

- [ ] **Step 3: Chạy test để chắc chắn nó fail**

Run: `pytest tests/test_settings_api_block.py -v`
Expected: FAIL — 404 vì `/settings/api` chưa tồn tại

- [ ] **Step 4: Viết route**

Trong `app/routes/settings.py`, thêm (bám đúng khuôn của route khối Reader vừa đọc ở Step 1):

```python
@router.get("/settings/api")
def settings_api(request: Request):
    """Khối cấu hình truy cập ngoài: token, CORS, URL catalog OPDS."""
    cfg = deps.cfg()
    return deps.templates.TemplateResponse(
        request,
        "settings_api.html",
        {
            "api": cfg.api,
            # Địa chỉ đúng như client đang gọi — nếu người dùng mở trang này
            # bằng IP LAN thì URL hiện ra cũng là IP LAN, dán vào readest trên
            # điện thoại là chạy. Hiện "localhost" ở đây là bẫy: trên điện
            # thoại nó trỏ về chính cái điện thoại.
            "opds_url": str(request.base_url).rstrip("/") + "/opds",
        },
    )


@router.post("/settings/api")
def settings_api_save(
    token: str = Form(""),
    cors_origins: str = Form(""),
):
    origins = [line.strip() for line in cors_origins.splitlines() if line.strip()]
    update_defaults(
        deps.WORKSPACE_PATH,
        {"api": {"token": token.strip(), "cors_origins": origins}},
    )
    return RedirectResponse(url="/settings/api", status_code=303)


@router.post("/settings/api/token")
def settings_api_new_token():
    """Sinh token ngẫu nhiên mới. Token cũ mất hiệu lực ngay — mọi thiết bị
    đã cấu hình phải nhập lại."""
    import secrets

    update_defaults(
        deps.WORKSPACE_PATH, {"api": {"token": secrets.token_urlsafe(32)}}
    )
    return RedirectResponse(url="/settings/api", status_code=303)
```

Kiểm tra `update_defaults`, `Form`, `RedirectResponse` đã được import ở đầu file chưa; thiếu thì thêm.

- [ ] **Step 5: Viết template**

Tạo `app/templates/settings_api.html` theo khuôn `settings_reader.html`, gồm:

- Ô `token` (`type="password"`, có nút hiện/ẩn), kèm nút submit tới `/settings/api/token` để sinh token mới.
- Ô `cors_origins` (`<textarea>`, mỗi origin một dòng), kèm chú thích rằng chỉ bản readest web mới cần.
- Khối chỉ đọc hiện `{{ opds_url }}` kèm nút chép, và một dòng hướng dẫn: dán URL này vào readest, để trống username, điền token vào ô password.
- Một cảnh báo: mở novel2epub ra LAN là mở **toàn bộ** web UI chứ không riêng OPDS.

Thêm liên kết tới khối mới trong `app/templates/settings.html`, cạnh liên kết khối Reader.

- [ ] **Step 6: Chạy test để xác nhận pass**

Run: `pytest tests/test_settings_api_block.py -v`
Expected: PASS (4 test)

- [ ] **Step 7: Commit**

```bash
git add app/routes/settings.py app/templates/settings_api.html app/templates/settings.html tests/test_settings_api_block.py
git commit -m "feat(settings): khối API — token, CORS, URL catalog OPDS"
```

---

### Task 11: Kiểm chứng bằng readest thật + tài liệu

Mọi thứ trước đây chứng minh code khớp *hiểu biết của ta* về readest. Task này kiểm chứng khớp *readest thật*.

**Files:**
- Modify: `docs/operations.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: toàn bộ các task trước

- [ ] **Step 1: Chạy toàn bộ suite**

Run: `pytest tests -v`
Expected: PASS toàn bộ. Không sang bước sau nếu còn test đỏ.

- [ ] **Step 2: Khởi động server và tự kiểm bằng curl**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Ở terminal khác — thay `<IP-LAN>` bằng IP thật của máy và `<TOKEN>` bằng token vừa sinh ở trang Cài đặt:

```bash
curl -s -u ":<TOKEN>" http://<IP-LAN>:8010/opds | head -40
```

Kiểm ba điều:
- Feed là XML hợp lệ và **không có ký tự nào sau `</feed>`**.
- Link trong feed dùng `<IP-LAN>`, không phải `localhost`.
- Bỏ `-u` thì trả **401** kèm header `WWW-Authenticate` (xem bằng `curl -i`), không phải 400 hay 403.

- [ ] **Step 3: Nối bằng readest thật**

Mở readest (web hoặc app), thêm catalog OPDS với URL `http://<IP-LAN>:8010/opds`, username để trống, password là token. Xác nhận:

- Danh sách truyện hiện ra, **có ảnh bìa**.
- Tiêu đề, tác giả, mô tả đúng — nhớ rằng readest **ưu tiên metadata của feed hơn metadata trong EPUB**, nên sai ở feed sẽ đè lên bản đúng trong EPUB.
- Tải một cuốn về và mở đọc được.

Thử luôn trên điện thoại nếu định dùng — đây là kịch bản mạng thật, và là chỗ nhiều khả năng lộ vấn đề nhất.

- [ ] **Step 4: Xác nhận neo còn nguyên trong file readest đã tải**

Lấy file EPUB readest tải về, giải nén một chương và kiểm `data-n2e-p` vẫn còn. Nếu readest xử lý lại file lúc import mà làm mất thuộc tính, đó là phát hiện quan trọng cho giai đoạn 2 — ghi lại vào phần Rủi ro của spec thay vì bỏ qua.

- [ ] **Step 5: Viết tài liệu vận hành**

Thêm mục "Đọc bằng readest qua OPDS" vào `docs/operations.md`:

- Cách sinh token ở Cài đặt > API.
- Chạy `uvicorn app.main:app --host 0.0.0.0 --port 8010` để máy khác với tới được.
- Dán URL, để trống username, token vào ô password.
- **Cảnh báo:** bind `0.0.0.0` mở toàn bộ web UI ra LAN, không riêng OPDS. Ai vào được `/opds` thì cũng vào được `/settings` và `/queue`. Dùng trên mạng không tin cậy thì đặt sau reverse proxy hoặc Tailscale.
- EPUB phải được build trước; ebook chưa build không xuất hiện trong catalog. Sách mới dịch thêm chương thì phải build lại (thủ công hoặc qua Tự động hoá) readest mới thấy bản mới.

Thêm một dòng vào phần tính năng của `README.md` trỏ tới mục đó.

- [ ] **Step 6: Commit**

```bash
git add docs/operations.md README.md
git commit -m "docs: hướng dẫn nối readest qua OPDS"
```

---

## Self-Review

**Spec coverage** — soi từng mục của spec:

| Mục spec | Task |
|---|---|
| §4 `novel2epub/opds.py` | Task 4 |
| §4 `novel2epub/api_auth.py` | Task 2 |
| §4 `app/routes/opds.py` | Task 5, 7 |
| §4 cấu hình khoá `api` riêng | Task 1 |
| §5 neo `data-n2e-p` theo `split_paras` | Task 6 |
| §5 chương chưa dịch không có neo | Task 6 Step 6–7 |
| §5 `anchored_stems` thay vì đổi tuple | Task 6 Step 5 |
| §5 client không lấy `expected` từ EPUB | Task 7 (docstring `ParagraphPatch`), Task 8 (test khứ hồi) |
| §6 feed OPDS 1.2 Atom, 4 endpoint | Task 4, 5 |
| §6 `<updated>` = mtime file EPUB | Task 5 `_collect_books` |
| §6 chưa build / đã archive thì vắng mặt | Task 5 |
| §6 rel ảnh token chính xác, mô tả ở `<summary>` | Task 4 |
| §6 API GET/PATCH đoạn, cấm text rỗng | Task 7 |
| §7 cột `api_json`, schema v8 | Task 1 |
| §7 Basic + Bearer, `compare_digest` | Task 2 |
| §7 401 kèm `WWW-Authenticate` | Task 2, 3 |
| §7 miễn localhost, không đọc `X-Forwarded-For` | Task 3 |
| §7 CORS theo cấu hình, không `*` | Task 9 |
| §7 đặt token ở đâu, URL phải là IP LAN | Task 10 |
| §7 token không vào log | Task 3 (test), Task 10 (test) |
| §8 bảng mã lỗi | Task 3, 5, 7 |
| §9 năm file test + test khứ hồi | Task 1–8 |
| §10 rủi ro #2 thử bằng readest thật | Task 11 |
| §10 rủi ro #5 cảnh báo mở LAN | Task 10 Step 5, Task 11 Step 5 |

Không còn mục nào trống.

**Sai lệch có chủ đích so với spec** — cả hai đã được ghi ngược vào spec:

1. Thêm `app/auth.py` (spec chỉ liệt kê 3 module mới). Tách dependency FastAPI khỏi `routes/opds.py` giữ file route chỉ lo route, và cho phép test xác thực mà không phải dựng cả catalog.
2. `build_epub` nhận `anchored_stems: set[str]` thay vì đổi `chapters_html` sang tuple 4 phần tử. Bám khuôn `footnotes_by_stem` ngay cạnh, và bỏ được cả nhánh tương thích lẫn task dọn dẹp.

**Nhất quán kiểu và tên** — đã đối chiếu: `split_paras`/`replace_para` (từ `novel2epub.notes`), `OpdsBook`/`navigation_feed`/`acquisition_feed`/`iso_utc`/`NAV_TYPE`/`ACQ_TYPE` (Task 4 định nghĩa, Task 5 dùng), `token_from_header`/`token_matches`/`is_local_client`/`WWW_AUTHENTICATE` (Task 2 định nghĩa, Task 3 dùng), `require_api_auth` (Task 3 định nghĩa, Task 5 dùng), `_ebook_or_404`/`_chapter_or_404`/`_epub_path` (Task 5 và 7), `_cfg`/`_client` (Task 5 định nghĩa, Task 7 và 8 import lại). `ApiConfig.token`/`ApiConfig.cors_origins` giữ nguyên tên qua Task 1, 3, 9, 10.

**Điểm cần dò trước khi code, đã ghi thẳng vào bước liên quan:** tên thật của `archived_slugs` (Task 5 Step 3), `Storage.write_raw` / `mark_translated_complete` / `save_cover_bytes` (Task 6 Step 7), khẳng định `SCHEMA_VERSION` trong `tests/test_db_schema.py` (Task 1 Step 7), hỗ trợ `TestClient(client=...)` của Starlette (Task 3 Step 4).
