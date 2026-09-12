from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from statebus.contracts import (
    CanonicalTaskSpec,
    EvidenceRequest,
    RuntimeIdentity,
    StepLifecycleState,
    TaskContractIdentity,
    WorkflowMode,
)
from statebus.runtime.adaptive_mainline import AdaptiveMainlineRunner
from statebus.runtime.adaptive_dispatcher import AdaptiveCapabilityDispatcher
from statebus.runtime.adaptive_runtime import AdaptiveStepResult
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.fixed_mainline import FixedMainlineRequest
from statebus.runtime.role_path import RolePathRunner
from statebus.runtime.role_providers import ProviderCandidate, ProviderRequest
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
    mainline_request = request.to_adaptive_mainline_request()
    observed: list[tuple[str, object]] = []
    original_handlers = dict(mainline_request.bindings.bound_provider_handlers)

    def observe_provider(capability_id: str):
        original = original_handlers[capability_id]

        def wrapped(provider_request: ProviderRequest):
            observed.append((provider_request.step.step_id, provider_request.bound_grant))
            return original(provider_request)

        return wrapped

    mainline_request.bindings.bound_provider_handlers = {
        capability_id: observe_provider(capability_id)
        for capability_id in original_handlers
    }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("canonical fixed mainline invoked a legacy path")

    monkeypatch.setattr(RolePathRunner, "__init__", forbidden)
    monkeypatch.setattr("statebus.runtime.smoke.run_smoke", forbidden)
    monkeypatch.setattr("statebus.runtime.driver.build_default_workflow", forbidden)
    monkeypatch.setattr(RuntimeDriver, "run", forbidden)

    result = AdaptiveMainlineRunner().run(mainline_request)

    assert result.completed
    assert result.runtime.session.workflow_mode == WorkflowMode.STRICT_FIXED.value
    assert result.runtime.session.session_id == request.runtime_identity.session_id
    assert [step_id for step_id, _grant in observed] == [
        "plan",
        "retrieve",
        "execute",
        "summarize",
    ]
    assert all(hasattr(grant, "grant") for _step_id, grant in observed)
    assert all(
        grant.grant.approved_plan_hash == result.runtime.approved_plan_hash
        for _step_id, grant in observed
    )
    assert all(
        grant.grant.session_id == request.runtime_identity.session_id
        for _step_id, grant in observed
    )
    assert len(result.runtime.session.workflow_steps) == 4
    assert all(
        isinstance(step, RuntimeWorkflowStep)
        and step.state == StepLifecycleState.COMPLETED.value
        for step in result.runtime.session.workflow_steps
    )
    assert len(result.runtime.session.attempt_records) == 4
    assert all(
        isinstance(record, StepAttemptRecord)
        and record.state == StepLifecycleState.COMPLETED.value
        for record in result.runtime.session.attempt_records
    )
    assert result.runtime.session.capability_grant_hashes == tuple(
        grant.grant.grant_hash for _step_id, grant in observed
    )
    assert result.memory_commit_decision.reason == "memory_commit_disabled"
    assert not result.infrastructure.memory_store.get_admitted("fixed-memory")
    assert any(
        stored.artifact.produced_by == "executor"
        and stored.artifact.verification_state.value == "verified"
        and stored.artifact.artifact_id in result.context.artifact_verification_receipts
        for stored in result.context.artifacts.values()
    )
    claim_artifacts = [
        stored
        for stored in result.context.artifacts.values()
        if stored.artifact.produced_by == "summarizer"
    ]
    assert len(claim_artifacts) == 1
    claim_artifact = claim_artifacts[0].artifact
    assert claim_artifact.verification_state.value == "verified"
    claim_set = result.context.claim_sets[claim_artifact.artifact_id]
    assert claim_set.claims[0].supporting_artifact_ref_ids[0] in result.context.artifacts
    assert result.context.artifacts[
        claim_set.claims[0].supporting_artifact_ref_ids[0]
    ].artifact.verification_state.value == "verified"
    assert all(not ref.startswith("fixed-compatibility:") for ref in result.runtime.dispatches[-1].output_refs)
    assert result.approved_plan_bundle is not None
    assert result.approved_plan_bundle.approved_plan_hash == result.runtime.approved_plan_hash


