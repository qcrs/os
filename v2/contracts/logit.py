from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from v2.utils import sha256_digest


LOGIT_STATE_SCHEMA_VERSION = "statebus.logit_state.v2"
CANDIDATE_SURFACE_SCHEMA_VERSION = "statebus.candidate_surface.v2"
LOGIT_PRODUCER_RECEIPT_SCHEMA_VERSION = "statebus.logit_producer_receipt.v2"
GATE_DECISION_SCHEMA_VERSION = "statebus.gate_decision.v1"
ACTION_EFFECT_RECEIPT_SCHEMA_VERSION = "statebus.action_effect_receipt.v1"
EXECUTOR_CHOICE_DECISION_TYPE = "executor_tool_recipe_choice_v1"
LOGIT_PROBABILITY_SEMANTICS = "candidate_order_plus_other_mass_v1"
LOGIT_DTYPE = "<f4"
LOGIT_BYTE_ORDER = "little"
LOGIT_CLAIM_BOUNDARY = (
    "closed_executor_choice_probability_state_only_no_hidden_state_or_kv_transfer"
)

_ALIASES = tuple("ABCDEFGH")


class LogitPolicy(StrEnum):
    OFF = "off"
    TELEMETRY_ONLY = "telemetry_only"
    GATED = "gated"


class LogitProducerStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class GateAction(StrEnum):
    ACCEPT = "accept"
    EXPAND_ONCE = "expand_once"
    VERIFY_ONCE = "verify_once"
    SELECTION_RETRY_ONCE = "selection_retry_once"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True)
class CandidateAliasBinding:
    ordinal: int
    alias: str
    candidate_id: str
    candidate_digest: str
    token_bytes_hex: str
    token_id: int = -1

    def __post_init__(self) -> None:
        if not 0 <= self.ordinal < len(_ALIASES):
            raise ValueError("candidate alias ordinal out of range")
        if self.alias != _ALIASES[self.ordinal]:
            raise ValueError("candidate aliases must be canonical A..H order")
        if not self.candidate_id.strip() or not self.candidate_digest.strip():
            raise ValueError("candidate alias binding requires candidate identity")
        try:
            token_bytes = bytes.fromhex(self.token_bytes_hex)
        except ValueError as exc:
            raise ValueError("candidate alias token bytes must be hexadecimal") from exc
        if token_bytes != self.alias.encode("ascii"):
            raise ValueError("candidate alias token bytes must exactly encode its ASCII alias")
        if self.token_id < -1:
            raise ValueError("candidate alias token_id must be -1 or non-negative")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "alias": self.alias,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "token_bytes_hex": self.token_bytes_hex,
            "token_id": self.token_id,
        }


