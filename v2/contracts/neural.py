from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from v2.contracts.constants import (
    LATENT_FORWARD_PROOF_SCHEMA_VERSION,
    LATENT_HANDOFF_DECISION_SCHEMA_VERSION,
    LATENT_LIFECYCLE_EVENT_SCHEMA_VERSION,
    NEURAL_COMPATIBILITY_SIGNATURE_SCHEMA_VERSION,
    SUPPORTED_LATENT_ALIGNMENT_METHODS,
)
from v2.utils import sha256_digest


class HandoffIntent(StrEnum):
    AUTO = "auto"
    TEXT = "text"
    LATENT_ASSIST = "latent_assist"
    EXACT_ARTIFACT_PREFERRED = "exact_artifact_preferred"


class LatentHandoffMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    PLANNER_ASSIST = "planner_assist"
    FORCE = "force"


class LatentLifecycleState(StrEnum):
    PREPARED = "prepared"
    COMMITTED = "committed"
    LEASED = "leased"
    CONSUMING = "consuming"
    CONSUMED = "consumed"
    RELEASED = "released"
    EXPIRED = "expired"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class LatentProofKind(StrEnum):
    NONE = "none"
    FAKE = "fake"
    WORKER_FORWARD = "worker_forward"


@dataclass(frozen=True)
class NeuralCompatibilitySignature:
    vllm_version: str
    engine_generation: str
    model_id: str
    model_revision_or_manifest_digest: str
    architecture: str
    tokenizer_id: str
    tokenizer_revision: str
    chat_template_digest: str
    active_lora_or_adapter_digest: str
    quantization_digest: str
    dtype: str
    hidden_size: int
    num_layers: int
    num_attention_heads: int
    num_kv_heads: int
    head_dim: int
    rope_config_digest: str
    attention_backend: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    worker_extension_version: str
    alignment_method: str
    alignment_config_digest: str
    position_contract_digest: str
    schema_version: str = NEURAL_COMPATIBILITY_SIGNATURE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "vllm_version": self.vllm_version,
            "engine_generation": self.engine_generation,
            "model_id": self.model_id,
            "model_revision_or_manifest_digest": self.model_revision_or_manifest_digest,
            "architecture": self.architecture,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "chat_template_digest": self.chat_template_digest,
            "active_lora_or_adapter_digest": self.active_lora_or_adapter_digest,
            "quantization_digest": self.quantization_digest,
            "dtype": self.dtype,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "num_attention_heads": self.num_attention_heads,
            "num_kv_heads": self.num_kv_heads,
            "head_dim": self.head_dim,
            "rope_config_digest": self.rope_config_digest,
            "attention_backend": self.attention_backend,
            "tensor_parallel_size": self.tensor_parallel_size,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "worker_extension_version": self.worker_extension_version,
            "alignment_method": self.alignment_method,
            "alignment_config_digest": self.alignment_config_digest,
            "position_contract_digest": self.position_contract_digest,
            "schema_version": self.schema_version,
        }

    @property
    def compatibility_digest(self) -> str:
        return sha256_digest(self.canonical_payload())

    def mismatch_fields(
        self,
        other: "NeuralCompatibilitySignature",
    ) -> tuple[str, ...]:
        left = self.canonical_payload()
        right = other.canonical_payload()
        return tuple(sorted(key for key in left if left[key] != right.get(key)))

    def is_exactly_compatible_with(
        self,
        other: "NeuralCompatibilitySignature",
    ) -> bool:
        return not self.mismatch_fields(other)

    def initial_support_matrix_errors(self) -> tuple[str, ...]:
        unknown_identities = {"", "none", "null", "unknown"}
        checks = {
            "vllm_version": self.vllm_version == "0.9.2",
            "engine_generation": self.engine_generation.upper() == "V0",
            "architecture": self.architecture == "Qwen3ForCausalLM",
            "hidden_size": self.hidden_size == 5120,
            "tensor_parallel_size": self.tensor_parallel_size == 1,
            "pipeline_parallel_size": self.pipeline_parallel_size == 1,
            "dtype": self.dtype.lower().replace("torch.", "")
            in {"bf16", "bfloat16"},
            "alignment_method": (
                self.alignment_method in SUPPORTED_LATENT_ALIGNMENT_METHODS
            ),
            "model_revision_or_manifest_digest": (
                self.model_revision_or_manifest_digest.strip().lower()
                not in unknown_identities
            ),
            "tokenizer_revision": (
                self.tokenizer_revision.strip().lower() not in unknown_identities
            ),
            "chat_template_digest": (
                self.chat_template_digest.strip().lower() not in unknown_identities
            ),
        }
        return tuple(key for key, ok in checks.items() if not ok)


