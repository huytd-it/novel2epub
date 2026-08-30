"""Quản lý Tailscale Serve/Funnel cho Web UI — expose cổng Web UI ra tailnet/Internet.

Nguyên tắc an toàn:
- KHÔNG log token/secret (nếu có trong argv tương lai).
- Mọi lệnh chạy qua subprocess shell=False + timeout.
- Parse JSON từ `tailscale status --json` và `serve status --json` để hiển thị,
  không tự suy diễn URL.
- Serve/Funnel chỉ thao tác trên cổng đã cấu hình (mặc định 8010) hoặc target
  `http://127.0.0.1:<port>`.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


class TailscaleError(ValueError):
    """Lỗi domain Tailscale — message sạch, không chứa secret."""


def _run(
    binary: str,
    args: list[str],
    *,
    timeout: float = 15.0,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    if not binary:
        raise TailscaleError("chưa cấu hình đường dẫn tailscale (tailscale.binary)")
    cmd = [binary, *args]
    try:
        # Dùng bytes mode + decode utf-8 replace để tránh UnicodeDecodeError
        # trên Windows cp1252 khi tailscale xuất byte 0x90/... (11100 bytes).
        # Không truyền encoding để tương thích với fake_run trong test (chỉ nhận text/capture_output).
        result = subprocess.run(
            cmd,
            cwd=cwd,
            shell=False,
            capture_output=True,
            timeout=timeout,
        )
        # Decode thủ công, an toàn với mọi byte
        def _dec(b: bytes | None) -> str:
            if b is None:
                return ""
            if isinstance(b, str):
                return b
            return b.decode("utf-8", errors="replace")

        # Trả CompletedProcess với stdout/stderr dạng str (giữ API cũ cho caller)
        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=_dec(result.stdout),
            stderr=_dec(result.stderr),
        )
    except FileNotFoundError:
        raise TailscaleError(f"không tìm thấy binary {Path(binary).name!r}") from None
    except subprocess.TimeoutExpired:
        raise TailscaleError(f"lệnh {Path(binary).name!r} chạy quá thời gian {timeout:.0f}s") from None
    except OSError as e:
        raise TailscaleError(f"không chạy được {Path(binary).name!r}: {e.strerror or 'lỗi hệ thống'}") from None


def _safe_json(text: str | bytes | None) -> dict[str, Any] | None:
    if text is None:
        return None
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            return None
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


@dataclass
class TailscaleServeInfo:
    """Trạng thái serve/funnel hiện tại (parse từ `tailscale serve status --json`)."""
    serve_config: dict[str, Any] | None = None
    funnel_on: bool = False
    serve_on: bool = False
    # raw JSON để frontend tự render nếu cần
    raw: dict[str, Any] | None = None


def get_serve_status(binary: str = "tailscale", *, timeout: float = 10.0) -> TailscaleServeInfo:
    """Lấy trạng thái serve/funnel. Không lỗi nếu chưa bật."""
    result = _run(binary, ["serve", "status", "--json"], timeout=timeout)
    # tailscale serve status trả 0 khi có config, 1/2 khi chưa có — cả hai đều có JSON
    raw_text = (result.stdout or "") or (result.stderr or "") or "{}"
    data = _safe_json(raw_text)
    if data is None:
        # Không có JSON hợp lệ — coi như chưa có serve (tránh crash UI)
        err_snip = (raw_text or "").strip()[:300]
        return TailscaleServeInfo(raw={"error": err_snip} if err_snip else None)
    # Các key dự kiến: "ServeConfig" hoặc "TCP" / "Web" / "Funnel"
    # Tài liệu: `tailscale serve status --json` trả { "ServeConfig": {...}, ... }
    serve_cfg = data.get("ServeConfig") or data.get("Config") or data.get("TCP") or data.get("Web")
    funnel_on = bool(data.get("FunnelOn") or data.get("AllowFunnel") or any(
        "funnel" in str(k).lower() for k in data.keys()
    ))
    # Xác định serve_on: có ServeConfig khác rỗng
    serve_on = bool(serve_cfg)
    if not serve_on and isinstance(data, dict):
        # Một số phiên bản dùng "Services" hoặc trực tiếp map
        for v in data.values():
            if isinstance(v, dict) and v:
                serve_on = True
                break
    return TailscaleServeInfo(
        serve_config=serve_cfg if isinstance(serve_cfg, dict) else (data if data else None),
        funnel_on=funnel_on,
        serve_on=serve_on,
        raw=data,
    )


def get_status(binary: str = "tailscale", *, timeout: float = 10.0) -> dict[str, Any]:
    """Lấy `tailscale status --json` — thông tin tailnet, self node, backend state."""
    result = _run(binary, ["status", "--json"], timeout=timeout)
    if result.returncode != 0:
        # Có thể chưa login hoặc tailscaled chưa chạy — trả lỗi sạch (đã decode utf-8 replace)
        stderr = (result.stderr or result.stdout or "") or ""
        stderr = stderr.strip()[:500]
        return {"ok": False, "error": stderr or f"tailscale status exit {result.returncode}"}
    # result.stdout luôn là str (encoding utf-8 replace), có thể rỗng hoặc không phải JSON
    data = _safe_json(result.stdout or "")
    if data is None:
        snippet = (result.stdout or "")[:300]
        return {"ok": False, "error": snippet.strip() or "không parse được JSON từ tailscale status"}
    return {"ok": True, "data": data}


def get_version(binary: str = "tailscale", *, timeout: float = 5.0) -> str:
    try:
        result = _run(binary, ["version"], timeout=timeout)
    except TailscaleError:
        return ""
    if result.returncode != 0:
        return ""
    out = result.stdout or ""
    # Đã decode utf-8 replace, an toàn splitlines
    return out.strip().splitlines()[0][:100] if out.strip() else ""


# ── Thao tác Serve/Funnel ────────────────────────────────────────────────────

def _check_target_reachable(target: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Kiểm tra nhanh target http://127.0.0.1:<port> có đang lắng nghe không.

    Dùng socket connect tránh phụ thuộc requests. Trả (ok, msg)."""
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(target)
        host = parsed.hostname or "127.0.0.1"
        tport = parsed.port or 80
        # Chỉ kiểm tra host loopback để tránh SSRF
        if host not in ("127.0.0.1", "localhost", "::1"):
            return True, ""
        with socket.create_connection((host, tport), timeout=timeout):
            return True, ""
    except OSError as e:
        return False, f"không kết nối được {target}: {e.strerror or str(e)}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def serve_enable(
    port: int = 8010,
    *,
    binary: str = "tailscale",
    use_https: bool = True,
    path: str = "/",
    target: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Bật Tailscale Serve: `tailscale serve --bg <port>` hoặc `https / -> target`.

    `port` là cổng Web UI đang chạy (mặc định 8010). Ưu tiên syntax tường minh
    `https / http://127.0.0.1:<port>` (ổn định qua các bản tailscale); fallback
    shorthand `--bg <port>` cho bản mới.
    Kiểm tra target có đang lắng nghe trước khi chạy lệnh — nếu không, báo lỗi
    rõ ràng để tránh 502 (backend không phản hồi).
    """
    port = int(port)
    if not (1 <= port <= 65535):
        raise TailscaleError(f"cổng không hợp lệ: {port}")
    tgt = target or f"http://127.0.0.1:{port}"
    # Pre-flight: backend phải phản hồi, nếu không 502 chắc chắn
    ok, msg = _check_target_reachable(tgt)
    if not ok:
        raise TailscaleError(
            f"Backend không phản hồi tại {tgt} — {msg}. "
            f"Kiểm tra uvicorn đang chạy đúng cổng {port} (ví dụ: uvicorn app.main:app --host 127.0.0.1 --port {port}) "
            f"và Port Web UI trong cấu hình Tailscale phải khớp cổng bạn đang mở."
        )
    last_err: str = ""
    # Ưu tiên explicit (ổn định), fallback shorthand
    for args in (
        ["serve", "--bg", "https", path, tgt] if use_https else ["serve", "--bg", path, tgt],
        ["serve", "--bg", str(port)],
    ):
        result = _run(binary, args, timeout=timeout)
        if result.returncode == 0:
            return {"ok": True, "args": args, "target": tgt}
        err = (result.stderr or result.stdout or "").strip()[:500]
        last_err = err
        if "unknown" in err.lower() or "invalid" in err.lower() or "usage" in err.lower():
            continue
        raise TailscaleError(err or f"tailscale serve exit {result.returncode}")
    raise TailscaleError(last_err or "không bật được tailscale serve")


def funnel_enable(
    port: int = 8010,
    *,
    binary: str = "tailscale",
    use_https: bool = True,
    path: str = "/",
    target: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Bật Funnel: `tailscale funnel --bg <port>` (công khai ra Internet)."""
    port = int(port)
    if not (1 <= port <= 65535):
        raise TailscaleError(f"cổng không hợp lệ: {port}")
    tgt = target or f"http://127.0.0.1:{port}"
    ok, msg = _check_target_reachable(tgt)
    if not ok:
        raise TailscaleError(
            f"Backend không phản hồi tại {tgt} — {msg}. "
            f"Kiểm tra uvicorn đang chạy đúng cổng {port}."
        )
    for args in (
        ["funnel", "--bg", "https", path, tgt] if use_https else ["funnel", "--bg", path, tgt],
        ["funnel", "--bg", str(port)],
    ):
        result = _run(binary, args, timeout=timeout)
        if result.returncode == 0:
            return {"ok": True, "args": args, "target": tgt}
        err = (result.stderr or result.stdout or "").strip()[:500]
        if "unknown" in err.lower() or "invalid" in err.lower() or "usage" in err.lower():
            continue
        raise TailscaleError(err or f"tailscale funnel exit {result.returncode}")
    raise TailscaleError("không bật được tailscale funnel")