@dataclass(frozen=True)
class CandidateSurfaceV2:
    bindings: tuple[CandidateAliasBinding, ...]
    decision_type: str = EXECUTOR_CHOICE_DECISION_TYPE
    schema_version: str = CANDIDATE_SURFACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CANDIDATE_SURFACE_SCHEMA_VERSION:
            raise ValueError(f"unsupported candidate surface schema: {self.schema_version}")
        if self.decision_type != EXECUTOR_CHOICE_DECISION_TYPE:
            raise ValueError(f"unsupported LogitState decision type: {self.decision_type}")
        if not 2 <= len(self.bindings) <= len(_ALIASES):
            raise ValueError("candidate surface requires 2..8 candidates")
        expected_ordinals = tuple(range(len(self.bindings)))
        if tuple(binding.ordinal for binding in self.bindings) != expected_ordinals:
            raise ValueError("candidate surface bindings must use contiguous canonical order")
        candidate_ids = tuple(binding.candidate_id for binding in self.bindings)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate surface candidate IDs must be unique")
        token_ids = tuple(binding.token_id for binding in self.bindings if binding.token_id >= 0)
        if token_ids and len(token_ids) != len(self.bindings):
            raise ValueError("candidate surface token IDs must be all present or all omitted")
        if len(set(token_ids)) != len(token_ids):
            raise ValueError("candidate surface token IDs must be unique")

    @classmethod
    def from_candidate_ids(
        cls,
        candidate_ids: tuple[str, ...],
        *,
        candidate_digests: tuple[str, ...] = (),
        token_ids: tuple[int, ...] = (),
    ) -> "CandidateSurfaceV2":
        if candidate_digests and len(candidate_digests) != len(candidate_ids):
            raise ValueError("candidate_digests length mismatch")
        if token_ids and len(token_ids) != len(candidate_ids):
            raise ValueError("token_ids length mismatch")
        bindings = tuple(
            CandidateAliasBinding(
                ordinal=index,
                alias=_ALIASES[index],
                candidate_id=candidate_id,
                candidate_digest=(
                    candidate_digests[index]
                    if candidate_digests
                    else sha256_digest({"candidate_id": candidate_id})
                ),
                token_bytes_hex=_ALIASES[index].encode("ascii").hex(),
                token_id=token_ids[index] if token_ids else -1,
            )
            for index, candidate_id in enumerate(candidate_ids)
        )
        return cls(bindings=bindings)

    @property
    def candidate_count(self) -> int:
        return len(self.bindings)

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(binding.alias for binding in self.bindings)

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(binding.candidate_id for binding in self.bindings)

    @property
    def alias_mapping_digest(self) -> str:
        return sha256_digest(
            [
                {
                    "ordinal": binding.ordinal,
                    "alias": binding.alias,
                    "candidate_id": binding.candidate_id,
                    "token_bytes_hex": binding.token_bytes_hex,
                    "token_id": binding.token_id,
                }
                for binding in self.bindings
            ]
        )

    @property
    def candidate_surface_digest(self) -> str:
        return sha256_digest(self.canonical_payload())

    def candidate_id_for_alias(self, alias: str) -> str:
        for binding in self.bindings:
            if binding.alias == alias:
                return binding.candidate_id
        raise KeyError(alias)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_type": self.decision_type,
            "bindings": [binding.canonical_payload() for binding in self.bindings],
            "candidate_count": self.candidate_count,
            "alias_mapping_digest": self.alias_mapping_digest,
            "claim_boundary": LOGIT_CLAIM_BOUNDARY,
        }


@dataclass(frozen=True)
class LogitProducerReceipt:
    request_id: str
    attempt_id: str
    status: LogitProducerStatus
    candidate_surface_digest: str
    alias_mapping_digest: str
    selected_alias: str = ""
    selected_candidate_id: str = ""
    decision_token_position: int = -1
    sequence_length: int = 0
    top_k: int = 0
    unavailable_reason: str = ""
    schema_version: str = LOGIT_PRODUCER_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LOGIT_PRODUCER_RECEIPT_SCHEMA_VERSION:
            raise ValueError(f"unsupported producer receipt schema: {self.schema_version}")
        if not self.request_id or not self.attempt_id:
            raise ValueError("producer receipt requires request and attempt IDs")
        if self.status is LogitProducerStatus.AVAILABLE:
            if self.unavailable_reason:
                raise ValueError("available producer receipt cannot have unavailable_reason")
            if not self.selected_alias or not self.selected_candidate_id:
                raise ValueError("available producer receipt requires selected alias/candidate")
            if self.decision_token_position < 0 or self.sequence_length <= self.decision_token_position:
                raise ValueError("available producer receipt has invalid token position")
        elif not self.unavailable_reason:
            raise ValueError("unavailable producer receipt requires a reason")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "status": self.status.value,
            "candidate_surface_digest": self.candidate_surface_digest,
            "alias_mapping_digest": self.alias_mapping_digest,
            "selected_alias": self.selected_alias,
            "selected_candidate_id": self.selected_candidate_id,
            "decision_token_position": self.decision_token_position,
            "sequence_length": self.sequence_length,
            "top_k": self.top_k,
            "unavailable_reason": self.unavailable_reason,
            "claim_boundary": LOGIT_CLAIM_BOUNDARY,
        }


