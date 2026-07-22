from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from v2.contracts.constants import (
    ADAPTIVE_TASK_ENVELOPE_SCHEMA_VERSION,
    APPROVED_PLAN_SCHEMA_VERSION,
    CAPABILITY_DESCRIPTOR_SCHEMA_VERSION,
    CAPABILITY_GRANT_SCHEMA_VERSION,
    CAPABILITY_QUALITY_REPORT_SCHEMA_VERSION,
    CLAIM_SET_SCHEMA_VERSION,
    CLAIM_SET_V2_SCHEMA_VERSION,
    EVIDENCE_COVERAGE_REPORT_SCHEMA_VERSION,
    EVIDENCE_PROJECTION_REPORT_SCHEMA_VERSION,
    EVIDENCE_PROJECTION_REQUEST_SCHEMA_VERSION,
    EVIDENCE_REQUEST_SCHEMA_VERSION,
    PLAN_POLICY_REPORT_SCHEMA_VERSION,
    PLAN_PROPOSAL_SCHEMA_VERSION,
    STATE_CONSUMPTION_RECORD_SCHEMA_VERSION,
    TRANSFORM_PROGRAM_SCHEMA_VERSION,
    ADAPTIVE_EXECUTION_AUDIT_SCHEMA_VERSION,
)
from v2.contracts.neural import HandoffIntent
from v2.utils import sha256_digest


class WorkflowMode(StrEnum):
    STRICT_FIXED = "strict_fixed"
    ADAPTIVE_SHADOW = "adaptive_shadow"
    ADAPTIVE_BOUNDED = "adaptive_bounded"


class ExecutionKind(StrEnum):
    RUNTIME_BUILTIN = "runtime_builtin"
    RETRIEVAL_ADAPTER = "retrieval_adapter"
    TRANSFORM_DSL = "transform_dsl"
    LLM_BOUNDED_PYTHON = "llm_bounded_python"


class RiskClass(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    BOUNDED_CODE = "bounded_code"


class PlanPolicyStatus(StrEnum):
    APPROVED = "approved"
    NORMALIZED = "normalized"
    REPAIR_REQUIRED = "repair_required"
    REJECTED = "rejected"
    FALLBACK_FIXED_PLAN = "fallback_fixed_plan"


class EvidenceCoverageStatus(StrEnum):
    COMPLETE = "complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class ClaimSetStatus(StrEnum):
    READY = "ready"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MISSING_CITATION = "missing_citation"
    FACT_CONFLICT = "fact_conflict"


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    owner_role: str
    description: str
    input_ref_kinds: tuple[str, ...]
    input_contract_version: str
    output_ref_kinds: tuple[str, ...]
    output_contract_version: str
    execution_kind: ExecutionKind
    side_effect_class: RiskClass
    max_runtime_ms: int
    supports_replay: bool
    # input_ref_kinds is the accepted union. Some capabilities additionally
    # require one verified input of every kind listed here.
    required_input_ref_kinds: tuple[str, ...] = ()
    validator_ids: tuple[str, ...] = ()
    fallback_capability_id: str = ""
    # This is an authority contract, not a JSON response schema.  It tells the
    # Planner which completion checks can be requested for this capability and
    # lets the policy reject criteria that the concrete implementation cannot
    # satisfy on its registered data surface.
    completion_criteria_contract: dict[str, dict[str, object]] = field(default_factory=dict)
    version: str = "v1"
    schema_version: str = CAPABILITY_DESCRIPTOR_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "owner_role": self.owner_role,
            "description": self.description,
            "input_ref_kinds": list(self.input_ref_kinds),
            "input_contract_version": self.input_contract_version,
            "output_ref_kinds": list(self.output_ref_kinds),
            "output_contract_version": self.output_contract_version,
            "execution_kind": self.execution_kind.value,
            "side_effect_class": self.side_effect_class.value,
            "max_runtime_ms": self.max_runtime_ms,
            "supports_replay": self.supports_replay,
            "required_input_ref_kinds": list(self.required_input_ref_kinds),
            "validator_ids": list(self.validator_ids),
            "fallback_capability_id": self.fallback_capability_id,
            "completion_criteria_contract": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.completion_criteria_contract.items())
            },
            "version": self.version,
            "schema_version": self.schema_version,
        }

    def public_view(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "role": self.owner_role,
            "description": self.description,
            "accepts": list(self.input_ref_kinds),
            "requires": list(self.required_input_ref_kinds),
            "produces": list(self.output_ref_kinds),
            "output_contract": self.output_contract_version,
            "execution_kind": self.execution_kind.value,
            "side_effect": self.side_effect_class.value,
            "fallback_capability_id": self.fallback_capability_id,
            "completion_criteria": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.completion_criteria_contract.items())
            },
        }