def serve_reset(*, binary: str = "tailscale", timeout: float = 10.0) -> dict[str, Any]:
    """Tắt toàn bộ serve: `tailscale serve reset`."""
    result = _run(binary, ["serve", "reset"], timeout=timeout)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:500]
        raise TailscaleError(err or f"tailscale serve reset exit {result.returncode}")
    return {"ok": True}


def funnel_reset(*, binary: str = "tailscale", timeout: float = 10.0) -> dict[str, Any]:
    """Tắt funnel: `tailscale funnel reset` (nếu có) — fallback serve reset."""
    result = _run(binary, ["funnel", "reset"], timeout=timeout)
    if result.returncode == 0:
        return {"ok": True}
    # Một số bản funnel reset không tồn tại riêng — dùng serve reset
    return serve_reset(binary=binary, timeout=timeout)


def collect_overview(
    binary: str = "tailscale",
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Tổng hợp status + serve status + version cho UI."""
    try:
        status = get_status(binary, timeout=timeout)
    except TailscaleError as e:
        status = {"ok": False, "error": str(e)}
    try:
        serve = get_serve_status(binary, timeout=timeout)
    except TailscaleError as e:
        serve = TailscaleServeInfo(serve_config=None, funnel_on=False, serve_on=False, raw={"error": str(e)})
    version = ""
    try:
        version = get_version(binary, timeout=5.0)
    except TailscaleError:
        pass

    # Trích thông tin gọn cho UI (không lộ key/secret)
    tailnet = ""
    self_dns = ""
    backend_state = ""
    self_ip = ""
    if status.get("ok") and isinstance(status.get("data"), dict):
        data = status["data"]
        backend_state = str(data.get("BackendState") or data.get("backendState") or "")
        self_info = data.get("Self") or {}
        if isinstance(self_info, dict):
            dns = self_info.get("DNSName") or self_info.get("Name") or ""
            self_dns = str(dns).strip().rstrip(".")
            # TailscaleIPs
            ips = self_info.get("TailscaleIPs") or []
            if isinstance(ips, list) and ips:
                self_ip = str(ips[0])
        # MagicDNSSuffix để suy ra tailnet
        magic = str(data.get("MagicDNSSuffix") or data.get("CurrentTailnet", {}).get("MagicDNSSuffix") or "")
        if isinstance(data.get("CurrentTailnet"), dict):
            magic = str(data["CurrentTailnet"].get("MagicDNSSuffix") or magic)
        tailnet = magic.strip().lstrip(".")

    return {
        "binary": binary,
        "version": version,
        "backend_state": backend_state,
        "tailnet": tailnet,
        "self_dns": self_dns,
        "self_ip": self_ip,
        "status_ok": bool(status.get("ok")),
        "status_error": status.get("error", ""),
        "status": status.get("data") if status.get("ok") else None,
        "serve": {
            "on": serve.serve_on,
            "funnel_on": serve.funnel_on,
            "config": serve.serve_config,
            "raw": serve.raw,
        },
    }


# ── Config persistence (qua settings.tailscale_json) ─────────────────────────

def read_config(db_path: str | Path) -> Any:
    from .config import load_config
    return load_config(db_path).tailscale


def write_config(db_path: str | Path, updates: dict[str, Any]) -> None:
    from .config_writer import update_defaults
    update_defaults(db_path, {"tailscale": updates})


def describe_config(cfg) -> dict[str, Any]:
    return {
        "binary": cfg.binary,
        "port": cfg.port,
        "serve_path": cfg.serve_path,
        "target": cfg.target,
        "use_https": cfg.use_https,
        "timeout_seconds": cfg.timeout_seconds,
    }
