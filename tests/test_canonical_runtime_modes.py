from __future__ import annotations

from dataclasses import replace

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityDescriptor,
    CapabilityGrant,
    ExecutionKind,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    RuntimeIdentity,
    StepLifecycleState,
    TaskContractIdentity,
    WorkflowMode,
)
from statebus.runtime.adaptive_runtime import (
    AdaptiveRuntimeEngine,
    AdaptiveRuntimeError,
    AdaptiveRuntimeRequest,
    AdaptiveStepResult,
)
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.session import RuntimeWorkflowStep, StepAttemptRecord


def _policy_approved_case():
    registry = CapabilityRegistry()
    for descriptor in (
        CapabilityDescriptor(
            capability_id="retrieve",
            owner_role="retriever",
            description="retrieve deterministic evidence",
            input_ref_kinds=(),
            input_contract_version="input-v1",
            output_ref_kinds=("evidence",),
            output_contract_version="evidence-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=100,
            supports_replay=True,
        ),
        CapabilityDescriptor(
            capability_id="execute",
            owner_role="executor",
            description="execute deterministic transform",
            input_ref_kinds=("evidence",),
            required_input_ref_kinds=("evidence",),
            input_contract_version="input-v1",
            output_ref_kinds=("artifact",),
            output_contract_version="artifact-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=100,
            supports_replay=True,
        ),
        CapabilityDescriptor(
            capability_id="summarize",
            owner_role="summarizer",
            description="summarize deterministic artifact",
            input_ref_kinds=("artifact",),
            required_input_ref_kinds=("artifact",),
            input_contract_version="input-v1",
            output_ref_kinds=("report",),
            output_contract_version="report-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=100,
            supports_replay=True,
        ),
    ):
        registry.register(descriptor)

    envelope = AdaptiveTaskEnvelope(
        task_id="mode-task",
        canonical_task_spec_hash="mode-contract",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="mode-test-pack",
        allowed_capability_ids=("retrieve", "execute", "summarize"),
        allowed_output_contracts=("evidence-v1", "artifact-v1", "report-v1"),
        role_cardinality={
            "retriever": (1, 1),
            "executor": (1, 1),
            "summarizer": (1, 1),
        },
        max_plan_steps=3,
        max_execution_runtime_ms=300,
        max_total_attempts=3,
        risk_class=RiskClass.READ_ONLY,
    )
    proposal = PlanProposal(
        proposal_id="mode-proposal",
        task_id=envelope.task_id,
        steps=(
            PlanStepProposal(
                step_id="retrieve",
                role="retriever",
                capability_id="retrieve",
                goal="retrieve deterministic evidence",
                output_contract_version="evidence-v1",
            ),
            PlanStepProposal(
                step_id="execute",
                role="executor",
                capability_id="execute",
                goal="execute deterministic transform",
                depends_on=("retrieve",),
                output_contract_version="artifact-v1",
            ),
            PlanStepProposal(
                step_id="summarize",
                role="summarizer",
                capability_id="summarize",
                goal="summarize deterministic artifact",
                depends_on=("execute",),
                output_contract_version="report-v1",
            ),
        ),
        final_output_contract_version="report-v1",
    )
    outcome = PlanPolicyValidator(registry).validate(proposal, envelope)
    assert outcome.approved_plan is not None
    return registry, envelope, outcome.approved_plan


def _run_mode(
    *,
    engine: AdaptiveRuntimeEngine,
    mode: WorkflowMode,
    runtime_root,
    registry: CapabilityRegistry,
    envelope: AdaptiveTaskEnvelope,
    approved_plan,
    run_label: str,
    observed_grants: list[CapabilityGrant],
    callback_steps: list[str],
):
    output_kinds = {
        "retrieve": "evidence",
        "execute": "artifact",
        "summarize": "report",
    }

    def execute(step, grant):
        callback_steps.append(step.step_id)
        observed_grants.append(grant)
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            output_refs=(f"ref-{run_label}-{step.step_id}",),
            output_ref_kinds=(output_kinds[step.step_id],),
            attempt_id=grant.attempt_id,
        )

    identity = RuntimeIdentity(
        runtime_task_id=envelope.task_id,
        run_id=f"run-{run_label}",
        session_id=f"session-{run_label}",
        trace_id=f"trace-{run_label}",
        task_contract=TaskContractIdentity.from_hash(
            envelope.canonical_task_spec_hash
        ),
    )
    return engine.run(
        AdaptiveRuntimeRequest(
            trace_id=identity.trace_id,
            task_id=envelope.task_id,
            canonical_task_spec_hash=envelope.canonical_task_spec_hash,
            envelope=replace(envelope, workflow_mode=mode),
            approved_plan=approved_plan,
            registry=registry,
            runtime_root=str(runtime_root),
            workspace_root_id=f"workspace-{run_label}",
            execute_step=execute,
            runtime_identity=identity,
        )
    )


