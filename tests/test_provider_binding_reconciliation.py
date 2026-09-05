from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
import time

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    BoundCapabilityGrant,
    CapabilityDescriptor,
    CapabilityGrant,
    CanonicalTaskSpec,
    ExecutionKind,
    LogicalCapabilityDescriptor,
    PlanProposal,
    PlanStepProposal,
    ProviderRuntimeFacts,
    RiskClass,
    RuntimeIdentity,
    TaskContractIdentity,
    WorkflowMode,
)
from statebus.runtime import adaptive_runtime
from statebus.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
)
from statebus.runtime.adaptive_runtime import (
    AdaptiveRuntimeEngine,
    AdaptiveRuntimeRequest,
    AdaptiveStepResult,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.fixed_mainline import FixedMainlineRequest
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.provider_registry import (
    ExecutionProviderRegistry,
    ProviderBindingError,
    compute_provider_eligibility,
    create_execution_binding,
    project_legacy_capability,
    project_legacy_provider,
    select_provider_deterministically,
)
from statebus.runtime.static_role_recipe import default_fixed_role_recipe


def _legacy_descriptor() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="deterministic-analysis",
        owner_role="executor",
        description="Produce a deterministic typed analysis result.",
        input_ref_kinds=("canonical_evidence_pack",),
        required_input_ref_kinds=("canonical_evidence_pack",),
        input_contract_version="analysis-input-v1",
        output_ref_kinds=("execution_artifact",),
        output_contract_version="analysis-output-v1",
        execution_kind=ExecutionKind.RUNTIME_BUILTIN,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=1_000,
        supports_replay=False,
        validator_ids=("analysis-validator",),
        completion_criteria_contract={
            "min_rows": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        version="v1",
    )


def _provider_facts(*provider_ids: str) -> dict[str, ProviderRuntimeFacts]:
    return {
        provider_id: ProviderRuntimeFacts(
            provider_id=provider_id,
            ready=True,
            healthy=True,
            prerequisites_satisfied=True,
            observed_at_ns=1,
        )
        for provider_id in provider_ids
    }


def _projection(
    *,
    logical: LogicalCapabilityDescriptor,
    providers: ExecutionProviderRegistry,
    facts: dict[str, ProviderRuntimeFacts],
    attempt_id: str = "attempt-1",
):
    return compute_provider_eligibility(
        task_id="task",
        session_id="session",
        step_id="execute",
        attempt_id=attempt_id,
        approved_plan_hash="approved-plan-hash",
        logical_capability=logical,
        provider_registry=providers,
        runtime_facts=facts,
        allowed_risk_class=RiskClass.READ_ONLY,
        required_runtime_ms=1_000,
    )


def _fixed_request(tmp_path: Path) -> FixedMainlineRequest:
    task_spec = CanonicalTaskSpec(
        task_family="provider_binding",
        intent_op="deterministic_bridge",
        target_entities=("fixture",),
        required_outputs=("cited_report",),
    )
    identity = RuntimeIdentity(
        runtime_task_id="mrr-04-fixed-task",
        run_id="mrr-04-run",
        session_id="mrr-04-session",
        trace_id="mrr-04-trace",
        task_contract=TaskContractIdentity.from_canonical_task_spec(task_spec),
    )
    return FixedMainlineRequest(
        runtime_identity=identity,
        canonical_task_spec=task_spec,
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspaces",
        recipe=default_fixed_role_recipe(),
    )


def test_legacy_descriptor_projects_to_isolated_logical_and_physical_contracts() -> None:
    legacy = _legacy_descriptor()
    logical = project_legacy_capability(legacy)
    provider = project_legacy_provider(legacy)
    registry = CapabilityRegistry()
    registry.register(legacy)

    logical_field_names = {field.name for field in fields(LogicalCapabilityDescriptor)}
    logical_payload = logical.canonical_payload()
    logical_public = registry.logical_public_view((legacy.capability_id,))[0]

    assert logical == project_legacy_capability(legacy)
    assert provider == project_legacy_provider(legacy)
    assert logical.semantic_contract_hash in provider.supported_semantic_contract_hashes
    assert provider.implementation_kind == legacy.execution_kind.value
    assert registry.logical_descriptor(legacy.capability_id) == logical
    assert registry.logical_digest
    for forbidden in ("execution_kind", "provider_id", "endpoint", "transport"):
        assert forbidden not in logical_field_names
        assert forbidden not in logical_payload
        assert forbidden not in logical_public


def test_eligibility_hard_filters_incompatible_provider_and_binds_stably() -> None:
    logical = project_legacy_capability(_legacy_descriptor())
    compatible = project_legacy_provider(
        _legacy_descriptor(),
        provider_id="provider-a",
    )
    incompatible = replace(
        compatible,
        provider_id="provider-b",
        supported_semantic_contract_hashes=("different-semantic-contract",),
    )
    providers = ExecutionProviderRegistry()
    providers.register(incompatible)
    providers.register(compatible)
    projection = _projection(
        logical=logical,
        providers=providers,
        facts=_provider_facts("provider-a", "provider-b"),
    )

    assert projection.candidate_provider_ids == ("provider-a", "provider-b")
    assert projection.eligible_provider_ids == ("provider-a",)
    assert projection.rejected_candidates[0].provider_id == "provider-b"
    assert "semantic_contract_hash_mismatch" in projection.rejected_candidates[0].reason_codes

    selected = select_provider_deterministically(projection, providers)
    binding = create_execution_binding(projection=projection, provider=selected)

    assert selected.provider_id == "provider-a"
    assert binding.selected_provider_id == "provider-a"
    assert binding.eligibility_projection_hash == projection.projection_hash
    assert binding.attempt_id == projection.attempt_id
    assert binding.reason_code == "stable_provider_id_order"


def test_provider_change_creates_new_binding_without_changing_approved_plan() -> None:
    legacy = _legacy_descriptor()
    logical = project_legacy_capability(legacy)
    provider_a = project_legacy_provider(legacy, provider_id="provider-a")
    provider_b = project_legacy_provider(legacy, provider_id="provider-b")
    providers = ExecutionProviderRegistry()
    providers.register(provider_b)
    providers.register(provider_a)
    step = PlanStepProposal(
        step_id="execute",
        role="executor",
        capability_id=logical.capability_id,
        goal="produce the approved analysis",
        output_contract_version=logical.output_contract_version,
    )
    approved_plan = ApprovedPlan(
        approved_plan_id="approved-logical-plan",
        task_id="task",
        source_proposal_id="proposal",
        steps=(step,),
        final_output_contract_version=logical.output_contract_version,
        plan_policy_report_hash="policy-report",
        capability_registry_digest="logical-registry",
        total_attempt_budget=2,
    )
    approved_hash = approved_plan.approved_plan_hash

    first_projection = _projection(
        logical=logical,
        providers=providers,
        facts=_provider_facts("provider-a", "provider-b"),
        attempt_id="attempt-1",
    )
    first_binding = create_execution_binding(
        projection=first_projection,
        provider=select_provider_deterministically(first_projection, providers),
    )
    second_facts = _provider_facts("provider-a", "provider-b")
    second_facts["provider-a"] = replace(second_facts["provider-a"], ready=False)
    second_projection = _projection(
        logical=logical,
        providers=providers,
        facts=second_facts,
        attempt_id="attempt-2",
    )
    second_binding = create_execution_binding(
        projection=second_projection,
        provider=select_provider_deterministically(second_projection, providers),
    )

    assert first_binding.selected_provider_id == "provider-a"
    assert second_binding.selected_provider_id == "provider-b"
    assert first_binding.binding_hash != second_binding.binding_hash
    assert first_binding.attempt_id != second_binding.attempt_id
    assert approved_plan.approved_plan_hash == approved_hash
    assert "provider" not in str(approved_plan.canonical_payload()).lower()


def test_canonical_fixed_runtime_binds_before_grant_and_dispatches_bound_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[tuple[str, str]] = []
    dispatched: list[BoundCapabilityGrant] = []
    original_eligibility = adaptive_runtime.compute_provider_eligibility
    original_binding = adaptive_runtime.create_execution_binding
    original_issue_grant = AdaptiveRuntimeEngine._issue_grant
    original_dispatch = AdaptiveCapabilityDispatcher.dispatch

    def observe_eligibility(**kwargs):
        order.append(("eligibility", kwargs["attempt_id"]))
        return original_eligibility(**kwargs)

    def observe_binding(**kwargs):
        projection = kwargs["projection"]
        order.append(("binding", projection.attempt_id))
        return original_binding(**kwargs)

    def observe_grant(**kwargs):
        order.append(("grant", kwargs["attempt_id"]))
        return original_issue_grant(**kwargs)

    def observe_dispatch(self, **kwargs):
        dispatched.append(kwargs["grant"])
        return original_dispatch(self, **kwargs)

    monkeypatch.setattr(adaptive_runtime, "compute_provider_eligibility", observe_eligibility)
    monkeypatch.setattr(adaptive_runtime, "create_execution_binding", observe_binding)
    monkeypatch.setattr(
        AdaptiveRuntimeEngine,
        "_issue_grant",
        staticmethod(observe_grant),
    )
    monkeypatch.setattr(AdaptiveCapabilityDispatcher, "dispatch", observe_dispatch)

    result = RuntimeDriver().run_mode(
        "strict_fixed",
        fixed_request=_fixed_request(tmp_path),
    )

    assert result.completed
    attempt_ids = [record.attempt_id for record in result.runtime.session.attempt_records]
    assert order == [
        item
        for attempt_id in attempt_ids
        for item in (
            ("eligibility", attempt_id),
            ("binding", attempt_id),
            ("grant", attempt_id),
        )
    ]
    assert len(result.runtime.provider_eligibility_projections) == 3
    assert len(result.runtime.execution_bindings) == 3
    assert len(result.runtime.bound_grants) == 3
    assert dispatched == list(result.runtime.bound_grants)
    for projection, binding, bound_grant in zip(
        result.runtime.provider_eligibility_projections,
        result.runtime.execution_bindings,
        result.runtime.bound_grants,
        strict=True,
    ):
        assert projection.attempt_id == binding.attempt_id == bound_grant.grant.attempt_id
        assert binding.eligibility_projection_hash == projection.projection_hash
        assert bound_grant.execution_binding_hash == binding.binding_hash
        assert bound_grant.provider_id == binding.selected_provider_id
    assert result.runtime.session.capability_grant_hashes == tuple(
        bound_grant.grant.grant_hash for bound_grant in result.runtime.bound_grants
    )
    assert result.approved_plan_bundle.approved_plan_hash == result.runtime.approved_plan_hash


def test_no_eligible_provider_fails_before_grant(tmp_path: Path, monkeypatch) -> None:
    legacy = _legacy_descriptor()
    registry = CapabilityRegistry()
    registry.register(legacy)
    envelope = AdaptiveTaskEnvelope(
        task_id="task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="binding-test",
        allowed_capability_ids=(legacy.capability_id,),
        allowed_output_contracts=(legacy.output_contract_version,),
        role_cardinality={"executor": (1, 1)},
        max_plan_steps=1,
        max_execution_runtime_ms=1_000,
        max_total_attempts=1,
        risk_class=RiskClass.READ_ONLY,
    )
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id="task",
        steps=(PlanStepProposal(
            step_id="execute",
            role="executor",
            capability_id=legacy.capability_id,
            goal="produce deterministic analysis",
            output_contract_version=legacy.output_contract_version,
            input_ref_ids=("evidence",),
            input_ref_kinds=("canonical_evidence_pack",),
        ),),
        final_output_contract_version=legacy.output_contract_version,
    )
    available_input_refs = {"evidence": "canonical_evidence_pack"}
    approved = PlanPolicyValidator(registry).validate(
        proposal,
        envelope,
        available_input_refs=available_input_refs,
    ).approved_plan
    assert approved is not None
    incompatible = replace(
        project_legacy_provider(legacy, provider_id="provider-incompatible"),
        supported_semantic_contract_hashes=("wrong-semantic-contract",),
    )
    providers = ExecutionProviderRegistry()
    providers.register(incompatible)

    def grant_must_not_be_issued(**_kwargs):
        raise AssertionError("grant issued before a valid execution binding")

    monkeypatch.setattr(
        AdaptiveRuntimeEngine,
        "_issue_grant",
        staticmethod(grant_must_not_be_issued),
    )

    with pytest.raises(ProviderBindingError, match="no_eligible_provider"):
        AdaptiveRuntimeEngine().run(AdaptiveRuntimeRequest(
            trace_id="trace",
            task_id="task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            provider_registry=providers,
            runtime_root=str(tmp_path),
            workspace_root_id="workspace",
            available_input_refs=available_input_refs,
            execute_step=lambda _step, _grant: (_ for _ in ()).throw(
                AssertionError("provider executed without a valid binding")
            ),
        ))