@dataclass(frozen=True)
class AdaptiveTaskEnvelope:
    task_id: str
    canonical_task_spec_hash: str
    workflow_mode: WorkflowMode
    domain_pack_id: str
    allowed_capability_ids: tuple[str, ...]
    allowed_output_contracts: tuple[str, ...]
    allowed_handoff_intents: tuple[str, ...] = (
        HandoffIntent.AUTO.value,
        HandoffIntent.TEXT.value,
        HandoffIntent.EXACT_ARTIFACT_PREFERRED.value,
    )
    allowed_memory_policies: tuple[str, ...] = (
        "none",
        "assist",
        "artifact",
        "strategy",
        "validated_replay",
        "exact_replay",
    )
    role_cardinality: dict[str, tuple[int, int]] = field(default_factory=dict)
    max_plan_steps: int = 6
    max_dependency_depth: int = 4
    max_planner_prompt_tokens: int = 8_192
    max_planner_completion_tokens: int = 2_048
    max_retrieval_steps: int = 2
    max_execution_runtime_ms: int = 96_000
    max_replans: int = 1
    max_retrieval_expansions: int = 1
    max_total_attempts: int = 8
    risk_class: RiskClass = RiskClass.WORKSPACE_WRITE
    allow_llm_python: bool = False
    policy_version: str = "statebus.plan_policy.v1"
    schema_version: str = ADAPTIVE_TASK_ENVELOPE_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "canonical_task_spec_hash": self.canonical_task_spec_hash,
            "workflow_mode": self.workflow_mode.value,
            "domain_pack_id": self.domain_pack_id,
            "allowed_capability_ids": list(self.allowed_capability_ids),
            "allowed_output_contracts": list(self.allowed_output_contracts),
            "allowed_handoff_intents": list(self.allowed_handoff_intents),
            "allowed_memory_policies": list(self.allowed_memory_policies),
            "role_cardinality": {
                role: {"minimum": bounds[0], "maximum": bounds[1]}
                for role, bounds in sorted(self.role_cardinality.items())
            },
            "max_plan_steps": self.max_plan_steps,
            "max_dependency_depth": self.max_dependency_depth,
            "max_planner_prompt_tokens": self.max_planner_prompt_tokens,
            "max_planner_completion_tokens": self.max_planner_completion_tokens,
            "max_retrieval_steps": self.max_retrieval_steps,
            "max_execution_runtime_ms": self.max_execution_runtime_ms,
            "max_replans": self.max_replans,
            "max_retrieval_expansions": self.max_retrieval_expansions,
            "max_total_attempts": self.max_total_attempts,
            "risk_class": self.risk_class.value,
            "allow_llm_python": self.allow_llm_python,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def envelope_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class PlanStepProposal:
    step_id: str
    role: str
    capability_id: str
    goal: str
    depends_on: tuple[str, ...] = ()
    input_ref_ids: tuple[str, ...] = ()
    input_ref_kinds: tuple[str, ...] = ()
    output_contract_version: str = ""
    completion_criteria: dict[str, object] = field(default_factory=dict)
    on_failure: str = "fail"
    # Field-level flow is semantic planning metadata. Ref kinds still define
    # authority; this tuple lets policy verify that a downstream Executor does
    # not assume columns its upstream Executor never promised to retain.
    required_input_fields: tuple[str, ...] = ()
    handoff_intent: HandoffIntent = HandoffIntent.AUTO

    def __post_init__(self) -> None:
        if not isinstance(self.handoff_intent, HandoffIntent):
            object.__setattr__(self, "handoff_intent", HandoffIntent(self.handoff_intent))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "role": self.role,
            "capability_id": self.capability_id,
            "goal": self.goal,
            "depends_on": list(self.depends_on),
            "input_ref_ids": list(self.input_ref_ids),
            "input_ref_kinds": list(self.input_ref_kinds),
            "output_contract_version": self.output_contract_version,
            "completion_criteria": dict(sorted(self.completion_criteria.items())),
            "on_failure": self.on_failure,
            "required_input_fields": list(self.required_input_fields),
            "handoff_intent": self.handoff_intent.value,
        }


