from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any, Mapping

from v2.utils import sha256_digest


NEURAL_STATE_HANDLE_SCHEMA_VERSION = "statebus.neural_state_handle.v1"
NEURAL_PREFIX_REUSE_ESTIMATE_SCHEMA_VERSION = "statebus.neural_prefix_reuse_estimate.v1"
DEFAULT_PREFIX_CONTRACT_VERSION = "statebus.engine_local_prefix.v1"
DEFAULT_NEURAL_REUSE_SCOPE = "task_session"
DEFAULT_NEURAL_REUSE_MODE = "shared_prefix_role_suffix"
DEFAULT_CLAIM_BOUNDARY = "engine_local_prefix_reuse_estimate_only_no_kv_tensor_export"


def build_corpus_prefix_hash(
    *,
    source_doc_hashes: tuple[str, ...] | list[str],
    evidence_pack_hash: str = "",
    hydrate_manifest_hash: str = "",
    system_prompt_version: str = "statebus-v2-shared-prefix-v1",
    prefix_contract_version: str = DEFAULT_PREFIX_CONTRACT_VERSION,
) -> str:
    """Stable identity for the shared evidence prefix, not for model-private KV bytes."""
    return sha256_digest(
        {
            "prefix_contract_version": prefix_contract_version,
            "system_prompt_version": system_prompt_version,
            "source_doc_hashes": sorted(str(item) for item in source_doc_hashes if str(item)),
            "evidence_pack_hash": evidence_pack_hash,
            "hydrate_manifest_hash": hydrate_manifest_hash,
        }
    )


@dataclass(frozen=True)
class NeuralStateHandle:
    engine_id: str
    session_id: str
    prefix_hash: str
    model_id: str
    tokenizer_id: str
    lifetime_scope: str = DEFAULT_NEURAL_REUSE_SCOPE
    created_step_id: str = ""
    expires_at_ns: int = 0
    prefix_token_count: int = 0
    cache_hit_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = NEURAL_STATE_HANDLE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "session_id": self.session_id,
            "prefix_hash": self.prefix_hash,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "lifetime_scope": self.lifetime_scope,
            "created_step_id": self.created_step_id,
            "expires_at_ns": self.expires_at_ns,
            "prefix_token_count": self.prefix_token_count,
            "cache_hit_count": self.cache_hit_count,
            "metadata": dict(sorted(dict(self.metadata).items())),
            "schema_version": self.schema_version,
        }

    def is_compatible_with(
        self,
        *,
        engine_id: str,
        session_id: str,
        prefix_hash: str,
        model_id: str,
        tokenizer_id: str,
    ) -> bool:
        return (
            self.engine_id == engine_id
            and self.session_id == session_id
            and self.prefix_hash == prefix_hash
            and self.model_id == model_id
            and self.tokenizer_id == tokenizer_id
        )


@dataclass(frozen=True)
class NeuralPrefixReuseEstimate:
    prefix_hash: str
    shared_prefix_bytes: int
    estimated_prefix_tokens: int
    eligible_consumer_roles: tuple[str, ...]
    first_prefill_role: str = ""
    downstream_reuse_roles: tuple[str, ...] = ()
    estimated_prefix_cache_query_count: int = 0
    estimated_prefix_cache_hit_count: int = 0
    estimated_prefill_saved_tokens: int = 0
    estimated_prefix_cache_hit_rate: float = 0.0
    estimated_prefill_savings_ratio: float = 0.0
    neural_reuse_scope: str = DEFAULT_NEURAL_REUSE_SCOPE
    neural_reuse_mode: str = DEFAULT_NEURAL_REUSE_MODE
    claim_boundary: str = DEFAULT_CLAIM_BOUNDARY
    schema_version: str = NEURAL_PREFIX_REUSE_ESTIMATE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "prefix_hash": self.prefix_hash,
            "shared_prefix_bytes": self.shared_prefix_bytes,
            "estimated_prefix_tokens": self.estimated_prefix_tokens,
            "eligible_consumer_roles": list(self.eligible_consumer_roles),
            "first_prefill_role": self.first_prefill_role,
            "downstream_reuse_roles": list(self.downstream_reuse_roles),
            "estimated_prefix_cache_query_count": self.estimated_prefix_cache_query_count,
            "estimated_prefix_cache_hit_count": self.estimated_prefix_cache_hit_count,
            "estimated_prefill_saved_tokens": self.estimated_prefill_saved_tokens,
            "estimated_prefix_cache_hit_rate": self.estimated_prefix_cache_hit_rate,
            "estimated_prefill_savings_ratio": self.estimated_prefill_savings_ratio,
            "neural_reuse_scope": self.neural_reuse_scope,
            "neural_reuse_mode": self.neural_reuse_mode,
            "claim_boundary": self.claim_boundary,
            "schema_version": self.schema_version,
        }

    def metrics(self) -> dict[str, float]:
        return {
            "neural_prefix_reuse_estimate_count": 1.0 if self.estimated_prefix_tokens > 0 else 0.0,
            "neural_prefix_shared_prefix_bytes": float(self.shared_prefix_bytes),
            "neural_prefix_estimated_prefix_tokens": float(self.estimated_prefix_tokens),
            "neural_prefix_cache_query_count_estimate": float(self.estimated_prefix_cache_query_count),
            "neural_prefix_cache_hit_count_estimate": float(self.estimated_prefix_cache_hit_count),
            "neural_prefix_cache_hit_rate_estimate": float(self.estimated_prefix_cache_hit_rate),
            "neural_prefix_prefill_saved_tokens_estimate": float(self.estimated_prefill_saved_tokens),
            "neural_prefix_prefill_savings_ratio_estimate": float(self.estimated_prefill_savings_ratio),
            "neural_prefix_consumer_role_count": float(len(self.eligible_consumer_roles)),
        }


def estimate_engine_local_prefix_reuse(
    *,
    prefix_hash: str,
    shared_prefix_bytes: int,
    consumer_roles: tuple[str, ...] | list[str],
    bytes_per_token: float = 4.0,
) -> NeuralPrefixReuseEstimate:
    roles = tuple(role for role in consumer_roles if role)
    prefix_bytes = max(int(shared_prefix_bytes), 0)
    token_divisor = bytes_per_token if bytes_per_token > 0 else 4.0
    prefix_tokens = int(ceil(prefix_bytes / token_divisor)) if prefix_bytes else 0
    query_count = len(roles) if prefix_tokens else 0
    hit_count = max(0, query_count - 1)
    saved_tokens = prefix_tokens * hit_count
    total_prefill_tokens = prefix_tokens * query_count
    return NeuralPrefixReuseEstimate(
        prefix_hash=prefix_hash,
        shared_prefix_bytes=prefix_bytes,
        estimated_prefix_tokens=prefix_tokens,
        eligible_consumer_roles=roles,
        first_prefill_role=roles[0] if roles else "",
        downstream_reuse_roles=roles[1:],
        estimated_prefix_cache_query_count=query_count,
        estimated_prefix_cache_hit_count=hit_count,
        estimated_prefill_saved_tokens=saved_tokens,
        estimated_prefix_cache_hit_rate=(hit_count / query_count) if query_count else 0.0,
        estimated_prefill_savings_ratio=(saved_tokens / total_prefill_tokens) if total_prefill_tokens else 0.0,
    )
