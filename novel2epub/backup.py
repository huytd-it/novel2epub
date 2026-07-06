"""Sao lưu / phục hồi toàn bộ trạng thái = 1 file `.db` duy nhất.

Vì mọi thứ (config, sources, dữ liệu ebook, queue, automation) nay nằm trong
1 file SQLite, backup = tạo bản sao nhất quán của file đó; restore = thay file
đó vào chỗ cũ. Deploy sang máy khác = copy file `.db` + mã nguồn.

Dùng `sqlite3.Connection.backup()` (online backup API) để chụp bản nhất quán
NGAY CẢ khi server đang chạy/ghi — an toàn hơn copy file thô ở chế độ WAL
(file `.db` có thể đang split sang `-wal`/`-shm`).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .db import SCHEMA_VERSION, get_connection, schema_version


def backup_db(src_path: str | Path, dest_path: str | Path) -> Path:
    """Chụp 1 bản sao nhất quán của DB tại `src_path` ra `dest_path` bằng
    online backup API (an toàn khi server đang chạy). Trả về `dest_path`."""
    src_path = Path(src_path)
    dest_path = Path(dest_path)
    if not src_path.exists():
        raise FileNotFoundError(f"Không tìm thấy DB nguồn: {src_path}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    src = get_connection(src_path)
    try:
        dst = sqlite3.connect(str(dest_path))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest_path


def timestamped_backup(src_path: str | Path, backups_dir: str | Path) -> Path:
    """Tạo backup với tên gắn timestamp trong thư mục `backups_dir`."""
    src_path = Path(src_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(backups_dir) / f"{src_path.stem}-{stamp}.db"
    return backup_db(src_path, dest)


def validate_backup_file(path: str | Path) -> tuple[bool, str]:
    """Kiểm tra `path` là 1 DB novel2epub hợp lệ trước khi restore.

    Trả `(ok, message)`. Không hợp lệ nếu: mở lỗi, thiếu bảng cốt lõi, hoặc
    schema_version mới hơn phiên bản mã hiện tại (tránh restore file từ bản
    app mới hơn lên bản cũ).
    """
    path = Path(path)
    if not path.exists():
        return False, f"Không tìm thấy file: {path}"
    try:
        conn = sqlite3.connect(str(path))
    except sqlite3.Error as e:
        return False, f"Không mở được như SQLite: {e}"
    try:
        try:
            names = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        except sqlite3.DatabaseError as e:
            return False, f"File không phải SQLite hợp lệ: {e}"
        required = {"_meta", "settings", "ebooks", "chapters"}
        missing = required - names
        if missing:
            return False, f"Thiếu bảng cốt lõi: {', '.join(sorted(missing))}"
        ver = schema_version(conn)
        if ver is None:
            return False, "Thiếu schema_version trong _meta."
        if ver > SCHEMA_VERSION:
            return False, (
                f"schema_version={ver} mới hơn phiên bản app hiện tại "
                f"({SCHEMA_VERSION}) — nâng cấp app trước khi restore."
            )
    finally:
        conn.close()
    return True, f"OK (schema_version={ver})"


def restore_db(src_backup: str | Path, target_db: str | Path) -> Path:
    """Thay `target_db` bằng nội dung từ `src_backup` (đã validate).

    An toàn:
    - Validate `src_backup` trước (raise ValueError nếu không hợp lệ).
    - Tự sao lưu DB HIỆN TẠI ra `<target>.pre-restore-<timestamp>` trước khi
      ghi đè (phòng chọn nhầm file).
    - Ghi bản backup vào file tạm rồi `os.replace` (atomic trên cùng ổ đĩa,
      theo đúng tiền lệ ghi atomic của `Storage.save_manifest` cũ).
    - Dọn file WAL/SHM cũ của target để không lẫn state cũ.

    CHỈ dùng cho CLI (không có server đang giữ kết nối tới `target_db`). Với
    web, dùng cơ chế marker `.pending-restore` + restart (xem app/main.py).
    """
    src_backup = Path(src_backup)
    target_db = Path(target_db)

    ok, message = validate_backup_file(src_backup)
    if not ok:
        raise ValueError(f"File backup không hợp lệ: {message}")

    if target_db.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = target_db.with_name(f"{target_db.name}.pre-restore-{stamp}")
        backup_db(target_db, safety)

    # Chụp src_backup ra file tạm cạnh target (đảm bảo cùng ổ đĩa cho os.replace
    # atomic + "gột" mọi WAL còn treo của src thành 1 file .db liền mạch).
    tmp = target_db.with_name(f"{target_db.name}.restore-tmp")
    backup_db(src_backup, tmp)
    os.replace(tmp, target_db)

    # Dọn WAL/SHM cũ của target — chúng thuộc về DB CŨ, giữ lại sẽ hỏng dữ liệu.
    for suffix in ("-wal", "-shm"):
        side = target_db.with_name(target_db.name + suffix)
        if side.exists():
            side.unlink()
    return target_db
