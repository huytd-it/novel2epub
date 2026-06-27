"""Startup-safe CTranslate2 import helpers."""
from __future__ import annotations

import importlib
import importlib.abc
import sys
from contextlib import contextmanager
from types import ModuleType
from typing import Iterator


class _OptionalTorchBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        del path, target
        if fullname == "torch" or fullname.startswith("torch."):
            raise ImportError("Blocked optional torch import during CTranslate2 startup.")
        return None


@contextmanager
def block_optional_torch_import() -> Iterator[None]:
    if "torch" in sys.modules:
        yield
        return
    blocker = _OptionalTorchBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        try:
            sys.meta_path.remove(blocker)
        except ValueError:
            pass


def import_ctranslate2(*, block_torch: bool = True) -> ModuleType:
    existing = sys.modules.get("ctranslate2")
    if existing is not None:
        return existing
    if not block_torch:
        return importlib.import_module("ctranslate2")
    with block_optional_torch_import():
        return importlib.import_module("ctranslate2")
