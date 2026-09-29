from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from statebus.contracts import (
    CapabilityDescriptor,
    ExecutionBindingReceipt,
    ExecutionProviderDescriptor,
    LogicalCapabilityDescriptor,
    ProviderEligibilityProjection,
    ProviderRejection,
    ProviderRuntimeFacts,
    RiskClass,
)
from statebus.utils import sha256_digest


class ProviderBindingError(ValueError):
    pass


DETERMINISTIC_FIXTURE_RUNTIME_FACTS_SOURCE = "deterministic_fixture"


@dataclass(frozen=True)
class PhysicalProviderImplementation:
    """Session-frozen implementation snapshot for one bound provider key."""

    provider_id: str
    provider_version: str
    implementation_kind: str
    model_id: str = ""
    model_revision: str = ""
    endpoint_origin: str = ""
    endpoint_fingerprint: str = ""
    request_schema_version: str = ""
    client_config_digest: str = ""
    implementation_snapshot_digest: str = ""
    client_factory_key: str = ""

    @property
    def snapshot_digest(self) -> str:
        return self.implementation_snapshot_digest or sha256_digest(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "implementation_kind": self.implementation_kind,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "endpoint_origin": self.endpoint_origin,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "request_schema_version": self.request_schema_version,
            "client_config_digest": self.client_config_digest,
            "implementation_snapshot_digest": self.implementation_snapshot_digest,
            "client_factory_key": self.client_factory_key,
        }

    @classmethod
    def from_descriptor(cls, provider: ExecutionProviderDescriptor) -> "PhysicalProviderImplementation":
        return cls(
            provider_id=provider.provider_id,
            provider_version=provider.provider_version,
            implementation_kind=provider.implementation_kind,
            request_schema_version=provider.schema_version,
        )


@dataclass(frozen=True)
class ResolvedPhysicalProvider:
    descriptor: ExecutionProviderDescriptor
    implementation: PhysicalProviderImplementation
    client: Any = None


_RISK_RANK = {
    RiskClass.READ_ONLY: 0,
    RiskClass.WORKSPACE_WRITE: 1,
    RiskClass.BOUNDED_CODE: 2,
}


def project_legacy_capability(
    descriptor: CapabilityDescriptor,
) -> LogicalCapabilityDescriptor:
    return LogicalCapabilityDescriptor(
        capability_id=descriptor.capability_id,
        version=descriptor.version,
        owner_role=descriptor.owner_role,
        description=descriptor.description,
        input_ref_kinds=descriptor.input_ref_kinds,
        required_input_ref_kinds=descriptor.required_input_ref_kinds,
        input_contract_version=descriptor.input_contract_version,
        output_ref_kinds=descriptor.output_ref_kinds,
        output_contract_version=descriptor.output_contract_version,
        side_effect_class=descriptor.side_effect_class,
        validator_ids=descriptor.validator_ids,
        fallback_capability_id=descriptor.fallback_capability_id,
        completion_criteria_contract=descriptor.completion_criteria_contract,
    )


def project_legacy_provider(
    descriptor: CapabilityDescriptor,
    *,
    provider_id: str = "",
) -> ExecutionProviderDescriptor:
    logical = project_legacy_capability(descriptor)
    return ExecutionProviderDescriptor(
        provider_id=(
            provider_id
            or f"legacy-{descriptor.capability_id}-{descriptor.execution_kind.value}"
        ),
        provider_version=descriptor.version,
        provider_kind="legacy_execution_provider",
        supported_capability_ids=(logical.capability_id,),
        supported_semantic_contract_hashes=(logical.semantic_contract_hash,),
        implementation_kind=descriptor.execution_kind.value,
        input_ref_kinds=logical.input_ref_kinds,
        required_input_ref_kinds=logical.required_input_ref_kinds,
        input_contract_version=logical.input_contract_version,
        output_ref_kinds=logical.output_ref_kinds,
        output_contract_version=logical.output_contract_version,
        side_effect_class=logical.side_effect_class,
        max_runtime_ms=descriptor.max_runtime_ms,
    )


