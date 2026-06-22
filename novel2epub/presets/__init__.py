"""Named presets for CLI translator configuration.

Each module exports a `load_preset(name: str) -> dict` that returns a flat
dictionary of CliTranslatorConfig overrides.  Loaded by `config.load_config()`
when `translate.preset` is set.
"""

from __future__ import annotations

import importlib
from typing import Any

_PRESETS: dict[str, str] = {"go": "novel2epub.presets.go"}


def available() -> list[str]:
    return sorted(_PRESETS)


def load(name: str) -> dict[str, Any]:
    mod_path = _PRESETS.get(name)
    if mod_path is None:
        raise ValueError(
            f"Unknown translate.preset: {name!r}. "
            f"Available: {', '.join(available())}"
        )
    mod = importlib.import_module(mod_path)
    return mod.load_preset()
