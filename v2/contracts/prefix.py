from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from v2.utils import sha256_digest


PREFIX_REUSE_INTENT_SCHEMA_VERSION = "statebus.prefix_reuse_intent.v2"
PREFIX_OBSERVATION_SCHEMA_VERSION = "statebus.prefix_observation.v2"
CANONICAL_SHARED_PREFIX_SCHEMA_VERSION = "statebus.canonical_shared_evidence_prefix.v2"
EXACT_TOKEN_PREFIX_IDENTITY_SCHEMA_VERSION = "statebus.exact_token_prefix_identity.v2"
PREFIX_CLAIM_BOUNDARY = "engine_local_exact_token_reuse_intent_only_no_kv_tensor_export"


class PrefixParticipantRole(StrEnum):
    EXECUTOR = "executor"
    SUMMARIZER = "summarizer"


class PrefixIntentStatus(StrEnum):
    INELIGIBLE = "ineligible"
    ELIGIBLE = "eligible"


class PrefixObservationStatus(StrEnum):
    OBSERVED_HIT = "observed_hit"
    OBSERVED_MISS = "observed_miss"
    UNAVAILABLE = "unavailable"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class CanonicalPrefixEntry:
    stable_key: str
    source_doc_hash: str
    locator_kind: str
    locator_fields: Mapping[str, Any]
    evidence_kind: str
    rendered_text: str

    def __post_init__(self) -> None:
        required = {
            "stable_key": self.stable_key,
            "source_doc_hash": self.source_doc_hash,
            "locator_kind": self.locator_kind,
            "evidence_kind": self.evidence_kind,
            "rendered_text": self.rendered_text,
        }
        missing = tuple(name for name, value in required.items() if not str(value).strip())
        if missing:
            raise ValueError(f"canonical prefix entry missing fields: {', '.join(missing)}")
        if not self.locator_fields:
            raise ValueError("canonical prefix entry requires locator_fields")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "stable_key": self.stable_key,
            "source_doc_hash": self.source_doc_hash,
            "locator_kind": self.locator_kind,
            "locator_fields": dict(sorted(dict(self.locator_fields).items())),
            "evidence_kind": self.evidence_kind,
            "rendered_text": self.rendered_text,
        }

    @property
    def entry_digest(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class CanonicalSharedEvidencePrefix:
    participant_roles: tuple[str, ...]
    authorized_common_keys: tuple[str, ...]
    entries: tuple[CanonicalPrefixEntry, ...]
    rendered_text: str
    eligible: bool
    ineligible_reason: str = ""
    prefix_layout_version: str = "statebus.shared_evidence_prefix.v2"
    normalizer_version: str = "statebus.prefix_normalizer.v2"
    visibility_policy_version: str = "statebus.role_visibility.v1"
    schema_version: str = CANONICAL_SHARED_PREFIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CANONICAL_SHARED_PREFIX_SCHEMA_VERSION:
            raise ValueError(f"unsupported canonical shared prefix schema: {self.schema_version}")
        if self.eligible and (not self.entries or not self.rendered_text):
            raise ValueError("eligible canonical shared prefix requires entries and rendered_text")
        if self.eligible and self.ineligible_reason:
            raise ValueError("eligible canonical shared prefix cannot have ineligible_reason")
        if not self.eligible and not self.ineligible_reason:
            raise ValueError("ineligible canonical shared prefix requires a reason")

    @property
    def authorized_common_keys_digest(self) -> str:
        return sha256_digest(list(self.authorized_common_keys))

    @property
    def shared_prefix_text_sha256(self) -> str:
        return sha256_digest(self.rendered_text.encode("utf-8"))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prefix_layout_version": self.prefix_layout_version,
            "normalizer_version": self.normalizer_version,
            "visibility_policy_version": self.visibility_policy_version,
            "participant_roles": list(self.participant_roles),
            "authorized_common_keys": list(self.authorized_common_keys),
            "authorized_common_keys_digest": self.authorized_common_keys_digest,
            "entries": [entry.canonical_payload() for entry in self.entries],
            "rendered_text": self.rendered_text,
            "shared_prefix_text_sha256": self.shared_prefix_text_sha256,
            "prefix_bytes": len(self.rendered_text.encode("utf-8")),
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
            "claim_boundary": PREFIX_CLAIM_BOUNDARY,
        }