@dataclass
class ExecutionProviderRegistry:
    _providers: dict[str, ExecutionProviderDescriptor] = field(default_factory=dict)
    _implementations: dict[tuple[str, str], PhysicalProviderImplementation] = field(
        default_factory=dict
    )

    def register(self, provider: ExecutionProviderDescriptor) -> None:
        if provider.provider_id in self._providers:
            raise ProviderBindingError(f"duplicate_execution_provider:{provider.provider_id}")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> ExecutionProviderDescriptor:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderBindingError(f"unknown_execution_provider:{provider_id}") from exc

    def providers(self) -> tuple[ExecutionProviderDescriptor, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))

    def register_implementation(self, implementation: PhysicalProviderImplementation) -> None:
        key = (implementation.provider_id, implementation.provider_version)
        if key in self._implementations:
            raise ProviderBindingError(
                f"duplicate_provider_implementation:{implementation.provider_id}:{implementation.provider_version}"
            )
        provider = self._providers.get(implementation.provider_id)
        if provider is None:
            raise ProviderBindingError("bound_provider_not_registered")
        if provider.provider_version != implementation.provider_version:
            raise ProviderBindingError("bound_provider_version_mismatch")
        if provider.implementation_kind != implementation.implementation_kind:
            raise ProviderBindingError("bound_provider_snapshot_mismatch")
        self._implementations[key] = implementation

    def implementation(self, provider_id: str, provider_version: str) -> PhysicalProviderImplementation:
        try:
            return self._implementations[(provider_id, provider_version)]
        except KeyError as exc:
            raise ProviderBindingError("bound_provider_snapshot_missing") from exc

    def resolve_bound(
        self,
        *,
        binding: ExecutionBindingReceipt,
        expected_request_schema_version: str = "",
        expected_model_fingerprint: str = "",
        expected_endpoint_fingerprint: str = "",
        expected_snapshot_digest: str = "",
        role_config_provider_id: str = "",
    ) -> ResolvedPhysicalProvider:
        if binding.provider_registry_digest != self.digest:
            raise ProviderBindingError("bound_provider_registry_digest_mismatch")
        if role_config_provider_id and role_config_provider_id != binding.selected_provider_id:
            raise ProviderBindingError("role_config_provider_override")
        try:
            provider = self.get(binding.selected_provider_id)
        except ProviderBindingError as exc:
            raise ProviderBindingError("bound_provider_not_registered") from exc
        if provider.provider_version != binding.selected_provider_version:
            raise ProviderBindingError("bound_provider_version_mismatch")
        if provider.implementation_kind != binding.selected_implementation_kind:
            raise ProviderBindingError("bound_provider_snapshot_mismatch")
        implementation = self._implementations.get(
            (binding.selected_provider_id, binding.selected_provider_version)
        )
        if implementation is None:
            raise ProviderBindingError("bound_provider_snapshot_missing")
        if implementation.implementation_kind != binding.selected_implementation_kind:
            raise ProviderBindingError("bound_provider_snapshot_mismatch")
        if expected_request_schema_version and implementation.request_schema_version != expected_request_schema_version:
            raise ProviderBindingError("bound_provider_request_schema_mismatch")
        if expected_model_fingerprint and implementation.model_revision != expected_model_fingerprint:
            raise ProviderBindingError("bound_provider_model_fingerprint_mismatch")
        if expected_endpoint_fingerprint and implementation.endpoint_fingerprint != expected_endpoint_fingerprint:
            raise ProviderBindingError("bound_provider_endpoint_fingerprint_mismatch")
        if expected_snapshot_digest and implementation.snapshot_digest != expected_snapshot_digest:
            raise ProviderBindingError("bound_provider_snapshot_mismatch")
        return ResolvedPhysicalProvider(provider, implementation)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "providers": [provider.canonical_payload() for provider in self.providers()],
            "implementations": [
                implementation.canonical_payload()
                for _key, implementation in sorted(self._implementations.items())
            ],
        }

    @property
    def digest(self) -> str:
        return sha256_digest(self.canonical_payload())

    @classmethod
    def from_legacy_capability_registry(
        cls,
        capability_registry,
    ) -> "ExecutionProviderRegistry":
        registry = cls()
        for descriptor in capability_registry.descriptors():
            registry.register(project_legacy_provider(descriptor))
        return registry


