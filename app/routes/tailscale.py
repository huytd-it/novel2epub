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

    try:
        ts.write_config(_db(), {
            "binary": binary,
            "port": port,
            "serve_path": serve_path,
            "target": target,
            "use_https": use_https,
            "timeout_seconds": timeout_seconds,
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


# ── Legacy form POSTs cho Jinja2 fallback (nếu còn dùng) ───────────────────
@router.post("/tailscale/config")
def tailscale_config_form(
    payload: dict | None = None,
):
    """Placeholder cho form POST cũ — chuyển hướng về SPA."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/tailscale", status_code=303)
