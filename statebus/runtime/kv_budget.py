from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


KV_CACHE_MODEL_PROFILE_SCHEMA_VERSION = "statebus.kv_cache_model_profile.v1"
KV_CACHE_FOOTPRINT_ESTIMATE_SCHEMA_VERSION = "statebus.kv_cache_footprint_estimate.v1"
KV_CACHE_CLAIM_BOUNDARY = (
    "model_config_based_kv_cache_sizing_only_not_a_runtime_vllm_allocation_measurement"
)


@dataclass(frozen=True)
class KVCacheModelProfile:
    model_id: str
    num_hidden_layers: int
    num_key_value_heads: int
    head_dim: int
    dtype_bytes: int = 2
    classic_kv_layer_count: int = 0
    config_model_type: str = ""
    architecture: str = ""
    schema_version: str = KV_CACHE_MODEL_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.classic_kv_layer_count <= 0:
            object.__setattr__(self, "classic_kv_layer_count", self.num_hidden_layers)

    @property
    def kv_bytes_per_token(self) -> int:
        return (
            self.classic_kv_layer_count
            * 2
            * self.num_key_value_heads
            * self.head_dim
            * self.dtype_bytes
        )

    def kv_bytes_for_tokens(self, token_count: int) -> int:
        return max(int(token_count), 0) * self.kv_bytes_per_token

    def canonical_payload(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "num_hidden_layers": self.num_hidden_layers,
            "classic_kv_layer_count": self.classic_kv_layer_count,
            "num_key_value_heads": self.num_key_value_heads,
            "head_dim": self.head_dim,
            "dtype_bytes": self.dtype_bytes,
            "kv_bytes_per_token": self.kv_bytes_per_token,
            "config_model_type": self.config_model_type,
            "architecture": self.architecture,
            "claim_boundary": KV_CACHE_CLAIM_BOUNDARY,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class KVCacheFootprintEstimate:
    profile: KVCacheModelProfile
    prompt_tokens: int
    max_output_tokens: int = 0
    target_dtype_bytes: int = 1
    usable_kv_cache_bytes: int = 0
    schema_version: str = KV_CACHE_FOOTPRINT_ESTIMATE_SCHEMA_VERSION

    @property
    def total_sequence_tokens(self) -> int:
        return max(self.prompt_tokens, 0) + max(self.max_output_tokens, 0)

    @property
    def prefill_kv_bytes(self) -> int:
        return self.profile.kv_bytes_for_tokens(self.prompt_tokens)

    @property
    def total_sequence_kv_bytes(self) -> int:
        return self.profile.kv_bytes_for_tokens(self.total_sequence_tokens)

    @property
    def target_dtype_total_sequence_kv_bytes(self) -> int:
        if self.profile.dtype_bytes <= 0:
            return 0
        return int(self.total_sequence_kv_bytes * max(self.target_dtype_bytes, 0) / self.profile.dtype_bytes)

    @property
    def target_dtype_savings_bytes(self) -> int:
        return max(self.total_sequence_kv_bytes - self.target_dtype_total_sequence_kv_bytes, 0)

    @property
    def target_dtype_savings_ratio(self) -> float:
        if self.total_sequence_kv_bytes <= 0:
            return 0.0
        return self.target_dtype_savings_bytes / self.total_sequence_kv_bytes

    @property
    def max_concurrency_at_sequence_len(self) -> float:
        if self.usable_kv_cache_bytes <= 0 or self.total_sequence_kv_bytes <= 0:
            return 0.0
        return self.usable_kv_cache_bytes / self.total_sequence_kv_bytes

    def canonical_payload(self) -> dict[str, object]:
        return {
            "profile": self.profile.canonical_payload(),
            "prompt_tokens": self.prompt_tokens,
            "max_output_tokens": self.max_output_tokens,
            "total_sequence_tokens": self.total_sequence_tokens,
            "prefill_kv_bytes": self.prefill_kv_bytes,
            "total_sequence_kv_bytes": self.total_sequence_kv_bytes,
            "target_dtype_bytes": self.target_dtype_bytes,
            "target_dtype_total_sequence_kv_bytes": self.target_dtype_total_sequence_kv_bytes,
            "target_dtype_savings_bytes": self.target_dtype_savings_bytes,
            "target_dtype_savings_ratio": self.target_dtype_savings_ratio,
            "usable_kv_cache_bytes": self.usable_kv_cache_bytes,
            "max_concurrency_at_sequence_len": self.max_concurrency_at_sequence_len,
            "claim_boundary": KV_CACHE_CLAIM_BOUNDARY,
            "schema_version": self.schema_version,
        }


def load_kv_cache_model_profile(
    model_path: str | Path,
    *,
    model_id: str | None = None,
    dtype_bytes: int = 2,
) -> KVCacheModelProfile:
    config_path = Path(model_path) / "config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return kv_cache_model_profile_from_hf_config(
        payload,
        model_id=model_id or Path(model_path).name,
        dtype_bytes=dtype_bytes,
    )


def kv_cache_model_profile_from_hf_config(
    config: Mapping[str, Any],
    *,
    model_id: str,
    dtype_bytes: int = 2,
) -> KVCacheModelProfile:
    text_config = config.get("text_config")
    model_config = dict(text_config) if isinstance(text_config, Mapping) else dict(config)
    layer_types = model_config.get("layer_types")
    full_attention_layer_count = (
        sum(1 for item in layer_types if str(item) == "full_attention")
        if isinstance(layer_types, list)
        else 0
    )
    return KVCacheModelProfile(
        model_id=model_id,
        num_hidden_layers=int(model_config.get("num_hidden_layers") or 0),
        num_key_value_heads=int(model_config.get("num_key_value_heads") or 0),
        head_dim=int(model_config.get("head_dim") or 0),
        dtype_bytes=max(int(dtype_bytes), 1),
        classic_kv_layer_count=full_attention_layer_count,
        config_model_type=str(model_config.get("model_type", config.get("model_type", ""))),
        architecture=str((config.get("architectures") or [""])[0]),
    )


def estimate_kv_cache_footprint(
    profile: KVCacheModelProfile,
    *,
    prompt_tokens: int,
    max_output_tokens: int = 0,
    target_dtype_bytes: int = 1,
    usable_kv_cache_bytes: int = 0,
) -> KVCacheFootprintEstimate:
    return KVCacheFootprintEstimate(
        profile=profile,
        prompt_tokens=max(int(prompt_tokens), 0),
        max_output_tokens=max(int(max_output_tokens), 0),
        target_dtype_bytes=max(int(target_dtype_bytes), 0),
        usable_kv_cache_bytes=max(int(usable_kv_cache_bytes), 0),
    )


def format_gib(byte_count: int | float) -> float:
    return float(byte_count) / 1024.0 / 1024.0 / 1024.0
