"""Web UI quản lý WireGuard toàn cục (xem novel2epub/wireguard.py).

AN TOÀN (bất biến, lặp lại từ domain):
- KHÔNG endpoint nào hiển thị/tải nội dung cấu hình WireGuard hoặc private key.
  Trang GET chỉ render cấu hình toàn cục ĐÃ LÀM SẠCH (describe_config) + metadata
  profile (id opaque, filename, source, enabled, position, status, timestamps).
- URL luôn dùng id profile OPAQUE (uuid hex), không dùng filename.
- Lỗi domain (WireGuardProfileError) được map về HTTPException với message sạch
  (không chứa nội dung cấu hình); xung đột (xóa profile đang active) → 409.
- Mọi mutation thành công đều 303-về /wireguard (phù hợp data-ajax: app.js theo
  redirect rồi swap #wireguard-region).
- Upload import: giới hạn kích thước chặt (streaming) + luôn dọn file tạm; không log nội dung.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from novel2epub import wireguard as wg
from novel2epub.wireguard import WireGuardProfileError

from .. import deps

router = APIRouter()

# Giới hạn kích thước file cấu hình import (strict): config thật rất nhỏ.
MAX_UPLOAD_BYTES = 1_000_000  # 1 MiB - "strict reasonable size limit"


def _back() -> RedirectResponse:
    return RedirectResponse("/wireguard", status_code=303)


def _db() -> str:
    return str(deps.DB_PATH)


def _profile_or_404(profile_id: str) -> dict:
    prof = wg.get_profile(_db(), profile_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy profile.")
    return prof


def _raise_domain(exception: WireGuardProfileError) -> HTTPException:
    """Map lỗi domain (message sạch) về HTTPException 400."""
    return HTTPException(status_code=400, detail=str(exception))


def _ui_config(cfg) -> dict:
    """Cấu hình dành riêng cho UI — KHÔNG kèm giá trị `wgcf.argv`.

    `wgcf.argv` có thể chứa token/secret → tuyệt đối không đưa vào HTML. Chỉ
    truyền thông tin cấu trúc an toàn: có cấu hình hay không + số tham số.
    `describe_config` trong domain vẫn giữ argv (dùng cho CLI operator), route
    này dùng helper riêng để cách ly UI khỏi giá trị nhạy cảm.
    """
    argv = list(cfg.wgcf.argv or [])
    return {
        "enabled": cfg.enabled,
        "profiles_dir": cfg.profiles_dir,
        "wg_exe": cfg.wg_exe,
        "manage_service": cfg.manage_service,
        "service_timeout_seconds": cfg.service_timeout_seconds,
        "lock_timeout_seconds": cfg.lock_timeout_seconds,
        "wgcf.enabled": cfg.wgcf.enabled,
        "wgcf.executable": cfg.wgcf.executable,
        "wgcf.output": cfg.wgcf.output,
        "wgcf.timeout_seconds": cfg.wgcf.timeout_seconds,
        "wgcf.argv_configured": bool(argv),
        "wgcf.argv_count": len(argv),
    }


# ── Cấu hình toàn cục ──────────────────────────────────────────────────────


@router.post("/wireguard/settings")
def wireguard_save_settings(
    enabled: str = Form(""),
    profiles_dir: str = Form(""),
    wg_exe: str = Form(""),
    manage_service: str = Form(""),
    service_timeout_seconds: float = Form(60.0),
    lock_timeout_seconds: float = Form(30.0),
    wgcf_enabled: str = Form(""),
    wgcf_executable: str = Form(""),
    wgcf_argv: str = Form(""),
    replace_wgcf_argv: str = Form(""),
    wgcf_output: str = Form("wgcf-profile.conf"),
    wgcf_timeout_seconds: float = Form(120.0),
):
    # `wgcf.argv` có thể chứa token/secret: không bao giờ log, không render.
    # Chỉ thay khi người dùng TÍCH `replace_wgcf_argv`; nếu không, giữ nguyên argv
    # đang có (không xoá/ghi đè). Tích replace + textarea rỗng = xoá sạch argv.
    if bool(replace_wgcf_argv):
        # Nhập 1 tham số / dòng — KHÔNG parse như shell command.
        argv = [line.strip() for line in wgcf_argv.splitlines() if line.strip()]
    else:
        current = deps.cfg().wireguard.wgcf.argv
        argv = list(current) if isinstance(current, (list, tuple)) else []
    try:
        wg.write_config(_db(), {
            "enabled": bool(enabled),
            "profiles_dir": profiles_dir.strip(),
            "wg_exe": wg_exe.strip(),
            "manage_service": bool(manage_service),
            "service_timeout_seconds": service_timeout_seconds,
            "lock_timeout_seconds": lock_timeout_seconds,
            "wgcf": {
                "enabled": bool(wgcf_enabled),
                "executable": wgcf_executable.strip(),
                "argv": argv,
                "output": wgcf_output.strip(),
                "timeout_seconds": wgcf_timeout_seconds,
            },
        })
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    return _back()


# ── Import (multipart, giới hạn kích thước + dọn tạm) ─────────────────────


@router.post("/wireguard/import")
def wireguard_import(file: UploadFile = File(...), name: str = Form("")):
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            # Không tạo temp, không log nội dung — từ chối trước khi rò rỉ.
            raise HTTPException(
                status_code=400,
                detail=f"File cấu hình quá lớn (giới hạn {MAX_UPLOAD_BYTES // 1024} KB).",
            )
        parts.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="File cấu hình rỗng.")

    cfg = deps.cfg().wireguard
    label = name.strip() or (file.filename or "")

    fd, tmppath = tempfile.mkstemp(suffix=".conf", prefix="n2e-wg-import-")
    os.close(fd)
    try:
        Path(tmppath).write_bytes(b"".join(parts))
        wg.import_profile(_db(), cfg.profiles_dir, tmppath, source="manual", name=label or None)
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    finally:
        try:
            Path(tmppath).unlink(missing_ok=True)
        except OSError:
            pass
    return _back()


# ── Discover / Provision ───────────────────────────────────────────────────


@router.post("/wireguard/discover")
def wireguard_discover():
    cfg = deps.cfg().wireguard
    try:
        wg.discover_profiles(_db(), cfg.profiles_dir)
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    return _back()


@router.post("/wireguard/provision")
def wireguard_provision(label: str = Form("")):
    cfg = deps.cfg().wireguard
    try:
        wg.provision_wgcf_profile(_db(), cfg, label=label.strip())
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    return _back()


# ── Thao tác profile (opaque id trong URL) ─────────────────────────────────


@router.post("/wireguard/{profile_id}/enable")
def wireguard_enable(profile_id: str):
    prof = _profile_or_404(profile_id)
    return _set_enabled(prof["id"], True)


@router.post("/wireguard/{profile_id}/disable")
def wireguard_disable(profile_id: str):
    prof = _profile_or_404(profile_id)
    return _set_enabled(prof["id"], False)


def _set_enabled(profile_id: str, enabled: bool) -> RedirectResponse:
    if not wg.set_enabled(_db(), profile_id, enabled):
        raise HTTPException(status_code=404, detail="Không tìm thấy profile.")
    return _back()


@router.post("/wireguard/{profile_id}/position")
def wireguard_position(profile_id: str, position: int = Form(...)):
    prof = _profile_or_404(profile_id)
    if not wg.set_order(_db(), prof["id"], position):
        raise HTTPException(status_code=404, detail="Không tìm thấy profile.")
    return _back()


@router.post("/wireguard/{profile_id}/activate")
def wireguard_activate(profile_id: str):
    prof = _profile_or_404(profile_id)
    cfg = deps.cfg().wireguard
    try:
        wg.activate_profile(_db(), cfg, prof["id"])
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    return _back()


@router.post("/wireguard/rotate")
def wireguard_rotate():
    cfg = deps.cfg().wireguard
    try:
        wg.rotate_profile(_db(), cfg)
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    return _back()


@router.post("/wireguard/{profile_id}/delete")
def wireguard_delete(profile_id: str):
    prof = _profile_or_404(profile_id)
    # Không thể xóa profile đang active (giữ tunnel service đang chạy) → 409.
    if prof["status"] == "active" or wg.get_active_id(_db()) == prof["id"]:
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa profile đang active — hủy active trước.",
        )
    cfg = deps.cfg().wireguard
    try:
        removed = wg.remove_profile(_db(), cfg.profiles_dir, prof["id"])
    except WireGuardProfileError as e:
        raise _raise_domain(e) from e
    if not removed:
        raise HTTPException(status_code=404, detail="Không tìm thấy profile.")
    return _back()