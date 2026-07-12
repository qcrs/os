from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any, Mapping

from v2.utils import sha256_digest


NEURAL_PREFIX_IDENTITY_SCHEMA_VERSION = "statebus.neural_prefix_identity.v1"
NEURAL_STATE_HANDLE_SCHEMA_VERSION = "statebus.neural_state_handle.v1"
NEURAL_PREFIX_REUSE_ESTIMATE_SCHEMA_VERSION = "statebus.neural_prefix_reuse_estimate.v1"
NEURAL_PREFIX_SCHEDULE_HINT_SCHEMA_VERSION = "statebus.neural_prefix_schedule_hint.v1"
DEFAULT_PREFIX_CONTRACT_VERSION = "statebus.engine_local_prefix.v1"
DEFAULT_NEURAL_REUSE_SCOPE = "task_session"
DEFAULT_NEURAL_REUSE_MODE = "shared_prefix_role_suffix"
DEFAULT_CLAIM_BOUNDARY = "engine_local_prefix_reuse_estimate_only_no_kv_tensor_export"
PREFIX_CONTROL_PLANE_CLAIM_BOUNDARY = (
    "prefix_identity_and_scheduling_control_plane_only_no_kv_tensor_export"
)


def build_corpus_prefix_hash(
    *,
    source_doc_hashes: tuple[str, ...] | list[str],
    evidence_pack_hash: str = "",
    hydrate_manifest_hash: str = "",
    system_prompt_version: str = "statebus-v2-shared-prefix-v1",
    prefix_contract_version: str = DEFAULT_PREFIX_CONTRACT_VERSION,
) -> str:
    """Stable identity for corpus-level scheduling, not for model-private KV bytes.

    ``evidence_pack_hash`` and ``hydrate_manifest_hash`` are accepted for backward
    compatibility with older callers, but corpus identity intentionally excludes
    them. Different queries over the same corpus should still land in the same
    cache-affinity group.
    """
    return sha256_digest(
        {
            "prefix_contract_version": prefix_contract_version,
            "system_prompt_version": system_prompt_version,
            "source_doc_hashes": sorted(str(item) for item in source_doc_hashes if str(item)),
        }
    )


def build_evidence_prefix_hash(
    *,
    source_doc_hashes: tuple[str, ...] | list[str] = (),
    corpus_prefix_hash: str = "",
    evidence_pack_hash: str = "",
    hydrate_manifest_hash: str = "",
    system_prompt_version: str = "statebus-v2-shared-prefix-v1",
    prefix_contract_version: str = DEFAULT_PREFIX_CONTRACT_VERSION,
) -> str:
    """Stable identity for an exact shared evidence prefix.

    This is stricter than ``corpus_prefix_hash`` and is the right identity for
    role-level shared-prefix probes where token-level equality matters.
    """
    corpus_hash = corpus_prefix_hash or build_corpus_prefix_hash(
        source_doc_hashes=source_doc_hashes,
        system_prompt_version=system_prompt_version,
        prefix_contract_version=prefix_contract_version,
    )
    return sha256_digest(
        {
            "prefix_contract_version": prefix_contract_version,
            "system_prompt_version": system_prompt_version,
            "corpus_prefix_hash": corpus_hash,
            "evidence_pack_hash": evidence_pack_hash,
            "hydrate_manifest_hash": hydrate_manifest_hash,
        }
    )


@dataclass(frozen=True)
class NeuralPrefixIdentity:
    corpus_prefix_hash: str
    evidence_prefix_hash: str
    source_doc_hashes: tuple[str, ...] = ()
    evidence_pack_hash: str = ""
    hydrate_manifest_hash: str = ""
    system_prompt_version: str = "statebus-v2-shared-prefix-v1"
    prefix_contract_version: str = DEFAULT_PREFIX_CONTRACT_VERSION
    claim_boundary: str = PREFIX_CONTROL_PLANE_CLAIM_BOUNDARY
    schema_version: str = NEURAL_PREFIX_IDENTITY_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "corpus_prefix_hash": self.corpus_prefix_hash,
            "evidence_prefix_hash": self.evidence_prefix_hash,
            "source_doc_hashes": list(self.source_doc_hashes),
            "evidence_pack_hash": self.evidence_pack_hash,
            "hydrate_manifest_hash": self.hydrate_manifest_hash,
            "system_prompt_version": self.system_prompt_version,
            "prefix_contract_version": self.prefix_contract_version,
            "claim_boundary": self.claim_boundary,
            "schema_version": self.schema_version,
        }


