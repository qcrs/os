from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from statebus.utils import sha256_digest


ENGINE_LOCAL_KV_SCHEMA_VERSION = "statebus.engine_local_kv.v1"
ENGINE_LOCAL_KV_PROOF_SCHEMA_VERSION = "statebus.engine_local_kv_proof.v1"


class KVHandleStatus(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    CONSUMING = "consuming"
    CONSUMED = "consumed"
    RELEASED = "released"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class EngineLocalKVHandle:
    handle_id: str
    engine_id: str
    engine_generation: str
    model_id: str
    model_revision: str
    tokenizer_digest: str
    task_id: str
    producer_request_id: str
    seq_len: int
    block_size: int
    token_digest: str
    kv_bytes_actual: int
    layer_count: int
    dtype: str
    storage_tier: str
    created_at_ns: int
    expires_at_ns: int
    status: KVHandleStatus = KVHandleStatus.PREPARING
    schema_version: str = ENGINE_LOCAL_KV_SCHEMA_VERSION

    def __post_init__(self) -> None:
        required = {
            "handle_id": self.handle_id,
            "engine_id": self.engine_id,
            "engine_generation": self.engine_generation,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_digest": self.tokenizer_digest,
            "task_id": self.task_id,
            "producer_request_id": self.producer_request_id,
            "token_digest": self.token_digest,
            "dtype": self.dtype,
            "storage_tier": self.storage_tier,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(f"missing engine-local KV fields: {','.join(missing)}")
        if self.seq_len <= 0 or self.block_size <= 0:
            raise ValueError("seq_len and block_size must be positive")
        if self.seq_len % self.block_size:
            raise ValueError("seq_len must be block aligned")
        if self.kv_bytes_actual < 0 or self.layer_count < 0:
            raise ValueError("KV byte and layer counts cannot be negative")
        if self.expires_at_ns <= self.created_at_ns:
            raise ValueError("expires_at_ns must be after created_at_ns")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "handle_id": self.handle_id,
            "engine_id": self.engine_id,
            "engine_generation": self.engine_generation,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_digest": self.tokenizer_digest,
            "task_id": self.task_id,
            "producer_request_id": self.producer_request_id,
            "seq_len": self.seq_len,
            "block_size": self.block_size,
            "token_digest": self.token_digest,
            "kv_bytes_actual": self.kv_bytes_actual,
            "layer_count": self.layer_count,
            "dtype": self.dtype,
            "storage_tier": self.storage_tier,
            "created_at_ns": self.created_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "status": self.status.value,
            "schema_version": self.schema_version,
        }

    @property
    def compatibility_digest(self) -> str:
        return sha256_digest({
            "engine_id": self.engine_id,
            "engine_generation": self.engine_generation,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_digest": self.tokenizer_digest,
            "block_size": self.block_size,
            "dtype": self.dtype,
            "schema_version": self.schema_version,
        })


@dataclass(frozen=True)
class KVForwardProof:
    handle_id: str
    request_id: str
    task_id: str
    engine_id: str
    engine_generation: str
    token_digest: str
    inherited_kv_tokens: int
    computed_prefill_tokens: int
    logical_prompt_tokens: int
    suffix_tokens: int
    layer_count: int
    kv_bytes_actual: int
    connector_load_count: int
    kv_load_ms: float
    worker_pid: int
    observed_at_ns: int
    proof_kind: str = "worker_kv_forward"
    schema_version: str = ENGINE_LOCAL_KV_PROOF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        required = {
            "handle_id": self.handle_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "engine_id": self.engine_id,
            "engine_generation": self.engine_generation,
            "token_digest": self.token_digest,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(f"missing KV forward proof fields: {','.join(missing)}")
        if (
            self.inherited_kv_tokens <= 0
            or self.computed_prefill_tokens <= 0
            or self.suffix_tokens != self.computed_prefill_tokens
            or self.logical_prompt_tokens
            != self.inherited_kv_tokens + self.computed_prefill_tokens
        ):
            raise ValueError("invalid KV forward token accounting")
        if (
            self.layer_count <= 0
            or self.kv_bytes_actual <= 0
            or self.connector_load_count != 1
            or self.kv_load_ms < 0
            or self.worker_pid <= 0
            or self.observed_at_ns <= 0
        ):
            raise ValueError("invalid KV forward mechanism evidence")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "handle_id": self.handle_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "engine_id": self.engine_id,
            "engine_generation": self.engine_generation,
            "token_digest": self.token_digest,
            "inherited_kv_tokens": self.inherited_kv_tokens,
            "computed_prefill_tokens": self.computed_prefill_tokens,
            "logical_prompt_tokens": self.logical_prompt_tokens,
            "suffix_tokens": self.suffix_tokens,
            "layer_count": self.layer_count,
            "kv_bytes_actual": self.kv_bytes_actual,
            "connector_load_count": self.connector_load_count,
            "kv_load_ms": self.kv_load_ms,
            "worker_pid": self.worker_pid,
            "observed_at_ns": self.observed_at_ns,
            "proof_kind": self.proof_kind,
            "schema_version": self.schema_version,
        }

    @property
    def proof_hash(self) -> str:
        return sha256_digest(self.canonical_payload())
