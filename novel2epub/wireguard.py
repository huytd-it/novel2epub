"""Quản lý profile WireGuard + cung cấp wgcf cho novel2epub — phiên bản AN TOÀN.

Nguyên tắc an toàn (bất biến):
- KHÔNG bao giờ đọc nội dung cấu hình WireGuard / private key vào DB, log,
  repr, hay message lỗi. Module này chỉ làm việc với metadata cấu trúc (tên
  key, độ hợp lệ) và tên file tương đối.
- Profile là file NGOÀI trong `wireguard.profiles_dir` (thư mục bảo mật).
  SQLite chỉ lưu metadata opaque (bảng `wireguard_profiles`).
- Mọi lệnh hệ thống chạy qua ``subprocess`` với ``shell=False`` + timeout.
- Chọn profile theo round-robin XÁC ĐỊNH (thứ tự position, id) — không ngẫu
  nhiên, không rotate giữa một thao tác mạng.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .config import WireGuardConfig
from .db import get_thread_connection

_PROFILE_EXT = ".conf"
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Key BẮT BUỘC để công nhận một file cấu hình WireGuard hợp lệ (chuẩn wgcf).
# Chỉ so khớp TÊN key, không bao giờ đọc GIÁ trị (không lộ private key).
_REQUIRED_INTERFACE_KEYS = ("PrivateKey", "Address")
_REQUIRED_PEER_KEYS = ("PublicKey", "Endpoint", "AllowedIPs")


class WireGuardProfileError(ValueError):
    """Lỗi profile/cấu hình WireGuard — message chỉ chứa thông tin cấu trúc
    (tên key thiếu, return code...), KHÔNG bao giờ chứa nội dung cấu hình."""


# ── Phân tích cấu hình (chỉ metadata cấu trúc, không nội dung) ────────────


@dataclass
class ParsedWireGuardConfig:
    """Kết quả phân tích: CHỈ danh sách TÊN key, không bao gồm giá trị.

    Đảm bảo repr/log không thể phát tán private key khi người dùng in object
    này ra."""
    interface_keys: tuple[str, ...] = ()
    peers_keys: tuple[tuple[str, ...], ...] = ()


def _parse_section_keys(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Parse INI đơn giản (WireGuard) — CHỈ giữ TÊN key, KHÔNG bao giờ giữ giá
    trị (không có private key nào sống sót qua hàm này, không lọt vào object
    hay repr)."""
    sections: list[tuple[str, tuple[str, ...]]] = []
    current: str | None = None
    keys: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            if current is not None:
                sections.append((current, tuple(keys)))
            current = line[1:-1].strip()
            keys = []
        elif current is not None and "=" in line:
            key, _, _ = line.partition("=")
            name = key.strip()
            if name and name not in keys:
                keys.append(name)
    if current is not None:
        sections.append((current, tuple(keys)))
    return sections


def parse_wireguard_config(text: str) -> ParsedWireGuardConfig:
    """Đọc cấu hình text, trả về metadata CẤU TRÚC (tên key). Không giữ giá trị."""
    sections = _parse_section_keys(text)
    interfaces = [keys for name, keys in sections if name.lower() == "interface"]
    peers = [keys for name, keys in sections if name.lower() == "peer"]

    missing: list[str] = []
    if not interfaces:
        missing.append("[Interface]")
    else:
        keys = {k.lower() for k in interfaces[0]}
        for key in _REQUIRED_INTERFACE_KEYS:
            if key.lower() not in keys:
                missing.append(f"[Interface] {key}")
    if not peers:
        missing.append("[Peer]")
    for i, peer in enumerate(peers, 1):
        pkeys = {k.lower() for k in peer}
        for key in _REQUIRED_PEER_KEYS:
            if key.lower() not in pkeys:
                missing.append(f"[Peer] thứ {i} thiếu {key}")
    if missing:
        raise WireGuardProfileError(
            "cấu hình WireGuard không hợp lệ, thiếu: " + ", ".join(missing)
        )
    return ParsedWireGuardConfig(
        interface_keys=tuple(interfaces[0]),
        peers_keys=tuple(peers),
    )