def build_neural_prefix_identity(
    *,
    source_doc_hashes: tuple[str, ...] | list[str],
    evidence_pack_hash: str = "",
    hydrate_manifest_hash: str = "",
    system_prompt_version: str = "statebus-v2-shared-prefix-v1",
    prefix_contract_version: str = DEFAULT_PREFIX_CONTRACT_VERSION,
) -> NeuralPrefixIdentity:
    normalized_doc_hashes = tuple(sorted(str(item) for item in source_doc_hashes if str(item)))
    corpus_prefix_hash = build_corpus_prefix_hash(
        source_doc_hashes=normalized_doc_hashes,
        system_prompt_version=system_prompt_version,
        prefix_contract_version=prefix_contract_version,
    )
    evidence_prefix_hash = build_evidence_prefix_hash(
        corpus_prefix_hash=corpus_prefix_hash,
        evidence_pack_hash=evidence_pack_hash,
        hydrate_manifest_hash=hydrate_manifest_hash,
        system_prompt_version=system_prompt_version,
        prefix_contract_version=prefix_contract_version,
    )
    return NeuralPrefixIdentity(
        corpus_prefix_hash=corpus_prefix_hash,
        evidence_prefix_hash=evidence_prefix_hash,
        source_doc_hashes=normalized_doc_hashes,
        evidence_pack_hash=evidence_pack_hash,
        hydrate_manifest_hash=hydrate_manifest_hash,
        system_prompt_version=system_prompt_version,
        prefix_contract_version=prefix_contract_version,
    )


@dataclass(frozen=True)
class NeuralStateHandle:
    engine_id: str
    session_id: str
    prefix_hash: str
    model_id: str
    tokenizer_id: str
    corpus_prefix_hash: str = ""
    evidence_prefix_hash: str = ""
    lifetime_scope: str = DEFAULT_NEURAL_REUSE_SCOPE
    created_step_id: str = ""
    expires_at_ns: int = 0
    prefix_token_count: int = 0
    cache_hit_count: int = 0
    last_observed_query_ns: int = 0
    last_observed_hit_ns: int = 0
    estimated_resident_until_ns: int = 0
    eviction_risk: str = "unknown"
    schedule_priority: float = 0.0
    claim_boundary: str = PREFIX_CONTROL_PLANE_CLAIM_BOUNDARY
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = NEURAL_STATE_HANDLE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "session_id": self.session_id,
            "prefix_hash": self.prefix_hash,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "corpus_prefix_hash": self.corpus_prefix_hash,
            "evidence_prefix_hash": self.evidence_prefix_hash,
            "lifetime_scope": self.lifetime_scope,
            "created_step_id": self.created_step_id,
            "expires_at_ns": self.expires_at_ns,
            "prefix_token_count": self.prefix_token_count,
            "cache_hit_count": self.cache_hit_count,
            "last_observed_query_ns": self.last_observed_query_ns,
            "last_observed_hit_ns": self.last_observed_hit_ns,
            "estimated_resident_until_ns": self.estimated_resident_until_ns,
            "eviction_risk": self.eviction_risk,
            "schedule_priority": self.schedule_priority,
            "claim_boundary": self.claim_boundary,
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
class NeuralPrefixRegistryResult:
    handle: NeuralStateHandle
    cache_hit: bool

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "handle": self.handle.canonical_payload(),
            "cache_hit": self.cache_hit,
            "schema_version": "statebus.neural_prefix_registry_result.v1",
        }


