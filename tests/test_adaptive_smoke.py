from __future__ import annotations

import json
from types import SimpleNamespace

from statebus.contracts import PlanProposal, WorkflowMode
from tests.test_adaptive_driver import _setup
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveShadowRequest, AdaptiveStepResult
from statebus.runtime.driver import RuntimeDriver


def test_small_deterministic_three_mode_adaptive_smoke(tmp_path) -> None:
    # strict is intentionally represented by the pre-existing fixed result; adaptive shadow must not mutate it.
    strict_fixed_result = {"revenue": 120, "previous_revenue": 100, "growth_pct": 20.0}
    registry, shadow_envelope, approved = _setup(WorkflowMode.ADAPTIVE_SHADOW)
    shadow = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="shadow", task_id="task", canonical_task_spec_hash="spec", envelope=shadow_envelope,
        approved_plan=approved, registry=registry, runtime_root=str(tmp_path / "shadow"), workspace_root_id="workspace",
        execute_step=lambda step, grant: (_ for _ in ()).throw(AssertionError("shadow must not execute")),
    ))
    assert shadow.shadow_only
    assert strict_fixed_result == {"revenue": 120, "previous_revenue": 100, "growth_pct": 20.0}

    registry, bounded_envelope, approved = _setup(WorkflowMode.ADAPTIVE_BOUNDED)
    decisions: list[tuple[str, tuple[str, ...]]] = []

    def execute(step, grant):
        decisions.append((step.capability_id, grant.input_ref_ids))
        kind = {
            "retrieve": "canonical_evidence_pack",
            "extract": "execution_artifact",
            "report": "execution_artifact",
        }[step.step_id]
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash, success=True, output_refs=(f"{step.step_id}-output",), output_ref_kinds=(kind,),
        )

    bounded = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="bounded", task_id="task", canonical_task_spec_hash="spec", envelope=bounded_envelope,
        approved_plan=approved, registry=registry, runtime_root=str(tmp_path / "bounded"), workspace_root_id="workspace", execute_step=execute,
    ))
    assert bounded.completed
    assert decisions[0][0] == "retrieve_semantic_evidence_v1"
    assert decisions[1][1] == ("retrieve-output",)
    assert decisions != [("plan_retrieval_and_execution", ())]


def test_shadow_audits_proposal_then_returns_the_unmodified_strict_result(tmp_path) -> None:
    registry, envelope, approved = _setup(WorkflowMode.ADAPTIVE_SHADOW)
    valid_fallback = PlanProposal(
        proposal_id="fixed-fallback",
        task_id="task",
        steps=approved.steps,
        final_output_contract_version=approved.final_output_contract_version,
    )
    rejected_candidate = PlanProposal(
        proposal_id="rejected-candidate",
        task_id="task",
        steps=approved.steps,
        final_output_contract_version=approved.final_output_contract_version,
        schema_version="statebus.plan_proposal.invalid",
    )
    strict_input = SimpleNamespace(
        trace_id="shadow-trace",
        task_id="task",
        step_id="executor.fixed",
        artifact_id="strict-artifact",
    )
    strict_result = {"revenue": 120, "previous_revenue": 100, "growth_pct": 20.0}
    calls: list[object] = []
    driver = RuntimeDriver()

    def run_strict(runtime_input):
        calls.append(runtime_input)
        return strict_result

    driver.run = run_strict  # type: ignore[method-assign]
    result = driver.run_adaptive_shadow(
        strict_input,
        AdaptiveShadowRequest(
            trace_id="shadow-trace",
            task_id="task",
            envelope=envelope,
            registry=registry,
            runtime_root=str(tmp_path),
            propose_plan=lambda: rejected_candidate,
            fallback_proposal=valid_fallback,
        ),
    )

    assert calls == [strict_input]
    assert result.strict_result is strict_result
    assert result.audit.proposal.proposal_hash == rejected_candidate.proposal_hash
    assert result.audit.policy_rejected
    assert result.audit.fallback_used
    assert not result.audit.proposal_valid
    assert result.audit.runtime_signature.workflow_mode == WorkflowMode.ADAPTIVE_SHADOW
    events = [
        json.loads(line)
        for line in (tmp_path / "telemetry" / "runtime_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    event = next(item for item in events if item["event_type"] == "ADAPTIVE_SHADOW_AUDITED")
    assert event["metrics"] == {
        "fallback_used": 1.0,
        "policy_rejected": 1.0,
        "proposal_valid": 0.0,
        "repair_used": 0.0,
    }