@dataclass(frozen=True)
class LogitStateContractV2:
    state_id: str
    task_id: str
    session_id: str
    trace_id: str
    step_id: str
    request_id: str
    attempt_id: str
    producer_role: str
    producer_component: str
    producer_pid: int
    logical_target: str
    consumer_component: str
    expected_consumer_pid: int
    decision_type: str
    candidate_surface_digest: str
    candidate_count: int
    alias_mapping_digest: str
    decision_token_position: int
    sequence_length: int
    top_k: int
    prompt_sha256: str
    source_evidence_digest: str
    hydration_digest: str
    model_id: str
    model_revision: str
    tokenizer_id: str
    tokenizer_revision: str
    chat_template_sha256: str
    template_kwargs_sha256: str
    response_schema_digest: str
    blob_hash: str
    size_bytes: int
    storage_kind: str
    owner_session_id: str
    lease_created_at_ns: int
    lease_expires_at_ns: int
    calibration_version: str
    threshold_policy_version: str
    gate_budget_version: str
    policy: LogitPolicy
    dtype: str = LOGIT_DTYPE
    byte_order: str = LOGIT_BYTE_ORDER
    shape: tuple[int, ...] = ()
    probability_semantics: str = LOGIT_PROBABILITY_SEMANTICS
    sensitivity_class: str = "derived_probability_state"
    schema_version: str = LOGIT_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LOGIT_STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported LogitState schema: {self.schema_version}")
        required = {
            "state_id": self.state_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "producer_role": self.producer_role,
            "producer_component": self.producer_component,
            "logical_target": self.logical_target,
            "consumer_component": self.consumer_component,
            "candidate_surface_digest": self.candidate_surface_digest,
            "alias_mapping_digest": self.alias_mapping_digest,
            "prompt_sha256": self.prompt_sha256,
            "source_evidence_digest": self.source_evidence_digest,
            "hydration_digest": self.hydration_digest,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "chat_template_sha256": self.chat_template_sha256,
            "template_kwargs_sha256": self.template_kwargs_sha256,
            "response_schema_digest": self.response_schema_digest,
            "blob_hash": self.blob_hash,
            "storage_kind": self.storage_kind,
            "owner_session_id": self.owner_session_id,
            "calibration_version": self.calibration_version,
            "threshold_policy_version": self.threshold_policy_version,
            "gate_budget_version": self.gate_budget_version,
        }
        missing = tuple(name for name, value in required.items() if not str(value).strip())
        if missing:
            raise ValueError(f"LogitState contract missing fields: {', '.join(missing)}")
        if self.producer_role != "executor":
            raise ValueError("LogitState producer role must be executor")
        if self.logical_target != "executor_choice":
            raise ValueError("LogitState logical target must be executor_choice")
        if self.consumer_component != "confidence_gate":
            raise ValueError("LogitState consumer component must be confidence_gate")
        if self.decision_type != EXECUTOR_CHOICE_DECISION_TYPE:
            raise ValueError(f"unsupported LogitState decision type: {self.decision_type}")
        if self.producer_pid <= 0 or self.expected_consumer_pid < 0:
            raise ValueError("invalid LogitState PID binding")
        if not 2 <= self.candidate_count <= len(_ALIASES):
            raise ValueError("LogitState candidate_count must be 2..8")
        if self.shape != (self.candidate_count + 1,):
            raise ValueError("LogitState shape must be [candidate_count + other_mass]")
        if self.dtype != LOGIT_DTYPE or self.byte_order != LOGIT_BYTE_ORDER:
            raise ValueError("LogitState payload must be little-endian float32")
        if self.probability_semantics != LOGIT_PROBABILITY_SEMANTICS:
            raise ValueError("unsupported LogitState probability semantics")
        if self.size_bytes != 4 * (self.candidate_count + 1):
            raise ValueError("LogitState payload byte count mismatch")
        if self.decision_token_position < 0 or self.decision_token_position >= self.sequence_length:
            raise ValueError("LogitState decision token position out of bounds")
        if self.top_k < self.candidate_count:
            raise ValueError("LogitState top_k does not cover candidate surface")
        if self.lease_created_at_ns <= 0 or self.lease_expires_at_ns <= self.lease_created_at_ns:
            raise ValueError("invalid LogitState lease")
        if self.policy is LogitPolicy.OFF:
            raise ValueError("off policy cannot publish LogitState")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
            "producer_role": self.producer_role,
            "producer_component": self.producer_component,
            "producer_pid": self.producer_pid,
            "logical_target": self.logical_target,
            "consumer_component": self.consumer_component,
            "expected_consumer_pid": self.expected_consumer_pid,
            "decision_type": self.decision_type,
            "candidate_surface_digest": self.candidate_surface_digest,
            "candidate_count": self.candidate_count,
            "alias_mapping_digest": self.alias_mapping_digest,
            "decision_token_position": self.decision_token_position,
            "sequence_length": self.sequence_length,
            "top_k": self.top_k,
            "prompt_sha256": self.prompt_sha256,
            "source_evidence_digest": self.source_evidence_digest,
            "hydration_digest": self.hydration_digest,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "chat_template_sha256": self.chat_template_sha256,
            "template_kwargs_sha256": self.template_kwargs_sha256,
            "response_schema_digest": self.response_schema_digest,
            "dtype": self.dtype,
            "byte_order": self.byte_order,
            "shape": list(self.shape),
            "probability_semantics": self.probability_semantics,
            "blob_hash": self.blob_hash,
            "size_bytes": self.size_bytes,
            "storage_kind": self.storage_kind,
            "owner_session_id": self.owner_session_id,
            "lease_created_at_ns": self.lease_created_at_ns,
            "lease_expires_at_ns": self.lease_expires_at_ns,
            "calibration_version": self.calibration_version,
            "threshold_policy_version": self.threshold_policy_version,
            "gate_budget_version": self.gate_budget_version,
            "policy": self.policy.value,
            "sensitivity_class": self.sensitivity_class,
            "claim_boundary": LOGIT_CLAIM_BOUNDARY,
        }


