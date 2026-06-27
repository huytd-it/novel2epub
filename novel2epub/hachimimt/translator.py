"""HachimiMT Marian translation backend — port from ngocdang83/HachimiMT-demo."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator

import sentencepiece as spm
from huggingface_hub import snapshot_download

from .chunker import split_chunks
from .hardware import (
    HardwareProfile,
    auto_all_gpus_by_default,
    detect_hardware_profile,
    resolve_gpu_indices,
)
from .line_restore import (
    assemble_paragraph_output,
    assemble_sentence_output,
    paragraph_chunk_fallback_indices,
    split_layout_lines,
)
from .token_chunker import (
    source_token_ids,
    split_for_translation,
    split_paragraphs_with_plan,
    split_sentence_lines_with_plan,
)
from .ct2_safe_import import import_ctranslate2

ctranslate2 = import_ctranslate2()

ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = Path(os.environ.get("HACHIMIMT_MODELS_DIR", ROOT / "models"))
SPECIAL_ID_TO_TOKEN = {0: "<pad>", 1: "<s>", 2: "</s>", 3: "<unk>"}
SPECIAL_TOKEN_TO_ID = {token: token_id for token_id, token in SPECIAL_ID_TO_TOKEN.items()}
EOS_TOKEN_ID = 2


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


def _ct2_download_patterns(config: ModelConfig) -> list[str]:
    return [
        "config.json",
        "generation_config.json",
        "source.spm",
        "target.spm",
        "tokenizer.json",
        "vocab.json",
        "tokenizer_config.json",
        f"{config.ct2_subdir}/*",
    ]


def _ct2_repo_id(config: ModelConfig) -> str:
    return config.ct2_model_id or config.model_id


SourceTokenJobs = list[Future[list[list[str]]]]


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 1024) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(min_value, min(max_value, int(raw)))
    except ValueError:
        return default


def _batched(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start: start + size]


def default_ct2_window_multiplier(profile: HardwareProfile) -> int:
    if profile.has_cuda:
        return 16
    return 4


def default_ct2_compute_type(device: str) -> str:
    env_compute_type = os.environ.get("HACHIMIMT_COMPUTE_TYPE", "").strip()
    if env_compute_type:
        return env_compute_type
    return "int8_float16" if device == "cuda" else "int8_float32"


def _ct2_gpu_index_attempts(gpu_indices: list[int]) -> list[list[int]]:
    if len(gpu_indices) <= 1:
        return [list(gpu_indices)]
    return [list(gpu_indices), [gpu_indices[0]]]


def _ct2_translator_kwargs(
    *,
    device: str,
    compute_type: str,
    intra_threads: int,
    inter_threads: int,
    gpu_indices: list[int] | None = None,
) -> tuple[dict[str, object], int, str | None]:
    actual_inter_threads = max(1, int(inter_threads))
    requested_intra_threads = max(1, int(intra_threads))
    kwargs: dict[str, object] = dict(
        device=device,
        compute_type=compute_type,
        inter_threads=actual_inter_threads,
    )
    worker_count = actual_inter_threads
    device_indices_label = None
    if device != "cuda":
        kwargs["intra_threads"] = max(1, requested_intra_threads // worker_count)
        return kwargs, worker_count, device_indices_label

    if not gpu_indices:
        raise RuntimeError("Không có GPU CUDA khả dụng.")
    selected = list(dict.fromkeys(gpu_indices))
    if len(selected) == 1:
        kwargs["device_index"] = selected[0]
    else:
        kwargs["device_index"] = selected
        kwargs["inter_threads"] = 1

    actual_inter_threads = int(kwargs["inter_threads"])
    worker_count = len(selected) * actual_inter_threads
    kwargs["intra_threads"] = max(1, requested_intra_threads // worker_count)
    device_indices_label = ",".join(str(i) for i in selected)
    return kwargs, worker_count, device_indices_label


@lru_cache(maxsize=1)
def _torch_import_probe_ok(timeout_s: float = 8.0) -> bool:
    code = "import torch"
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except Exception:
        return False
    return result.returncode == 0


@lru_cache(maxsize=1)
def _optional_torch():
    if "torch" not in sys.modules and not _torch_import_probe_ok():
        return None
    try:
        import torch
    except Exception:
        return None
    return torch


def _require_torch():
    torch = _optional_torch()
    if torch is None:
        raise RuntimeError(
            "Backend PyTorch cần cài torch. Engine mặc định CTranslate2 không cần torch."
        )
    return torch


class CT2SentencePieceTokenizer:
    """Minimal Marian SentencePiece tokenizer for CTranslate2 inference."""

    pad_token_id = 0

    def __init__(self, model_path: Path) -> None:
        self._source_sp = spm.SentencePieceProcessor(model_file=str(model_path / "source.spm"))
        self._target_sp = spm.SentencePieceProcessor(model_file=str(model_path / "target.spm"))
        self._encode_cache_max = _env_int("HACHIMIMT_TOKEN_CACHE_SIZE", 0, min_value=0, max_value=500_000)
        self._encode_cache: OrderedDict[str, list[int]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    def _full_encode_one(self, text: str) -> list[int]:
        if self._encode_cache_max > 0:
            cached = self._encode_cache.get(text)
            if cached is not None:
                self._encode_cache.move_to_end(text)
                self._cache_hits += 1
                return list(cached)
        self._cache_misses += 1
        token_ids = list(self._source_sp.encode(text, out_type=int))
        token_ids.append(EOS_TOKEN_ID)
        if self._encode_cache_max > 0:
            self._encode_cache[text] = list(token_ids)
            self._encode_cache.move_to_end(text)
            while len(self._encode_cache) > self._encode_cache_max:
                self._encode_cache.popitem(last=False)
        return token_ids

    def cache_stats(self) -> dict[str, int]:
        return {
            "token_cache_entries": len(self._encode_cache),
            "token_cache_hits": self._cache_hits,
            "token_cache_misses": self._cache_misses,
        }

    def _encode_one(self, text: str, *, truncation: bool = False, max_length: int | None = None) -> list[int]:
        token_ids = self._full_encode_one(text)
        if truncation and max_length is not None and len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
            if token_ids:
                token_ids[-1] = EOS_TOKEN_ID
        return token_ids

    def __call__(self, text_or_texts: str | list[str], *, truncation: bool = False, max_length: int | None = None, padding: bool = False) -> dict[str, list[int] | list[list[int]]]:
        del padding
        if isinstance(text_or_texts, str):
            return {"input_ids": self._encode_one(text_or_texts, truncation=truncation, max_length=max_length)}
        return {
            "input_ids": [
                self._encode_one(text, truncation=truncation, max_length=max_length)
                for text in text_or_texts
            ]
        }

    def convert_ids_to_tokens(self, token_ids: list[int]) -> list[str]:
        tokens: list[str] = []
        for token_id in token_ids:
            if token_id in SPECIAL_ID_TO_TOKEN:
                tokens.append(SPECIAL_ID_TO_TOKEN[token_id])
            else:
                tokens.append(self._source_sp.id_to_piece(int(token_id)))
        return tokens

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[int]:
        token_ids: list[int] = []
        for token in tokens:
            if token in SPECIAL_TOKEN_TO_ID:
                token_ids.append(SPECIAL_TOKEN_TO_ID[token])
            else:
                token_ids.append(int(self._target_sp.piece_to_id(token)))
        return token_ids

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool = True) -> str:
        return self.batch_decode([token_ids], skip_special_tokens=skip_special_tokens)[0]

    def batch_decode(self, token_ids_batch: list[list[int]], *, skip_special_tokens: bool = True) -> list[str]:
        decoded: list[str] = []
        for token_ids in token_ids_batch:
            if skip_special_tokens:
                token_ids = [token_id for token_id in token_ids if token_id not in SPECIAL_ID_TO_TOKEN]
            pieces = [self._target_sp.id_to_piece(int(token_id)) for token_id in token_ids]
            decoded.append(self._target_sp.decode(pieces))
        return decoded

    def decode_tokens_batch(self, tokens_batch: list[list[str]]) -> list[str]:
        decoded: list[str] = []
        for tokens in tokens_batch:
            pieces = [token for token in tokens if token not in SPECIAL_TOKEN_TO_ID]
            decoded.append(self._target_sp.decode(pieces).strip())
        return decoded


class CT2FastTokenizer:
    """Minimal tokenizer.json wrapper for CTranslate2 inference."""

    def __init__(self, model_path: Path) -> None:
        try:
            from tokenizers import Tokenizer
        except Exception as exc:
            raise RuntimeError("Model này dùng tokenizer.json; cần cài package tokenizers.") from exc
        self._tokenizer = Tokenizer.from_file(str(model_path / "tokenizer.json"))
        self.pad_token_id = self._tokenizer.token_to_id("<pad>")
        self._eos_token_id = self._tokenizer.token_to_id("</s>")
        self._encode_cache_max = _env_int("HACHIMIMT_TOKEN_CACHE_SIZE", 0, min_value=0, max_value=500_000)
        self._encode_cache: OrderedDict[str, list[int]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    def _full_encode_one(self, text: str) -> list[int]:
        if self._encode_cache_max > 0:
            cached = self._encode_cache.get(text)
            if cached is not None:
                self._encode_cache.move_to_end(text)
                self._cache_hits += 1
                return list(cached)
        self._cache_misses += 1
        token_ids = list(self._tokenizer.encode(text).ids)
        if self._encode_cache_max > 0:
            self._encode_cache[text] = list(token_ids)
            self._encode_cache.move_to_end(text)
            while len(self._encode_cache) > self._encode_cache_max:
                self._encode_cache.popitem(last=False)
        return token_ids

    def cache_stats(self) -> dict[str, int]:
        return {
            "token_cache_entries": len(self._encode_cache),
            "token_cache_hits": self._cache_hits,
            "token_cache_misses": self._cache_misses,
        }

    def _encode_one(self, text: str, *, truncation: bool = False, max_length: int | None = None) -> list[int]:
        token_ids = self._full_encode_one(text)
        if truncation and max_length is not None and len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
            if token_ids and self._eos_token_id is not None:
                token_ids[-1] = self._eos_token_id
        return token_ids

    def __call__(self, text_or_texts: str | list[str], *, truncation: bool = False, max_length: int | None = None, padding: bool = False) -> dict[str, list[int] | list[list[int]]]:
        del padding
        if isinstance(text_or_texts, str):
            return {"input_ids": self._encode_one(text_or_texts, truncation=truncation, max_length=max_length)}
        return {
            "input_ids": [
                self._encode_one(text, truncation=truncation, max_length=max_length)
                for text in text_or_texts
            ]
        }

    def convert_ids_to_tokens(self, token_ids: list[int]) -> list[str]:
        tokens: list[str] = []
        for token_id in token_ids:
            token = self._tokenizer.id_to_token(int(token_id))
            if token is None:
                raise ValueError(f"Token id không có trong vocab: {token_id}")
            tokens.append(token)
        return tokens

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[int]:
        token_ids: list[int] = []
        for token in tokens:
            token_id = self._tokenizer.token_to_id(token)
            if token_id is None:
                raise ValueError(f"Token không có trong vocab: {token!r}")
            token_ids.append(int(token_id))
        return token_ids

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool = True) -> str:
        return self.batch_decode([token_ids], skip_special_tokens=skip_special_tokens)[0]

    def batch_decode(self, token_ids_batch: list[list[int]], *, skip_special_tokens: bool = True) -> list[str]:
        return [
            self._tokenizer.decode(token_ids, skip_special_tokens=skip_special_tokens)
            for token_ids in token_ids_batch
        ]

    def decode_tokens_batch(self, tokens_batch: list[list[str]]) -> list[str]:
        token_ids_batch = [self.convert_tokens_to_ids(tokens) for tokens in tokens_batch]
        return [text.strip() for text in self.batch_decode(token_ids_batch, skip_special_tokens=True)]


def _load_ct2_tokenizer(model_path: Path):
    if (model_path / "source.spm").exists() and (model_path / "target.spm").exists():
        return CT2SentencePieceTokenizer(model_path)
    if (model_path / "tokenizer.json").exists():
        return CT2FastTokenizer(model_path)
    raise RuntimeError("Không tìm thấy tokenizer CT2: cần source.spm/target.spm hoặc tokenizer.json.")


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


def ensure_model_files(config: ModelConfig, backend: Backend) -> Path:
    local_dir = model_local_dir(config)
    local_dir.mkdir(parents=True, exist_ok=True)

    if backend == Backend.CT2:
        if _ct2_ready(local_dir, config.ct2_subdir) and _tokenizer_ready(local_dir):
            return local_dir
        patterns = _ct2_download_patterns(config)
        repo_id = _ct2_repo_id(config)
    else:
        if _pytorch_ready(local_dir) and _tokenizer_ready(local_dir):
            return local_dir
        patterns = None
        repo_id = config.model_id

    snapshot_download(repo_id, local_dir=str(local_dir), allow_patterns=patterns)
    return local_dir


class HachimiTranslator:
    def __init__(self, profile: HardwareProfile | None = None) -> None:
        self._profile = profile or detect_hardware_profile()
        self._torch_device = "cpu"
        self._model_key: str | None = None
        self._backend: Backend | None = None
        self._tokenizer = None
        self._torch_model = None
        self._ct2_model = None
        self._model_path: Path | None = None
        self._ct2_threads = self._profile.ct2_threads
        self._ct2_inter_threads = _env_int("HACHIMIMT_INTER_THREADS", 1, max_value=8)
        self._ct2_window_multiplier = _env_int(
            "HACHIMIMT_CT2_WINDOW_MULTIPLIER",
            default_ct2_window_multiplier(self._profile),
            max_value=16,
        )
        self._tokenize_job_size = _env_int("HACHIMIMT_TOKENIZE_JOB_SIZE", 32, max_value=256)
        batch_type = os.environ.get("HACHIMIMT_CT2_BATCH_TYPE", "tokens").strip().lower()
        self._ct2_batch_type = batch_type if batch_type in {"examples", "tokens"} else "tokens"
        self._ct2_compute_type: str | None = None
        self._ct2_actual_intra_threads = self._ct2_threads
        self._ct2_actual_inter_threads = self._ct2_inter_threads
        self._ct2_worker_count = 1
        self._ct2_device_indices_label: str | None = None
        self._batch_size = self._profile.batch_size
        self._tokenize_workers = self._profile.tokenize_workers
        self._tokenize_pool: ThreadPoolExecutor | None = None
        self._last_profile: dict[str, float | int | str] = {}

    @property
    def hardware_profile(self) -> HardwareProfile:
        return self._profile

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def backend(self) -> Backend | None:
        return self._backend

    @property
    def model_key(self) -> str | None:
        return self._model_key

    def set_batch_size(self, batch_size: int) -> None:
        self._batch_size = max(4, min(128, int(batch_size)))

    @property
    def device(self) -> str:
        if self._backend == Backend.CT2 and self._ct2_model is not None:
            return self._ct2_model.device
        return self._torch_device

    def device_label(self) -> str:
        if self.device == "cuda":
            return self._profile.gpu_name or "CUDA GPU"
        return "CPU"

    def load(self, model_key: str = DEFAULT_MODEL_KEY, backend: Backend | str = Backend.CT2) -> str:
        if isinstance(backend, str):
            backend = Backend(backend)
        if model_key not in MODELS:
            raise ValueError(f"Unknown model: {model_key}")

        if (
            self._model_key == model_key
            and self._backend == backend
            and self._tokenizer is not None
            and (self._ct2_model is not None or self._torch_model is not None)
        ):
            return f"Model {MODELS[model_key].label} already loaded ({self.device_label()})"

        config = MODELS[model_key]
        self._unload_models()

        if backend == Backend.CT2:
            self._load_ct2(config)
        else:
            self._load_transformers(config)

        self._model_key = model_key
        self._backend = backend

        try:
            self.translate_chunk("你好。", beam_size=1)
        except Exception:
            pass

        return self._status_message(model_key, backend)

    def _status_message(self, model_key: str, backend: Backend, *, beam_size: int | None = None) -> str:
        config = MODELS[model_key]
        engine = "CTranslate2 INT8" if backend == Backend.CT2 else "PyTorch"
        return f"Đã tải {config.label} · {engine} · {self.device_label()}"

    @staticmethod
    def clamp_beam(beam_size: int) -> int:
        return max(1, min(4, int(beam_size)))

    def _unload_models(self) -> None:
        self._torch_model = None
        self._ct2_model = None
        self._tokenizer = None
        self._model_path = None
        self._ct2_compute_type = None
        self._ct2_actual_intra_threads = self._ct2_threads
        self._ct2_actual_inter_threads = self._ct2_inter_threads
        self._ct2_worker_count = 1
        self._ct2_device_indices_label = None
        if self._tokenize_pool is not None:
            self._tokenize_pool.shutdown(wait=False, cancel_futures=True)
            self._tokenize_pool = None

    def _get_tokenize_pool(self) -> ThreadPoolExecutor:
        if self._tokenize_pool is None:
            self._tokenize_pool = ThreadPoolExecutor(
                max_workers=self._tokenize_workers,
                thread_name_prefix="hachimi-tokenize",
            )
        return self._tokenize_pool

    def _tokenize_chunks_parallel(self, chunks: list[str]) -> list[list[str]]:
        if not chunks:
            return []
        if len(chunks) <= self._tokenize_job_size or self._tokenize_workers <= 1:
            return self._source_tokens_batch(chunks)
        pool = self._get_tokenize_pool()
        groups = list(_batched(chunks, self._tokenize_job_size))
        nested = pool.map(self._source_tokens_batch, groups)
        return [tokens for group in nested for tokens in group]

    def _submit_tokenize_jobs(self, chunks: list[str]) -> SourceTokenJobs:
        pool = self._get_tokenize_pool()
        return [
            pool.submit(self._source_tokens_batch, group)
            for group in _batched(chunks, self._tokenize_job_size)
        ]

    @staticmethod
    def _collect_tokenize_jobs(jobs: SourceTokenJobs) -> list[list[str]]:
        return [tokens for job in jobs for tokens in job.result()]

    def _decode_ct2_results(self, results) -> list[str]:
        start = time.perf_counter()
        hypotheses = [result.hypotheses[0] for result in results]
        decode_tokens_batch = getattr(self._tokenizer, "decode_tokens_batch", None)
        if callable(decode_tokens_batch):
            decoded = decode_tokens_batch(hypotheses)
            self._profile_add("decode_s", time.perf_counter() - start)
            return decoded
        token_ids = [self._tokenizer.convert_tokens_to_ids(tokens) for tokens in hypotheses]
        decoded = [text.strip() for text in self._tokenizer.batch_decode(token_ids, skip_special_tokens=True)]
        self._profile_add("decode_s", time.perf_counter() - start)
        return decoded

    def _load_ct2(self, config: ModelConfig) -> None:
        model_path = ensure_model_files(config, Backend.CT2)
        tokenizer = _load_ct2_tokenizer(model_path)
        env_compute_type = os.environ.get("HACHIMIMT_COMPUTE_TYPE", "").strip()
        ct2_device = "cuda" if self._profile.has_cuda else "cpu"
        attempts: list[tuple[str, str, list[int] | None]] = []
        if ct2_device == "cuda":
            try:
                cuda_count = ctranslate2.get_cuda_device_count()
            except Exception:
                cuda_count = 0
            gpu_indices = resolve_gpu_indices(
                cuda_count,
                os.environ.get("HACHIMIMT_GPU_INDICES"),
                auto_all=auto_all_gpus_by_default(),
            )
            compute_types = [default_ct2_compute_type("cuda")]
            if not env_compute_type and "int8_float32" not in compute_types:
                compute_types.append("int8_float32")
            for compute_type in compute_types:
                for candidate_indices in _ct2_gpu_index_attempts(gpu_indices):
                    attempts.append(("cuda", compute_type, candidate_indices))
            attempts.append(("cpu", "int8_float32", None))
        else:
            cpu_compute_type = default_ct2_compute_type("cpu")
            attempts.append(("cpu", cpu_compute_type, None))
            if cpu_compute_type != "int8_float32":
                attempts.append(("cpu", "int8_float32", None))

        translator = None
        last_error: Exception | None = None
        for device, compute_type, gpu_indices in attempts:
            try:
                kwargs, worker_count, device_indices_label = _ct2_translator_kwargs(
                    device=device,
                    compute_type=compute_type,
                    intra_threads=self._ct2_threads,
                    inter_threads=self._ct2_inter_threads,
                    gpu_indices=gpu_indices,
                )
                translator = ctranslate2.Translator(str(model_path / config.ct2_subdir), **kwargs)
                self._ct2_compute_type = compute_type
                self._ct2_actual_intra_threads = int(kwargs["intra_threads"])
                self._ct2_actual_inter_threads = int(kwargs["inter_threads"])
                self._ct2_worker_count = worker_count
                self._ct2_device_indices_label = device_indices_label
                break
            except Exception as exc:
                last_error = exc

        if translator is None:
            raise RuntimeError("Không tải được CTranslate2 backend.") from last_error

        self._tokenizer = tokenizer
        self._ct2_model = translator
        self._model_path = model_path

    def _load_transformers(self, config: ModelConfig) -> None:
        torch = _require_torch()
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, MarianMTModel
        except Exception as exc:
            raise RuntimeError("Backend PyTorch cần transformers. Cài thêm: pip install transformers") from exc

        model_path = ensure_model_files(config, Backend.TRANSFORMERS)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        try:
            self._torch_device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            self._torch_device = "cpu"
        if config.use_marian_class:
            model = MarianMTModel.from_pretrained(model_path)
        else:
            model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        model = model.to(self._torch_device).eval()
        self._tokenizer = tokenizer
        self._torch_model = model

    def _chunk_text(self, text: str, chunk_mode: str) -> list[str]:
        config = MODELS[self._model_key]
        if self._backend == Backend.CT2 and self._tokenizer is not None:
            return split_for_translation(
                self._tokenizer, text, max_tokens=config.ct2_max_input_tokens, chunk_mode=chunk_mode,
            )
        return split_chunks(text, mode=chunk_mode)

    def _source_tokens(self, text: str) -> list[str]:
        config = MODELS[self._model_key]
        token_ids = source_token_ids(self._tokenizer, text, max_length=config.ct2_max_input_tokens, truncation=True)
        return self._tokenizer.convert_ids_to_tokens(token_ids)

    def _source_tokens_batch(self, chunks: list[str]) -> list[list[str]]:
        config = MODELS[self._model_key]
        encoded = self._tokenizer(chunks, truncation=True, max_length=config.ct2_max_input_tokens, padding=False)["input_ids"]
        pad_id = self._tokenizer.pad_token_id
        if pad_id is not None:
            encoded = [[token_id for token_id in token_ids if token_id != pad_id] for token_ids in encoded]
        return [self._tokenizer.convert_ids_to_tokens(token_ids) for token_ids in encoded]

    def _torch_generate_kwargs(self, beam_size: int) -> dict:
        config = MODELS[self._model_key]
        kwargs = dict(config.generate_kwargs)
        kwargs["num_beams"] = beam_size
        if config.use_marian_class:
            kwargs["early_stopping"] = beam_size > 1
        return kwargs

    def _runtime_batch_size(self, beam_size: int) -> int:
        if self._backend == Backend.CT2:
            return self._batch_size
        beam_size = self.clamp_beam(beam_size)
        vram_factor = max(1, beam_size * 2)
        return max(4, min(self._batch_size, 48 // vram_factor))

    def _runtime_window_size(self, beam_size: int) -> int:
        batch_size = self._runtime_batch_size(beam_size)
        if self._backend == Backend.CT2:
            return max(batch_size, batch_size * self._ct2_effective_window_multiplier())
        return batch_size

    def _ct2_effective_window_multiplier(self) -> int:
        multiplier = self._ct2_window_multiplier
        if self._ct2_batch_type == "tokens" and self._ct2_worker_count > 1:
            multiplier *= min(self._ct2_worker_count * 4, 8)
        return max(1, min(32, multiplier))

    def _ct2_max_batch_size(self, config: ModelConfig) -> int:
        if self._ct2_batch_type == "tokens":
            return self._batch_size * config.ct2_max_input_tokens
        return self._batch_size

    def _translate_torch_batch(self, chunks: list[str], *, beam_size: int) -> list[str]:
        if not chunks:
            return []
        torch = _require_torch()
        config = MODELS[self._model_key]
        max_length = 256 if config.use_marian_class else 512
        inputs = self._tokenizer(chunks, return_tensors="pt", padding=True, truncation=True, max_length=max_length).to(self._torch_device)
        with torch.inference_mode():
            outputs = self._torch_model.generate(**inputs, **self._torch_generate_kwargs(beam_size))
        return [self._tokenizer.decode(output, skip_special_tokens=True).strip() for output in outputs]

    def _profile_add(self, key: str, seconds: float) -> None:
        self._last_profile[key] = float(self._last_profile.get(key, 0.0)) + seconds

    def _profile_set(self, key: str, value: float | int | str) -> None:
        self._last_profile[key] = value

    def _reset_profile(self) -> None:
        self._last_profile = {}

    @staticmethod
    def _ct2_repetition_kwargs(config: "ModelConfig") -> dict:
        gk = config.generate_kwargs
        kwargs = {}
        if "no_repeat_ngram_size" in gk:
            kwargs["no_repeat_ngram_size"] = gk["no_repeat_ngram_size"]
        if "repetition_penalty" in gk:
            kwargs["repetition_penalty"] = gk["repetition_penalty"]
        return kwargs

    def translate_chunk(self, text: str, *, beam_size: int = 2) -> str:
        if self._tokenizer is None:
            raise RuntimeError("Chưa tải model. Gọi load() trước.")
        beam_size = self.clamp_beam(beam_size)
        if self._backend == Backend.CT2:
            return self._translate_chunks_ct2([text], beam_size=beam_size)[0]
        return self._translate_torch_batch([text], beam_size=beam_size)[0]

    def _translate_ct2_batch(self, chunks: list[str], *, beam_size: int, source_batches: list[list[str]] | None = None) -> list[str]:
        config = MODELS[self._model_key]
        if source_batches is None:
            tokenize_start = time.perf_counter()
            source_batches = self._tokenize_chunks_parallel(chunks)
            self._profile_add("tokenize_s", time.perf_counter() - tokenize_start)
        infer_start = time.perf_counter()
        results = self._ct2_model.translate_batch(
            source_batches,
            max_batch_size=self._ct2_max_batch_size(config),
            batch_type=self._ct2_batch_type,
            beam_size=beam_size,
            max_decoding_length=config.ct2_max_output_tokens,
            **self._ct2_repetition_kwargs(config),
        )
        self._profile_add("ct2_infer_s", time.perf_counter() - infer_start)
        return self._decode_ct2_results(results)

    def _translate_chunks_ct2(self, chunks: list[str], *, beam_size: int) -> list[str]:
        if self._ct2_model is None:
            raise RuntimeError("CTranslate2 chưa được tải.")
        beam_size = self.clamp_beam(beam_size)
        if not chunks:
            return []
        return self._translate_ct2_batch(chunks, beam_size=beam_size)

    def translate_lines(self, lines: list[str], *, beam_size: int = 2, chunk_mode: str = "sentence") -> list[str]:
        if not self._model_key or not self._backend:
            raise RuntimeError("Chưa tải model. Gọi load() trước.")
        config = MODELS[self._model_key]
        beam_size = self.clamp_beam(beam_size)

        if self._backend == Backend.CT2 and self._tokenizer is not None:
            all_chunks: list[str] = []
            line_chunk_map: list[list[int]] = []
            for line in lines:
                if not line.strip():
                    line_chunk_map.append([])
                    continue
                if chunk_mode == "sentence":
                    from .token_chunker import sentence_chunks
                    chunks = sentence_chunks(self._tokenizer, line, max_tokens=config.ct2_max_input_tokens)
                else:
                    from .token_chunker import split_for_translation
                    chunks = split_for_translation(self._tokenizer, line, max_tokens=config.ct2_max_input_tokens, chunk_mode="paragraph")
                indices = list(range(len(all_chunks), len(all_chunks) + len(chunks)))
                all_chunks.extend(chunks)
                line_chunk_map.append(indices)

            translated_chunks = self._translate_chunks_ct2(all_chunks, beam_size=beam_size)

            out_lines: list[str] = []
            for indices in line_chunk_map:
                if not indices:
                    out_lines.append("")
                else:
                    out_lines.append(" ".join(translated_chunks[i] for i in indices).strip())
            return out_lines

        out_lines = []
        for line in lines:
            if not line.strip():
                out_lines.append("")
                continue
            out_lines.append(self.translate_chunk(line, beam_size=beam_size))
        return out_lines

    def translate_text(self, text: str, *, beam_size: int = 2, chunk_mode: str = "sentence") -> str:
        lines = text.split("\n")
        translated = self.translate_lines(lines, beam_size=beam_size, chunk_mode=chunk_mode)
        return "\n".join(translated)
