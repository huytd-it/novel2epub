"""Web UI quản lý Tailscale Serve/Funnel — expose cổng Web UI ra tailnet/Internet.

Tương tự wireguard.py nhưng cho Tailscale:
- GET  /api/tailscale/status  — tổng hợp status + serve status + version
- GET  /api/tailscale/config  — cấu hình toàn cục (binary, port...)
- POST /api/tailscale/config  — lưu cấu hình
- POST /api/tailscale/serve/enable  — bật serve (tailnet riêng)
- POST /api/tailscale/funnel/enable — bật funnel (công khai)
- POST /api/tailscale/serve/reset   — tắt serve
- POST /api/tailscale/funnel/reset  — tắt funnel
- POST /api/tailscale/disable       — tắt cả (serve reset)
- POST /api/tailscale/tcp/serve/enable  — mở TCP qua tailnet
- POST /api/tailscale/tcp/funnel/enable — mở TCP ra Internet
- POST /api/tailscale/tcp/reset         — tắt TCP forward (theo port hoặc toàn bộ)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from novel2epub import tailscale as ts
from novel2epub.tailscale import TailscaleError

from .. import deps

router = APIRouter()


def _db() -> str:
    return str(deps.DB_PATH)


def _raise(e: TailscaleError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.get("/api/tailscale/status")
def tailscale_status():
    cfg = deps.cfg().tailscale
    # collect_overview đã tự xử lý TailscaleError nội bộ và trả overview với status_error,
    # không ném 500. Chỉ phòng hờ lỗi ngoại lệ lạ.
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {
            "binary": cfg.binary,
            "version": "",
            "backend_state": "",
            "tailnet": "",
            "self_dns": "",
            "self_ip": "",
            "status_ok": False,
            "status_error": str(e)[:500],
            "status": None,
            "serve": {"on": False, "funnel_on": False, "config": None, "raw": None},
            "tcp": {"on": False, "funnel_on": False, "config": None},
        }
    return JSONResponse(overview)


@router.get("/api/tailscale/config")
def tailscale_config():
    cfg = deps.cfg().tailscale
    return JSONResponse(ts.describe_config(cfg))


@router.post("/api/tailscale/config")
def tailscale_save_config(payload: dict):
    # Validate
    binary = str(payload.get("binary", "tailscale")).strip() or "tailscale"
    try:
        port = int(payload.get("port", 8010))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="port phải là số nguyên 1-65535.")
    if not (1 <= port <= 65535):
        raise HTTPException(status_code=400, detail="port phải trong khoảng 1-65535.")
    serve_path = str(payload.get("serve_path", "/")).strip() or "/"
    target = str(payload.get("target", "")).strip()
    use_https = bool(payload.get("use_https", True))
    try:
        timeout_seconds = float(payload.get("timeout_seconds", 15.0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="timeout_seconds phải là số.")
    timeout_seconds = max(1.0, min(120.0, timeout_seconds))

    # TCP forward (optional)
    try:
        tcp_port_raw = payload.get("tcp_port", 0)
        tcp_port = int(tcp_port_raw) if str(tcp_port_raw).strip() != "" else 0
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="tcp_port phải là số 0-65535 (0 = tắt).")
    if not (0 <= tcp_port <= 65535):
        raise HTTPException(status_code=400, detail="tcp_port phải trong khoảng 0-65535.")
    tcp_target = str(payload.get("tcp_target", "")).strip()
    tcp_tls_terminated = bool(payload.get("tcp_tls_terminated", False))

    try:
        ts.write_config(_db(), {
            "binary": binary,
            "port": port,
            "serve_path": serve_path,
            "target": target,
            "use_https": use_https,
            "timeout_seconds": timeout_seconds,
            "tcp_port": tcp_port,
            "tcp_target": tcp_target,
            "tcp_tls_terminated": tcp_tls_terminated,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    cfg = deps.cfg().tailscale
    return JSONResponse(ts.describe_config(cfg))


@router.post("/api/tailscale/serve/enable")
def tailscale_serve_enable(payload: dict | None = None):
    cfg = deps.cfg().tailscale
    port = cfg.port
    target = cfg.target
    use_https = cfg.use_https
    serve_path = cfg.serve_path
    if payload:
        if "port" in payload:
            try:
                port = int(payload["port"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="port không hợp lệ.")
        if "target" in payload and payload["target"]:
            target = str(payload["target"]).strip()
        if "use_https" in payload:
            use_https = bool(payload["use_https"])
        if "serve_path" in payload and payload["serve_path"]:
            serve_path = str(payload["serve_path"]).strip()
    try:
        result = ts.serve_enable(
            port,
            binary=cfg.binary,
            use_https=use_https,
            path=serve_path,
            target=target or None,
            timeout=cfg.timeout_seconds,
        )
    except TailscaleError as e:
        raise _raise(e) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


@router.post("/api/tailscale/funnel/enable")
def tailscale_funnel_enable(payload: dict | None = None):
    cfg = deps.cfg().tailscale
    port = cfg.port
    target = cfg.target
    use_https = cfg.use_https
    serve_path = cfg.serve_path
    if payload:
        if "port" in payload:
            try:
                port = int(payload["port"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="port không hợp lệ.")
        if "target" in payload and payload["target"]:
            target = str(payload["target"]).strip()
        if "use_https" in payload:
            use_https = bool(payload["use_https"])
        if "serve_path" in payload and payload["serve_path"]:
            serve_path = str(payload["serve_path"]).strip()
    try:
        result = ts.funnel_enable(
            port,
            binary=cfg.binary,
            use_https=use_https,
            path=serve_path,
            target=target or None,
            timeout=cfg.timeout_seconds,
        )
    except TailscaleError as e:
        raise _raise(e) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


@router.post("/api/tailscale/serve/reset")
def tailscale_serve_reset():
    cfg = deps.cfg().tailscale
    try:
        result = ts.serve_reset(binary=cfg.binary, timeout=cfg.timeout_seconds)
    except TailscaleError as e:
        raise _raise(e) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


@router.post("/api/tailscale/funnel/reset")
def tailscale_funnel_reset():
    cfg = deps.cfg().tailscale
    try:
        result = ts.funnel_reset(binary=cfg.binary, timeout=cfg.timeout_seconds)
    except TailscaleError as e:
        raise _raise(e) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


@router.post("/api/tailscale/disable")
def tailscale_disable():
    """Tắt toàn bộ (alias cho serve reset) — nút một chạm trong UI."""
    cfg = deps.cfg().tailscale
    try:
        result = ts.serve_reset(binary=cfg.binary, timeout=cfg.timeout_seconds)
    except TailscaleError as e:
        raise _raise(e) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})



def _tcp_target_from_payload(payload: dict | None, cfg) -> tuple[int, str, bool]:
    """Resolve (public_port, target_hostport, tls_terminated) from payload or cfg."""
    public_port = int(getattr(cfg, "tcp_port", 0) or 0)
    target = str(getattr(cfg, "tcp_target", "") or "").strip()
    tls_term = bool(getattr(cfg, "tcp_tls_terminated", False))
    if payload:
        if "tcp_port" in payload and payload["tcp_port"] not in (None, ""):
            try:
                public_port = int(payload["tcp_port"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="tcp_port kh\u00f4ng h\u1ee3p l\u1ec7.")
        if "tcp_target" in payload and str(payload["tcp_target"]).strip():
            target = str(payload["tcp_target"]).strip()
        if "tcp_tls_terminated" in payload:
            tls_term = bool(payload["tcp_tls_terminated"])
        # allow generic keys too
        if "port" in payload and not public_port:
            try:
                public_port = int(payload["port"])
            except (TypeError, ValueError):
                pass
        if "target" in payload and not target:
            target = str(payload["target"]).strip()
    if not public_port:
        raise HTTPException(status_code=400, detail="Ch\u01b0a c\u1ea5u h\u00ecnh tcp_port (c\u1ed5ng public cho TCP).")
    if not target:
        # default: loopback + same port as tcp_port if not configured
        target = f"127.0.0.1:{public_port}"
    # normalize target: allow http://host:port or host:port
    if "://" in target:
        from urllib.parse import urlparse
        parsed = urlparse(target)
        host = parsed.hostname or "127.0.0.1"
        prt = parsed.port or public_port
        target = f"{host}:{prt}"
    # validate host:port
    if ":" not in target:
        target = f"{target}:{public_port}"
    return public_port, target, tls_term


@router.post("/api/tailscale/tcp/serve/enable")
def tailscale_tcp_serve_enable(payload: dict | None = None):
    cfg = deps.cfg().tailscale
    try:
        public_port, target, tls_term = _tcp_target_from_payload(payload, cfg)
        result = ts.tcp_serve_enable(public_port, target, binary=cfg.binary, tls_terminated=tls_term, timeout=cfg.timeout_seconds)
    except HTTPException:
        raise
    except Exception as e:
        # TailscaleError -> 400
        from novel2epub.tailscale import TailscaleError as _TE
        if isinstance(e, _TE):
            raise _raise(e) from e
        raise HTTPException(status_code=400, detail=str(e)[:600]) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}, "tcp": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


@router.post("/api/tailscale/tcp/funnel/enable")
def tailscale_tcp_funnel_enable(payload: dict | None = None):
    cfg = deps.cfg().tailscale
    try:
        public_port, target, tls_term = _tcp_target_from_payload(payload, cfg)
        result = ts.tcp_funnel_enable(public_port, target, binary=cfg.binary, tls_terminated=tls_term, timeout=cfg.timeout_seconds)
    except HTTPException:
        raise
    except Exception as e:
        from novel2epub.tailscale import TailscaleError as _TE
        if isinstance(e, _TE):
            raise _raise(e) from e
        raise HTTPException(status_code=400, detail=str(e)[:600]) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}, "tcp": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


@router.post("/api/tailscale/tcp/reset")
def tailscale_tcp_reset(payload: dict | None = None):
    cfg = deps.cfg().tailscale
    public_port = None
    tls_term = bool(getattr(cfg, "tcp_tls_terminated", False))
    if payload and payload.get("tcp_port") not in (None, ""):
        try:
            public_port = int(payload["tcp_port"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="tcp_port kh\u00f4ng h\u1ee3p l\u1ec7.")
    if payload and "tcp_tls_terminated" in payload:
        tls_term = bool(payload["tcp_tls_terminated"])
    try:
        result = ts.tcp_reset(public_port, binary=cfg.binary, tls_terminated=tls_term, timeout=cfg.timeout_seconds)
    except Exception as e:
        from novel2epub.tailscale import TailscaleError as _TE
        if isinstance(e, _TE):
            raise _raise(e) from e
        raise HTTPException(status_code=400, detail=str(e)[:600]) from e
    try:
        overview = ts.collect_overview(cfg.binary, timeout=cfg.timeout_seconds)
    except Exception as e:  # noqa: BLE001
        overview = {"status_ok": False, "status_error": str(e)[:500], "serve": {"on": False, "funnel_on": False}, "tcp": {"on": False, "funnel_on": False}}
    return JSONResponse({"result": result, "overview": overview})


# ── Legacy form POSTs cho Jinja2 fallback (nếu còn dùng) ───────────────────
@router.post("/tailscale/config")
def tailscale_config_form(
    payload: dict | None = None,
):
    """Placeholder cho form POST cũ — chuyển hướng về SPA."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/tailscale", status_code=303)