@dataclass(frozen=True)
class PlanProposal:
    proposal_id: str
    task_id: str
    steps: tuple[PlanStepProposal, ...]
    final_output_contract_version: str
    requested_memory_policy: str = "none"
    planner_notes: str = ""
    model_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    raw_output_hash: str = ""
    schema_version: str = PLAN_PROPOSAL_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "steps": [step.canonical_payload() for step in self.steps],
            "final_output_contract_version": self.final_output_contract_version,
            "requested_memory_policy": self.requested_memory_policy,
            "planner_notes": self.planner_notes,
            "model_id": self.model_id,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "raw_output_hash": self.raw_output_hash,
            "schema_version": self.schema_version,
        }

    @property
    def proposal_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class PlanPolicyIssue:
    error_code: str
    step_id: str = ""
    field_path: str = ""
    proposed_value_hash: str = ""
    resolution: str = ""

    def canonical_payload(self) -> dict[str, str]:
        return {
            "error_code": self.error_code,
            "step_id": self.step_id,
            "field_path": self.field_path,
            "proposed_value_hash": self.proposed_value_hash,
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class PlanPolicyReport:
    proposal_id: str
    status: PlanPolicyStatus
    issues: tuple[PlanPolicyIssue, ...] = ()
    normalized_fields: tuple[str, ...] = ()
    policy_version: str = "statebus.plan_policy.v1"
    schema_version: str = PLAN_POLICY_REPORT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "status": self.status.value,
            "issues": [issue.canonical_payload() for issue in self.issues],
            "normalized_fields": list(self.normalized_fields),
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def report_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class ApprovedPlan:
    approved_plan_id: str
    task_id: str
    source_proposal_id: str
    steps: tuple[PlanStepProposal, ...]
    final_output_contract_version: str
    plan_policy_report_hash: str
    capability_registry_digest: str
    total_attempt_budget: int
    requested_memory_policy: str = "none"
    normalized_fields: tuple[str, ...] = ()
    schema_version: str = APPROVED_PLAN_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "approved_plan_id": self.approved_plan_id,
            "task_id": self.task_id,
            "source_proposal_id": self.source_proposal_id,
            "steps": [step.canonical_payload() for step in self.steps],
            "final_output_contract_version": self.final_output_contract_version,
            "plan_policy_report_hash": self.plan_policy_report_hash,
            "capability_registry_digest": self.capability_registry_digest,
            "total_attempt_budget": self.total_attempt_budget,
            "requested_memory_policy": self.requested_memory_policy,
            "normalized_fields": list(self.normalized_fields),
            "schema_version": self.schema_version,
        }

    @property
    def approved_plan_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class EvidenceRequest:
    request_id: str
    task_id: str
    step_id: str
    queries: tuple[str, ...]
    evidence_types: tuple[str, ...]
    target_entities: tuple[str, ...] = ()
    time_scope: str = ""
    corpus_scope_ids: tuple[str, ...] = ()
    memory_policy: str = "none"
    max_candidates: int = 12
    max_prompt_visible_bytes: int = 16_384
    required_locator: bool = True
    source_plan_step_id: str = ""
    schema_version: str = EVIDENCE_REQUEST_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "queries": list(self.queries),
            "evidence_types": list(self.evidence_types),
            "target_entities": list(self.target_entities),
            "time_scope": self.time_scope,
            "corpus_scope_ids": list(self.corpus_scope_ids),
            "memory_policy": self.memory_policy,
            "max_candidates": self.max_candidates,
            "max_prompt_visible_bytes": self.max_prompt_visible_bytes,
            "required_locator": self.required_locator,
            "source_plan_step_id": self.source_plan_step_id,
            "schema_version": self.schema_version,
        }

    @property
    def request_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class EvidenceCoverageReport:
    status: EvidenceCoverageStatus
    covered_evidence_types: tuple[str, ...]
    missing_evidence_types: tuple[str, ...]
    entity_coverage: tuple[str, ...] = ()
    requested_entities: tuple[str, ...] = ()
    missing_entities: tuple[str, ...] = ()
    evidence_types_coverage: bool = True
    entity_coverage_ok: bool = True
    locator_coverage: bool = True
    requested_time_scope: str = ""
    time_scope_coverage: bool = True
    locator_count: int = 0
    conflict_item_ids: tuple[str, ...] = ()
    consumed_state_ref_ids: tuple[str, ...] = ()
    evidence_pack_hash: str = ""
    coverage_policy_version: str = "statebus.evidence_coverage.v1"
    schema_version: str = EVIDENCE_COVERAGE_REPORT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "covered_evidence_types": list(self.covered_evidence_types),
            "missing_evidence_types": list(self.missing_evidence_types),
            "entity_coverage": list(self.entity_coverage),
            "requested_entities": list(self.requested_entities),
            "missing_entities": list(self.missing_entities),
            "evidence_types_coverage": self.evidence_types_coverage,
            "entity_coverage_ok": self.entity_coverage_ok,
            "locator_coverage": self.locator_coverage,
            "requested_time_scope": self.requested_time_scope,
            "time_scope_coverage": self.time_scope_coverage,
            "locator_count": self.locator_count,
            "conflict_item_ids": list(self.conflict_item_ids),
            "consumed_state_ref_ids": list(self.consumed_state_ref_ids),
            "evidence_pack_hash": self.evidence_pack_hash,
            "coverage_policy_version": self.coverage_policy_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class TransformStep:
    op: str
    arguments: dict[str, object] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return {"op": self.op, "arguments": dict(sorted(self.arguments.items()))}