def build_config(interface: dict[str, str], peers: list[dict[str, str]]) -> str:
    """Dựng text cấu hình WireGuard — hỗ trợ writer/init/test fixture."""
    lines = ["[Interface]"]
    lines += [f"{key} = {value}" for key, value in interface.items()]
    for peer in peers:
        lines.append("")
        lines.append("[Peer]")
        lines += [f"{key} = {value}" for key, value in peer.items()]
    return "\n".join(lines) + "\n"


def validate_config_file(path: Path) -> ParsedWireGuardConfig:
    """Xác thực 1 file cấu hình WireGuard đã tồn tại — không trả nội dung."""
    p = Path(path)
    if not p.is_file():
        raise WireGuardProfileError(f"không tìm thấy file cấu hình: {p}")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise WireGuardProfileError(f"không đọc được file cấu hình: {e.strerror}") from None
    return parse_wireguard_config(text)


# ── Registry metadata (DB) — profile ngoài, metadata opaque trong DB ──────


def list_profiles(db_path: str | Path) -> list[dict[str, Any]]:
    conn = get_thread_connection(db_path)
    rows = conn.execute(
        "SELECT id, filename, source, enabled, position, status, error, "
        "activated_at, last_error_at, created_at, updated_at "
        "FROM wireguard_profiles ORDER BY position, id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_profile(db_path: str | Path, selector: str) -> dict[str, Any] | None:
    """Tìm profile theo opaque id HOẶC filename (metadata_only)."""
    conn = get_thread_connection(db_path)
    row = conn.execute(
        "SELECT * FROM wireguard_profiles WHERE id = ? OR filename = ? "
        "ORDER BY position, id",
        (selector, selector),
    ).fetchone()
    return dict(row) if row else None


def get_active(db_path: str | Path) -> dict[str, Any] | None:
    conn = get_thread_connection(db_path)
    row = conn.execute(
        "SELECT * FROM wireguard_profiles WHERE status = 'active' ORDER BY position, id"
    ).fetchone()
    return dict(row) if row else None


def get_active_id(db_path: str | Path) -> str | None:
    active = get_active(db_path)
    return active["id"] if active else None


def _next_position(conn) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM wireguard_profiles"
    ).fetchone()
    return int(row[0]) + 1


def add_profile(
    db_path: str | Path, *, filename: str, source: str = "manual", position: int | None = None
) -> str:
    conn = get_thread_connection(db_path)
    pid = uuid.uuid4().hex[:16]
    if position is None:
        position = _next_position(conn)
    with conn:
        conn.execute(
            "INSERT INTO wireguard_profiles (id, filename, source, position) "
            "VALUES (?, ?, ?, ?)",
            (pid, filename, source, position),
        )
    return pid


def _delete_row(conn, profile_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM wireguard_profiles WHERE id = ?", (profile_id,))


def set_enabled(db_path: str | Path, selector: str, enabled: bool) -> bool:
    prof = get_profile(db_path, selector)
    if prof is None:
        return False
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE wireguard_profiles SET enabled = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (1 if enabled else 0, prof["id"]),
        )
    return True


def set_order(db_path: str | Path, selector: str, position: int) -> bool:
    prof = get_profile(db_path, selector)
    if prof is None:
        return False
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE wireguard_profiles SET position = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (int(position), prof["id"]),
        )
    return True


def set_status(db_path: str | Path, selector: str, *, status: str, error: str = "") -> bool:
    prof = get_profile(db_path, selector)
    if prof is None:
        return False
    conn = get_thread_connection(db_path)
    last_error_at = "datetime('now')" if error else "''"
    with conn:
        conn.execute(
            f"UPDATE wireguard_profiles SET status = ?, error = ?, "
            f"last_error_at = {last_error_at}, updated_at = datetime('now') WHERE id = ?",
            (status, error, prof["id"]),
        )
    return True


