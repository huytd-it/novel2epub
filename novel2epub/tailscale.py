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
    # TCP forward (raw TCP / TLS-terminated TCP)
    tcp_on: bool = False
    tcp_funnel_on: bool = False
    tcp_config: dict[str, Any] | None = None
    # raw JSON để frontend tự render nếu cần
    raw: dict[str, Any] | None = None


def _extract_tcp_info(data: dict[str, Any]) -> tuple[bool, bool, dict[str, Any] | None]:
    """Trích TCP forward info từ JSON `serve status --json`.

    Trả (tcp_on, tcp_funnel_on, tcp_config)."""
    if not isinstance(data, dict):
        return False, False, None
    sc = data.get("ServeConfig") if isinstance(data.get("ServeConfig"), dict) else {}
    # ServeConfig.TCP là map port -> {TCPForward|...}
    tcp_cfg: Any = None
    if isinstance(sc.get("TCP"), dict) and sc["TCP"]:
        tcp_cfg = sc["TCP"]
    elif isinstance(data.get("TCP"), dict) and data["TCP"]:
        tcp_cfg = data["TCP"]
    # Fallback: quét toàn bộ data tìm TCPForward
    if tcp_cfg is None:
        for v in data.values():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if isinstance(v2, dict) and "TCPForward" in v2:
                        tcp_cfg = {k2: v2}
                        break
                if tcp_cfg:
                    break
    tcp_on = bool(isinstance(tcp_cfg, dict) and tcp_cfg)
    tcp_funnel_on = False
    if tcp_on and isinstance(tcp_cfg, dict):
        # AllowFunnel có thể ở top-level hoặc ServeConfig
        allow = data.get("FunnelOn")
        if allow is None and isinstance(sc, dict):
            allow = sc.get("AllowFunnel")
        if isinstance(allow, dict):
            for pk in tcp_cfg.keys():
                pk_s = str(pk)
                for ak in allow.keys():
                    ak_s = str(ak)
                    if pk_s == ak_s or pk_s in ak_s or ak_s.endswith(f":{pk_s}") or ak_s == f"tcp:{pk_s}":
                        tcp_funnel_on = True
                        break
                if tcp_funnel_on:
                    break
        elif isinstance(allow, bool):
            tcp_funnel_on = bool(allow and tcp_on)
        else:
            # Heuristic: nếu AllowFunnel là dict truthy và chứa bất kỳ
            if isinstance(sc.get("AllowFunnel"), dict) and tcp_cfg:
                for pk in tcp_cfg.keys():
                    if any(str(pk) in str(k) for k in sc["AllowFunnel"].keys()):
                        tcp_funnel_on = True
                        break
    return tcp_on, tcp_funnel_on, tcp_cfg if isinstance(tcp_cfg, dict) else None


def get_serve_status(binary: str = "tailscale", *, timeout: float = 10.0) -> TailscaleServeInfo:
    """Lấy trạng thái serve/funnel. Không lỗi nếu chưa bật."""
    result = _run(binary, ["serve", "status", "--json"], timeout=timeout)
    raw_text = (result.stdout or "") or (result.stderr or "") or "{}"
    data = _safe_json(raw_text)
    if data is None:
        err_snip = (raw_text or "").strip()[:300]
        return TailscaleServeInfo(raw={"error": err_snip} if err_snip else None)
    sc = data.get("ServeConfig") if isinstance(data.get("ServeConfig"), dict) else {}
    # Web config
    web_cfg: Any = None
    if isinstance(sc.get("Web"), dict) and sc["Web"]:
        web_cfg = sc["Web"]
    elif isinstance(data.get("Web"), dict) and data["Web"]:
        web_cfg = data["Web"]
    else:
        # Fallback cho bản cũ: ServeConfig trực tiếp là Web map
        maybe = data.get("ServeConfig")
        if isinstance(maybe, dict) and maybe and not isinstance(maybe.get("TCP"), dict):
            # Nếu ServeConfig không có TCP/Web mà chứa trực tiếp handlers
            if any(isinstance(v, dict) and ("Handlers" in v or "Proxy" in str(v)) for v in maybe.values()):
                web_cfg = maybe
    tcp_on, tcp_funnel_on, tcp_cfg = _extract_tcp_info(data)
    # funnel cho Web
    allow_web = sc.get("AllowFunnel") if isinstance(sc, dict) else None
    funnel_on = False
    if isinstance(data.get("FunnelOn"), bool):
        funnel_on = bool(data["FunnelOn"] and web_cfg)
    elif isinstance(allow_web, dict) and web_cfg:
        # AllowFunnel chứa host:port của Web
        funnel_on = any(bool(v) for v in allow_web.values()) and bool(web_cfg)
    elif isinstance(data.get("FunnelOn"), dict):
        funnel_on = bool(data["FunnelOn"])
    # fallback heuristic cũ
    if not funnel_on and web_cfg and any("funnel" in str(k).lower() for k in data.keys()):
        funnel_on = bool(data.get("FunnelOn"))

    serve_on = bool(isinstance(web_cfg, dict) and web_cfg)
    # Nếu không xác định được web_cfg mà có data rỗng và có tcp thì web vẫn off
    if not serve_on and not tcp_on:
        # Check fallback: có ServeConfig khác rỗng nhưng không phải TCP
        if isinstance(data.get("ServeConfig"), dict) and data["ServeConfig"]:
            # Nếu ServeConfig có key khác TCP/Web nhưng có dữ liệu
            other = {k: v for k, v in data["ServeConfig"].items() if k not in ("TCP", "Web", "AllowFunnel")}
            if other and any(isinstance(v, dict) and v for v in other.values()):
                serve_on = True
                web_cfg = data["ServeConfig"]

    return TailscaleServeInfo(
        serve_config=web_cfg if isinstance(web_cfg, dict) else (web_cfg if web_cfg else None),
        funnel_on=funnel_on,
        serve_on=serve_on,
        tcp_on=tcp_on,
        tcp_funnel_on=tcp_funnel_on,
        tcp_config=tcp_cfg,
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
        # Hỗ trợ cả dạng host:port thuần cho TCP forward (vd 127.0.0.1:5432)
        probe = target
        if "://" not in probe:
            probe = f"http://{probe}"
        parsed = urlparse(probe)
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


def tcp_serve_enable(
    public_port: int,
    target: str = "127.0.0.1",
    *,
    binary: str = "tailscale",
    tls_terminated: bool = False,
    timeout: float = 15.0,
) -> dict[str, Any]:
    public_port = int(public_port)
    if not (1 <= public_port <= 65535):
        raise TailscaleError(f"cổng public không hợp lệ: {public_port}")
    ok, msg = _check_target_reachable(target)
    if not ok:
        raise TailscaleError(f"TCP target không phản hồi tại {target} — {msg}.")
    flag = "--tls-terminated-tcp" if tls_terminated else "--tcp"
    args = ["serve", "--bg", flag, str(public_port), target]
    result = _run(binary, args, timeout=timeout)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:600]
        raise TailscaleError(err or f"tailscale serve tcp exit {result.returncode}")
    return {"ok": True, "args": args, "target": target, "port": public_port}


