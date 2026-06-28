"""True vLLM KV-transfer handoff helpers.

This module is intentionally separate from ``vllm_cache_runtime.py``.
``vllm_cache_runtime`` wraps vLLM prefix caching by reusing the same textual
prefix. This module configures vLLM's experimental KV transfer connector so the
runtime saves/loads actual KV cache tensors through a connector backend.

The first supported backend is vLLM's ``SharedStorageConnector``. It persists
KV tensors to a shared storage directory and loads them in a later Agent/LLM
instance keyed by the same token sequence. This is a real model-intermediate
state transfer path, not just an application-level text-summary handoff.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any



@dataclass
class TrueKVHandoffHandle:
    """Serializable handle for a real vLLM KV-transfer artifact."""

    handoff_id: str
    backend: str
    connector: str
    storage_path: str
    model_path: str
    token_hash: str
    prompt_tokens: int
    prompt_chars: int
    producer_agent: str
    created_at: float
    prompt_text_required_for_lookup: bool = True
    note: str = (
        "The handle points to KV tensors stored by vLLM KVTransferConfig. "
        "The same token prefix is still used as lookup key, but the cached K/V "
        "tensors are saved and loaded by the connector."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_shared_storage_kv_transfer_config(storage_path: str | Path) -> dict[str, Any]:
    """Return a vLLM KVTransferConfig payload for true KV transfer.

    ``SharedStorageConnector`` is the least intrusive vLLM-provided connector
    for an offline proof: producer and consumer LLM instances can share a local
    directory containing KV tensors written by safetensors.
    """

    return {
        "kv_connector": "SharedStorageConnector",
        "kv_role": "kv_both",
        "kv_connector_extra_config": {
            "shared_storage_path": str(storage_path),
        },
    }


def _env_bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


def _env_float(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def _model_path() -> str:
    return os.environ.get("VLLM_MODEL_PATH", os.environ.get("LOCAL_MODEL_PATH", "/data/models/Qwen3-8B"))


def build_llm_kwargs(*, storage_path: str | Path, enable_prefix_caching: bool = False) -> dict[str, Any]:
    """Build LLM kwargs with vLLM's real KV transfer connector enabled."""

    from vllm.config import KVTransferConfig

    transfer_config = build_shared_storage_kv_transfer_config(storage_path)
    kwargs: dict[str, Any] = {
        "model": _model_path(),
        "dtype": os.environ.get("VLLM_DTYPE", os.environ.get("LOCAL_MODEL_DTYPE", "bfloat16")),
        "max_model_len": _env_int("VLLM_MAX_MODEL_LEN", "8192"),
        "max_num_seqs": _env_int("VLLM_MAX_NUM_SEQS", "4"),
        "max_num_batched_tokens": _env_int("VLLM_MAX_NUM_BATCHED_TOKENS", "4096"),
        "gpu_memory_utilization": _env_float("VLLM_GPU_MEMORY_UTILIZATION", "0.85"),
        "tensor_parallel_size": _env_int("VLLM_TENSOR_PARALLEL_SIZE", "1"),
        "trust_remote_code": _env_bool("VLLM_TRUST_REMOTE_CODE", "1"),
        "enable_prefix_caching": enable_prefix_caching,
        "kv_transfer_config": KVTransferConfig.from_cli(json.dumps(transfer_config)),
    }
    if _env_bool("VLLM_ENFORCE_EAGER", "1"):
        kwargs["enforce_eager"] = True
    return kwargs


def ensure_storage_path(path: str | Path) -> Path:
    storage = Path(path)
    storage.mkdir(parents=True, exist_ok=True)
    return storage


def make_handoff_handle(
    *,
    prompt: str,
    prompt_tokens: int,
    storage_path: str | Path,
    producer_agent: str,
    model_path: str | None = None,
) -> TrueKVHandoffHandle:
    token_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    handoff_id = f"true-kv-{producer_agent}-{token_hash}"
    return TrueKVHandoffHandle(
        handoff_id=handoff_id,
        backend="vllm_kv_transfer",
        connector="SharedStorageConnector",
        storage_path=str(storage_path),
        model_path=model_path or _model_path(),
        token_hash=token_hash,
        prompt_tokens=prompt_tokens,
        prompt_chars=len(prompt),
        producer_agent=producer_agent,
        created_at=time.time(),
    )


def describe_runtime_contract() -> dict[str, Any]:
    """Machine-readable contract used by docs/tests."""

    return {
        "strict_true_kv_handoff": True,
        "uses_vllm_kv_transfer_config": True,
        "connector": "SharedStorageConnector",
        "transferred_state": "KV cache tensors saved/loaded by vLLM connector",
        "not_text_only": True,
        "lookup_key": "exact same prompt token sequence",
        "limitations": [
            "vLLM still requires the same prompt tokens as the connector lookup key.",
            "The public LLM.generate API does not accept an opaque kv_handle + suffix-only request.",
            "This proof demonstrates real KV tensor transfer between vLLM instances, not source-prefix removal from request tokenization.",
        ],
    }


def default_storage_path() -> Path:
    return Path(os.environ.get(
        "TRUE_KV_SHARED_STORAGE_PATH",
        "/data/mingwei/SynapseX/exp/kv_cache_exp/true_kv_shared_storage",
    ))