def set_active(db_path: str | Path, profile_id: str | None) -> None:
    """Profile active là runtime metadata (1 lúc 1 nơi). Chuyển toàn bộ về
    inactive rồi đánh active cho `profile_id` (None = không có ai active)."""
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE wireguard_profiles SET status = 'inactive', "
            "updated_at = datetime('now') WHERE status = 'active'"
        )
        if profile_id is not None:
            conn.execute(
                "UPDATE wireguard_profiles SET status = 'active', "
                "activated_at = datetime('now'), error = '', "
                "updated_at = datetime('now') WHERE id = ?",
                (profile_id,),
            )


# ── Tuyển chọn round-robin XÁC ĐỊNH ────────────────────────────────────────


def _candidates(conn, *, exclude_error: bool = True) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM wireguard_profiles WHERE enabled = 1 ORDER BY position, id"
    ).fetchall()
    out = []
    for r in rows:
        if exclude_error and r["status"] == "error":
            continue
        out.append(dict(r))
    return out


def select_profile_id(db_path: str | Path, *, exclude_id: str | None = None) -> str | None:
    """Chọn profile XÁC ĐỊNH dùng cho 1 thao tác mạng: enabled, không lỗi, thứ
    tự (position, id) — cùng đầu vào luôn trả cùng kết quả."""
    conn = get_thread_connection(db_path)
    candidates = _candidates(conn)
    if exclude_id:
        rest = [c for c in candidates if c["id"] != exclude_id]
        if rest:
            candidates = rest
    return candidates[0]["id"] if candidates else None


def rotate_profile_id(db_path: str | Path, *, current_id: str | None = None) -> str | None:
    """Round-robin: chọn profile kế tiếp theo thứ tự (position, id) sau profile
    đang dùng; hết vòng thì quay lại đầu. Xác định, không ngẫu nhiên."""
    conn = get_thread_connection(db_path)
    candidates = _candidates(conn)
    if not candidates:
        return None
    order = [c["id"] for c in candidates]
    if current_id is None:
        return order[0]
    try:
        idx = order.index(current_id)
    except ValueError:
        return order[0]
    return order[(idx + 1) % len(order)]


# ── Nhập / Discovery / Xóa (file + metadata) ───────────────────────────────


def _safe_dest_name(profiles_dir: Path, prefer: str | None) -> str:
    base = prefer or ""
    if not base or base in (".", "..") or not _SAFE_NAME_RE.match(base):
        base = "wg-profile"
    if not base.endswith(_PROFILE_EXT):
        base += _PROFILE_EXT
    candidate = base
    while (profiles_dir / candidate).exists():
        candidate = f"{Path(base).stem}-{uuid.uuid4().hex[:8]}{_PROFILE_EXT}"
    return candidate


def import_profile(
    db_path: str | Path,
    profiles_dir: str | Path,
    src_path: str | Path,
    *,
    source: str = "manual",
    name: str | None = None,
) -> dict[str, Any]:
    """Nhập profile: XÁC THỰC (không lộ key) → copy vào profiles_dir → ghi metadata."""
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    src = Path(src_path)
    if not src.is_file():
        raise WireGuardProfileError(f"không tìm thấy file nguồn: {src}")
    validate_config_file(src)  # chỉ xác thực cấu trúc, không đọc giá trị ra ngoài

    dest_name = _safe_dest_name(profiles_dir, prefer=name)
    dest = profiles_dir / dest_name
    shutil.copy2(src, dest)
    try:
        pid = add_profile(db_path, filename=dest_name, source=source)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return get_profile(db_path, pid) or {}


