from pathlib import Path
import pytest

from statebus.benchmark.contest_fairness import build_c2a_pilot_records, audit_oracle_visibility
from statebus.benchmark.minimal_runner import run_c2a_pilot, run_c2b_formal_suite, _c2a_envelope, _c2a_identity, _c2a_task_spec
from statebus.benchmark.external_text_baseline import run_pure_text_mas, run_direct_single_agent
from statebus.benchmark.metric_aggregation import project_metric_availability
from statebus.benchmark.task_registry import c2a_pilot_samples, load_c2b_positive_samples, c2b_control_specs
from statebus.contracts import AdaptiveTaskEnvelope, CanonicalTaskSpec, PlanProposal, PlanStepProposal, RuntimeIdentity, TaskContractIdentity, WorkflowMode
from statebus.runtime.adaptive_mainline import AdaptiveMainlineBindings, AdaptiveMainlineError, AdaptiveMainlineRequest
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import c2a_four_role_pack, register_c2a_four_role_capabilities, register_long_doc_analysis_capabilities
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.fixed_mainline import FixedMainlineRequest
from statebus.runtime.static_role_recipe import default_fixed_role_recipe


def _request(tmp_path: Path) -> FixedMainlineRequest:
    spec = CanonicalTaskSpec(task_family="c2a", intent_op="extract")
    identity = RuntimeIdentity(
        external_case_id="c2a-case", runtime_task_id="c2a-task", run_id="c2a-run",
        session_id="c2a-session", trace_id="c2a-trace",
        task_contract=TaskContractIdentity.from_canonical_task_spec(spec),
    )
    return FixedMainlineRequest(
        runtime_identity=identity, canonical_task_spec=spec,
        recipe=default_fixed_role_recipe(), runtime_root=tmp_path / "runtime", workspace_root=tmp_path / "workspace",
    )


def test_static_role_recipe_four_role_topology() -> None:
    recipe = default_fixed_role_recipe()
    recipe.validate_fixed_topology()
    assert [(step.step_id, step.role) for step in recipe.steps] == [
        ("plan", "planner"), ("retrieve", "retriever"), ("execute", "executor"), ("summarize", "summarizer")
    ]


def test_fixed_strict_planner_attempt_binding_receipt_and_dependency(tmp_path: Path) -> None:
    result = RuntimeDriver().run_mode("strict_fixed", fixed_request=_request(tmp_path))
    assert result.completed
    assert [record.owner_role for record in result.runtime.session.attempt_records] == [
        "planner", "retriever", "executor", "summarizer"
    ]
    assert result.runtime.execution_bindings and result.runtime.bound_grants and result.runtime.attempt_result_admissions
    assert result.runtime.dispatches[0].step_id == "plan"
    assert result.context.planner_handoffs
    assert result.runtime.session.workflow_mode == WorkflowMode.STRICT_FIXED.value


def test_c2a_registry_and_isolation(tmp_path: Path) -> None:
    assert len(c2a_pilot_samples()) == 8
    report = build_c2a_pilot_records(case_ids=[s.task_id for s in c2a_pilot_samples()], root=tmp_path)
    assert len(report["terminal_records"]) == 32
    assert report["failure_denominator"]["attempted_count"] == 32
    assert report["root_isolation"]["ok"]


def test_oracle_and_metric_availability() -> None:
    assert audit_oracle_visibility(provider_request={"task": "x"})["ok"]
    assert not audit_oracle_visibility(provider_request={"expected_route": "gold"})["ok"]
    projection = project_metric_availability()
    assert projection["recipe_step_skip"]["status"] == "deferred"
    assert projection["recipe_step_skip"]["reason"] == "recipe_step_skip_deferred_to_c2"
    assert all(
        item["status"] == "unsupported"
        for name, item in projection.items()
        if name != "recipe_step_skip"
    )


