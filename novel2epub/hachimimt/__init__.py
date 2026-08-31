"""HachimiMT translation engine — port from ngocdang83/HachimiMT-demo.

`__init__` CHỈ re-export các tên qua `__getattr__` (lazy) để import
`novel2epub.hachimimt.models` (metadata thuần) không kéo theo
`ctranslate2`/`sentencepiece`/`huggingface_hub` — các dep đó chỉ cần khi
thực sự tải model/dịch.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .hardware import HardwareProfile, detect_hardware_profile
    from .honorific_normalize import HONORIFIC_MODES, normalize_honorifics
    from .line_restore import restore_line_breaks
    from .models import MODELS, Backend, ModelConfig
    from .translator import HachimiTranslator

__all__ = [
    "HachimiTranslator",
    "Backend",
    "ModelConfig",
    "MODELS",
    "HardwareProfile",
    "detect_hardware_profile",
    "normalize_honorifics",
    "HONORIFIC_MODES",
    "restore_line_breaks",
]


def __getattr__(name: str):
    module_for = {
        "HachimiTranslator": "translator",
        "Backend": "models",
        "ModelConfig": "models",
        "MODELS": "models",
        "HardwareProfile": "hardware",
        "detect_hardware_profile": "hardware",
        "normalize_honorifics": "honorific_normalize",
        "HONORIFIC_MODES": "honorific_normalize",
        "restore_line_breaks": "line_restore",
    }
    if name in module_for:
        mod = importlib.import_module(f"{__name__}.{module_for[name]}")
        value = getattr(mod, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