def test_engine_accepts_strict_fixed_and_owns_attempts_and_grants(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, envelope, approved_plan = _policy_approved_case()
    legacy_calls: list[str] = []

    def legacy_run(*_args, **_kwargs):
        legacy_calls.append("run")
        raise AssertionError("canonical strict execution invoked RuntimeDriver.run")

    monkeypatch.setattr(RuntimeDriver, "run", legacy_run)
    grants: list[CapabilityGrant] = []
    callback_steps: list[str] = []
    result = _run_mode(
        engine=AdaptiveRuntimeEngine(),
        mode=WorkflowMode.STRICT_FIXED,
        runtime_root=tmp_path / "strict",
        registry=registry,
        envelope=envelope,
        approved_plan=approved_plan,
        run_label="strict",
        observed_grants=grants,
        callback_steps=callback_steps,
    )

    assert result.completed
    assert not result.shadow_only
    assert legacy_calls == []
    assert callback_steps == ["retrieve", "execute", "summarize"]
    assert result.session.workflow_mode == WorkflowMode.STRICT_FIXED.value
    assert all(isinstance(step, RuntimeWorkflowStep) for step in result.session.workflow_steps)
    assert all(isinstance(record, StepAttemptRecord) for record in result.session.attempt_records)
    assert all(isinstance(grant, CapabilityGrant) for grant in grants)
    assert [step.state for step in result.session.workflow_steps] == [
        StepLifecycleState.COMPLETED.value,
        StepLifecycleState.COMPLETED.value,
        StepLifecycleState.COMPLETED.value,
    ]
    expected_attempt_ids = [
        "adaptive-attempt-run-strict-1",
        "adaptive-attempt-run-strict-2",
        "adaptive-attempt-run-strict-3",
    ]
    assert [record.attempt_id for record in result.session.attempt_records] == expected_attempt_ids
    assert [grant.attempt_id for grant in grants] == expected_attempt_ids
    assert [dispatch.attempt_id for dispatch in result.dispatches] == expected_attempt_ids
    assert {grant.session_id for grant in grants} == {"session-strict"}
    assert {grant.approved_plan_hash for grant in grants} == {
        approved_plan.approved_plan_hash
    }
    assert result.session.capability_grant_hashes == tuple(
        grant.grant_hash for grant in grants
    )
    assert [record.resource_handles for record in result.session.attempt_records] == [
        (grant.grant_hash,) for grant in grants
    ]


def test_strict_and_adaptive_execute_same_plan_through_same_workflow_function(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, envelope, approved_plan = _policy_approved_case()
    projected_plan_hashes: list[str] = []
    original_workflow = AdaptiveRuntimeEngine._workflow

    def record_workflow(plan, *, completed=None, failed=None):
        projected_plan_hashes.append(plan.approved_plan_hash)
        return original_workflow(plan, completed=completed, failed=failed)

    monkeypatch.setattr(
        AdaptiveRuntimeEngine,
        "_workflow",
        staticmethod(record_workflow),
    )
    results = {}
    callbacks = {}
    for mode, label in (
        (WorkflowMode.STRICT_FIXED, "strict-parity"),
        (WorkflowMode.ADAPTIVE_BOUNDED, "adaptive-parity"),
    ):
        grants: list[CapabilityGrant] = []
        callback_steps: list[str] = []
        results[mode] = _run_mode(
            engine=AdaptiveRuntimeEngine(),
            mode=mode,
            runtime_root=tmp_path / label,
            registry=registry,
            envelope=envelope,
            approved_plan=approved_plan,
            run_label=label,
            observed_grants=grants,
            callback_steps=callback_steps,
        )
        callbacks[mode] = callback_steps

    strict = results[WorkflowMode.STRICT_FIXED]
    adaptive = results[WorkflowMode.ADAPTIVE_BOUNDED]
    assert strict.completed and adaptive.completed
    assert strict.approved_plan_hash == adaptive.approved_plan_hash
    assert projected_plan_hashes == [
        approved_plan.approved_plan_hash,
        approved_plan.approved_plan_hash,
    ]
    assert callbacks[WorkflowMode.STRICT_FIXED] == callbacks[WorkflowMode.ADAPTIVE_BOUNDED]
    assert [
        (step.step_id, step.role, step.capability, step.depends_on, step.state)
        for step in strict.session.workflow_steps
    ] == [
        (step.step_id, step.role, step.capability, step.depends_on, step.state)
        for step in adaptive.session.workflow_steps
    ]
    assert strict.session.attempt_count == adaptive.session.attempt_count == 3
    assert len(strict.dispatches) == len(adaptive.dispatches) == 3


def test_engine_rejects_unsupported_workflow_mode(tmp_path) -> None:
    registry, envelope, approved_plan = _policy_approved_case()
    invalid_envelope = replace(envelope, workflow_mode="unsupported")

    with pytest.raises(AdaptiveRuntimeError, match="unsupported_runtime_workflow_mode"):
        AdaptiveRuntimeEngine().run(
            AdaptiveRuntimeRequest(
                trace_id="trace-invalid",
                task_id=envelope.task_id,
                canonical_task_spec_hash=envelope.canonical_task_spec_hash,
                envelope=invalid_envelope,
                approved_plan=approved_plan,
                registry=registry,
                runtime_root=str(tmp_path / "invalid"),
                workspace_root_id="workspace-invalid",
                execute_step=lambda _step, _grant: (_ for _ in ()).throw(
                    AssertionError("unsupported mode dispatched work")
                ),
            )
        )
