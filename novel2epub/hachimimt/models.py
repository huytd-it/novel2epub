"""Danh mục model Local MT — metadata thuần, KHÔNG import runtime nặng.

Tách khỏi `translator.py` để trang quản lý model (`settings.py`) chỉ cần đọc
danh sách/trạng thái model mà không kéo theo `ctranslate2`, `sentencepiece`,
`huggingface_hub`. Những dep đó chỉ cần khi thực sự TẢI/dịch, ở
`translator.py`/`download.py`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Backend(str, Enum):
    CT2 = "ct2"
    TRANSFORMERS = "transformers"


@dataclass(frozen=True)
class ModelConfig:
    label: str
    model_id: str
    use_marian_class: bool
    generate_kwargs: dict
    ct2_max_input_tokens: int
    ct2_max_output_tokens: int
    ct2_max_batch_size: int = 8
    default_beam: int = 2
    ct2_size_mb: int | None = None
    ct2_subdir: str = "ct2-int8_float32"
    ct2_model_id: str | None = None


MODELS: dict[str, ModelConfig] = {
    "HachimiMT-60": ModelConfig(
        label="HachimiMT-60",
        model_id="ngocdang83/HachimiMT-60-zh-vi",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            "repetition_penalty": 1.2,
        },
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=300,
        default_beam=2,
        ct2_size_mb=57,
    ),
    "HachimiMT-30": ModelConfig(
        label="HachimiMT-30",
        model_id="ngocdang83/HachimiMT-30-zh-vi",
        use_marian_class=False,
        generate_kwargs={"max_length": 512},
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=1,
        ct2_size_mb=35,
    ),
    "MoxhiMT-60": ModelConfig(
        label="MoxhiMT-60",
        model_id="DanVP/MoxhiMT-60",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            "repetition_penalty": 1.2,
        },
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=300,
        default_beam=2,
        ct2_size_mb=58,
        ct2_subdir="ct2-int8",
    ),
    "MoxhiMT-30": ModelConfig(
        label="MoxhiMT-30",
        model_id="DanVP/MoxhiMT-30",
        use_marian_class=True,
        generate_kwargs={
            "max_new_tokens": 300,
            "repetition_penalty": 1.2,
        },
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=2,
        ct2_size_mb=38,
    ),
    "HirashibaMT-Medium": ModelConfig(
        label="HirashibaMT-Medium",
        model_id="Moleys/hirashiba-mt-medium",
        use_marian_class=True,
        generate_kwargs={"max_new_tokens": 256},
        ct2_max_input_tokens=128,
        ct2_max_output_tokens=256,
        default_beam=4,
        ct2_size_mb=62,
        ct2_model_id="ngungodan/hirashiba-mt-medium-ct2",
    ),
    "HirashibaMT-Tiny": ModelConfig(
        label="HirashibaMT-Tiny",
        model_id="chi-vi/hirashiba-mt-tiny-zh-vi",
        use_marian_class=True,
        generate_kwargs={"max_length": 512},
        ct2_max_input_tokens=160,
        ct2_max_output_tokens=512,
        default_beam=1,
        ct2_size_mb=17,
        ct2_subdir="ct2-int8-keeppad",
        ct2_model_id="ngungodan/hirashiba-mt-tiny-zh-vi-ct2",
    ),
}

DEFAULT_MODEL_KEY = "HachimiMT-60"
DEFAULT_CT2_SUBDIR = "ct2-int8_float32"

# Thư mục gốc chứa model — đặt cạnh DB/workspace (không nằm trong package).
ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = Path(os.environ.get("HACHIMIMT_MODELS_DIR", ROOT / "models"))


def model_local_dir(config: ModelConfig) -> Path:
    return MODELS_DIR / config.model_id.split("/")[-1]


def _ct2_ready(path: Path, ct2_subdir: str = DEFAULT_CT2_SUBDIR) -> bool:
    ct2_path = path / ct2_subdir
    return ct2_path.is_dir() and any(ct2_path.iterdir())


def _pytorch_ready(path: Path) -> bool:
    return any(path.glob("*.safetensors")) or any(path.glob("pytorch_model*.bin"))


def _tokenizer_ready(path: Path) -> bool:
    has_sentencepiece = (path / "source.spm").exists() and (path / "target.spm").exists()
    return has_sentencepiece or (path / "tokenizer.json").exists()


def is_model_downloaded(model_key: str, backend: Backend | str = Backend.CT2) -> bool:
    if isinstance(backend, str):
        backend = Backend(backend)
    if model_key not in MODELS:
        return False
    config = MODELS[model_key]
    path = model_local_dir(config)
    if backend == Backend.CT2:
        weights_ready = _ct2_ready(path, config.ct2_subdir)
    else:
        weights_ready = _pytorch_ready(path)
    return weights_ready and _tokenizer_ready(path)