@dataclass(frozen=True)
class GateDecision:
    decision_id: str
    action_token: str
    ref_id: str
    task_id: str
    request_id: str
    consumer_pid: int
    producer_pid: int
    action: GateAction
    selected_candidate_probability: float
    entropy: float
    normalized_entropy: float
    top_margin: float
    other_mass: float
    candidate_count: int
    calibration_version: str
    threshold_policy_version: str
    gate_budget_version: str
    reason: str = ""
    schema_version: str = GATE_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GATE_DECISION_SCHEMA_VERSION:
            raise ValueError(f"unsupported gate decision schema: {self.schema_version}")
        required = {
            "decision_id": self.decision_id,
            "action_token": self.action_token,
            "ref_id": self.ref_id,
            "task_id": self.task_id,
            "request_id": self.request_id,
            "calibration_version": self.calibration_version,
            "threshold_policy_version": self.threshold_policy_version,
            "gate_budget_version": self.gate_budget_version,
        }
        if any(not str(value).strip() for value in required.values()):
            raise ValueError("gate decision missing required identity")
        if self.consumer_pid <= 0 or self.producer_pid <= 0:
            raise ValueError("gate decision requires producer and consumer PIDs")
        if self.consumer_pid == self.producer_pid:
            raise ValueError("gate decision must be produced in an independent PID")
        if not 2 <= self.candidate_count <= len(_ALIASES):
            raise ValueError("invalid gate decision candidate_count")
        numeric = (
            self.selected_candidate_probability,
            self.entropy,
            self.normalized_entropy,
            self.top_margin,
            self.other_mass,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("gate decision features must be finite")
        if not 0.0 <= self.selected_candidate_probability <= 1.0:
            raise ValueError("selected candidate probability out of range")
        if not 0.0 <= self.normalized_entropy <= 1.0 + 1e-6:
            raise ValueError("normalized entropy out of range")
        if not 0.0 <= self.other_mass <= 1.0:
            raise ValueError("other mass out of range")
        if self.action is GateAction.FAIL_CLOSED and not self.reason:
            raise ValueError("fail_closed gate decision requires a reason")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "action_token": self.action_token,
            "ref_id": self.ref_id,
            "task_id": self.task_id,
            "request_id": self.request_id,
            "consumer_pid": self.consumer_pid,
            "producer_pid": self.producer_pid,
            "action": self.action.value,
            "selected_candidate_probability": self.selected_candidate_probability,
            "entropy": self.entropy,
            "normalized_entropy": self.normalized_entropy,
            "top_margin": self.top_margin,
            "other_mass": self.other_mass,
            "candidate_count": self.candidate_count,
            "calibration_version": self.calibration_version,
            "threshold_policy_version": self.threshold_policy_version,
            "gate_budget_version": self.gate_budget_version,
            "reason": self.reason,
            "claim_boundary": LOGIT_CLAIM_BOUNDARY,
        }