def test_fixed_formal_entrypoint_runs_bound_provider_graph_without_legacy_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = RuntimeDriver()
    entrypoint_calls: list[str] = []
    entrypoint_requests = []
    original_run_adaptive_mainline = driver.run_adaptive_mainline

    def observe_entrypoint(request):
        entrypoint_calls.append("run_adaptive_mainline")
        entrypoint_requests.append(request)
        return original_run_adaptive_mainline(request)

    monkeypatch.setattr(driver, "run_adaptive_mainline", observe_entrypoint)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("formal fixed entrypoint invoked a legacy path")

    monkeypatch.setattr(RolePathRunner, "__init__", forbidden)
    monkeypatch.setattr("statebus.runtime.smoke.run_smoke", forbidden)
    monkeypatch.setattr("statebus.runtime.driver.build_default_workflow", forbidden)
    monkeypatch.setattr(RuntimeDriver, "run", forbidden)

    result = driver.run_mode("strict_fixed", fixed_request=_fixed_request(tmp_path))

    assert result.completed
    assert entrypoint_calls == ["run_adaptive_mainline"]
    assert len(entrypoint_requests) == 1
    assert entrypoint_requests[0].provider_registry is not None
    assert result.context.provider_registry is entrypoint_requests[0].provider_registry
    assert result.runtime.session.workflow_mode == WorkflowMode.STRICT_FIXED.value
    assert result.runtime.bound_grants
    assert result.runtime.execution_bindings
    assert result.runtime.dispatches[-1].state == StepLifecycleState.COMPLETED.value
    assert result.runtime.provider_registry_digest == entrypoint_requests[0].provider_registry.digest
    assert result.context.artifact_verification_receipts
    assert any(
        stored.artifact.verification_state.value == "verified"
        and stored.artifact.artifact_id in result.context.artifact_verification_receipts
        for stored in result.context.artifacts.values()
    )
    for binding in result.runtime.execution_bindings:
        provider = entrypoint_requests[0].provider_registry.get(binding.selected_provider_id)
        implementation = entrypoint_requests[0].provider_registry.implementation(
            binding.selected_provider_id,
            binding.selected_provider_version,
        )
        assert provider.provider_version == binding.selected_provider_version
        assert provider.implementation_kind == binding.selected_implementation_kind
        assert implementation.request_schema_version == provider.schema_version
    assert result.memory_commit_decision.reason == "memory_commit_disabled"
    assert all(
        not ref.startswith("fixed-compatibility:")
        for dispatch in result.runtime.dispatches
        for ref in dispatch.output_refs
    )


@pytest.mark.parametrize("mutation", ("wrong_task", "wrong_step", "wrong_scope"))
def test_fixed_mainline_rejects_unbound_provider_candidates(
    tmp_path: Path,
    mutation: str,
) -> None:
    mainline_request = _fixed_request(tmp_path).to_adaptive_mainline_request()
    retrieve_capability = next(
        step.capability_id
        for step in mainline_request.approved_plan_bundle.approved_plan.steps
        if step.role == "retriever"
    )
    def invalid_handler(request: ProviderRequest):
        candidate = EvidenceRequest(
            request_id="invalid-fixed-request",
            task_id=("wrong-task" if mutation == "wrong_task" else request.envelope.task_id),
            step_id=("wrong-step" if mutation == "wrong_step" else request.step.step_id),
            queries=("revenue",),
            evidence_types=("table",),
            corpus_scope_ids=(("wrong-scope",) if mutation == "wrong_scope" else ("fixed-local",)),
        )
        return ProviderCandidate(True, "retrieval_request", candidate)

    mainline_request.bindings.bound_provider_handlers[retrieve_capability] = invalid_handler
    result = AdaptiveMainlineRunner().run(mainline_request)

    assert not result.completed
    assert len(result.runtime.session.attempt_records) == 2
    assert result.runtime.dispatches[-1].state == StepLifecycleState.FAILED.value
    assert result.runtime.dispatches[-1].error_code in {
        "provider_candidate_scope_mismatch",
        "unknown_corpus_scope",
    }


def test_fixed_mainline_rejects_unregistered_execution_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _fixed_request(tmp_path).to_adaptive_mainline_request()
    original_dispatch = AdaptiveCapabilityDispatcher._dispatch_transform_dsl

    def unregistered_result(self, envelope, approved_plan, step, grant, attempt_workspace, **kwargs):
        if step.step_id == "execute":
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=True,
                attempt_id=grant.attempt_id,
                output_refs=("missing-execution-artifact",),
                output_ref_kinds=("execution_artifact",),
            )
        return original_dispatch(
            self,
            envelope,
            approved_plan,
            step,
            grant,
            attempt_workspace,
            **kwargs,
        )

    monkeypatch.setattr(
        AdaptiveCapabilityDispatcher,
        "_dispatch_transform_dsl",
        unregistered_result,
    )

    result = AdaptiveMainlineRunner().run(request)

    assert not result.completed
    assert result.runtime.dispatches[-1].step_id == "execute"
    assert result.runtime.dispatches[-1].error_code == "artifact_candidate_not_registered"
    assert "missing-execution-artifact" not in result.context.artifacts
