"""HachimiMT translation engine — port from ngocdang83/HachimiMT-demo."""
from __future__ import annotations

from .translator import HachimiTranslator, Backend, ModelConfig, MODELS
from .hardware import HardwareProfile, detect_hardware_profile
from .honorific_normalize import normalize_honorifics, HONORIFIC_MODES
from .line_restore import restore_line_breaks

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
