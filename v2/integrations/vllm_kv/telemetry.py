from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from v2.utils import sha256_digest


@dataclass(frozen=True)
class KVProducerTelemetry:
    request_id: str
    task_id: str
    capture_kv: bool
    logical_prompt_tokens: int
    parent_tokens: int
    producer_suffix_tokens: int
    computed_prefill_tokens: int
    generated_tokens: int
    server_first_output_ms: float
    server_wall_ms: float
    kv_store_ms: float = 0.0
    kv_bytes_actual: int = 0
    layer_count: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "capture_kv": self.capture_kv,
            "logical_prompt_tokens": self.logical_prompt_tokens,
            "parent_tokens": self.parent_tokens,
            "producer_suffix_tokens": self.producer_suffix_tokens,
            "computed_prefill_tokens": self.computed_prefill_tokens,
            "generated_tokens": self.generated_tokens,
            "server_first_output_ms": self.server_first_output_ms,
            "server_wall_ms": self.server_wall_ms,
            "kv_store_ms": self.kv_store_ms,
            "kv_bytes_actual": self.kv_bytes_actual,
            "layer_count": self.layer_count,
            "extra": dict(sorted(self.extra.items())),
        }

    @property
    def telemetry_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class KVConsumerTelemetry:
    request_id: str
    task_id: str
    lane: str
    logical_prompt_tokens: int
    parent_tokens: int
    suffix_tokens: int
    inherited_kv_tokens: int
    computed_prefill_tokens: int
    generated_tokens: int
    server_first_output_ms: float
    server_wall_ms: float
    connector_load_count: int = 0
    kv_load_ms: float = 0.0
    kv_bytes_actual: int = 0
    layer_count: int = 0
    num_cached_tokens_reported: int = 0
    forward_proof_hash: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "lane": self.lane,
            "logical_prompt_tokens": self.logical_prompt_tokens,
            "parent_tokens": self.parent_tokens,
            "suffix_tokens": self.suffix_tokens,
            "inherited_kv_tokens": self.inherited_kv_tokens,
            "computed_prefill_tokens": self.computed_prefill_tokens,
            "generated_tokens": self.generated_tokens,
            "server_first_output_ms": self.server_first_output_ms,
            "server_wall_ms": self.server_wall_ms,
            "connector_load_count": self.connector_load_count,
            "kv_load_ms": self.kv_load_ms,
            "kv_bytes_actual": self.kv_bytes_actual,
            "layer_count": self.layer_count,
            "num_cached_tokens_reported": self.num_cached_tokens_reported,
            "forward_proof_hash": self.forward_proof_hash,
            "extra": dict(sorted(self.extra.items())),
        }

    @property
    def telemetry_hash(self) -> str:
        return sha256_digest(self.canonical_payload())
