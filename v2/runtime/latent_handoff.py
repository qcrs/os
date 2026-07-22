from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Callable, Mapping

from v2.contracts import (
    HandoffIntent,
    LatentAnchor,
    LatentForwardProof,
    LatentGateCheck,
    LatentHandoffDecision,
    LatentHandoffMode,
    LatentLifecycleState,
    LatentProofKind,
    NeuralCompatibilitySignature,
)
from v2.integrations.vllm_latent.alignment import sanitize_alignment_diagnostics
from v2.refs import LatentStateRef
from v2.runtime.role_model_backend import (
    LatentBackendError,
    LatentBackendHealth,
    LatentCompleteRequest,
    LatentProduceRequest,
    RoleModelBackend,
)


@dataclass(frozen=True)
class LatentHandoffPolicyConfig:
    mode: LatentHandoffMode = LatentHandoffMode.OFF
    min_evidence_tokens: int = 1024
    max_evidence_tokens: int = 6144
    latent_steps: int = 8
    ttl_s: int = 60
    fallback_policy: str = "full_evidence_text"

    @classmethod
    def from_env(cls) -> "LatentHandoffPolicyConfig":
        return cls(
            mode=LatentHandoffMode(
                os.environ.get("STATEBUS_LATENT_HANDOFF_MODE", "off").strip().lower()
            ),
            min_evidence_tokens=int(
                os.environ.get("STATEBUS_LATENT_MIN_EVIDENCE_TOKENS", "1024")
            ),
            max_evidence_tokens=int(
                os.environ.get("STATEBUS_LATENT_MAX_EVIDENCE_TOKENS", "6144")
            ),
            latent_steps=int(os.environ.get("STATEBUS_LATENT_STEPS", "8")),
            ttl_s=int(os.environ.get("STATEBUS_LATENT_TTL_S", "60")),
        )


@dataclass(frozen=True)
class LatentHandoffOutcome:
    decision: LatentHandoffDecision
    final_output: str
    latent_attempted: bool
    latent_committed: bool
    latent_consumed: bool
    latent_quality_passed: bool
    text_fallback_used: bool
    ref_id: str = ""
    fallback_reason: str = ""


_LATENT_TELEMETRY_AUDIT_FIELDS = frozenset({
    "aligned_tensor_bytes",
    "aligned_tensor_digest",
    "aligned_tensor_dtype",
    "aligned_tensor_shape",
    "alignment_config_digest",
    "alignment_diagnostics",
    "alignment_method",
    "anchor_digest",
    "combined_prompt_embed_bytes",
    "combined_prompt_embed_shape",
    "compatibility_digest",
    "compatibility_gate_ms",
    "completion_tokens",
    "consumer_forward_event_id",
    "consumer_forward_inputs_embeds_digest",
    "consumer_forward_inputs_embeds_dtype",
    "consumer_forward_inputs_embeds_shape",
    "consumer_forward_observed",
    "consumer_model_ms",
    "d2h_ms",
    "engine_id",
    "h2d_ms",
    "hidden_steps_captured",
    "internal_scheduler_sample_count",
    "latent_rollout_ms",
    "latent_steps_committed",
    "latent_steps_requested",
    "latent_vector_count",
    "lease_ms",
    "left_token_count",
    "model_revision",
    "producer_pid",
    "producer_prefill_ms",
    "producer_role",
    "raw_hidden_shape",
    "recurrence_injection_count",
    "ref_id",
    "registry_commit_ms",
    "registry_load_ms",
    "release_ms",
    "request_id",
    "right_token_count",
    "source_evidence_pack_hash",
    "worker_pid",
})


