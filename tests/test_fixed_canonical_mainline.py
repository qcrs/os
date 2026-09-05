from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from statebus.contracts import (
    CapabilityGrant,
    CanonicalTaskSpec,
    RuntimeIdentity,
    StepLifecycleState,
    TaskContractIdentity,
    WorkflowMode,
)
from statebus.runtime.adaptive_dispatcher import AdaptiveCapabilityDispatcher
from statebus.runtime.adaptive_mainline import AdaptiveMainlineRunner
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.fixed_mainline import FixedMainlineRequest
from statebus.runtime.role_path import RolePathRunner
from statebus.runtime.session import RuntimeWorkflowStep, StepAttemptRecord
from statebus.runtime.static_role_recipe import default_fixed_role_recipe


def _fixed_request(tmp_path: Path) -> FixedMainlineRequest:
    task_spec = CanonicalTaskSpec(
        task_family="fixed_compatibility",
        intent_op="deterministic_bridge",
        target_entities=("fixture",),
        required_outputs=("cited_report",),
    )
    runtime_identity = RuntimeIdentity(
        external_case_id="mrr-03b-case",
        runtime_task_id="mrr-03b-fixed-task",
        run_id="mrr-03b-run",
        session_id="mrr-03b-session",
        trace_id="mrr-03b-trace",
        task_contract=TaskContractIdentity.from_canonical_task_spec(task_spec),
    )
    return FixedMainlineRequest(
        runtime_identity=runtime_identity,
        canonical_task_spec=task_spec,
        recipe=default_fixed_role_recipe(),
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspaces",
    )


def test_fixed_mainline_request_builds_strict_envelope_from_static_recipe_bundle(
    tmp_path: Path,
) -> None:
    request = _fixed_request(tmp_path)
    mainline_request = request.to_adaptive_mainline_request()
    bundle = mainline_request.approved_plan_bundle

    assert mainline_request.envelope.workflow_mode == WorkflowMode.STRICT_FIXED
    assert mainline_request.runtime_identity == request.runtime_identity
    assert mainline_request.canonical_task_spec == request.canonical_task_spec
    assert mainline_request.memory_commit_enabled is False
    assert mainline_request.propose_plan is None
    assert bundle is not None and bundle.verify_hash_links()
    assert bundle.recipe_id == request.recipe.recipe_id
    assert bundle.recipe_version == request.recipe.recipe_version
    assert bundle.approved_plan is not None
    assert bundle.approved_plan.capability_registry_digest == mainline_request.registry.digest
    assert tuple(step.canonical_payload() for step in bundle.source_proposal.steps) == tuple(
        step.to_plan_step().canonical_payload() for step in request.recipe.steps
    )

    bundle_request = replace(
        request,
        recipe=None,
        approved_plan_bundle=bundle,
        runtime_root=tmp_path / "bundle-runtime",
        workspace_root=tmp_path / "bundle-workspaces",
    )
    rebuilt = bundle_request.to_adaptive_mainline_request()

    assert rebuilt.approved_plan_bundle is bundle
    assert rebuilt.propose_plan is None
    assert rebuilt.registry.digest == bundle.logical_capability_registry_digest


def test_fixed_mainline_completes_through_runtime_grants_without_legacy_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _fixed_request(tmp_path)
    observed: list[tuple[str, CapabilityGrant]] = []
    original_dispatch_builtin = AdaptiveCapabilityDispatcher._dispatch_builtin

    def observe_builtin(self, envelope, approved_plan, step, grant, attempt_workspace):
        observed.append((step.step_id, grant))
        return original_dispatch_builtin(
            self,
            envelope,
            approved_plan,
            step,
            grant,
            attempt_workspace,
        )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("canonical fixed mainline invoked a legacy path")

    monkeypatch.setattr(AdaptiveCapabilityDispatcher, "_dispatch_builtin", observe_builtin)
    monkeypatch.setattr(RolePathRunner, "__init__", forbidden)
    monkeypatch.setattr("statebus.runtime.smoke.run_smoke", forbidden)
    monkeypatch.setattr("statebus.runtime.driver.build_default_workflow", forbidden)
    monkeypatch.setattr(RuntimeDriver, "run", forbidden)

    result = RuntimeDriver().run_mode("strict_fixed", fixed_request=request)

    assert result.completed
    assert result.runtime.session.workflow_mode == WorkflowMode.STRICT_FIXED.value
    assert result.runtime.session.session_id == request.runtime_identity.session_id
    assert [step_id for step_id, _grant in observed] == [
        "retrieve",
        "execute",
        "summarize",
    ]
    assert all(isinstance(grant, CapabilityGrant) for _step_id, grant in observed)
    assert all(
        grant.approved_plan_hash == result.runtime.approved_plan_hash
        for _step_id, grant in observed
    )
    assert all(
        grant.session_id == request.runtime_identity.session_id
        for _step_id, grant in observed
    )
    assert len(result.runtime.session.workflow_steps) == 3
    assert all(
        isinstance(step, RuntimeWorkflowStep)
        and step.state == StepLifecycleState.COMPLETED.value
        for step in result.runtime.session.workflow_steps
    )
    assert len(result.runtime.session.attempt_records) == 3
    assert all(
        isinstance(record, StepAttemptRecord)
        and record.state == StepLifecycleState.COMPLETED.value
        for record in result.runtime.session.attempt_records
    )
    assert result.runtime.session.capability_grant_hashes == tuple(
        grant.grant_hash for _step_id, grant in observed
    )
    assert result.memory_commit_decision.reason == "memory_commit_disabled"
    assert result.approved_plan_bundle is not None
    assert result.approved_plan_bundle.approved_plan_hash == result.runtime.approved_plan_hash


@pytest.mark.parametrize(
    ("result_mutation", "expected_error"),
    (
        ("grant_hash", "grant_binding_mismatch"),
        ("attempt_id", "grant_binding_mismatch"),
        ("output_ref_kind", "step_validator_failed"),
    ),
)
def test_fixed_mainline_rejects_unbound_handler_results(
    tmp_path: Path,
    result_mutation: str,
    expected_error: str,
) -> None:
    mainline_request = _fixed_request(tmp_path).to_adaptive_mainline_request()
    retrieve_capability = mainline_request.approved_plan_bundle.approved_plan.steps[0].capability_id
    original_handler = mainline_request.bindings.builtin_handlers[retrieve_capability]

    def invalid_handler(envelope, approved_plan, step, grant, attempt_workspace):
        result = original_handler(
            envelope,
            approved_plan,
            step,
            grant,
            attempt_workspace,
        )
        if result_mutation == "grant_hash":
            return replace(result, grant_hash="sha256:wrong-grant")
        if result_mutation == "attempt_id":
            return replace(result, attempt_id="wrong-attempt")
        return replace(result, output_ref_kinds=("wrong_ref_kind",))

    mainline_request.bindings.builtin_handlers[retrieve_capability] = invalid_handler
    result = AdaptiveMainlineRunner().run(mainline_request)

    assert not result.completed
    assert len(result.runtime.session.attempt_records) == 1
    assert result.runtime.dispatches[0].state == StepLifecycleState.FAILED.value
    assert result.runtime.dispatches[0].error_code == expected_error