@dataclass(frozen=True)
class ActionEffectReceipt:
    decision_id: str
    action_token: str
    ref_id: str
    task_id: str
    step_id: str
    consumer_pid: int
    action: GateAction
    before_decision_surface_hash: str
    after_decision_surface_hash: str
    selection_changed: bool
    error_recovered: bool
    extra_llm_calls: int
    extra_tool_calls: int
    extra_tokens: int
    extra_latency_ms: float
    extra_evidence_bytes: int
    outcome: str
    fallback_reason: str
    release_reason: str
    downstream_ref_ids: tuple[str, ...] = ()
    schema_version: str = ACTION_EFFECT_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ACTION_EFFECT_RECEIPT_SCHEMA_VERSION:
            raise ValueError(f"unsupported action effect schema: {self.schema_version}")
        required = (
            self.decision_id,
            self.action_token,
            self.ref_id,
            self.task_id,
            self.step_id,
            self.before_decision_surface_hash,
            self.after_decision_surface_hash,
            self.outcome,
            self.release_reason,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("action effect receipt missing required identity")
        if self.consumer_pid <= 0:
            raise ValueError("action effect receipt requires consumer PID")
        counts = (
            self.extra_llm_calls,
            self.extra_tool_calls,
            self.extra_tokens,
            self.extra_evidence_bytes,
        )
        if any(value < 0 for value in counts) or self.extra_latency_ms < 0:
            raise ValueError("action effect costs cannot be negative")
        if self.extra_llm_calls > 1 or self.extra_tool_calls > 1:
            raise ValueError("LogitState action budget exceeded")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "action_token": self.action_token,
            "ref_id": self.ref_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "consumer_pid": self.consumer_pid,
            "action": self.action.value,
            "before_decision_surface_hash": self.before_decision_surface_hash,
            "after_decision_surface_hash": self.after_decision_surface_hash,
            "selection_changed": self.selection_changed,
            "error_recovered": self.error_recovered,
            "extra_llm_calls": self.extra_llm_calls,
            "extra_tool_calls": self.extra_tool_calls,
            "extra_tokens": self.extra_tokens,
            "extra_latency_ms": self.extra_latency_ms,
            "extra_evidence_bytes": self.extra_evidence_bytes,
            "outcome": self.outcome,
            "fallback_reason": self.fallback_reason,
            "release_reason": self.release_reason,
            "downstream_ref_ids": list(self.downstream_ref_ids),
            "claim_boundary": LOGIT_CLAIM_BOUNDARY,
        }