def latent_telemetry_audit_view(values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep mechanism/performance facts without persisting prompts or secrets."""

    projected: dict[str, Any] = {}
    for key, value in sorted(values.items()):
        if key not in _LATENT_TELEMETRY_AUDIT_FIELDS:
            continue
        if key == "alignment_diagnostics":
            diagnostics = sanitize_alignment_diagnostics(value)
            if diagnostics:
                projected[key] = diagnostics
            continue
        if (
            value is None
            or isinstance(value, (str, int, float, bool))
            or (
                isinstance(value, (tuple, list))
                and all(isinstance(item, (str, int, float, bool)) for item in value)
            )
        ):
            projected[key] = value
    return projected


@dataclass
class AdaptiveLatentHandoffState:
    """Runtime-private binding between one Retriever and one Summarizer step."""

    task_id: str
    session_id: str
    approved_plan_hash: str
    producer_step_id: str
    consumer_step_id: str
    evidence_ref_id: str
    anchor: LatentAnchor
    decision: LatentHandoffDecision
    producer_signature: NeuralCompatibilitySignature
    consumer_signature: NeuralCompatibilitySignature
    producer_grant_hash: str
    ref: LatentStateRef | None = None
    producer_request_id: str = ""
    consumer_request_id: str = ""
    captured_step_count: int = 0
    recurrence_injection_count: int = 0
    internal_scheduler_sample_count: int = 0
    latent_attempted: bool = False
    latent_committed: bool = False
    latent_consumed: bool = False
    latent_quality_passed: bool = False
    release_attempted: bool = False
    released: bool = False
    text_fallback_used: bool = False
    fallback_call_count: int = 0
    fallback_reason: str = ""
    release_reason: str = ""
    forward_proof: LatentForwardProof | None = None
    latent_claim_validation_errors: tuple[str, ...] = ()
    producer_telemetry: dict[str, Any] = field(default_factory=dict)
    consumer_telemetry: dict[str, Any] = field(default_factory=dict)

    @property
    def ref_id(self) -> str:
        return "" if self.ref is None else self.ref.ref_id

    def canonical_payload(self) -> dict[str, Any]:
        ref_payload: dict[str, Any] = {}
        if self.ref is not None:
            ref_payload = {
                "ref_id": self.ref.ref_id,
                "ref_kind": "latent_state",
                "status": self.ref.status.value,
                "storage_kind": self.ref.storage_kind.value,
                "producer_role": self.ref.producer_role,
                "consumer_role": self.ref.consumer_role,
                "source_task_id": self.ref.source_task_id,
                "source_step_id": self.ref.source_step_id,
                "source_evidence_pack_hash": self.ref.source_evidence_pack_hash,
                "anchor_item_ids": list(self.ref.anchor_item_ids),
                "anchor_locator_digest": self.ref.anchor_locator_digest,
                "model_id": self.ref.model_id,
                "model_revision": self.ref.model_revision,
                "hidden_size": self.ref.hidden_size,
                "latent_step_count": self.ref.latent_step_count,
                "alignment_method": self.ref.alignment_method,
                "alignment_config_digest": self.ref.alignment_config_digest,
                "position_contract_digest": self.ref.position_contract_digest,
                "dtype": self.ref.dtype,
                "shape": list(self.ref.shape),
                "tensor_bytes": self.ref.tensor_bytes,
                "tensor_digest": self.ref.tensor_digest,
                "producer_pid": self.ref.producer_pid,
                "engine_id": self.ref.engine_id,
                "created_at_ns": self.ref.created_at_ns,
                "expires_at_ns": self.ref.expires_at_ns,
                "compatibility_digest": self.ref.compatibility_digest,
                "schema_version": self.ref.schema_version,
            }
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "approved_plan_hash": self.approved_plan_hash,
            "producer_step_id": self.producer_step_id,
            "consumer_step_id": self.consumer_step_id,
            "evidence_ref_id": self.evidence_ref_id,
            "anchor": self.anchor.canonical_payload(),
            "decision": self.decision.canonical_payload(),
            "producer_compatibility_digest": (
                self.producer_signature.compatibility_digest
            ),
            "consumer_compatibility_digest": (
                self.consumer_signature.compatibility_digest
            ),
            "producer_grant_hash": self.producer_grant_hash,
            "producer_request_id": self.producer_request_id,
            "consumer_request_id": self.consumer_request_id,
            "captured_step_count": self.captured_step_count,
            "recurrence_injection_count": self.recurrence_injection_count,
            "internal_scheduler_sample_count": self.internal_scheduler_sample_count,
            "latent_attempted": self.latent_attempted,
            "latent_committed": self.latent_committed,
            "latent_consumed": self.latent_consumed,
            "latent_quality_passed": self.latent_quality_passed,
            "release_attempted": self.release_attempted,
            "released": self.released,
            "text_fallback_used": self.text_fallback_used,
            "fallback_call_count": self.fallback_call_count,
            "fallback_reason": self.fallback_reason,
            "release_reason": self.release_reason,
            "forward_proof": (
                None
                if self.forward_proof is None
                else self.forward_proof.canonical_payload()
            ),
            "latent_claim_validation_errors": list(
                self.latent_claim_validation_errors
            ),
            "producer_telemetry": latent_telemetry_audit_view(
                self.producer_telemetry
            ),
            "consumer_telemetry": latent_telemetry_audit_view(
                self.consumer_telemetry
            ),
            "ref": ref_payload,
            "schema_version": "statebus.adaptive_latent_handoff.v1",
        }


class LatentHandoffController:
    def __init__(self, config: LatentHandoffPolicyConfig | None = None) -> None:
        self.config = config or LatentHandoffPolicyConfig.from_env()

    def decide(
        self,
        *,
        requested_policy: HandoffIntent,
        producer_role: str,
        consumer_role: str,
        evidence_kinds: tuple[str, ...],
        evidence_token_estimate: int,
        exact_artifact_only: bool,
        numeric_table_only: bool,
        evidence_coverage_complete: bool,
        producer_signature: NeuralCompatibilitySignature,
        consumer_signature: NeuralCompatibilitySignature,
        plugin_health: LatentBackendHealth,
        registry_budget_available: bool,
        claim_validator_available: bool,
        text_fallback_available: bool,
    ) -> LatentHandoffDecision:
        mode = self.config.mode
        requested = (
            mode == LatentHandoffMode.FORCE
            or requested_policy == HandoffIntent.LATENT_ASSIST
        )
        narrative = bool(
            {kind.strip().lower() for kind in evidence_kinds}
            & {"narrative", "semantic", "semantic_context", "conflict", "risk"}
        )
        signature_mismatches = producer_signature.mismatch_fields(consumer_signature)
        support_errors = producer_signature.initial_support_matrix_errors()
        checks = (
            LatentGateCheck("mode_enabled", mode != LatentHandoffMode.OFF, mode.value),
            LatentGateCheck("planner_or_force_requested", requested, requested_policy.value),
            LatentGateCheck(
                "role_edge_allowed",
                producer_role == "retriever" and consumer_role == "summarizer",
                f"{producer_role}->{consumer_role}",
            ),
            LatentGateCheck("narrative_evidence", narrative, ",".join(evidence_kinds)),
            LatentGateCheck(
                "evidence_token_budget",
                self.config.min_evidence_tokens
                <= evidence_token_estimate
                <= self.config.max_evidence_tokens,
                str(evidence_token_estimate),
            ),
            LatentGateCheck("not_exact_artifact_only", not exact_artifact_only),
            LatentGateCheck("not_numeric_table_only", not numeric_table_only),
            LatentGateCheck("evidence_coverage_complete", evidence_coverage_complete),
            LatentGateCheck(
                "signature_exact_match",
                not signature_mismatches,
                ",".join(signature_mismatches),
            ),
            LatentGateCheck(
                "initial_support_matrix",
                not support_errors,
                ",".join(support_errors),
            ),
            LatentGateCheck(
                "plugin_health_ready",
                plugin_health.ready,
                plugin_health.status,
            ),
            LatentGateCheck(
                "plugin_signature_match",
                plugin_health.compatibility_signature.compatibility_digest
                == producer_signature.compatibility_digest,
            ),
            LatentGateCheck("registry_budget_available", registry_budget_available),
            LatentGateCheck("claim_validator_available", claim_validator_available),
            LatentGateCheck("text_fallback_available", text_fallback_available),
        )
        first_failed = next((check.name for check in checks if not check.passed), "")
        if first_failed:
            effective_policy = "text"
        elif mode == LatentHandoffMode.SHADOW:
            effective_policy = "latent_shadow"
        else:
            effective_policy = "latent"
        return LatentHandoffDecision(
            mode=mode,
            requested_policy=requested_policy,
            effective_policy=effective_policy,
            checks=checks,
            rejection_reason=first_failed,
            plugin_health_digest=plugin_health.health_digest,
            compatibility_digest=producer_signature.compatibility_digest,
            fallback_policy=self.config.fallback_policy,
        )

    def run(
        self,
        *,
        decision: LatentHandoffDecision,
        backend: RoleModelBackend,
        produce_request: LatentProduceRequest,
        complete_request_factory: Callable[[str], LatentCompleteRequest],
        validate_output: Callable[[str], bool],
        text_fallback: Callable[[], str],
    ) -> LatentHandoffOutcome:
        if not decision.latent_enabled:
            return self._fallback(
                decision=decision,
                text_fallback=text_fallback,
                reason=decision.rejection_reason or "latent_not_enabled",
            )

        ref_id = ""
        committed = False
        try:
            produced = backend.produce(produce_request)
            ref = produced.ref
            ref_id = ref.ref_id
            self.validate_produced_ref(produce_request, produced)
            committed = True
            if decision.effective_policy == "latent_shadow":
                backend.release(ref_id)
                return self._fallback(
                    decision=decision,
                    text_fallback=text_fallback,
                    reason="shadow_mode_text_selected",
                    latent_attempted=True,
                    latent_committed=True,
                    ref_id=ref_id,
                )

            complete_request = complete_request_factory(ref_id)
            completion = backend.complete(complete_request)
            self.validate_completion_forward(
                ref=ref,
                request=complete_request,
                completion=completion,
            )
            if not validate_output(completion.text):
                raise LatentBackendError("latent_output_validation_failed")
            backend.release(ref_id)
            return LatentHandoffOutcome(
                decision=decision,
                final_output=completion.text,
                latent_attempted=True,
                latent_committed=True,
                latent_consumed=True,
                latent_quality_passed=True,
                text_fallback_used=False,
                ref_id=ref_id,
            )
        except LatentBackendError as exc:
            if ref_id:
                backend.release(ref_id)
            return self._fallback(
                decision=decision,
                text_fallback=text_fallback,
                reason=exc.error_code,
                latent_attempted=True,
                latent_committed=committed,
                ref_id=ref_id,
            )

    @staticmethod
    def validate_produced_ref(produce_request, produced) -> None:
        ref = produced.ref
        expected_shape = (
            produce_request.latent_steps,
            produce_request.compatibility_signature.hidden_size,
        )
        if ref.status != LatentLifecycleState.COMMITTED:
            raise LatentBackendError("latent_capture_incomplete")
        if (
            produced.captured_step_count != produce_request.latent_steps
            or produced.recurrence_injection_count != produce_request.latent_steps - 1
            or ref.shape != expected_shape
            or ref.tensor_bytes != expected_shape[0] * expected_shape[1] * 2
        ):
            raise LatentBackendError("latent_capture_incomplete")
        if (
            ref.source_task_id != produce_request.task_id
            or ref.source_step_id != produce_request.source_step_id
            or ref.producer_role != produce_request.producer_role
            or ref.consumer_role != produce_request.consumer_role
        ):
            raise LatentBackendError("latent_request_invalid")
        anchor = produce_request.anchor
        if (
            ref.source_evidence_pack_hash != anchor.evidence_pack_hash
            or ref.anchor_item_ids != anchor.item_ids
            or ref.anchor_locator_digest != anchor.locator_digest
        ):
            raise LatentBackendError("latent_anchor_mismatch")
        if ref.compatibility_digest != produce_request.compatibility_signature.compatibility_digest:
            raise LatentBackendError("latent_model_incompatible")

    @staticmethod
    def validate_completion_forward(*, ref, request, completion) -> None:
        proof = completion.forward_proof
        if (
            not completion.consumer_forward_observed
            or completion.consumed_ref_id != ref.ref_id
            or proof is None
            or proof.ref_id != ref.ref_id
            or proof.request_id != request.request_id
            or proof.proof_kind != LatentProofKind.WORKER_FORWARD
            or proof.worker_pid <= 0
            or not proof.event_id
            or not proof.engine_id
            or proof.observed_at_ns <= 0
            or not proof.inputs_embeds_digest
            or proof.inputs_embeds_shape != completion.prompt_embed_shape
            or len(proof.inputs_embeds_shape) != 2
            or proof.inputs_embeds_shape[-1] != ref.hidden_size
            or proof.inputs_embeds_dtype.lower().replace("torch.", "")
            not in {"bf16", "bfloat16"}
        ):
            raise LatentBackendError("latent_consumer_forward_not_observed")
        telemetry = dict(completion.telemetry)
        bindings = {
            "request_id": proof.request_id,
            "ref_id": proof.ref_id,
            "consumer_forward_observed": True,
            "consumer_forward_event_id": proof.event_id,
            "consumer_forward_inputs_embeds_digest": proof.inputs_embeds_digest,
            "consumer_forward_inputs_embeds_dtype": proof.inputs_embeds_dtype,
            "consumer_forward_inputs_embeds_shape": list(proof.inputs_embeds_shape),
        }
        for key, expected in bindings.items():
            if key not in telemetry:
                raise LatentBackendError("latent_consumer_forward_not_observed")
            observed = telemetry[key]
            if key.endswith("_shape"):
                observed = list(observed)
            if observed != expected:
                raise LatentBackendError("latent_consumer_forward_not_observed")

    @staticmethod
    def _fallback(
        *,
        decision: LatentHandoffDecision,
        text_fallback: Callable[[], str],
        reason: str,
        latent_attempted: bool = False,
        latent_committed: bool = False,
        ref_id: str = "",
    ) -> LatentHandoffOutcome:
        return LatentHandoffOutcome(
            decision=decision,
            final_output=text_fallback(),
            latent_attempted=latent_attempted,
            latent_committed=latent_committed,
            latent_consumed=False,
            latent_quality_passed=False,
            text_fallback_used=True,
            ref_id=ref_id,
            fallback_reason=reason,
        )
