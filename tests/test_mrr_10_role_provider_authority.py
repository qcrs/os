from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    CapabilityDescriptor,
    CapabilityGrant,
    ClaimSet,
    ExecutionKind,
    EvidenceRequest,
    PlanStepProposal,
    RiskClass,
    RuntimeIdentity,
    TaskContractIdentity,
    TransformProgram,
    WorkflowMode,
)
from statebus.runtime.adaptive_dispatcher import AdaptiveCapabilityDispatcher, AdaptiveDispatchContext
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.provider_registry import (
    ExecutionProviderRegistry,
    PhysicalProviderImplementation,
    ProviderBindingError,
    compute_provider_eligibility,
    create_execution_binding,
    default_provider_runtime_facts,
    project_legacy_provider,
)
from statebus.runtime.role_providers import (
    AttemptBoundProviderStateReadFacade,
    ImmutableStateReadView,
    ProviderAuthorityError,
    ProviderCandidate,
    ProviderRequest,
    RolePathExecutorProvider,
    RolePathRetrieverProvider,
    RolePathSummarizerProvider,
    RoleProviderContext,
)


def _fixture(
    role: str,
    *,
    input_refs: tuple[str, ...] = (),
    with_snapshot: bool = False,
):
    capability = CapabilityDescriptor(
        capability_id=f"{role}-capability",
        owner_role=role,
        description=f"{role} provider fixture",
        input_ref_kinds=(),
        input_contract_version="input.v1",
        output_ref_kinds=("candidate",),
        output_contract_version="output.v1",
        execution_kind=ExecutionKind.RUNTIME_BUILTIN,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=1000,
        supports_replay=False,
    )
    registry = CapabilityRegistry()
    registry.register(capability)
    provider_registry = ExecutionProviderRegistry()
    provider = project_legacy_provider(capability, provider_id=f"provider-{role}")
    provider_registry.register(provider)
    if with_snapshot:
        provider_registry.register_implementation(
            PhysicalProviderImplementation(
                provider_id=provider.provider_id,
                provider_version=provider.provider_version,
                implementation_kind=provider.implementation_kind,
                request_schema_version=provider.schema_version,
            )
        )
    step = PlanStepProposal(
        step_id=f"{role}-step",
        role=role,
        capability_id=capability.capability_id,
        goal=f"run {role}",
        input_ref_ids=input_refs,
        output_contract_version=capability.output_contract_version,
    )
    plan = ApprovedPlan(
        approved_plan_id="approved",
        task_id="task",
        source_proposal_id="proposal",
        steps=(step,),
        final_output_contract_version=capability.output_contract_version,
        plan_policy_report_hash="policy",
        capability_registry_digest=registry.digest,
        total_attempt_budget=1,
    )
    projection = compute_provider_eligibility(
        task_id="task",
        session_id="session",
        step_id=step.step_id,
        attempt_id="attempt",
        approved_plan_hash=plan.approved_plan_hash,
        logical_capability=registry.logical_descriptor(capability.capability_id),
        provider_registry=provider_registry,
        runtime_facts=default_provider_runtime_facts(provider_registry),
        allowed_risk_class=RiskClass.READ_ONLY,
        required_runtime_ms=1000,
    )
    binding = create_execution_binding(projection=projection, provider=provider)
    grant = CapabilityGrant(
        grant_id="grant",
        task_id="task",
        session_id="session",
        step_id=step.step_id,
        attempt_id="attempt",
        capability_id=capability.capability_id,
        capability_version=capability.version,
        input_ref_ids=input_refs,
        output_contract_version=capability.output_contract_version,
        workspace_root_id="workspace",
        max_runtime_ms=1000,
        expires_at_ns=time.time_ns() + 10_000_000_000,
        approved_plan_hash=plan.approved_plan_hash,
    )
    envelope = AdaptiveTaskEnvelope(
        task_id="task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="mrr10a-test",
        allowed_capability_ids=(capability.capability_id,),
        allowed_output_contracts=(capability.output_contract_version,),
    )
    identity = RuntimeIdentity(
        runtime_task_id="task",
        run_id="run",
        session_id="session",
        trace_id="trace",
        task_contract=TaskContractIdentity.from_hash("spec"),
    )
    from statebus.contracts import BoundCapabilityGrant

    return (
        envelope,
        plan,
        step,
        BoundCapabilityGrant(grant=grant, execution_binding=binding),
        identity,
        registry,
        provider_registry,
    )


def test_three_role_adapters_receive_exact_bound_grant_once() -> None:
    payloads = {
        "retriever": EvidenceRequest(
            request_id="request",
            task_id="task",
            step_id="retriever-step",
            queries=("revenue",),
            evidence_types=("table",),
            corpus_scope_ids=("local",),
        ),
        "executor": TransformProgram(
            program_id="program",
            input_artifact_refs=(),
            operations=(),
            output_contract_version="output.v1",
        ),
        "summarizer": ClaimSet(claim_set_id="claims", task_id="task", claims=()),
    }
    adapters = {
        "retriever": RolePathRetrieverProvider(lambda request: payloads[request.step.role]),
        "executor": RolePathExecutorProvider(lambda request: payloads[request.step.role]),
        "summarizer": RolePathSummarizerProvider(lambda request: payloads[request.step.role]),
    }
    for role, adapter in adapters.items():
        _envelope, plan, step, bound_grant, identity, _registry, _providers = _fixture(role)
        seen = []
        request = ProviderRequest(
            envelope=_envelope,
            approved_plan=plan,
            step=step,
            bound_grant=bound_grant,
            runtime_identity=identity,
            attempt_workspace=Path("/tmp/mrr10a-provider"),
            provider_input_refs=(),
            role_context=RoleProviderContext(role=role),
        )
        candidate = adapter(request)
        seen.append(request.bound_grant)
        assert seen == [bound_grant]
        assert candidate.success
        assert not hasattr(candidate, "output_refs")
        assert candidate.candidate_kind in {
            "retrieval_request",
            "executor_program",
            "summary_claim_set",
        }