def discover_profiles(
    db_path: str | Path, profiles_dir: str | Path, *, source: str = "discovered"
) -> list[dict[str, Any]]:
    """Quét profiles_dir, đăng ký các file `.conf` hợp lệ chưa có trong DB."""
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.is_dir():
        return []
    profiles_dir.mkdir(parents=True, exist_ok=True)
    known = {p["filename"] for p in list_profiles(db_path)}
    added: list[dict[str, Any]] = []
    for f in sorted(profiles_dir.glob(f"*{_PROFILE_EXT}")):
        if f.name in known:
            continue
        try:
            validate_config_file(f)
        except WireGuardProfileError:
            continue
        pid = add_profile(db_path, filename=f.name, source=source)
        added.append(get_profile(db_path, pid) or {})
    return added


def _managed_profile_path(profiles_dir: Path, filename: str) -> Path:
    """Trả đường dẫn file cấu hình của profile trong profiles_dir, ĐẢM BẢO file
    nằm TRONG profiles_dir (chống traversal/symlink thoát thư mục)."""
    base = Path(profiles_dir).resolve()
    dest = (base / filename).resolve()
    try:
        inside = dest.is_relative_to(base)
    except ValueError:
        inside = False
    if not inside or dest.parent != base or not dest.name:
        raise WireGuardProfileError(
            f"file profile không hợp lệ trong profiles_dir: {filename!r}"
        )
    return dest


def remove_profile(db_path: str | Path, profiles_dir: str | Path, selector: str) -> bool:
    """Xóa metadata + file ngoài (nếu thuộc profiles_dir).

    TỪ CHỐI xóa profile đang active — không để mất tunnel service đang chạy."""
    prof = get_profile(db_path, selector)
    if prof is None:
        return False
    if prof["status"] == "active" or get_active_id(db_path) == prof["id"]:
        raise WireGuardProfileError(
            f"không thể xóa profile đang active ({prof['filename']!r}) — hủy active trước"
        )
    conn = get_thread_connection(db_path)
    _delete_row(conn, prof["id"])
    f = Path(profiles_dir) / prof["filename"]
    if f.is_file():
        f.unlink()
    return True


# ── Khóa liên-tiến-trình (Windows-native, fallback an toàn) ───────────────


def _available_lock_backend() -> str:
    for name in ("msvcrt", "fcntl"):
        try:
            __import__(name)
            return name
        except ImportError:
            continue
    return "exclusive"


class CrossProcessLock:
    """Khóa mutex liên tiến trình cho hoạt động WireGuard (1 lúc 1 nơi).

    Windows: ``msvcrt.locking``. POSIX: ``fcntl.flock``. Nền tảng không có sẵn:
    fallback AN TOÀN bằng tạo file độc quyền (``O_EXCL``). `_available_lock_
    backend` tách riêng để test chọn backend cụ thể."""
    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 30.0,
        poll: float = 0.1,
        backend: str | None = None,
    ):
        self.path = Path(path)
        self.timeout = timeout
        self.poll = poll
        self.backend = backend or _available_lock_backend()
        self._fd: Any = None
        self._exclusive: bool = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        if self.backend == "exclusive":
            while True:
                try:
                    fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise WireGuardProfileError(f"khóa wireguard bận: {self.path}")
                    time.sleep(self.poll)
                    continue
                os.close(fd)
                self._exclusive = True
                return

        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR)
        try:
            os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
        except OSError:
            pass
        while True:
            try:
                if self.backend == "msvcrt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise WireGuardProfileError(f"khóa wireguard bận: {self.path}")
                time.sleep(self.poll)

    def release(self) -> None:
        if self._exclusive:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._exclusive = False
            return
        if self._fd is not None:
            try:
                os.lseek(self._fd, 0, os.SEEK_SET)
                if self.backend == "msvcrt":
                    import msvcrt
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> "CrossProcessLock":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


def file_lock(path: str | Path, *, timeout: float = 30.0) -> CrossProcessLock:
    return CrossProcessLock(path, timeout=timeout)


# ── Subprocess an toàn + tunnel service WirelessGuard for Windows ──────────