def default_provider_runtime_facts(
    registry: ExecutionProviderRegistry,
) -> dict[str, ProviderRuntimeFacts]:
    return {
        provider.provider_id: ProviderRuntimeFacts(
            provider_id=provider.provider_id,
            ready=True,
            healthy=True,
            prerequisites_satisfied=True,
            observed_at_ns=0,
        )
        for provider in registry.providers()
    }


def provider_runtime_facts_metadata(
    runtime_facts: dict[str, ProviderRuntimeFacts],
    *,
    source: str,
) -> dict[str, object]:
    """Return explicit provenance for runtime facts without changing frozen contracts."""
    if source == DETERMINISTIC_FIXTURE_RUNTIME_FACTS_SOURCE:
        return {
            "runtime_facts_source": DETERMINISTIC_FIXTURE_RUNTIME_FACTS_SOURCE,
            "observed_at_ns": 0,
            "live_health_verified": False,
            "provider_ids": tuple(sorted(runtime_facts)),
        }
    if any(facts.observed_at_ns <= 0 for facts in runtime_facts.values()):
        raise ProviderBindingError("bound_provider_runtime_facts_invalid")
    return {
        "runtime_facts_source": source,
        "observed_at_ns": max(facts.observed_at_ns for facts in runtime_facts.values()),
        "live_health_verified": True,
        "provider_ids": tuple(sorted(runtime_facts)),
    }


def compute_provider_eligibility(
    *,
    task_id: str,
    session_id: str,
    step_id: str,
    attempt_id: str,
    approved_plan_hash: str,
    logical_capability: LogicalCapabilityDescriptor,
    provider_registry: ExecutionProviderRegistry,
    runtime_facts: dict[str, ProviderRuntimeFacts],
    allowed_risk_class: RiskClass,
    required_runtime_ms: int,
) -> ProviderEligibilityProjection:
    candidates = provider_registry.providers()
    rejected: list[ProviderRejection] = []
    eligible: list[str] = []
    for provider in candidates:
        reasons: list[str] = []
        facts = runtime_facts.get(provider.provider_id)
        if not provider.enabled:
            reasons.append("provider_disabled")
        if logical_capability.capability_id not in provider.supported_capability_ids:
            reasons.append("logical_capability_not_supported")
        if logical_capability.semantic_contract_hash not in provider.supported_semantic_contract_hashes:
            reasons.append("semantic_contract_hash_mismatch")
        if provider.input_contract_version != logical_capability.input_contract_version:
            reasons.append("input_contract_mismatch")
        if provider.output_contract_version != logical_capability.output_contract_version:
            reasons.append("output_contract_mismatch")
        if provider.input_ref_kinds != logical_capability.input_ref_kinds:
            reasons.append("input_ref_kinds_mismatch")
        if provider.required_input_ref_kinds != logical_capability.required_input_ref_kinds:
            reasons.append("required_input_ref_kinds_mismatch")
        if provider.output_ref_kinds != logical_capability.output_ref_kinds:
            reasons.append("output_ref_kinds_mismatch")
        if _RISK_RANK[provider.side_effect_class] > _RISK_RANK[allowed_risk_class]:
            reasons.append("risk_class_exceeded")
        if provider.max_runtime_ms < required_runtime_ms:
            reasons.append("runtime_budget_insufficient")
        if facts is None:
            reasons.append("provider_runtime_facts_missing")
        else:
            if not facts.ready:
                reasons.append("provider_not_ready")
            if not facts.healthy:
                reasons.append("provider_unhealthy")
            if not facts.prerequisites_satisfied:
                reasons.append("runtime_prerequisites_unsatisfied")
        if reasons:
            rejected.append(
                ProviderRejection(
                    provider_id=provider.provider_id,
                    reason_codes=tuple(reasons),
                )
            )
        else:
            eligible.append(provider.provider_id)

    candidate_ids = {provider.provider_id for provider in candidates}
    facts_digest = sha256_digest({
        provider_id: runtime_facts[provider_id].facts_digest
        for provider_id in sorted(runtime_facts)
        if provider_id in candidate_ids
    })
    return ProviderEligibilityProjection(
        task_id=task_id,
        session_id=session_id,
        step_id=step_id,
        attempt_id=attempt_id,
        approved_plan_hash=approved_plan_hash,
        logical_capability_id=logical_capability.capability_id,
        logical_capability_version=logical_capability.version,
        semantic_contract_hash=logical_capability.semantic_contract_hash,
        provider_registry_digest=provider_registry.digest,
        candidate_provider_ids=tuple(provider.provider_id for provider in candidates),
        rejected_candidates=tuple(rejected),
        eligible_provider_ids=tuple(eligible),
        runtime_facts_digest=facts_digest,
    )