def test_bound_dispatcher_projects_provider_failure_without_provider_retry() -> None:
    envelope, plan, step, bound_grant, identity, registry, providers = _fixture(
        "executor",
        with_snapshot=True,
    )
    calls = []

    def provider(request: ProviderRequest) -> ProviderCandidate:
        calls.append(request.bound_grant)
        return ProviderCandidate(
            success=False,
            candidate_kind="failure",
            error_code="provider_parse_failed",
            retryable=True,
        )

    dispatcher = AdaptiveCapabilityDispatcher(
        context=AdaptiveDispatchContext(
            registry=registry,
            provider_registry=providers,
            bound_provider_handlers={step.capability_id: provider},
        )
    )
    result = dispatcher.dispatch(
        envelope=envelope,
        approved_plan=plan,
        step=step,
        grant=bound_grant,
        attempt_workspace=Path("/tmp/mrr10a-dispatch"),
        runtime_identity=identity,
    )
    assert calls == [bound_grant]
    assert not result.success
    assert result.error_code == "provider_parse_failed"
    assert result.retryable


def test_provider_state_facade_is_scoped_detached_and_closes() -> None:
    view = ImmutableStateReadView(
        ref_id="state-1",
        state_identity_hash="identity",
        channel="semantic",
        dtype="float32",
        shape=(2,),
        payload_digest="digest",
        values=(1.0, 2.0),
    )
    facade = AttemptBoundProviderStateReadFacade(
        runtime_task_id="task",
        session_id="session",
        step_id="step",
        attempt_id="attempt",
        execution_binding_hash="binding",
        grant_hash="grant",
        provider_id="provider",
        allowed_ref_ids=("state-1",),
        expires_at_ns=time.time_ns() + 1_000_000_000,
        read_fn=lambda _ref_id: view,
    )
    assert facade.read("state-1").values == (1.0, 2.0)
    with pytest.raises(ProviderAuthorityError, match="out_of_scope"):
        facade.read("state-2")
    facade.close()
    with pytest.raises(ProviderAuthorityError, match="closed"):
        facade.read("state-1")


def test_provider_snapshot_resolution_is_unique_and_fail_closed() -> None:
    _envelope, _plan, _step, bound_grant, _identity, _registry, providers = _fixture("executor")
    provider = providers.get(bound_grant.provider_id)
    providers.register_implementation(
        PhysicalProviderImplementation(
            provider_id=provider.provider_id,
            provider_version=provider.provider_version,
            implementation_kind=provider.implementation_kind,
            model_id="model",
            model_revision="rev-1",
            endpoint_fingerprint="endpoint-1",
            request_schema_version=provider.schema_version,
        )
    )
    # Binding must be made from the session-frozen registry digest.
    projection = compute_provider_eligibility(
        task_id="task",
        session_id="session",
        step_id="executor-step",
        attempt_id="attempt-2",
        approved_plan_hash=bound_grant.grant.approved_plan_hash,
        logical_capability=_registry.logical_descriptor("executor-capability"),
        provider_registry=providers,
        runtime_facts=default_provider_runtime_facts(providers),
        allowed_risk_class=RiskClass.READ_ONLY,
        required_runtime_ms=1000,
    )
    binding = create_execution_binding(projection=projection, provider=provider)
    resolved = providers.resolve_bound(binding=binding)
    assert resolved.implementation.model_revision == "rev-1"
    with pytest.raises(ProviderBindingError, match="role_config_provider_override"):
        providers.resolve_bound(binding=binding, role_config_provider_id="other-provider")


def test_missing_provider_snapshot_fails_closed_without_invoking_handler() -> None:
    envelope, plan, step, bound_grant, identity, registry, providers = _fixture("executor")
    calls = []

    def handler(request: ProviderRequest) -> ProviderCandidate:
        calls.append(request)
        return ProviderCandidate(
            success=False,
            candidate_kind="failure",
            error_code="must_not_run",
        )

    with pytest.raises(ProviderBindingError, match="^bound_provider_snapshot_missing$") as exc_info:
        providers.resolve_bound(binding=bound_grant.execution_binding)
    assert str(exc_info.value) == "bound_provider_snapshot_missing"

    dispatcher = AdaptiveCapabilityDispatcher(
        context=AdaptiveDispatchContext(
            registry=registry,
            provider_registry=providers,
            bound_provider_handlers={step.capability_id: handler},
        )
    )
    result = dispatcher.dispatch(
        envelope=envelope,
        approved_plan=plan,
        step=step,
        grant=bound_grant,
        attempt_workspace=Path("/tmp/mrr10a-provider-missing-snapshot"),
        runtime_identity=identity,
    )
    assert not result.success
    assert result.error_code == "bound_provider_snapshot_missing"
    assert calls == []


def test_candidate_kind_is_closed_and_authority_fields_are_absent() -> None:
    with pytest.raises(ValueError, match="payload_type_mismatch"):
        ProviderCandidate(success=True, candidate_kind="retrieval_request", payload=None)
