from __future__ import annotations

from dataclasses import dataclass, field

from statebus.contracts.adaptive import CapabilityGrant, RiskClass
from statebus.utils import sha256_digest


LOGICAL_CAPABILITY_DESCRIPTOR_SCHEMA_VERSION = "statebus.logical_capability_descriptor.v1"
EXECUTION_PROVIDER_DESCRIPTOR_SCHEMA_VERSION = "statebus.execution_provider_descriptor.v1"
PROVIDER_RUNTIME_FACTS_SCHEMA_VERSION = "statebus.provider_runtime_facts.v1"
PROVIDER_ELIGIBILITY_PROJECTION_SCHEMA_VERSION = "statebus.provider_eligibility_projection.v1"
EXECUTION_BINDING_RECEIPT_SCHEMA_VERSION = "statebus.execution_binding_receipt.v1"
BOUND_CAPABILITY_GRANT_SCHEMA_VERSION = "statebus.bound_capability_grant.v1"


class ProviderBindingContractError(ValueError):
    pass


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ProviderBindingContractError(f"{field_name}_required")
    return normalized


@dataclass(frozen=True)
class LogicalCapabilityDescriptor:
    capability_id: str
    version: str
    owner_role: str
    description: str
    input_ref_kinds: tuple[str, ...]
    required_input_ref_kinds: tuple[str, ...]
    input_contract_version: str
    output_ref_kinds: tuple[str, ...]
    output_contract_version: str
    side_effect_class: RiskClass
    validator_ids: tuple[str, ...] = ()
    fallback_capability_id: str = ""
    completion_criteria_contract: dict[str, dict[str, object]] = field(
        default_factory=dict
    )
    schema_version: str = LOGICAL_CAPABILITY_DESCRIPTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "capability_id",
            "version",
            "owner_role",
            "description",
            "input_contract_version",
            "output_contract_version",
            "schema_version",
        ):
            _required_text(getattr(self, field_name), field_name)
        if not set(self.required_input_ref_kinds) <= set(self.input_ref_kinds):
            raise ProviderBindingContractError("logical_required_input_kind_not_accepted")
        if not self.output_ref_kinds:
            raise ProviderBindingContractError("logical_output_ref_kind_required")

    @property
    def semantic_contract_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "owner_role": self.owner_role,
            "description": self.description,
            "input_ref_kinds": list(self.input_ref_kinds),
            "required_input_ref_kinds": list(self.required_input_ref_kinds),
            "input_contract_version": self.input_contract_version,
            "output_ref_kinds": list(self.output_ref_kinds),
            "output_contract_version": self.output_contract_version,
            "side_effect_class": self.side_effect_class.value,
            "validator_ids": list(self.validator_ids),
            "fallback_capability_id": self.fallback_capability_id,
            "completion_criteria_contract": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.completion_criteria_contract.items())
            },
            "schema_version": self.schema_version,
        }

    def public_view(self) -> dict[str, object]:
        return {
            "id": self.capability_id,
            "version": self.version,
            "role": self.owner_role,
            "description": self.description,
            "accepts": list(self.input_ref_kinds),
            "requires": list(self.required_input_ref_kinds),
            "input_contract": self.input_contract_version,
            "produces": list(self.output_ref_kinds),
            "output_contract": self.output_contract_version,
            "side_effect": self.side_effect_class.value,
            "validator_ids": list(self.validator_ids),
            "fallback_capability_id": self.fallback_capability_id,
            "completion_criteria": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.completion_criteria_contract.items())
            },
            "semantic_contract_hash": self.semantic_contract_hash,
        }