def tcp_funnel_enable(
    public_port: int,
    target: str = "127.0.0.1",
    *,
    binary: str = "tailscale",
    tls_terminated: bool = False,
    timeout: float = 15.0,
) -> dict[str, Any]:
    public_port = int(public_port)
    if not (1 <= public_port <= 65535):
        raise TailscaleError(f"cổng public không hợp lệ: {public_port}")
    ok, msg = _check_target_reachable(target)
    if not ok:
        raise TailscaleError(f"TCP target không phản hồi tại {target} — {msg}.")
    flag = "--tls-terminated-tcp" if tls_terminated else "--tcp"
    args = ["funnel", "--bg", flag, str(public_port), target]
    result = _run(binary, args, timeout=timeout)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:600]
        raise TailscaleError(err or f"tailscale funnel tcp exit {result.returncode}")
    return {"ok": True, "args": args, "target": target, "port": public_port}


def tcp_reset(
    public_port: int | None = None,
    *,
    binary: str = "tailscale",
    tls_terminated: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    if public_port is not None:
        public_port = int(public_port)
        if not (1 <= public_port <= 65535):
            raise TailscaleError(f"cổng không hợp lệ: {public_port}")
        flag = "--tls-terminated-tcp" if tls_terminated else "--tcp"
        for args in (
            ["serve", f"{flag}={public_port}", "off"],
            ["serve", flag, str(public_port), "off"],
            ["funnel", f"{flag}={public_port}", "off"],
        ):
            result = _run(binary, args, timeout=timeout)
            if result.returncode == 0:
                return {"ok": True, "args": args}
            err = (result.stderr or result.stdout or "").strip()[:500].lower()
            if "unknown" in err or "invalid" in err:
                continue
        result = _run(binary, ["serve", "reset"], timeout=timeout)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()[:500]
            raise TailscaleError(err or "không tắt được TCP forward")
        return {"ok": True}
    info = get_serve_status(binary, timeout=timeout)
    ports = []
    if info.tcp_config:
        for k in info.tcp_config.keys():
            try:
                ports.append(int(str(k).split(":")[-1]))
            except ValueError:
                continue
    if not ports:
        return {"ok": True, "note": "không có TCP forward đang mở"}
    last_err = ""
    for pp in ports:
        try:
            tcp_reset(pp, binary=binary, timeout=timeout)
        except TailscaleError as e:
            last_err = str(e)
    if last_err:
        result = _run(binary, ["serve", "reset"], timeout=timeout)
        if result.returncode != 0:
            raise TailscaleError(last_err)
    return {"ok": True, "ports": ports}


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
        "tcp": {
            "on": serve.tcp_on,
            "funnel_on": serve.tcp_funnel_on,
            "config": serve.tcp_config,
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
        "tcp_port": int(getattr(cfg, "tcp_port", 0) or 0),
        "tcp_target": str(getattr(cfg, "tcp_target", "") or ""),
        "tcp_tls_terminated": bool(getattr(cfg, "tcp_tls_terminated", False)),
    }