def run_tool(
    exe: str, argv: list[str], *, cwd: str | None = None, timeout: float
) -> subprocess.CompletedProcess:
    """Chạy executable bằng subprocess shell=False + timeout. Lỗi được làm sạch
    (sanitized): KHÔNG bao giờ nhúng stdout/stderr (có thể chứa key) vào lỗi."""
    if not exe:
        raise WireGuardProfileError("chưa cấu hình đường dẫn executable (wg/wgcf)")
    cmd = [exe, *argv]
    try:
        # Bytes mode + decode utf-8 replace để tránh cp1252 UnicodeDecodeError
        # khi wgcf/wg xuất byte ngoài cp1252. Giữ tương thích với fake_run trong test.
        result = subprocess.run(
            cmd,
            cwd=cwd,
            shell=False,
            capture_output=True,
            timeout=timeout,
        )
        def _dec(b: bytes | None) -> str:
            if b is None:
                return ""
            if isinstance(b, str):
                return b
            return b.decode("utf-8", errors="replace")

        return subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=_dec(result.stdout),
            stderr=_dec(result.stderr),
        )
    except FileNotFoundError:
        raise WireGuardProfileError(
            f"không tìm thấy executable {Path(exe).name!r}"
        ) from None
    except subprocess.TimeoutExpired:
        raise WireGuardProfileError(
            f"lệnh {Path(exe).name!r} chạy quá thời gian {timeout:.0f}s"
        ) from None
    except OSError as e:
        raise WireGuardProfileError(
            f"không chạy được {Path(exe).name!r}: {e.strerror or 'lỗi hệ thống'}"
        ) from None


def service_install_args(profile_path: Path) -> list[str]:
    """Tham số cài tunnel service (WireGuard for Windows)."""
    return ["/installtunnelservice", str(profile_path)]


def service_uninstall_args(service_name: str) -> list[str]:
    """Tham số gỡ tunnel service — tên service = stem tên file cấu hình."""
    return ["/uninstalltunnelservice", service_name]


def install_tunnel_service(cfg: WireGuardConfig, profile_path: Path, *, timeout: float | None = None) -> None:
    if not cfg.manage_service:
        raise WireGuardProfileError("quản lý tunnel service chưa bật (wireguard.manage_service=true)")
    result = run_tool(cfg.wg_exe, service_install_args(profile_path), timeout=timeout or cfg.service_timeout_seconds)
    if result.returncode != 0:
        raise WireGuardProfileError(
            f"cài tunnel service thất bại (exit {result.returncode}); kiểm tra nhật ký WireGuard"
        )


def uninstall_tunnel_service(cfg: WireGuardConfig, profile_path: Path, *, timeout: float | None = None) -> None:
    if not cfg.manage_service:
        raise WireGuardProfileError("quản lý tunnel service chưa bật (wireguard.manage_service=true)")
    service_name = Path(profile_path).stem
    result = run_tool(cfg.wg_exe, service_uninstall_args(service_name), timeout=timeout or cfg.service_timeout_seconds)
    if result.returncode != 0:
        raise WireGuardProfileError(
            f"gỡ tunnel service thất bại (exit {result.returncode}); kiểm tra nhật ký WireGuard"
        )


def _sanitize_activation_error(exc: BaseException) -> str:
    """Rút lỗi activation về message sạch — KHÔNG chứa nội dung cấu hình."""
    if isinstance(exc, WireGuardProfileError):
        return str(exc)
    return "lỗi hệ thống khi kích hoạt"