@dataclass(frozen=True)
class ExactTokenPrefixIdentity:
    participant_roles: tuple[str, ...]
    exact_token_ids: tuple[int, ...]
    full_request_token_ids_sha256: Mapping[str, str]
    block_size: int
    full_block_token_count: int
    eligible: bool
    ineligible_reason: str = ""
    position_base: int = 0
    message_shape_digest: str = ""
    shared_prefix_text_sha256: str = ""
    prefix_bytes: int = 0
    schema_version: str = EXACT_TOKEN_PREFIX_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXACT_TOKEN_PREFIX_IDENTITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported exact token prefix schema: {self.schema_version}")
        if self.block_size <= 0:
            raise ValueError("block_size must be positive")
        if self.position_base != 0:
            raise ValueError("engine-local shared prefix must start at token position 0")
        if self.full_block_token_count < 0 or self.full_block_token_count > len(self.exact_token_ids):
            raise ValueError("invalid full_block_token_count")
        if self.full_block_token_count % self.block_size:
            raise ValueError("full_block_token_count must align to block_size")
        if self.eligible and self.full_block_token_count == 0:
            raise ValueError("eligible exact token prefix requires at least one full block")
        if self.eligible and self.ineligible_reason:
            raise ValueError("eligible exact token prefix cannot have ineligible_reason")
        if not self.eligible and not self.ineligible_reason:
            raise ValueError("ineligible exact token prefix requires a reason")

    @property
    def exact_token_ids_sha256(self) -> str:
        return sha256_digest(list(self.exact_token_ids))

    @property
    def exact_token_count(self) -> int:
        return len(self.exact_token_ids)

    def canonical_payload(self, *, include_token_ids: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "participant_roles": list(self.participant_roles),
            "exact_token_ids_sha256": self.exact_token_ids_sha256,
            "exact_token_count": self.exact_token_count,
            "full_block_token_count": self.full_block_token_count,
            "block_size": self.block_size,
            "position_base": self.position_base,
            "message_shape_digest": self.message_shape_digest,
            "shared_prefix_text_sha256": self.shared_prefix_text_sha256,
            "prefix_bytes": self.prefix_bytes,
            "full_request_token_ids_sha256": dict(
                sorted(dict(self.full_request_token_ids_sha256).items())
            ),
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
            "claim_boundary": PREFIX_CLAIM_BOUNDARY,
        }
        if include_token_ids:
            payload["exact_token_ids"] = list(self.exact_token_ids)
        return payload


@dataclass(frozen=True)
class PrefixReuseIntentV2:
    intent_id: str
    trace_id: str
    task_id: str
    step_id: str
    request_id: str
    participant_role: PrefixParticipantRole
    engine_instance_id: str
    cache_namespace: str
    cache_epoch: str
    model_id: str
    model_revision: str
    weights_digest: str
    tokenizer_id: str
    tokenizer_revision: str
    chat_template_sha256: str
    template_kwargs_sha256: str
    prefix_layout_version: str
    normalizer_version: str
    source_doc_hashes: tuple[str, ...]
    evidence_pack_hash: str
    hydrate_manifest_hash: str
    authorized_common_keys_digest: str
    visibility_policy_version: str
    shared_prefix_text_sha256: str
    prefix_bytes: int
    exact_token_ids_sha256: str
    exact_token_count: int
    full_block_token_count: int
    block_size: int
    message_shape_digest: str
    adapter_digest: str = "none"
    multimodal_digest: str = "none"
    cache_salt_digest: str = "none"
    rope_config_digest: str = ""
    kv_cache_dtype: str = ""
    quantization_digest: str = "none"
    tensor_parallel_size: int = 1
    pipeline_parallel_size: int = 1
    status: PrefixIntentStatus = PrefixIntentStatus.INELIGIBLE
    eligible_reason: str = ""
    ineligible_reason: str = ""
    dependency_ids: tuple[str, ...] = ()
    ready_set_epoch: int = 0
    schedule_priority: float = 0.0
    lease_expires_at_ns: int = 0
    schema_version: str = PREFIX_REUSE_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PREFIX_REUSE_INTENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported prefix reuse intent schema: {self.schema_version}")
        required = {
            "intent_id": self.intent_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "request_id": self.request_id,
            "engine_instance_id": self.engine_instance_id,
            "cache_namespace": self.cache_namespace,
            "cache_epoch": self.cache_epoch,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "chat_template_sha256": self.chat_template_sha256,
            "template_kwargs_sha256": self.template_kwargs_sha256,
            "prefix_layout_version": self.prefix_layout_version,
            "normalizer_version": self.normalizer_version,
        }
        missing = tuple(name for name, value in required.items() if not str(value).strip())
        if missing:
            raise ValueError(f"prefix reuse intent missing fields: {', '.join(missing)}")
        if self.block_size <= 0 or self.exact_token_count < 0 or self.full_block_token_count < 0:
            raise ValueError("invalid prefix token/block counts")
        if self.full_block_token_count > self.exact_token_count:
            raise ValueError("full_block_token_count exceeds exact_token_count")
        if self.full_block_token_count % self.block_size:
            raise ValueError("full_block_token_count must align to block_size")
        if self.status is PrefixIntentStatus.ELIGIBLE:
            if self.ineligible_reason:
                raise ValueError("eligible prefix intent cannot have ineligible_reason")
            if not self.exact_token_ids_sha256 or self.full_block_token_count == 0:
                raise ValueError("eligible prefix intent requires exact token identity and full block")
        elif not self.ineligible_reason:
            raise ValueError("ineligible prefix intent requires ineligible_reason")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "request_id": self.request_id,
            "participant_role": self.participant_role.value,
            "engine_instance_id": self.engine_instance_id,
            "cache_namespace": self.cache_namespace,
            "cache_epoch": self.cache_epoch,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "weights_digest": self.weights_digest,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "chat_template_sha256": self.chat_template_sha256,
            "template_kwargs_sha256": self.template_kwargs_sha256,
            "prefix_layout_version": self.prefix_layout_version,
            "normalizer_version": self.normalizer_version,
            "source_doc_hashes": list(self.source_doc_hashes),
            "evidence_pack_hash": self.evidence_pack_hash,
            "hydrate_manifest_hash": self.hydrate_manifest_hash,
            "authorized_common_keys_digest": self.authorized_common_keys_digest,
            "visibility_policy_version": self.visibility_policy_version,
            "shared_prefix_text_sha256": self.shared_prefix_text_sha256,
            "prefix_bytes": self.prefix_bytes,
            "exact_token_ids_sha256": self.exact_token_ids_sha256,
            "exact_token_count": self.exact_token_count,
            "full_block_token_count": self.full_block_token_count,
            "block_size": self.block_size,
            "position_base": 0,
            "message_shape_digest": self.message_shape_digest,
            "adapter_digest": self.adapter_digest,
            "multimodal_digest": self.multimodal_digest,
            "cache_salt_digest": self.cache_salt_digest,
            "rope_config_digest": self.rope_config_digest,
            "kv_cache_dtype": self.kv_cache_dtype,
            "quantization_digest": self.quantization_digest,
            "tensor_parallel_size": self.tensor_parallel_size,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "status": self.status.value,
            "eligible_reason": self.eligible_reason,
            "ineligible_reason": self.ineligible_reason,
            "dependency_ids": list(self.dependency_ids),
            "ready_set_epoch": self.ready_set_epoch,
            "schedule_priority": self.schedule_priority,
            "lease_expires_at_ns": self.lease_expires_at_ns,
            "claim_boundary": PREFIX_CLAIM_BOUNDARY,
        }