@dataclass
class EngineLocalPrefixRegistry:
    engine_id: str
    model_id: str
    tokenizer_id: str
    handles: dict[tuple[str, str, str, str, str], NeuralStateHandle] = field(default_factory=dict)

    def ensure_handle(
        self,
        *,
        session_id: str,
        prefix_hash: str,
        prefix_token_count: int,
        corpus_prefix_hash: str = "",
        evidence_prefix_hash: str = "",
        created_step_id: str = "",
        expires_at_ns: int = 0,
        observed_ns: int = 0,
        estimated_resident_until_ns: int = 0,
        eviction_risk: str = "unknown",
        schedule_priority: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> NeuralPrefixRegistryResult:
        key = self._key(
            session_id=session_id,
            prefix_hash=prefix_hash,
            model_id=self.model_id,
            tokenizer_id=self.tokenizer_id,
        )
        existing = self.handles.get(key)
        if existing is not None:
            merged_metadata = {
                **dict(existing.metadata),
                **dict(metadata or {}),
            }
            updated = NeuralStateHandle(
                engine_id=existing.engine_id,
                session_id=existing.session_id,
                prefix_hash=existing.prefix_hash,
                model_id=existing.model_id,
                tokenizer_id=existing.tokenizer_id,
                corpus_prefix_hash=existing.corpus_prefix_hash or corpus_prefix_hash,
                evidence_prefix_hash=existing.evidence_prefix_hash or evidence_prefix_hash,
                lifetime_scope=existing.lifetime_scope,
                created_step_id=existing.created_step_id,
                expires_at_ns=max(existing.expires_at_ns, int(expires_at_ns or 0)),
                prefix_token_count=max(existing.prefix_token_count, int(prefix_token_count or 0)),
                cache_hit_count=existing.cache_hit_count + 1,
                last_observed_query_ns=observed_ns or existing.last_observed_query_ns,
                last_observed_hit_ns=observed_ns or existing.last_observed_hit_ns,
                estimated_resident_until_ns=(
                    estimated_resident_until_ns or existing.estimated_resident_until_ns
                ),
                eviction_risk=(
                    eviction_risk if eviction_risk != "unknown" else existing.eviction_risk
                ),
                schedule_priority=(
                    schedule_priority if schedule_priority != 0.0 else existing.schedule_priority
                ),
                claim_boundary=existing.claim_boundary,
                metadata=merged_metadata,
            )
            self.handles[key] = updated
            return NeuralPrefixRegistryResult(handle=updated, cache_hit=True)
        handle = NeuralStateHandle(
            engine_id=self.engine_id,
            session_id=session_id,
            prefix_hash=prefix_hash,
            model_id=self.model_id,
            tokenizer_id=self.tokenizer_id,
            corpus_prefix_hash=corpus_prefix_hash,
            evidence_prefix_hash=evidence_prefix_hash,
            created_step_id=created_step_id,
            expires_at_ns=expires_at_ns,
            prefix_token_count=max(int(prefix_token_count), 0),
            last_observed_query_ns=max(int(observed_ns), 0),
            estimated_resident_until_ns=max(int(estimated_resident_until_ns), 0),
            eviction_risk=eviction_risk,
            schedule_priority=float(schedule_priority),
            metadata=metadata or {},
        )
        self.handles[key] = handle
        return NeuralPrefixRegistryResult(handle=handle, cache_hit=False)

    def lookup(
        self,
        *,
        session_id: str,
        prefix_hash: str,
        model_id: str | None = None,
        tokenizer_id: str | None = None,
    ) -> NeuralStateHandle | None:
        return self.handles.get(
            self._key(
                session_id=session_id,
                prefix_hash=prefix_hash,
                model_id=model_id or self.model_id,
                tokenizer_id=tokenizer_id or self.tokenizer_id,
            )
        )

    def invalidate_session(self, session_id: str) -> int:
        keys = [key for key in self.handles if key[1] == session_id]
        for key in keys:
            del self.handles[key]
        return len(keys)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "handle_count": len(self.handles),
            "handles": [handle.canonical_payload() for _, handle in sorted(self.handles.items())],
            "schema_version": "statebus.engine_local_prefix_registry.v1",
        }

    def _key(
        self,
        *,
        session_id: str,
        prefix_hash: str,
        model_id: str,
        tokenizer_id: str,
    ) -> tuple[str, str, str, str, str]:
        return (self.engine_id, session_id, prefix_hash, model_id, tokenizer_id)


@dataclass(frozen=True)
class NeuralPrefixReuseEstimate:
    prefix_hash: str
    shared_prefix_bytes: int
    estimated_prefix_tokens: int
    eligible_consumer_roles: tuple[str, ...]
    corpus_prefix_hash: str = ""
    evidence_prefix_hash: str = ""
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
            "corpus_prefix_hash": self.corpus_prefix_hash,
            "evidence_prefix_hash": self.evidence_prefix_hash,
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
            # NOTE: neural_prefix_cache_hit_count_estimate 是控制面推断（estimated_prefix_tokens > 0）
            # 不是 vLLM 内部 raw hit counter。直接 GPU 指标见 vllm:gpu_prefix_cache_hit_rate
            "neural_prefix_cache_hit_count_estimate": float(self.estimated_prefix_cache_hit_count),
            "neural_prefix_cache_hit_rate_estimate": float(self.estimated_prefix_cache_hit_rate),
            "neural_prefix_prefill_saved_tokens_estimate": float(self.estimated_prefill_saved_tokens),
            "neural_prefix_prefill_savings_ratio_estimate": float(self.estimated_prefill_savings_ratio),
            "neural_prefix_consumer_role_count": float(len(self.eligible_consumer_roles)),
        }