def activate_profile(db_path: str | Path, cfg: WireGuardConfig, selector: str) -> dict[str, Any]:
    """Kích hoạt profile với vòng đời tunnel service THẬT — TỪ CHỐI khi manage_service=false.

    Toàn bộ nằm trong khóa liên tiến trình host (1 lúc 1 nơi):
      1. Validate profile tồn tại + enabled; file cấu hình nằm trong profiles_dir.
      2. Nhớ profile active trước đó (nếu có).
      3. Nếu có profile trước KHÁC target: gỡ tunnel service của profile đó —
         CHỈ gỡ service thuộc registry của chúng ta, không bao giờ đụng tunnel lạ.
      4. Cài tunnel service target bằng lệnh WireGuard for Windows chuẩn.
      5. CẬP NHẬT DB active CHỈ SAU khi cài thành công.
      Nếu cài target thất bại: cài LẠI profile trước (rollback); giữ trạng thái
      lỗi đã làm sạch (không để nội dung cấu hình lọt vào DB/lỗi).
    """
    prof = get_profile(db_path, selector)
    if prof is None:
        raise WireGuardProfileError(f"không tìm thấy profile {selector!r}")
    if not prof["enabled"]:
        raise WireGuardProfileError("profile đã tắt — bật trước khi activate")
    if not cfg.manage_service:
        raise WireGuardProfileError(
            "không thể activate/rotate khi wireguard.manage_service=false — "
            "bật manage_service để thao tác tunnel service thật"
        )
    profiles_dir = Path(cfg.profiles_dir)
    target_path = _managed_profile_path(profiles_dir, prof["filename"])
    if not target_path.is_file():
        raise WireGuardProfileError(f"file profile không tồn tại: {target_path}")
    validate_config_file(target_path)  # chỉ xác thực cấu trúc, không đọc giá trị ra ngoài

    profiles_dir.mkdir(parents=True, exist_ok=True)
    lock = CrossProcessLock(profiles_dir / "wireguard.lock", timeout=cfg.lock_timeout_seconds)
    with lock:
        previous = get_active(db_path)
        target_id = prof["id"]

        try:
            if previous is not None and previous["id"] != target_id:
                prev_path = _managed_profile_path(profiles_dir, previous["filename"])
                uninstall_tunnel_service(cfg, prev_path)
            install_tunnel_service(cfg, target_path)
        except Exception as e:  # noqa: BLE001 - rollback cho mọi lỗi hệ thống
            err = _sanitize_activation_error(e)
            set_status(db_path, target_id, status="error", error=err)
            if previous is not None and previous["id"] != target_id:
                try:
                    prev_path = _managed_profile_path(profiles_dir, previous["filename"])
                    install_tunnel_service(cfg, prev_path)
                    set_active(db_path, previous["id"])
                except Exception as prev_e:  # noqa: BLE001 - giữ lỗi làm sạch
                    set_status(
                        db_path, previous["id"], status="error",
                        error=_sanitize_activation_error(prev_e),
                    )
            raise WireGuardProfileError(
                f"kích hoạt profile {prof['filename']!r} thất bại: {err}"
            ) from e

        set_active(db_path, target_id)
        return get_profile(db_path, target_id) or {}


def rotate_profile(
    db_path: str | Path, cfg: WireGuardConfig, *, current_id: str | None = None
) -> dict[str, Any]:
    """Chuyển sang profile kế tiếp (round-robin xác định) — kích hoạt THẬT.

    `current_id` rỗng = dùng profile đang active trong DB. Chọn kế tiếp rồi
    giao hẳn cho activate_profile (khóa, cài/gỡ service, rollback, cập nhật DB).
    """
    previous = current_id if current_id is not None else get_active_id(db_path)
    nxt = rotate_profile_id(db_path, current_id=previous)
    if nxt is None:
        raise WireGuardProfileError("không có profile đã bật để rotate")
    return activate_profile(db_path, cfg, nxt)


# ── cung cấp wgcf (argv tường minh + file tương đối + dọn artifact) ────────


def _validate_relative_output(name: str) -> str:
    """Kiểm tra điều kiện output wgcf: tên file tương đối đơn giản, không thoát cwd."""
    if not name or name in (".", ".."):
        raise WireGuardProfileError("wireguard.wgcf.output không hợp lệ (rỗng)")
    if os.path.isabs(name) or "\\" in name or "/" in name or Path(name).name != name:
        raise WireGuardProfileError(
            "wireguard.wgcf.output phải là tên file tương đối đơn giản (không có thư mục)"
        )
    return name