def test_c2a_pilot_has_real_four_role_and_denominator_closure(tmp_path: Path) -> None:
    report = run_c2a_pilot(root=tmp_path)
    assert len(report["terminal_records"]) == 32
    # A pilot without persisted targeted-test and compile evidence is not
    # acceptance-eligible, even when all 32 execution rows are terminal.
    assert report["pilot_eligible"] is False
    assert report["c2a_eligibility"]["pilot_eligible"] is False
    assert report["failure_denominator"] == {
        "attempted_count": 32,
        "success_count": 20,
        "quality_fail_count": 0,
        "timeout_count": 2,
        "unsupported_count": 5,
        "runtime_fail_count": 3,
        "policy_reject_count": 2,
        "environment_fail_count": 0,
        "failure_count": 12,
        "quality_pass_rate": 20 / 32,
    }
    for record in report["terminal_records"]:
        manifest = record["manifest"]
        assert manifest["registration_only"] is False
        if manifest["lane"] in {"fixed_structured", "adaptive_routed"} and not manifest["case_id"].startswith("control_"):
            assert manifest["trace"]["role_sequence"] == ["planner", "retriever", "executor", "summarizer"]
            assert manifest["trace"]["role_count"] == {role: 1 for role in ("planner", "retriever", "executor", "summarizer")}
            assert len(manifest["trace"]["attempts"]) == 4
        if manifest["lane"] == "pure_text_mas" and not manifest["case_id"].startswith("control_"):
            assert len(manifest["trace"]["calls"]) == 4
        if manifest["lane"] == "direct_single_agent" and not manifest["case_id"].startswith("control_"):
            assert len(manifest["trace"]["calls"]) == 1


def test_c2b_registry_and_formal_matrix_close_pair_denominators(tmp_path: Path) -> None:
    assert len(load_c2b_positive_samples()) == 48
    assert len(c2b_control_specs()) == 12
    report = run_c2b_formal_suite(root=tmp_path / "c2b")
    assert report["positive_rows"] == 576
    assert report["control_rows"] == 48
    assert report["holdout_rows"] == 96
    assert len(report["rows"]) == 720
    assert report["benchmark_superiority"] == "NOT_ESTABLISHED"
    assert report["live_vllm_gpu_validation"] == "NOT_RUN"
    assert (tmp_path / "c2b" / "pair_repeat_seed_index.json").is_file()
    assert (tmp_path / "c2b" / "failed_rows.json").is_file()


def test_canonical_adaptive_rejects_three_role_proposal(tmp_path: Path) -> None:
    sample = c2a_pilot_samples()[0]
    spec = _c2a_task_spec(sample)
    identity = _c2a_identity(sample, "adaptive_routed")
    registry = CapabilityRegistry()
    pack = register_c2a_four_role_capabilities(registry)
    envelope = _c2a_envelope(task_id=identity.runtime_task_id, spec_hash=spec.spec_hash, pack=pack)
    proposal = PlanProposal(
        proposal_id="legacy-three-role",
        task_id=identity.runtime_task_id,
        steps=(
            PlanStepProposal("retrieve", "retriever", "retrieve_table_evidence_v1", "retrieve", output_contract_version="statebus.evidence_pack.v2"),
            PlanStepProposal("execute", "executor", "extract_metric_series_v1", "execute", depends_on=("retrieve",), output_contract_version="statebus.metric_series.v1"),
            PlanStepProposal("summarize", "summarizer", "compose_cited_report_v1", "summarize", depends_on=("execute",), output_contract_version="statebus.cited_report.v1"),
        ),
        final_output_contract_version="statebus.cited_report.v1",
    )
    request = AdaptiveMainlineRequest(
        trace_id=identity.trace_id, task_id=identity.runtime_task_id, canonical_task_spec_hash=spec.spec_hash,
        canonical_task_spec=spec, envelope=envelope, registry=registry, runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspace", propose_plan=lambda: proposal, bindings=AdaptiveMainlineBindings(),
        runtime_identity=identity,
    )
    with pytest.raises(AdaptiveMainlineError, match="c2a.adaptive.proposal_rejected:adaptive_canonical_requires_four_role_proposal"):
        from statebus.runtime.adaptive_mainline import AdaptiveMainlineRunner
        AdaptiveMainlineRunner().run(request)


def test_c2a_pack_isolated_from_legacy_three_role_fallback() -> None:
    legacy_registry = CapabilityRegistry()
    legacy_pack = register_long_doc_analysis_capabilities(legacy_registry)
    assert "plan_retrieval_and_execution_v1" not in legacy_pack.capability_ids
    assert len(legacy_pack.fallback_proposal(AdaptiveTaskEnvelope(task_id="t", canonical_task_spec_hash="s", workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED, domain_pack_id=legacy_pack.pack_id, allowed_capability_ids=legacy_pack.capability_ids, allowed_output_contracts=(legacy_pack.final_output_contract,))).steps) == 3
    with pytest.raises(ValueError, match="no_hidden_fixed_fallback"):
        c2a_four_role_pack().fallback_proposal(AdaptiveTaskEnvelope(task_id="t", canonical_task_spec_hash="s", workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED, domain_pack_id="c2a_four_role_v1", allowed_capability_ids=c2a_four_role_pack().capability_ids, allowed_output_contracts=("statebus.cited_report.v1",)))