@dataclass(frozen=True)
class ExecutionProviderDescriptor:
    provider_id: str
    provider_version: str
    provider_kind: str
    supported_capability_ids: tuple[str, ...]
    supported_semantic_contract_hashes: tuple[str, ...]
    implementation_kind: str
    input_ref_kinds: tuple[str, ...]
    required_input_ref_kinds: tuple[str, ...]
    input_contract_version: str
    output_ref_kinds: tuple[str, ...]
    output_contract_version: str
    side_effect_class: RiskClass
    max_runtime_ms: int
    runtime_prerequisites: tuple[str, ...] = ()
    enabled: bool = True
    schema_version: str = EXECUTION_PROVIDER_DESCRIPTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "provider_id",
            "provider_version",
            "provider_kind",
            "implementation_kind",
            "input_contract_version",
            "output_contract_version",
            "schema_version",
        ):
            _required_text(getattr(self, field_name), field_name)
        if not self.supported_capability_ids or not self.supported_semantic_contract_hashes:
            raise ProviderBindingContractError("provider_supported_capability_required")
        if self.max_runtime_ms <= 0:
            raise ProviderBindingContractError("provider_runtime_budget_invalid")

    @property
    def provider_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_kind": self.provider_kind,
            "supported_capability_ids": list(self.supported_capability_ids),
            "supported_semantic_contract_hashes": list(
                self.supported_semantic_contract_hashes
            ),
            "implementation_kind": self.implementation_kind,
            "input_ref_kinds": list(self.input_ref_kinds),
            "required_input_ref_kinds": list(self.required_input_ref_kinds),
            "input_contract_version": self.input_contract_version,
            "output_ref_kinds": list(self.output_ref_kinds),
            "output_contract_version": self.output_contract_version,
            "side_effect_class": self.side_effect_class.value,
            "max_runtime_ms": self.max_runtime_ms,
            "runtime_prerequisites": list(self.runtime_prerequisites),
            "enabled": self.enabled,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ProviderRuntimeFacts:
    provider_id: str
    ready: bool
    healthy: bool
    prerequisites_satisfied: bool
    observed_at_ns: int
    schema_version: str = PROVIDER_RUNTIME_FACTS_SCHEMA_VERSION

    @property
    def facts_digest(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "ready": self.ready,
            "healthy": self.healthy,
            "prerequisites_satisfied": self.prerequisites_satisfied,
            "observed_at_ns": self.observed_at_ns,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ProviderRejection:
    provider_id: str
    reason_codes: tuple[str, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class ProviderEligibilityProjection:
    task_id: str
    session_id: str
    step_id: str
    attempt_id: str
    approved_plan_hash: str
    logical_capability_id: str
    logical_capability_version: str
    semantic_contract_hash: str
    provider_registry_digest: str
    candidate_provider_ids: tuple[str, ...]
    rejected_candidates: tuple[ProviderRejection, ...]
    eligible_provider_ids: tuple[str, ...]
    runtime_facts_digest: str
    policy_version: str = "statebus.provider_eligibility.v1"
    schema_version: str = PROVIDER_ELIGIBILITY_PROJECTION_SCHEMA_VERSION

    @property
    def projection_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "approved_plan_hash": self.approved_plan_hash,
            "logical_capability_id": self.logical_capability_id,
            "logical_capability_version": self.logical_capability_version,
            "semantic_contract_hash": self.semantic_contract_hash,
            "provider_registry_digest": self.provider_registry_digest,
            "candidate_provider_ids": list(self.candidate_provider_ids),
            "rejected_candidates": [
                rejection.canonical_payload() for rejection in self.rejected_candidates
            ],
            "eligible_provider_ids": list(self.eligible_provider_ids),
            "runtime_facts_digest": self.runtime_facts_digest,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExecutionBindingReceipt:
    binding_id: str
    task_id: str
    session_id: str
    step_id: str
    attempt_id: str
    approved_plan_hash: str
    logical_capability_id: str
    logical_capability_version: str
    semantic_contract_hash: str
    provider_registry_digest: str
    provider_runtime_facts_digest: str
    eligibility_projection_hash: str
    selected_provider_id: str
    selected_provider_version: str
    selected_provider_kind: str
    selected_implementation_kind: str
    binding_policy_version: str = "statebus.execution_binding.stable_provider_id.v1"
    reason_code: str = "stable_provider_id_order"
    schema_version: str = EXECUTION_BINDING_RECEIPT_SCHEMA_VERSION

    @property
    def binding_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "approved_plan_hash": self.approved_plan_hash,
            "logical_capability_id": self.logical_capability_id,
            "logical_capability_version": self.logical_capability_version,
            "semantic_contract_hash": self.semantic_contract_hash,
            "provider_registry_digest": self.provider_registry_digest,
            "provider_runtime_facts_digest": self.provider_runtime_facts_digest,
            "eligibility_projection_hash": self.eligibility_projection_hash,
            "selected_provider_id": self.selected_provider_id,
            "selected_provider_version": self.selected_provider_version,
            "selected_provider_kind": self.selected_provider_kind,
            "selected_implementation_kind": self.selected_implementation_kind,
            "binding_policy_version": self.binding_policy_version,
            "reason_code": self.reason_code,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class BoundCapabilityGrant:
    grant: CapabilityGrant
    execution_binding: ExecutionBindingReceipt
    schema_version: str = BOUND_CAPABILITY_GRANT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        binding = self.execution_binding
        if (
            self.grant.task_id != binding.task_id
            or self.grant.session_id != binding.session_id
            or self.grant.step_id != binding.step_id
            or self.grant.attempt_id != binding.attempt_id
            or self.grant.approved_plan_hash != binding.approved_plan_hash
            or self.grant.capability_id != binding.logical_capability_id
            or self.grant.capability_version != binding.logical_capability_version
        ):
            raise ProviderBindingContractError("bound_capability_grant_scope_mismatch")

    @property
    def execution_binding_hash(self) -> str:
        return self.execution_binding.binding_hash

    @property
    def eligibility_projection_hash(self) -> str:
        return self.execution_binding.eligibility_projection_hash

    @property
    def provider_id(self) -> str:
        return self.execution_binding.selected_provider_id

    @property
    def provider_version(self) -> str:
        return self.execution_binding.selected_provider_version

    @property
    def bound_grant_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "grant": self.grant.canonical_payload(),
            "capability_grant_hash": self.grant.grant_hash,
            "execution_binding_hash": self.execution_binding_hash,
            "eligibility_projection_hash": self.eligibility_projection_hash,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "schema_version": self.schema_version,
        }


__all__ = [
    "BOUND_CAPABILITY_GRANT_SCHEMA_VERSION",
    "EXECUTION_BINDING_RECEIPT_SCHEMA_VERSION",
    "EXECUTION_PROVIDER_DESCRIPTOR_SCHEMA_VERSION",
    "LOGICAL_CAPABILITY_DESCRIPTOR_SCHEMA_VERSION",
    "PROVIDER_ELIGIBILITY_PROJECTION_SCHEMA_VERSION",
    "PROVIDER_RUNTIME_FACTS_SCHEMA_VERSION",
    "BoundCapabilityGrant",
    "ExecutionBindingReceipt",
    "ExecutionProviderDescriptor",
    "LogicalCapabilityDescriptor",
    "ProviderBindingContractError",
    "ProviderEligibilityProjection",
    "ProviderRejection",
    "ProviderRuntimeFacts",
]
