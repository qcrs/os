"""Provider-neutral plan provenance contracts.

The adaptive contracts in :mod:`statebus.contracts.adaptive` intentionally
remain v1-compatible.  This module adds the provenance objects needed by the
MRR-02 control-plane bridge without changing the payloads (and therefore the
hashes) of those existing contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Mapping

from statebus.contracts.adaptive import (
    ApprovedPlan,
    PlanPolicyReport,
    PlanPolicyStatus,
    PlanProposal,
    PlanStepProposal,
)
from statebus.contracts.identity import RuntimeIdentity, TaskContractIdentity
from statebus.utils import sha256_digest

if TYPE_CHECKING:
    from statebus.runtime.capability_registry import CapabilityRegistry


PLAN_NORMALIZATION_RECEIPT_SCHEMA_VERSION = "statebus.plan_normalization_receipt.v1"
APPROVED_PLAN_BUNDLE_SCHEMA_VERSION = "statebus.approved_plan_bundle.v1"
STATIC_ROLE_RECIPE_SCHEMA_VERSION = "statebus.static_role_recipe.v1"


class PlanProvenanceError(ValueError):
    """Raised when plan provenance objects cannot be made self-consistent."""


class PlanNormalizationClass(StrEnum):
    MECHANICAL_BINDING = "mechanical_binding"


def _text(value: object, field_name: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise PlanProvenanceError(f"{field_name}_must_be_string")
    normalized = value.strip()
    if required and not normalized:
        raise PlanProvenanceError(f"{field_name}_required")
    return normalized


def _semantic_value(value: object) -> object:
    """Canonicalize values that are formatting-only in a plan proposal."""

    if isinstance(value, Mapping):
        return {
            str(key): _semantic_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_semantic_value(item) for item in value]
    return value


def semantic_plan_payload(
    proposal: PlanProposal,
    *,
    runtime_task_id: str | None = None,
    task_contract_hash: str = "",
    task_identity: RuntimeIdentity | TaskContractIdentity | None = None,
    dependency_order_sensitive: bool = False,
) -> dict[str, object]:
    """Return the semantic portion of a plan proposal.

    Planner telemetry (proposal id, notes, model and token/latency fields) is
    deliberately excluded.  Dependencies are represented as graph edges by
    default, so controller-owned ordering of newly completed typed edges does
    not look like a semantic replan.  Proposal-level repair can request
    ``dependency_order_sensitive=True`` when the original order itself is part
    of the untrusted proposal contract.
    """

    if not isinstance(proposal, PlanProposal):
        raise PlanProvenanceError("plan_proposal_required")

    resolved_task_id = runtime_task_id or proposal.task_id
    resolved_contract_hash = task_contract_hash
    if runtime_task_id is not None and proposal.task_id != runtime_task_id:
        raise PlanProvenanceError("runtime_task_id_proposal_mismatch")
    if isinstance(task_identity, RuntimeIdentity):
        if runtime_task_id is not None and runtime_task_id != task_identity.runtime_task_id:
            raise PlanProvenanceError("runtime_task_id_identity_mismatch")
        if proposal.task_id != task_identity.runtime_task_id:
            raise PlanProvenanceError("runtime_task_id_proposal_mismatch")
        if task_contract_hash and task_contract_hash != task_identity.task_contract.contract_hash:
            raise PlanProvenanceError("task_contract_hash_identity_mismatch")
        resolved_task_id = task_identity.runtime_task_id
        resolved_contract_hash = task_identity.task_contract.contract_hash
    elif isinstance(task_identity, TaskContractIdentity):
        if task_contract_hash and task_contract_hash != task_identity.contract_hash:
            raise PlanProvenanceError("task_contract_hash_identity_mismatch")
        resolved_contract_hash = task_identity.contract_hash
    elif task_identity is not None:
        raise PlanProvenanceError("task_identity_type_required")

    steps: list[dict[str, object]] = []
    for step in proposal.steps:
        dependencies = tuple(dict.fromkeys(str(item).strip() for item in step.depends_on))
        if not dependency_order_sensitive:
            dependencies = tuple(sorted(dependencies))
        required_fields = tuple(
            dict.fromkeys(str(item).strip() for item in step.required_input_fields)
        )
        if step.role.strip().lower() != "executor":
            required_fields = ()
        steps.append(
            {
                "step_id": step.step_id.strip(),
                "role": step.role.strip().lower(),
                "capability_id": step.capability_id.strip(),
                "goal": step.goal.strip(),
                "depends_on": list(dependencies),
                "input_ref_ids": list(step.input_ref_ids),
                "input_ref_kinds": list(step.input_ref_kinds),
                "output_contract_version": step.output_contract_version.strip(),
                "completion_criteria": _semantic_value(step.completion_criteria),
                "on_failure": step.on_failure.strip(),
                "required_input_fields": list(required_fields),
            }
        )
    return {
        "runtime_task_id": str(resolved_task_id),
        "task_contract_hash": str(resolved_contract_hash),
        "steps": steps,
        "final_output_contract_version": proposal.final_output_contract_version.strip(),
        "requested_memory_policy": proposal.requested_memory_policy.strip(),
    }


def semantic_plan_hash(
    proposal: PlanProposal,
    *,
    runtime_task_id: str | None = None,
    task_contract_hash: str = "",
    task_identity: RuntimeIdentity | TaskContractIdentity | None = None,
    dependency_order_sensitive: bool = False,
) -> str:
    """Compute a stable hash for the semantic plan graph."""

    return sha256_digest(
        semantic_plan_payload(
            proposal,
            runtime_task_id=runtime_task_id,
            task_contract_hash=task_contract_hash,
            task_identity=task_identity,
            dependency_order_sensitive=dependency_order_sensitive,
        )
    )


def mechanical_semantic_plan_payload(
    proposal: PlanProposal,
    *,
    registry: "CapabilityRegistry | None" = None,
    runtime_task_id: str | None = None,
    task_contract_hash: str = "",
    task_identity: RuntimeIdentity | TaskContractIdentity | None = None,
) -> dict[str, object]:
    """Return a semantic payload after removing only registry-implied edges.

    ``compile_required_input_wiring`` may add a dependency that is already
    implied by a capability's required typed input.  Those edges are
    controller-owned completion, not a new semantic stage.  All other graph
    changes remain visible in the payload and therefore change its hash.
    """

    payload = semantic_plan_payload(
        proposal,
        runtime_task_id=runtime_task_id,
        task_contract_hash=task_contract_hash,
        task_identity=task_identity,
        dependency_order_sensitive=False,
    )
    if registry is None:
        return payload
    step_by_id = {step.step_id: step for step in proposal.steps}
    payload_steps = {str(step["step_id"]): step for step in payload["steps"]}  # type: ignore[index]
    for step in proposal.steps:
        if not registry.contains(step.capability_id):
            continue
        descriptor = registry.get(step.capability_id)
        required_kinds = set(descriptor.required_input_ref_kinds)
        if not required_kinds:
            continue
        inferred_edges: set[str] = set()
        for dependency in step.depends_on:
            producer = step_by_id.get(dependency)
            if producer is None or not registry.contains(producer.capability_id):
                continue
            producer_kinds = set(registry.get(producer.capability_id).output_ref_kinds)
            if required_kinds.intersection(producer_kinds):
                inferred_edges.add(dependency)
        if inferred_edges:
            step_payload = payload_steps.get(step.step_id)
            if step_payload is not None:
                step_payload["depends_on"] = [
                    item
                    for item in step_payload["depends_on"]  # type: ignore[index]
                    if item not in inferred_edges
                ]
    return payload


def mechanical_semantic_plan_hash(
    proposal: PlanProposal,
    *,
    registry: "CapabilityRegistry | None" = None,
    runtime_task_id: str | None = None,
    task_contract_hash: str = "",
    task_identity: RuntimeIdentity | TaskContractIdentity | None = None,
) -> str:
    return sha256_digest(
        mechanical_semantic_plan_payload(
            proposal,
            registry=registry,
            runtime_task_id=runtime_task_id,
            task_contract_hash=task_contract_hash,
            task_identity=task_identity,
        )
    )


def _mechanical_dependency_change_is_monotonic(
    source: PlanProposal,
    effective: PlanProposal,
) -> bool:
    """Allow binding to add/reorder edges, never remove a proposed edge."""

    if len(source.steps) != len(effective.steps):
        return False
    for source_step, effective_step in zip(source.steps, effective.steps, strict=True):
        if source_step.step_id != effective_step.step_id:
            return False
        if not set(source_step.depends_on) <= set(effective_step.depends_on):
            return False
    return True


def _observed_plan_changes(
    source: PlanProposal,
    effective: PlanProposal,
) -> tuple[str, ...]:
    """Describe every field whose stored proposal representation changed."""

    changed: list[str] = []
    for field_name in (
        "proposal_id",
        "task_id",
        "final_output_contract_version",
        "requested_memory_policy",
        "planner_notes",
        "model_id",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "raw_output_hash",
        "schema_version",
    ):
        if getattr(source, field_name) != getattr(effective, field_name):
            changed.append(field_name)
    if len(source.steps) != len(effective.steps):
        changed.append("steps")
        return tuple(changed)
    for index, (source_step, effective_step) in enumerate(
        zip(source.steps, effective.steps, strict=True)
    ):
        step_id = effective_step.step_id or source_step.step_id or str(index)
        for field_name in (
            "step_id",
            "role",
            "capability_id",
            "goal",
            "depends_on",
            "input_ref_ids",
            "input_ref_kinds",
            "output_contract_version",
            "completion_criteria",
            "on_failure",
            "required_input_fields",
        ):
            if getattr(source_step, field_name) != getattr(effective_step, field_name):
                changed.append(f"steps.{step_id}.{field_name}")
    return tuple(changed)


# Explicit aliases make the helper discoverable without forcing callers to
# depend on one spelling while the MRR contracts settle.
canonical_semantic_plan_hash = semantic_plan_hash
plan_semantic_hash = semantic_plan_hash


@dataclass(frozen=True)
class PlanNormalizationReceipt:
    """Evidence that a proposal changed only through mechanical binding."""

    normalization_id: str
    normalizer_id: str
    normalizer_version: str
    source_proposal_hash: str
    effective_proposal_hash: str
    normalization_class: PlanNormalizationClass | str = (
        PlanNormalizationClass.MECHANICAL_BINDING
    )
    before_semantic_hash: str = ""
    after_semantic_hash: str = ""
    changed_fields: tuple[str, ...] = ()
    schema_version: str = PLAN_NORMALIZATION_RECEIPT_SCHEMA_VERSION
    runtime_task_id: str = ""
    task_contract_hash: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "normalization_id",
            "normalizer_id",
            "normalizer_version",
            "source_proposal_hash",
            "effective_proposal_hash",
            "before_semantic_hash",
            "after_semantic_hash",
            "schema_version",
        ):
            _text(getattr(self, field_name), field_name)
        normalization_class = _text(
            self.normalization_class,
            "normalization_class",
        )
        if normalization_class != PlanNormalizationClass.MECHANICAL_BINDING.value:
            raise PlanProvenanceError("unsupported_plan_normalization_class")
        if self.before_semantic_hash != self.after_semantic_hash:
            raise PlanProvenanceError("mechanical_normalization_changed_semantics")
        if self.runtime_task_id:
            _text(self.runtime_task_id, "runtime_task_id")
        if self.task_contract_hash:
            _text(self.task_contract_hash, "task_contract_hash")
        object.__setattr__(
            self,
            "normalization_class",
            PlanNormalizationClass(normalization_class),
        )
        object.__setattr__(
            self,
            "changed_fields",
            tuple(dict.fromkeys(str(item) for item in self.changed_fields if str(item))),
        )

    @classmethod
    def from_proposals(
        cls,
        source: PlanProposal,
        effective: PlanProposal,
        *,
        normalizer_id: str = "statebus.runtime.compile_required_input_wiring",
        normalizer_version: str = "v1",
        changed_fields: tuple[str, ...] = (),
        runtime_task_id: str | None = None,
        task_contract_hash: str = "",
        task_identity: RuntimeIdentity | TaskContractIdentity | None = None,
        registry: "CapabilityRegistry | None" = None,
    ) -> "PlanNormalizationReceipt":
        if not _mechanical_dependency_change_is_monotonic(source, effective):
            raise PlanProvenanceError("mechanical_normalization_removed_dependency")
        before = mechanical_semantic_plan_hash(
            source,
            registry=registry,
            runtime_task_id=runtime_task_id,
            task_contract_hash=task_contract_hash,
            task_identity=task_identity,
        )
        after = mechanical_semantic_plan_hash(
            effective,
            registry=registry,
            runtime_task_id=runtime_task_id,
            task_contract_hash=task_contract_hash,
            task_identity=task_identity,
        )
        if before != after:
            raise PlanProvenanceError("mechanical_normalization_changed_semantics")
        resolved_task_id = runtime_task_id
        resolved_contract_hash = task_contract_hash
        if isinstance(task_identity, RuntimeIdentity):
            resolved_task_id = task_identity.runtime_task_id
            resolved_contract_hash = task_identity.task_contract.contract_hash
        elif isinstance(task_identity, TaskContractIdentity):
            resolved_contract_hash = task_identity.contract_hash
        resolved_task_id = resolved_task_id or source.task_id
        normalization_id = (
            f"normalization-{source.proposal_hash[:16]}-{effective.proposal_hash[:16]}"
        )
        recorded_changes = tuple(
            dict.fromkeys((*changed_fields, *_observed_plan_changes(source, effective)))
        )
        return cls(
            normalization_id=normalization_id,
            normalizer_id=normalizer_id,
            normalizer_version=normalizer_version,
            source_proposal_hash=source.proposal_hash,
            effective_proposal_hash=effective.proposal_hash,
            before_semantic_hash=before,
            after_semantic_hash=after,
            changed_fields=recorded_changes,
            runtime_task_id=resolved_task_id,
            task_contract_hash=resolved_contract_hash,
        )

    @property
    def receipt_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    @property
    def normalization_hash(self) -> str:
        return self.receipt_hash

    @property
    def hash(self) -> str:
        return self.receipt_hash

    @property
    def semantic_hash(self) -> str:
        return self.before_semantic_hash

    def canonical_payload(self) -> dict[str, object]:
        return {
            "normalization_id": self.normalization_id,
            "normalizer_id": self.normalizer_id,
            "normalizer_version": self.normalizer_version,
            "source_proposal_hash": self.source_proposal_hash,
            "effective_proposal_hash": self.effective_proposal_hash,
            "normalization_class": (
                self.normalization_class.value
                if isinstance(self.normalization_class, PlanNormalizationClass)
                else self.normalization_class
            ),
            "before_semantic_hash": self.before_semantic_hash,
            "after_semantic_hash": self.after_semantic_hash,
            "changed_fields": list(self.changed_fields),
            "schema_version": self.schema_version,
            "runtime_task_id": self.runtime_task_id,
            "task_contract_hash": self.task_contract_hash,
        }


@dataclass(frozen=True)
class ApprovedPlanBundle:
    """Provider-neutral plan approval plus verifiable provenance links."""

    runtime_task_id: str
    task_contract_hash: str
    source_proposal_hash: str
    effective_proposal_hash: str
    normalization_receipt_hash: str
    plan_policy_report_hash: str
    approved_plan_hash: str
    logical_capability_registry_digest: str
    schema_version: str = APPROVED_PLAN_BUNDLE_SCHEMA_VERSION
    source_proposal: PlanProposal | None = None
    effective_proposal: PlanProposal | None = None
    normalization_receipt: PlanNormalizationReceipt | None = None
    plan_policy_report: PlanPolicyReport | None = None
    approved_plan: ApprovedPlan | None = None
    recipe_id: str = ""
    recipe_version: str = ""
    fallback_used: bool = False
    fallback_proposal_hash: str = ""

    def __post_init__(self) -> None:
        source_proposal_id = "" if self.source_proposal is None else self.source_proposal.proposal_id
        effective_proposal_id = (
            "" if self.effective_proposal is None else self.effective_proposal.proposal_id
        )
        expected_approved_source_id = (
            source_proposal_id if self.fallback_used else effective_proposal_id
        )
        for field_name in (
            "runtime_task_id",
            "task_contract_hash",
            "source_proposal_hash",
            "effective_proposal_hash",
            "normalization_receipt_hash",
            "plan_policy_report_hash",
            "approved_plan_hash",
            "logical_capability_registry_digest",
            "schema_version",
        ):
            _text(getattr(self, field_name), field_name)
        if self.recipe_id:
            _text(self.recipe_id, "recipe_id")
        if self.recipe_version:
            _text(self.recipe_version, "recipe_version")
        if self.fallback_proposal_hash:
            _text(self.fallback_proposal_hash, "fallback_proposal_hash")
        if self.source_proposal is not None:
            if self.source_proposal.proposal_hash != self.source_proposal_hash:
                raise PlanProvenanceError("source_proposal_hash_mismatch")
            if self.source_proposal.task_id != self.runtime_task_id:
                raise PlanProvenanceError("source_proposal_task_id_mismatch")
        if self.effective_proposal is not None:
            if self.effective_proposal.proposal_hash != self.effective_proposal_hash:
                raise PlanProvenanceError("effective_proposal_hash_mismatch")
            if self.effective_proposal.task_id != self.runtime_task_id:
                raise PlanProvenanceError("effective_proposal_task_id_mismatch")
        if self.normalization_receipt is not None:
            if self.normalization_receipt.receipt_hash != self.normalization_receipt_hash:
                raise PlanProvenanceError("normalization_receipt_hash_mismatch")
            if self.normalization_receipt.source_proposal_hash != self.source_proposal_hash:
                raise PlanProvenanceError("normalization_receipt_source_hash_mismatch")
            if self.normalization_receipt.runtime_task_id not in {"", self.runtime_task_id}:
                raise PlanProvenanceError("normalization_receipt_task_id_mismatch")
            if (
                self.normalization_receipt.task_contract_hash
                and self.normalization_receipt.task_contract_hash != self.task_contract_hash
            ):
                raise PlanProvenanceError("normalization_receipt_contract_hash_mismatch")
            if (
                not self.fallback_used
                and self.normalization_receipt.effective_proposal_hash
                != self.effective_proposal_hash
            ):
                raise PlanProvenanceError("normalization_receipt_effective_hash_mismatch")
        if self.plan_policy_report is not None:
            if self.plan_policy_report.report_hash != self.plan_policy_report_hash:
                raise PlanProvenanceError("plan_policy_report_hash_mismatch")
            if self.fallback_used:
                if self.plan_policy_report.status != PlanPolicyStatus.FALLBACK_FIXED_PLAN:
                    raise PlanProvenanceError("fallback_policy_report_status_mismatch")
                if source_proposal_id and self.plan_policy_report.proposal_id != source_proposal_id:
                    raise PlanProvenanceError("fallback_policy_report_source_mismatch")
            elif (
                self.effective_proposal is not None
                and self.plan_policy_report.proposal_id
                != self.effective_proposal.proposal_id
            ):
                raise PlanProvenanceError("plan_policy_report_proposal_mismatch")
        if self.approved_plan is not None:
            if self.approved_plan.approved_plan_hash != self.approved_plan_hash:
                raise PlanProvenanceError("approved_plan_hash_mismatch")
            if self.approved_plan.task_id != self.runtime_task_id:
                raise PlanProvenanceError("approved_plan_task_id_mismatch")
            if self.approved_plan.capability_registry_digest != self.logical_capability_registry_digest:
                raise PlanProvenanceError("capability_registry_digest_mismatch")
            if self.effective_proposal is not None:
                if (
                    expected_approved_source_id
                    and self.approved_plan.source_proposal_id != expected_approved_source_id
                ):
                    raise PlanProvenanceError("approved_plan_source_proposal_mismatch")
                approved_projection = PlanProposal(
                    proposal_id=self.effective_proposal.proposal_id,
                    task_id=self.effective_proposal.task_id,
                    steps=self.approved_plan.steps,
                    final_output_contract_version=self.approved_plan.final_output_contract_version,
                    requested_memory_policy=self.approved_plan.requested_memory_policy,
                )
                if semantic_plan_hash(
                    approved_projection,
                    runtime_task_id=self.runtime_task_id,
                    task_contract_hash=self.task_contract_hash,
                ) != semantic_plan_hash(
                    self.effective_proposal,
                    runtime_task_id=self.runtime_task_id,
                    task_contract_hash=self.task_contract_hash,
                ):
                    raise PlanProvenanceError("approved_plan_steps_mismatch")
            if self.approved_plan.plan_policy_report_hash != self.plan_policy_report_hash:
                raise PlanProvenanceError("approved_plan_policy_report_hash_mismatch")
        if self.fallback_used:
            if not self.fallback_proposal_hash:
                raise PlanProvenanceError("fallback_proposal_hash_required")
            if self.fallback_proposal_hash != self.effective_proposal_hash:
                raise PlanProvenanceError("fallback_proposal_hash_mismatch")
        elif self.fallback_proposal_hash:
            raise PlanProvenanceError("unexpected_fallback_proposal_hash")

    @classmethod
    def from_parts(
        cls,
        *,
        runtime_task_id: str,
        task_contract_hash: str,
        source_proposal: PlanProposal,
        effective_proposal: PlanProposal,
        normalization_receipt: PlanNormalizationReceipt,
        plan_policy_report: PlanPolicyReport,
        approved_plan: ApprovedPlan,
        logical_capability_registry_digest: str,
        recipe_id: str = "",
        recipe_version: str = "",
        fallback_used: bool = False,
        fallback_proposal_hash: str = "",
    ) -> "ApprovedPlanBundle":
        return cls(
            runtime_task_id=runtime_task_id,
            task_contract_hash=task_contract_hash,
            source_proposal_hash=source_proposal.proposal_hash,
            effective_proposal_hash=effective_proposal.proposal_hash,
            normalization_receipt_hash=normalization_receipt.receipt_hash,
            plan_policy_report_hash=plan_policy_report.report_hash,
            approved_plan_hash=approved_plan.approved_plan_hash,
            logical_capability_registry_digest=logical_capability_registry_digest,
            source_proposal=source_proposal,
            effective_proposal=effective_proposal,
            normalization_receipt=normalization_receipt,
            plan_policy_report=plan_policy_report,
            approved_plan=approved_plan,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            fallback_used=fallback_used,
            fallback_proposal_hash=fallback_proposal_hash,
        )

    @classmethod
    def assemble(cls, **kwargs: object) -> "ApprovedPlanBundle":
        """Compatibility spelling for callers assembling a bundle."""

        return cls.from_parts(**kwargs)  # type: ignore[arg-type]

    @property
    def bundle_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    @property
    def plan_policy_hash(self) -> str:
        return self.plan_policy_report_hash

    @property
    def policy_report_hash(self) -> str:
        return self.plan_policy_report_hash

    @property
    def approved_plan_bundle_hash(self) -> str:
        return self.bundle_hash

    @property
    def hash(self) -> str:
        return self.bundle_hash

    @property
    def registry_digest(self) -> str:
        return self.logical_capability_registry_digest

    def verify_hash_links(self) -> bool:
        """Return whether all embedded provenance objects still match hashes."""

        try:
            self.__post_init__()
        except PlanProvenanceError:
            return False
        return True

    def canonical_payload(self) -> dict[str, object]:
        return {
            "runtime_task_id": self.runtime_task_id,
            "task_contract_hash": self.task_contract_hash,
            "source_proposal_hash": self.source_proposal_hash,
            "effective_proposal_hash": self.effective_proposal_hash,
            "normalization_receipt_hash": self.normalization_receipt_hash,
            "plan_policy_report_hash": self.plan_policy_report_hash,
            "approved_plan_hash": self.approved_plan_hash,
            "logical_capability_registry_digest": self.logical_capability_registry_digest,
            "schema_version": self.schema_version,
            "source_proposal": (
                None if self.source_proposal is None else self.source_proposal.canonical_payload()
            ),
            "effective_proposal": (
                None if self.effective_proposal is None else self.effective_proposal.canonical_payload()
            ),
            "normalization_receipt": (
                None
                if self.normalization_receipt is None
                else self.normalization_receipt.canonical_payload()
            ),
            "plan_policy_report": (
                None
                if self.plan_policy_report is None
                else self.plan_policy_report.canonical_payload()
            ),
            "approved_plan": (
                None if self.approved_plan is None else self.approved_plan.canonical_payload()
            ),
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "fallback_used": self.fallback_used,
            "fallback_proposal_hash": self.fallback_proposal_hash,
        }


def build_approved_plan_bundle(
    *,
    runtime_task_id: str,
    task_contract_hash: str,
    source_proposal: PlanProposal,
    effective_proposal: PlanProposal,
    normalization_receipt: PlanNormalizationReceipt,
    plan_policy_report: PlanPolicyReport,
    approved_plan: ApprovedPlan,
    logical_capability_registry_digest: str,
    recipe_id: str = "",
    recipe_version: str = "",
    fallback_used: bool = False,
    fallback_proposal_hash: str = "",
) -> ApprovedPlanBundle:
    return ApprovedPlanBundle.from_parts(
        runtime_task_id=runtime_task_id,
        task_contract_hash=task_contract_hash,
        source_proposal=source_proposal,
        effective_proposal=effective_proposal,
        normalization_receipt=normalization_receipt,
        plan_policy_report=plan_policy_report,
        approved_plan=approved_plan,
        logical_capability_registry_digest=logical_capability_registry_digest,
        recipe_id=recipe_id,
        recipe_version=recipe_version,
        fallback_used=fallback_used,
        fallback_proposal_hash=fallback_proposal_hash,
    )


__all__ = [
    "APPROVED_PLAN_BUNDLE_SCHEMA_VERSION",
    "PLAN_NORMALIZATION_RECEIPT_SCHEMA_VERSION",
    "STATIC_ROLE_RECIPE_SCHEMA_VERSION",
    "ApprovedPlanBundle",
    "PlanNormalizationClass",
    "PlanNormalizationReceipt",
    "PlanProvenanceError",
    "build_approved_plan_bundle",
    "canonical_semantic_plan_hash",
    "mechanical_semantic_plan_hash",
    "mechanical_semantic_plan_payload",
    "plan_semantic_hash",
    "semantic_plan_hash",
    "semantic_plan_payload",
]
