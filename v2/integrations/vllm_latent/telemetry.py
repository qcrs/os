from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from v2.integrations.vllm_latent.alignment import sanitize_alignment_diagnostics
from v2.utils import sha256_digest


@dataclass(frozen=True)
class LatentProducerTelemetry:
    request_id: str
    ref_id: str
    producer_role: str
    worker_pid: int
    engine_id: str
    model_revision: str
    compatibility_digest: str
    source_evidence_pack_hash: str
    anchor_digest: str
    latent_steps_requested: int
    hidden_steps_captured: int
    latent_steps_committed: int
    recurrence_injection_count: int
    alignment_method: str
    alignment_config_digest: str
    raw_hidden_shape: tuple[int, ...]
    aligned_tensor_shape: tuple[int, ...]
    aligned_tensor_dtype: str
    aligned_tensor_bytes: int
    aligned_tensor_digest: str
    producer_prefill_ms: float = 0.0
    latent_rollout_ms: float = 0.0
    d2h_ms: float = 0.0
    registry_commit_ms: float = 0.0
    internal_scheduler_sample_count: int = 0
    alignment_diagnostics: Mapping[str, float | int] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "ref_id": self.ref_id,
            "producer_role": self.producer_role,
            "worker_pid": self.worker_pid,
            "engine_id": self.engine_id,
            "model_revision": self.model_revision,
            "compatibility_digest": self.compatibility_digest,
            "source_evidence_pack_hash": self.source_evidence_pack_hash,
            "anchor_digest": self.anchor_digest,
            "latent_steps_requested": self.latent_steps_requested,
            "hidden_steps_captured": self.hidden_steps_captured,
            "latent_steps_committed": self.latent_steps_committed,
            "recurrence_injection_count": self.recurrence_injection_count,
            "alignment_method": self.alignment_method,
            "alignment_config_digest": self.alignment_config_digest,
            "raw_hidden_shape": list(self.raw_hidden_shape),
            "aligned_tensor_shape": list(self.aligned_tensor_shape),
            "aligned_tensor_dtype": self.aligned_tensor_dtype,
            "aligned_tensor_bytes": self.aligned_tensor_bytes,
            "aligned_tensor_digest": self.aligned_tensor_digest,
            "producer_prefill_ms": self.producer_prefill_ms,
            "latent_rollout_ms": self.latent_rollout_ms,
            "d2h_ms": self.d2h_ms,
            "registry_commit_ms": self.registry_commit_ms,
            "internal_scheduler_sample_count": self.internal_scheduler_sample_count,
            "alignment_diagnostics": sanitize_alignment_diagnostics(
                self.alignment_diagnostics
            ),
            "extra": dict(sorted(self.extra.items())),
        }

    @property
    def telemetry_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class LatentConsumerTelemetry:
    request_id: str
    ref_id: str
    lease_ms: float
    compatibility_gate_ms: float
    registry_load_ms: float
    h2d_ms: float
    left_token_count: int
    right_token_count: int
    latent_vector_count: int
    combined_prompt_embed_shape: tuple[int, ...]
    combined_prompt_embed_bytes: int
    consumer_forward_observed: bool
    consumer_forward_event_id: str
    consumer_forward_inputs_embeds_shape: tuple[int, ...]
    consumer_forward_inputs_embeds_dtype: str
    consumer_forward_inputs_embeds_digest: str
    consumer_model_ms: float = 0.0
    completion_tokens: int = 0
    claim_validation_verdict: str = ""
    release_ms: float = 0.0
    fallback_reason: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "ref_id": self.ref_id,
            "lease_ms": self.lease_ms,
            "compatibility_gate_ms": self.compatibility_gate_ms,
            "registry_load_ms": self.registry_load_ms,
            "h2d_ms": self.h2d_ms,
            "left_token_count": self.left_token_count,
            "right_token_count": self.right_token_count,
            "latent_vector_count": self.latent_vector_count,
            "combined_prompt_embed_shape": list(self.combined_prompt_embed_shape),
            "combined_prompt_embed_bytes": self.combined_prompt_embed_bytes,
            "consumer_forward_observed": self.consumer_forward_observed,
            "consumer_forward_event_id": self.consumer_forward_event_id,
            "consumer_forward_inputs_embeds_shape": list(
                self.consumer_forward_inputs_embeds_shape
            ),
            "consumer_forward_inputs_embeds_dtype": self.consumer_forward_inputs_embeds_dtype,
            "consumer_forward_inputs_embeds_digest": self.consumer_forward_inputs_embeds_digest,
            "consumer_model_ms": self.consumer_model_ms,
            "completion_tokens": self.completion_tokens,
            "claim_validation_verdict": self.claim_validation_verdict,
            "release_ms": self.release_ms,
            "fallback_reason": self.fallback_reason,
            "extra": dict(sorted(self.extra.items())),
        }

    @property
    def telemetry_hash(self) -> str:
        return sha256_digest(self.canonical_payload())
