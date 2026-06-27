"""Cài torch bản CUDA phù hợp để bật GPU cho CTranslate2."""
from __future__ import annotations

import subprocess
import os
import sys
from typing import Callable, Iterator

_TORCH_CUDA_CHANNELS = [
    (12, 8, "cu128"),
    (12, 6, "cu126"),
    (11, 8, "cu118"),
]


def choose_cuda_channel(driver_cuda: str | None) -> str | None:
    if not driver_cuda:
        return "cu118"
    try:
        major, minor = (int(part) for part in driver_cuda.split(".")[:2])
    except (ValueError, TypeError):
        return "cu118"
    for ch_major, ch_minor, channel in _TORCH_CUDA_CHANNELS:
        if (major, minor) >= (ch_major, ch_minor):
            return channel
    return None


def torch_install_command(channel: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "torch",
        "--index-url",
        f"https://download.pytorch.org/whl/{channel}",
    ]


def verify_torch_cuda() -> tuple[bool, str]:
    code = (
        "import torch,sys;"
        "print('TORCH_VERSION='+torch.__version__);"
        "print('CUDA_OK='+str(torch.cuda.is_available()))"
    )
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except Exception as exc:
        return False, f"Không kiểm tra được torch sau cài: {exc}"
    out = result.stdout
    version = ""
    for line in out.splitlines():
        if line.startswith("TORCH_VERSION="):
            version = line.split("=", 1)[1]
    cuda_ok = "CUDA_OK=True" in out
    if cuda_ok:
        return True, f"torch {version} đã nhận GPU."
    return False, (
        f"Đã cài torch {version or '(?)'} nhưng torch.cuda vẫn = False — "
        "có thể driver chưa phù hợp hoặc bản torch không khớp. Xem README."
    )


def verify_ct2_cuda() -> tuple[bool, str]:
    code = (
        "import os,sys;"
        "os.environ.pop('CUDA_VISIBLE_DEVICES', None);"
        "import torch;"
        "print('TORCH_VERSION='+torch.__version__);"
        "print('TORCH_CUDA_OK='+str(torch.cuda.is_available()));"
        "import ctranslate2;"
        "count=ctranslate2.get_cuda_device_count();"
        "print('CT2_VERSION='+ctranslate2.__version__);"
        "print('CT2_CUDA_COUNT='+str(count));"
        "types=ctranslate2.get_supported_compute_types('cuda') if count else set();"
        "print('CT2_CUDA_TYPES='+','.join(sorted(types)));"
        "sys.exit(0 if count > 0 else 2)"
    )
    env = dict(os.environ)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except Exception as exc:
        return False, f"Không kiểm tra được CTranslate2 CUDA: {exc}"
    stdout = result.stdout.strip()
    count = ""
    version = ""
    types = ""
    for line in stdout.splitlines():
        if line.startswith("CT2_CUDA_COUNT="):
            count = line.split("=", 1)[1]
        elif line.startswith("CT2_VERSION="):
            version = line.split("=", 1)[1]
        elif line.startswith("CT2_CUDA_TYPES="):
            types = line.split("=", 1)[1]
    try:
        cuda_count = int(count)
    except ValueError:
        cuda_count = 0
    if result.returncode == 0 and cuda_count > 0:
        type_text = f", compute={types}" if types else ""
        return True, f"CTranslate2 {version or '(?)'} đã thấy {count} GPU CUDA{type_text}."
    detail = stdout or result.stderr.strip() or f"exit={result.returncode}"
    return False, (
        "torch đã nhận GPU nhưng CTranslate2 chưa qua smoke test CUDA. "
        f"Chi tiết: {detail}"
    )