@dataclass(frozen=True)
class PrefixObservationV2:
    intent_id: str
    request_id: str
    engine_instance_id: str
    cache_epoch: str
    status: PrefixObservationStatus
    observed_query_token_delta: float = 0.0
    observed_hit_token_delta: float = 0.0
    counter_unit: str = "tokens"
    counter_series_digest: str = ""
    unavailable_reason: str = ""
    exclusive_interval: bool = False
    pollution_detected: bool = False
    retry_count: int = 0
    schema_version: str = PREFIX_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PREFIX_OBSERVATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported prefix observation schema: {self.schema_version}")
        if self.counter_unit != "tokens":
            raise ValueError("prefix observation counter_unit must be tokens")
        if self.status in {
            PrefixObservationStatus.OBSERVED_HIT,
            PrefixObservationStatus.OBSERVED_MISS,
        }:
            if not self.exclusive_interval or self.pollution_detected or self.retry_count:
                raise ValueError("observed prefix sample requires one exclusive retry-free interval")
            if self.observed_query_token_delta <= 0:
                raise ValueError("observed prefix sample requires positive query token delta")
            if not 0 <= self.observed_hit_token_delta <= self.observed_query_token_delta:
                raise ValueError("invalid observed prefix hit token delta")
            if self.status is PrefixObservationStatus.OBSERVED_HIT and self.observed_hit_token_delta <= 0:
                raise ValueError("observed_hit requires non-zero hit token delta")
            if self.status is PrefixObservationStatus.OBSERVED_MISS and self.observed_hit_token_delta != 0:
                raise ValueError("observed_miss requires zero hit token delta")
            if self.unavailable_reason:
                raise ValueError("valid observed prefix sample cannot have unavailable_reason")
        elif not self.unavailable_reason:
            raise ValueError("unavailable or invalidated prefix observation requires a reason")

    @property
    def observed_token_hit_rate(self) -> float | None:
        if self.observed_query_token_delta <= 0:
            return None
        return self.observed_hit_token_delta / self.observed_query_token_delta

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "request_id": self.request_id,
            "engine_instance_id": self.engine_instance_id,
            "cache_epoch": self.cache_epoch,
            "status": self.status.value,
            "observed_query_token_delta": self.observed_query_token_delta,
            "observed_hit_token_delta": self.observed_hit_token_delta,
            "observed_token_hit_rate": self.observed_token_hit_rate,
            "counter_unit": self.counter_unit,
            "counter_series_digest": self.counter_series_digest,
            "unavailable_reason": self.unavailable_reason,
            "exclusive_interval": self.exclusive_interval,
            "pollution_detected": self.pollution_detected,
            "retry_count": self.retry_count,
            "claim_boundary": PREFIX_CLAIM_BOUNDARY,
        }
