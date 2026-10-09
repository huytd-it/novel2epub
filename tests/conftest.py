"""Fixture pytest dùng chung; helper import trực tiếp nằm trong tests.helpers."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def local_testclient(monkeypatch):
    """Mặc định client là localhost; giữ nguyên địa chỉ remote truyền tường minh.

    API token gate chỉ miễn token cho localhost thật, không phải "testclient".
    Các test auth/CORS vẫn có thể truyền ``client=`` để kiểm tra truy cập từ xa.
    """
    original = TestClient.__init__

    def patched(self, app, *args, **kwargs):
        kwargs.setdefault("client", ("127.0.0.1", 12345))
        return original(self, app, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", patched)