@dataclass(frozen=True)
class TransformProgram:
    program_id: str
    input_artifact_refs: tuple[str, ...]
    operations: tuple[TransformStep, ...]
    output_contract_version: str
    schema_version: str = TRANSFORM_PROGRAM_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "input_artifact_refs": list(self.input_artifact_refs),
            "operations": [operation.canonical_payload() for operation in self.operations],
            "output_contract_version": self.output_contract_version,
            "schema_version": self.schema_version,
        }

    @property
    def program_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class RoleExecutionReceipt:
    """Controller-checkable evidence of what a role actually used.

    A role may return this wrapper around its normal result.  Prepared inputs
    are deliberately not treated as consumption: only IDs named here (or the
    strict validated-replay path) can create a memory consumption record.
    ``result`` is intentionally opaque and is consumed by the role-specific
    dispatcher.
    """

    result: Any
    consumed_memory_ids: tuple[str, ...] = ()
    consumption_modes: dict[str, str] = field(default_factory=dict)
    rendered_request_hash: str = ""
    executed_recipe_hashes: tuple[str, ...] = ()
    executed_recipe_hashes_by_memory_id: dict[str, str] = field(default_factory=dict)
    memory_actions: dict[str, str] = field(default_factory=dict)
    behavioral_effects: dict[str, str] = field(default_factory=dict)
    effect_evidence_hashes: dict[str, str] = field(default_factory=dict)
    output_decision_surface_hash: str = ""
    execution_outcome: str = "accepted"
    producer_role: str = ""
    producer_pid: int = 0
    physical_consumer_component: str = ""
    physical_consumer_pid: int = 0
    logical_target_role: str = ""
    receipt_id: str = ""
    issued_at_ns: int = 0
    schema_version: str = "statebus.role_execution_receipt.v2"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "consumed_memory_ids": list(self.consumed_memory_ids),
            "consumption_modes": dict(sorted(self.consumption_modes.items())),
            "rendered_request_hash": self.rendered_request_hash,
            "executed_recipe_hashes": list(self.executed_recipe_hashes),
            "executed_recipe_hashes_by_memory_id": dict(
                sorted(self.executed_recipe_hashes_by_memory_id.items())
            ),
            "memory_actions": dict(sorted(self.memory_actions.items())),
            "behavioral_effects": dict(sorted(self.behavioral_effects.items())),
            "effect_evidence_hashes": dict(sorted(self.effect_evidence_hashes.items())),
            "output_decision_surface_hash": self.output_decision_surface_hash,
            "execution_outcome": self.execution_outcome,
            "producer_role": self.producer_role,
            "producer_pid": self.producer_pid,
            "physical_consumer_component": self.physical_consumer_component,
            "physical_consumer_pid": self.physical_consumer_pid,
            "logical_target_role": self.logical_target_role,
            "receipt_id": self.receipt_id,
            "issued_at_ns": self.issued_at_ns,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryCounterfactualCallEvidence:
    pair_id: str
    task_id: str
    step_id: str
    pairing_digest: str
    no_memory_generation_call_count: int
    no_memory_repair_call_count: int
    no_memory_quality_verified: bool
    no_memory_citation_coverage_passed: bool
    serialized_execution: bool = True
    lane_order: str = "no_memory_then_memory"
    schema_version: str = "statebus.memory_counterfactual_call_evidence.v1"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "pair_id": self.pair_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "pairing_digest": self.pairing_digest,
            "no_memory_generation_call_count": self.no_memory_generation_call_count,
            "no_memory_repair_call_count": self.no_memory_repair_call_count,
            "no_memory_quality_verified": self.no_memory_quality_verified,
            "no_memory_citation_coverage_passed": self.no_memory_citation_coverage_passed,
            "serialized_execution": self.serialized_execution,
            "lane_order": self.lane_order,
            "schema_version": self.schema_version,
        }

    @property
    def evidence_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def verified_avoided_call_count(
        self,
        *,
        task_id: str,
        step_id: str,
        pairing_digest: str,
    ) -> int:
        if (
            self.task_id != task_id
            or self.step_id != step_id
            or self.pairing_digest != pairing_digest
            or not self.serialized_execution
            or not self.no_memory_quality_verified
            or not self.no_memory_citation_coverage_passed
        ):
            return 0
        return max(
            0,
            int(self.no_memory_generation_call_count)
            + int(self.no_memory_repair_call_count),
        )


