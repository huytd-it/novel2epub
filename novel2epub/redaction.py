"""Rút gọn cấu hình hiệu lực — che bí mật trước khi trả ra API — logic thuần.

`redact_cfg(cfg)` chuyển dataclass `Config` (hoặc bất kỳ dataclass nào) thành
dict lồng nhau qua `dataclasses.asdict`, rồi che giá trị của các field nhạy cảm
bằng `"••••••••"` (mặc định). Field được coi là nhạy cảm nếu tên chứa `key`,
`secret`, `token` hoặc `password` (không phân biệt hoa/thường).

Che xong trả thêm `redacted_fields` — danh sách đường dẫn đã che (dạng
`translate.openai.api_key`) để UI hiện dấu "đã bị che" thay vì để người dùng
tưởng trống. Giá trị rỗng không bị che (không có bí mật để che), tránh làm
người dùng lầm rằng đã đặt key.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

MASK = "••••••••"
_SENSITIVE_SUBSTRINGS = ("key", "secret", "token", "password")


def _is_sensitive(field_name: str) -> bool:
    name = field_name.lower()
    return any(sub in name for sub in _SENSITIVE_SUBSTRINGS)


def _walk(node, path: str, masked: list[str]) -> dict | list:
    if isinstance(node, dict):
        out: dict = {}
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                out[key] = _walk(value, child, masked)
            elif _is_sensitive(key) and value not in (None, "", 0, False):
                out[key] = MASK
                masked.append(child)
            else:
                out[key] = value
        return out
    if isinstance(node, list):
        return [_walk(item, path, masked) for item in node]
    return node


def redact_cfg(cfg) -> dict:
    """Chuyển `cfg` (dataclass Config) thành dict lồng nhau đã che bí mật.

    Trả `{"config": {...}, "redacted_fields": [...]}` — `redacted_fields` là
    đường dẫn đầy đủ (vd `translate.openai.api_key`) của các field đã che.
    """
    if not is_dataclass(cfg):
        raise TypeError("redact_cfg chỉ nhận dataclass (Config).")
    masked: list[str] = []
    config = _walk(asdict(cfg), "", masked)
    return {"config": config, "redacted_fields": sorted(masked)}


def redact_dict(data: dict) -> dict:
    """Che bí mật trong dict bất kỳ (JSON đã flatten), trả `{"config", "redacted_fields"}`
    giống `redact_cfg` để API không phải phân biệt kiểu nguồn."""
    masked: list[str] = []
    config = _walk(data, "", masked)
    return {"config": config, "redacted_fields": sorted(masked)}