def test_dispatcher_rejects_unbound_or_mismatched_provider_before_handler(
    tmp_path: Path,
) -> None:
    legacy = _legacy_descriptor()
    registry = CapabilityRegistry()
    registry.register(legacy)
    logical = registry.logical_descriptor(legacy.capability_id)
    providers = ExecutionProviderRegistry()
    provider = project_legacy_provider(legacy, provider_id="provider-a")
    providers.register(provider)
    step = PlanStepProposal(
        step_id="execute",
        role="executor",
        capability_id=legacy.capability_id,
        goal="execute",
        output_contract_version=legacy.output_contract_version,
    )
    approved = ApprovedPlan(
        approved_plan_id="approved",
        task_id="task",
        source_proposal_id="proposal",
        steps=(step,),
        final_output_contract_version=legacy.output_contract_version,
        plan_policy_report_hash="policy",
        capability_registry_digest=registry.digest,
        total_attempt_budget=1,
    )
    projection = replace(
        _projection(
            logical=logical,
            providers=providers,
            facts=_provider_facts(provider.provider_id),
        ),
        approved_plan_hash=approved.approved_plan_hash,
    )
    binding = create_execution_binding(projection=projection, provider=provider)
    grant = CapabilityGrant(
        grant_id="grant",
        task_id="task",
        session_id="session",
        step_id="execute",
        attempt_id="attempt-1",
        capability_id=legacy.capability_id,
        capability_version=legacy.version,
        input_ref_ids=(),
        output_contract_version=legacy.output_contract_version,
        workspace_root_id="workspace",
        max_runtime_ms=1_000,
        expires_at_ns=time.time_ns() + 1_000_000_000,
        approved_plan_hash=approved.approved_plan_hash,
    )
    calls: list[str] = []

    def handler(_envelope, _plan, _step, issued_grant, _workspace):
        calls.append(issued_grant.grant_id)
        return AdaptiveStepResult(grant_hash=issued_grant.grant_hash, success=True)

    dispatcher = AdaptiveCapabilityDispatcher(context=AdaptiveDispatchContext(
        registry=registry,
        builtin_handlers={legacy.capability_id: handler},
    ))
    envelope = AdaptiveTaskEnvelope(
        task_id="task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="binding-test",
        allowed_capability_ids=(legacy.capability_id,),
        allowed_output_contracts=(legacy.output_contract_version,),
    )
    runtime_identity = RuntimeIdentity(
        runtime_task_id="task",
        run_id="run-provider-binding-test",
        session_id="session",
        trace_id="trace-provider-binding-test",
        task_contract=TaskContractIdentity.from_hash("spec"),
    )

    unbound = dispatcher.dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=step,
        grant=grant,
        attempt_workspace=tmp_path / "unbound",
        runtime_identity=runtime_identity,
    )
    mismatched_binding = replace(
        binding,
        selected_implementation_kind=ExecutionKind.TRANSFORM_DSL.value,
    )
    mismatched = dispatcher.dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=step,
        grant=BoundCapabilityGrant(
            grant=grant,
            execution_binding=mismatched_binding,
        ),
        attempt_workspace=tmp_path / "mismatched",
        runtime_identity=runtime_identity,
    )

    assert not unbound.success
    assert unbound.error_code == "execution_binding_required"
    assert not mismatched.success
    assert mismatched.error_code == "execution_binding_implementation_mismatch"
    assert calls == []