JSONScalar = str | int | float | bool | None


@dataclass(frozen=True)
class ClaimFieldSupport:
    """Machine-readable lineage for one factual field in a claim."""

    field_path: str
    normalized_value_hash: str
    support_kind: str
    evidence_item_ids: tuple[str, ...] = ()
    artifact_ref_id: str = ""
    artifact_field_path: str = ""
    source_locators: tuple[str, ...] = ()
    schema_version: str = CLAIM_SET_V2_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "field_path": self.field_path,
            "normalized_value_hash": self.normalized_value_hash,
            "support_kind": self.support_kind,
            "evidence_item_ids": list(self.evidence_item_ids),
            "artifact_ref_id": self.artifact_ref_id,
            "artifact_field_path": self.artifact_field_path,
            "source_locators": list(self.source_locators),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class Claim:
    claim_id: str
    claim_text: str
    claim_type: str
    supporting_evidence_item_ids: tuple[str, ...] = ()
    supporting_artifact_ref_ids: tuple[str, ...] = ()
    citation_locators: tuple[str, ...] = ()
    numeric_fields: dict[str, float] = field(default_factory=dict)
    uncertainty_note: str = ""
    status: str = "ready"
    factual_fields: dict[str, JSONScalar] = field(default_factory=dict)
    field_support: tuple[ClaimFieldSupport, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        payload = {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "claim_type": self.claim_type,
            "supporting_evidence_item_ids": list(self.supporting_evidence_item_ids),
            "supporting_artifact_ref_ids": list(self.supporting_artifact_ref_ids),
            "citation_locators": list(self.citation_locators),
            "numeric_fields": dict(sorted(self.numeric_fields.items())),
            "uncertainty_note": self.uncertainty_note,
            "status": self.status,
        }
        if self.factual_fields:
            payload["factual_fields"] = dict(sorted(self.factual_fields.items()))
        if self.field_support:
            payload["field_support"] = [item.canonical_payload() for item in self.field_support]
        return payload


@dataclass(frozen=True)
class ClaimSet:
    claim_set_id: str
    task_id: str
    claims: tuple[Claim, ...]
    status: ClaimSetStatus = ClaimSetStatus.READY
    schema_version: str = CLAIM_SET_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "claim_set_id": self.claim_set_id,
            "task_id": self.task_id,
            "claims": [claim.canonical_payload() for claim in self.claims],
            "status": self.status.value,
            "schema_version": self.schema_version,
        }

    @property
    def claim_set_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class StateConsumptionRecord:
    state_ref_id: str
    consumer_role: str
    consumer_step_id: str
    operation: str
    read_field_ids: tuple[str, ...]
    input_decision_surface_hash: str
    output_decision_surface_hash: str
    selected_ids: tuple[str, ...]
    behavioral_effect: str
    downstream_ref_ids: tuple[str, ...] = ()
    # Identity attributes are deliberately separate from additive telemetry
    # counters. ``consumer_role`` remains the legacy downstream-role field.
    logical_owner_role: str = ""
    logical_step_id: str = ""
    producer_role: str = ""
    producer_pid: int = 0
    physical_consumer_component: str = ""
    physical_consumer_pid: int = 0
    physical_consumer_uid: int = 0
    downstream_role: str = ""
    logical_target_role: str = ""
    downstream_hydration_roles: tuple[str, ...] = ()
    hydrate_manifest_id: str = ""
    hydrate_manifest_hash: str = ""
    hydration_receipt_id: str = ""
    hydration_receipt_hash: str = ""
    release_receipt_id: str = ""
    release_receipt_hash: str = ""
    released_by_component: str = ""
    release_reason: str = ""
    released_at_ns: int = 0
    consumed_at_ns: int = 0
    policy_version: str = "statebus.state_consumption.v1"
    schema_version: str = STATE_CONSUMPTION_RECORD_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "state_ref_id": self.state_ref_id,
            "consumer_role": self.consumer_role,
            "consumer_step_id": self.consumer_step_id,
            "operation": self.operation,
            "read_field_ids": list(self.read_field_ids),
            "input_decision_surface_hash": self.input_decision_surface_hash,
            "output_decision_surface_hash": self.output_decision_surface_hash,
            "selected_ids": list(self.selected_ids),
            "behavioral_effect": self.behavioral_effect,
            "downstream_ref_ids": list(self.downstream_ref_ids),
            "logical_owner_role": self.logical_owner_role,
            "logical_step_id": self.logical_step_id,
            "producer_role": self.producer_role,
            "producer_pid": self.producer_pid,
            "physical_consumer_component": self.physical_consumer_component,
            "physical_consumer_pid": self.physical_consumer_pid,
            "physical_consumer_uid": self.physical_consumer_uid,
            "downstream_role": self.downstream_role,
            "logical_target_role": self.logical_target_role,
            "downstream_hydration_roles": list(self.downstream_hydration_roles),
            "hydrate_manifest_id": self.hydrate_manifest_id,
            "hydrate_manifest_hash": self.hydrate_manifest_hash,
            "hydration_receipt_id": self.hydration_receipt_id,
            "hydration_receipt_hash": self.hydration_receipt_hash,
            "release_receipt_id": self.release_receipt_id,
            "release_receipt_hash": self.release_receipt_hash,
            "released_by_component": self.released_by_component,
            "release_reason": self.release_reason,
            "released_at_ns": self.released_at_ns,
            "consumed_at_ns": self.consumed_at_ns,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class CapabilityGrant:
    grant_id: str
    task_id: str
    session_id: str
    step_id: str
    attempt_id: str
    capability_id: str
    capability_version: str
    input_ref_ids: tuple[str, ...]
    output_contract_version: str
    workspace_root_id: str
    max_runtime_ms: int
    expires_at_ns: int
    approved_plan_hash: str
    # Per-attempt nonce and issuance timestamp make a grant token single-use
    # and auditable across process boundaries.  They are part of the hashed
    # binding, never a secret.
    grant_nonce: str = ""
    issued_at_ns: int = 0
    schema_version: str = CAPABILITY_GRANT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "input_ref_ids": list(self.input_ref_ids),
            "output_contract_version": self.output_contract_version,
            "workspace_root_id": self.workspace_root_id,
            "max_runtime_ms": self.max_runtime_ms,
            "expires_at_ns": self.expires_at_ns,
            "approved_plan_hash": self.approved_plan_hash,
            "grant_nonce": self.grant_nonce,
            "issued_at_ns": self.issued_at_ns,
            "schema_version": self.schema_version,
        }

    @property
    def grant_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class EvidenceProjectionRequest:
    task_id: str
    session_id: str
    step_id: str
    evidence_pack_ref_id: str
    evidence_pack_hash: str
    requested_fields: tuple[str, ...]
    allowed_evidence_types: tuple[str, ...] = ("table",)
    required_locator: bool = True
    output_contract_version: str = "statebus.transform_input.v1"
    projection_policy_version: str = "statebus.evidence_projection.v1"
    schema_version: str = EVIDENCE_PROJECTION_REQUEST_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "evidence_pack_ref_id": self.evidence_pack_ref_id,
            "evidence_pack_hash": self.evidence_pack_hash,
            "requested_fields": list(self.requested_fields),
            "allowed_evidence_types": list(self.allowed_evidence_types),
            "required_locator": self.required_locator,
            "output_contract_version": self.output_contract_version,
            "projection_policy_version": self.projection_policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def request_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class EvidenceProjectionReport:
    request_hash: str
    input_evidence_pack_hash: str
    consumed_evidence_item_ids: tuple[str, ...]
    row_lineage: tuple[dict[str, object], ...]
    output_fields: tuple[str, ...]
    row_count: int
    output_artifact_ref_id: str = ""
    output_artifact_hash: str = ""
    missing_fields: tuple[str, ...] = ()
    conflict_item_ids: tuple[str, ...] = ()
    rejection_reason: str = ""
    projection_policy_version: str = "statebus.evidence_projection.v1"
    schema_version: str = EVIDENCE_PROJECTION_REPORT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "request_hash": self.request_hash,
            "input_evidence_pack_hash": self.input_evidence_pack_hash,
            "consumed_evidence_item_ids": list(self.consumed_evidence_item_ids),
            "row_lineage": [dict(sorted(row.items())) for row in self.row_lineage],
            "output_fields": list(self.output_fields),
            "row_count": self.row_count,
            "output_artifact_ref_id": self.output_artifact_ref_id,
            "output_artifact_hash": self.output_artifact_hash,
            "missing_fields": list(self.missing_fields),
            "conflict_item_ids": list(self.conflict_item_ids),
            "rejection_reason": self.rejection_reason,
            "projection_policy_version": self.projection_policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def report_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class CapabilityQualityReport:
    capability_id: str
    validator_id: str
    input_artifact_hashes: tuple[str, ...]
    output_artifact_hash: str
    schema_passed: bool
    recomputation_passed: bool
    provenance_passed: bool
    completion_criteria_passed: bool
    verified: bool
    recomputation_evaluated: bool = True
    error_codes: tuple[str, ...] = ()
    numeric_differences: dict[str, float] = field(default_factory=dict)
    schema_version: str = CAPABILITY_QUALITY_REPORT_SCHEMA_VERSION

    @property
    def execution_verified(self) -> bool:
        return self.verified

    @property
    def semantic_verification_status(self) -> str:
        if not self.recomputation_evaluated:
            return "not_evaluated"
        return "verified" if self.verified and self.recomputation_passed else "failed"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "validator_id": self.validator_id,
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "output_artifact_hash": self.output_artifact_hash,
            "schema_passed": self.schema_passed,
            "recomputation_passed": self.recomputation_passed,
            "provenance_passed": self.provenance_passed,
            "completion_criteria_passed": self.completion_criteria_passed,
            "verified": self.verified,
            "execution_verified": self.execution_verified,
            "recomputation_evaluated": self.recomputation_evaluated,
            "semantic_verification_status": self.semantic_verification_status,
            "error_codes": list(self.error_codes),
            "numeric_differences": dict(sorted(self.numeric_differences.items())),
            "schema_version": self.schema_version,
        }

    @property
    def report_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class AdaptiveExecutionAudit:
    proposal_hash: str
    approved_plan_hash: str
    selected_capability_ids: tuple[str, ...]
    grant_hashes: tuple[str, ...]
    evidence_pack_hashes: tuple[str, ...] = ()
    projection_report_hashes: tuple[str, ...] = ()
    input_artifact_hashes: tuple[str, ...] = ()
    output_artifact_hashes: tuple[str, ...] = ()
    program_hashes: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()
    quality_report_hashes: tuple[str, ...] = ()
    claim_set_hash: str = ""
    fallback_count: int = 0
    repair_count: int = 0
    replan_count: int = 0
    model_decision_behavioral_effect: str = "unknown"
    schema_version: str = ADAPTIVE_EXECUTION_AUDIT_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "proposal_hash": self.proposal_hash,
            "approved_plan_hash": self.approved_plan_hash,
            "selected_capability_ids": list(self.selected_capability_ids),
            "grant_hashes": list(self.grant_hashes),
            "evidence_pack_hashes": list(self.evidence_pack_hashes),
            "projection_report_hashes": list(self.projection_report_hashes),
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "output_artifact_hashes": list(self.output_artifact_hashes),
            "program_hashes": list(self.program_hashes),
            "source_hashes": list(self.source_hashes),
            "quality_report_hashes": list(self.quality_report_hashes),
            "claim_set_hash": self.claim_set_hash,
            "fallback_count": self.fallback_count,
            "repair_count": self.repair_count,
            "replan_count": self.replan_count,
            "model_decision_behavioral_effect": self.model_decision_behavioral_effect,
            "schema_version": self.schema_version,
        }

    @property
    def audit_hash(self) -> str:
        return sha256_digest(self.canonical_payload())