def provision_wgcf_profile(db_path: str | Path, cfg: WireGuardConfig, *, label: str = "") -> dict[str, Any]:
    """Chạy wgcf trong cwd tạm CÔ LẬP, nhập profile sinh ra vào profiles_dir,
    rồi dọn hết artifact. KHÔNG tự thêm/bịa cờ cho wgcf — chỉ dùng.
    """
    w = cfg.wgcf
    if not w.enabled:
        raise WireGuardProfileError("wgcf chưa bật (wireguard.wgcf.enabled=true)")
    if not w.executable:
        raise WireGuardProfileError("chưa cấu hình wireguard.wgcf.executable")
    if not isinstance(w.argv, (list, tuple)):
        raise WireGuardProfileError("wireguard.wgcf.argv phải là danh sách tham số")
    out_name = _validate_relative_output(w.output)

    profiles_dir = Path(cfg.profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="n2e-wgcf-") as tmp:
        cwd = Path(tmp)
        result = run_tool(w.executable, list(w.argv), cwd=str(cwd), timeout=w.timeout_seconds)
        if result.returncode != 0:
            raise WireGuardProfileError(f"wgcf thất bại (exit {result.returncode}); kiểm tra nhật ký wgcf")
        generated = cwd / out_name
        if not generated.is_file():
            raise WireGuardProfileError(f"wgcf không tạo ra {out_name!r} trong thư mục làm việc tạm")
        # TemporaryDirectory tự dọn sạch mọi artifact (kể cả file sinh ra) khi thoát.
        return import_profile(db_path, profiles_dir, generated, source="wgcf", name=label or None)


# ── Scope thao tác mạng (chọn profile — KHÔNG kích hoạt) ──────────────────


@contextmanager
def wireguard_network_scope(cfg: WireGuardConfig, db_path: str | Path) -> Iterator[str | None]:
    """CHỌN 1 profile xác định cho toàn bộ 1 thao tác mạng (toc/crawl).

    Context manager này **metadata-free/manual**: nó CHỈ giữ khóa liên tiến
    trình (1 lúc 1 nơi) và trả id profile được chọn theo round-robin xác định
    cho caller dùng suốt thao tác. Nó KHÔNG cài/gỡ tunnel service và KHÔNG ghi
    DB active — KHÔNG tự nhận là "đã kích hoạt". Vòng đời service thật là việc
    của activate_profile/rotate_profile (bắt buộc manage_service=true).
    """
    if not cfg.enabled:
        yield None
        return
    profiles_dir = Path(cfg.profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    lock = CrossProcessLock(profiles_dir / "wireguard.lock", timeout=cfg.lock_timeout_seconds)
    with lock:
        pid = select_profile_id(db_path)
        if pid is None:
            raise WireGuardProfileError("không có profile WireGuard đã bật để dùng cho thao tác mạng")
        yield pid


# ── Cấu hình (đọc/ghi metadata từ settings.wireguard_json) ────────────────


def read_config(db_path: str | Path) -> "Any":
    from .config import load_config

    return load_config(db_path).wireguard


def write_config(db_path: str | Path, updates: dict[str, Any]) -> None:
    """Merge `updates` vào settings.wireguard_json (chuyện ghi qua config_writer)."""
    from .config_writer import update_defaults

    update_defaults(db_path, {"wireguard": updates})


def nested_update(key: str, value: Any) -> dict[str, Any]:
    """Chuyển 'wgcf.output' + 'x' -> {'wgcf': {'output': 'x'}}."""
    parts = key.split(".")
    if not parts or not parts[0]:
        raise WireGuardProfileError(f"key cấu hình không hợp lệ: {key!r}")
    node: Any = value
    for part in reversed(parts[1:]):
        node = {part: node}
    return {parts[0]: node}


def describe_config(cfg: WireGuardConfig) -> dict[str, Any]:
    """Cấu hình hiển thị (config/status) — KHÔNG chứa key/text cấu hình."""
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
        "wgcf.argv": list(cfg.wgcf.argv),
    }