def estimate_engine_local_prefix_reuse(
    *,
    prefix_hash: str,
    corpus_prefix_hash: str = "",
    evidence_prefix_hash: str = "",
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
        corpus_prefix_hash=corpus_prefix_hash,
        evidence_prefix_hash=evidence_prefix_hash or prefix_hash,
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


@dataclass(frozen=True)
class PrefixReuseScheduleHint:
    task_id: str
    corpus_prefix_hash: str
    evidence_prefix_hash: str = ""
    estimated_prefix_tokens: int = 0
    cache_affinity_group: str = ""
    schedule_priority: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    claim_boundary: str = PREFIX_CONTROL_PLANE_CLAIM_BOUNDARY
    schema_version: str = NEURAL_PREFIX_SCHEDULE_HINT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "corpus_prefix_hash": self.corpus_prefix_hash,
            "evidence_prefix_hash": self.evidence_prefix_hash,
            "estimated_prefix_tokens": self.estimated_prefix_tokens,
            "cache_affinity_group": self.affinity_group(),
            "schedule_priority": self.schedule_priority,
            "metadata": dict(sorted(dict(self.metadata).items())),
            "claim_boundary": self.claim_boundary,
            "schema_version": self.schema_version,
        }

    def affinity_group(self) -> str:
        return self.cache_affinity_group or self.corpus_prefix_hash or "unknown"


def order_prefix_schedule_hints(
    hints: tuple[PrefixReuseScheduleHint, ...] | list[PrefixReuseScheduleHint],
    *,
    mode: str = "cache_friendly",
) -> tuple[PrefixReuseScheduleHint, ...]:
    """Order task hints without touching the LLM engine or KV tensors."""
    normalized_mode = mode.strip().lower()
    ordered_hints = tuple(hints)
    if normalized_mode in {"input", "input_order", "none"}:
        return ordered_hints
    if normalized_mode in {"cache_hostile", "interleaved"}:
        return _interleave_prefix_groups(ordered_hints)
    return tuple(
        sorted(
            ordered_hints,
            key=lambda hint: (
                hint.affinity_group(),
                -float(hint.schedule_priority),
                -int(hint.estimated_prefix_tokens),
                hint.task_id,
            ),
        )
    )


def order_prefix_schedule_hints_by_task_ids(
    hints: tuple[PrefixReuseScheduleHint, ...] | list[PrefixReuseScheduleHint],
    task_ids: tuple[str, ...] | list[str],
    *,
    strict: bool = True,
) -> tuple[PrefixReuseScheduleHint, ...]:
    """Apply a manifest-declared schedule order to prefix schedule hints.

    This bridges dataset-level schedules such as ``cache_friendly_order`` and
    ``cache_hostile_order`` to the generic control-plane hint objects.
    """
    hints_by_task_id = {hint.task_id: hint for hint in hints}
    ordered_task_ids = tuple(str(task_id).strip() for task_id in task_ids if str(task_id).strip())
    missing = tuple(task_id for task_id in ordered_task_ids if task_id not in hints_by_task_id)
    if strict and missing:
        raise ValueError(f"schedule references unknown task ids: {', '.join(missing)}")
    ordered = [hints_by_task_id[task_id] for task_id in ordered_task_ids if task_id in hints_by_task_id]
    if strict:
        extra = sorted(set(hints_by_task_id) - set(ordered_task_ids))
        if extra:
            raise ValueError(f"schedule omits task ids: {', '.join(extra)}")
    else:
        scheduled_ids = {hint.task_id for hint in ordered}
        ordered.extend(hint for hint in hints if hint.task_id not in scheduled_ids)
    return tuple(ordered)


def _interleave_prefix_groups(
    hints: tuple[PrefixReuseScheduleHint, ...],
) -> tuple[PrefixReuseScheduleHint, ...]:
    groups: dict[str, list[PrefixReuseScheduleHint]] = {}
    for hint in hints:
        groups.setdefault(hint.affinity_group(), []).append(hint)
    for group_hints in groups.values():
        group_hints.sort(
            key=lambda hint: (
                -float(hint.schedule_priority),
                -int(hint.estimated_prefix_tokens),
                hint.task_id,
            )
        )
    result: list[PrefixReuseScheduleHint] = []
    group_names = sorted(groups)
    while any(groups.values()):
        for group_name in group_names:
            if groups[group_name]:
                result.append(groups[group_name].pop(0))
    return tuple(result)