def select_provider_deterministically(
    projection: ProviderEligibilityProjection,
    registry: ExecutionProviderRegistry,
) -> ExecutionProviderDescriptor:
    if projection.provider_registry_digest != registry.digest:
        raise ProviderBindingError("provider_registry_digest_mismatch")
    if not projection.eligible_provider_ids:
        raise ProviderBindingError("no_eligible_provider")
    return registry.get(sorted(projection.eligible_provider_ids)[0])


def create_execution_binding(
    *,
    projection: ProviderEligibilityProjection,
    provider: ExecutionProviderDescriptor,
) -> ExecutionBindingReceipt:
    if provider.provider_id not in projection.eligible_provider_ids:
        raise ProviderBindingError("selected_provider_not_eligible")
    if projection.logical_capability_id not in provider.supported_capability_ids:
        raise ProviderBindingError("selected_provider_capability_mismatch")
    if projection.semantic_contract_hash not in provider.supported_semantic_contract_hashes:
        raise ProviderBindingError("selected_provider_semantic_contract_mismatch")
    return ExecutionBindingReceipt(
        binding_id=f"binding-{projection.attempt_id}-{provider.provider_id}",
        task_id=projection.task_id,
        session_id=projection.session_id,
        step_id=projection.step_id,
        attempt_id=projection.attempt_id,
        approved_plan_hash=projection.approved_plan_hash,
        logical_capability_id=projection.logical_capability_id,
        logical_capability_version=projection.logical_capability_version,
        semantic_contract_hash=projection.semantic_contract_hash,
        provider_registry_digest=projection.provider_registry_digest,
        provider_runtime_facts_digest=projection.runtime_facts_digest,
        eligibility_projection_hash=projection.projection_hash,
        selected_provider_id=provider.provider_id,
        selected_provider_version=provider.provider_version,
        selected_provider_kind=provider.provider_kind,
        selected_implementation_kind=provider.implementation_kind,
    )


__all__ = [
    "ExecutionProviderRegistry",
    "DETERMINISTIC_FIXTURE_RUNTIME_FACTS_SOURCE",
    "PhysicalProviderImplementation",
    "ProviderBindingError",
    "ResolvedPhysicalProvider",
    "compute_provider_eligibility",
    "create_execution_binding",
    "default_provider_runtime_facts",
    "provider_runtime_facts_metadata",
    "project_legacy_capability",
    "project_legacy_provider",
    "select_provider_deterministically",
]