@dataclass(frozen=True)
class LatentAnchor:
    evidence_pack_hash: str
    item_ids: tuple[str, ...]
    locator_digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "evidence_pack_hash": self.evidence_pack_hash,
            "item_ids": list(self.item_ids),
            "locator_digest": self.locator_digest,
        }

    @property
    def anchor_digest(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class LatentGateCheck:
    name: str
    passed: bool
    detail: str = ""

    def canonical_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LatentHandoffDecision:
    mode: LatentHandoffMode
    requested_policy: HandoffIntent
    effective_policy: str
    checks: tuple[LatentGateCheck, ...]
    rejection_reason: str = ""
    plugin_health_digest: str = ""
    compatibility_digest: str = ""
    fallback_policy: str = "full_evidence_text"
    schema_version: str = LATENT_HANDOFF_DECISION_SCHEMA_VERSION

    @property
    def latent_enabled(self) -> bool:
        return self.effective_policy in {"latent", "latent_shadow"}

    def canonical_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "requested_policy": self.requested_policy.value,
            "effective_policy": self.effective_policy,
            "checks": [check.canonical_payload() for check in self.checks],
            "rejection_reason": self.rejection_reason,
            "plugin_health_digest": self.plugin_health_digest,
            "compatibility_digest": self.compatibility_digest,
            "fallback_policy": self.fallback_policy,
            "schema_version": self.schema_version,
        }

    @property
    def decision_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class LatentForwardProof:
    ref_id: str
    request_id: str
    worker_pid: int
    engine_id: str
    inputs_embeds_shape: tuple[int, ...]
    inputs_embeds_dtype: str
    inputs_embeds_digest: str
    observed_at_ns: int
    event_id: str
    proof_kind: LatentProofKind = LatentProofKind.WORKER_FORWARD
    schema_version: str = LATENT_FORWARD_PROOF_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ref_id": self.ref_id,
            "request_id": self.request_id,
            "worker_pid": self.worker_pid,
            "engine_id": self.engine_id,
            "inputs_embeds_shape": list(self.inputs_embeds_shape),
            "inputs_embeds_dtype": self.inputs_embeds_dtype,
            "inputs_embeds_digest": self.inputs_embeds_digest,
            "observed_at_ns": self.observed_at_ns,
            "event_id": self.event_id,
            "proof_kind": self.proof_kind.value,
            "schema_version": self.schema_version,
        }

    @property
    def proof_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class LatentLifecycleEvent:
    event_id: str
    ref_id: str
    event_type: str
    state_before: LatentLifecycleState | None
    state_after: LatentLifecycleState
    occurred_at_ns: int
    request_id: str = ""
    reason: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LATENT_LIFECYCLE_EVENT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "ref_id": self.ref_id,
            "event_type": self.event_type,
            "state_before": None if self.state_before is None else self.state_before.value,
            "state_after": self.state_after.value,
            "occurred_at_ns": self.occurred_at_ns,
            "request_id": self.request_id,
            "reason": self.reason,
            "attributes": dict(sorted(dict(self.attributes).items())),
            "schema_version": self.schema_version,
        }
