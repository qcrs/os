from __future__ import annotations

from statebus.contracts import AdaptiveTaskEnvelope, PlanProposal, PlanStepProposal, RiskClass, WorkflowMode
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import (
    register_generic_adaptive_analysis_capabilities,
    register_long_doc_analysis_capabilities,
)
from statebus.runtime.plan_policy import PlanPolicyValidator


def _envelope(pack, registry) -> AdaptiveTaskEnvelope:
    return AdaptiveTaskEnvelope(
        task_id="surface-task",
        canonical_task_spec_hash="surface-spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=tuple(
            sorted({registry.get(capability_id).output_contract_version for capability_id in pack.capability_ids})
        ),
        risk_class=RiskClass.WORKSPACE_WRITE,
        max_plan_steps=6,
        max_execution_runtime_ms=128_000,
    )


def _dsl_plan(*, retrieval_capability: str, executor_capability: str, report_capability: str) -> PlanProposal:
    return PlanProposal(
        proposal_id=f"surface-{retrieval_capability}-{executor_capability}",
        task_id="surface-task",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="retrieve",
                role="retriever",
                capability_id=retrieval_capability,
                goal="retrieve approved evidence",
                output_contract_version="statebus.evidence_pack.v2",
                completion_criteria={"min_locator_count": 1},
            ),
            PlanStepProposal(
                step_id="extract",
                role="executor",
                capability_id="extract_metric_series_v1",
                goal="extract a verified metric series",
                depends_on=("retrieve",),
                output_contract_version="statebus.metric_series.v1",
                completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                step_id="analyze",
                role="executor",
                capability_id=executor_capability,
                goal="apply the selected bounded metric analysis",
                depends_on=("extract",),
                output_contract_version=(
                    "statebus.aggregation.v1" if executor_capability == "aggregate_metrics_v1" else "statebus.anomaly_report.v1"
                ),
                completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                step_id="report",
                role="summarizer",
                capability_id=report_capability,
                goal="compose the selected cited report",
                depends_on=("retrieve", "analyze"),
                output_contract_version="statebus.cited_report.v1",
                completion_criteria={"min_locator_count": 1},
            ),
        ),
    )


def test_domain_pack_exposes_multiple_legal_capabilities_per_adaptive_role() -> None:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    public = registry.public_view(pack.capability_ids)
    by_role: dict[str, list[str]] = {}
    for descriptor in public:
        by_role.setdefault(str(descriptor["role"]), []).append(str(descriptor["id"]))

    assert len(by_role["retriever"]) >= 2
    assert len(by_role["executor"]) >= 6
    assert len(by_role["summarizer"]) >= 3
    assert "retrieve_memory_assist_v1" not in pack.capability_ids
    assert registry.contains("retrieve_memory_assist_v1")
    assert all("completion_criteria" in descriptor for descriptor in public)
    assert all("fallback_capability_id" in descriptor for descriptor in public)
    assert all("root_id" not in descriptor and "network" not in descriptor for descriptor in public)


def test_generic_execution_capabilities_publish_linear_dsl_boundary() -> None:
    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(registry)
    public = {
        str(descriptor["id"]): descriptor
        for descriptor in registry.public_view(pack.capability_ids)
    }

    dsl_description = str(public["execute_analysis_dsl_v2"]["description"])
    python_description = str(public["execute_bounded_python_v2"]["description"])
    assert "one linear row pipeline" in dsl_description
    assert "pivot category rows into columns" in dsl_description
    assert "cross-row alignment" in python_description
    assert "branch-and-recombine processing" in python_description


def test_distinct_financial_analysis_plans_are_approved_with_distinct_hashes() -> None:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = _envelope(pack, registry)
    validator = PlanPolicyValidator(registry)
    aggregation = _dsl_plan(
        retrieval_capability="retrieve_table_evidence_v1",
        executor_capability="aggregate_metrics_v1",
        report_capability="compose_comparison_report_v1",
    )
    anomaly = _dsl_plan(
        retrieval_capability="retrieve_semantic_evidence_v1",
        executor_capability="detect_anomaly_v1",
        report_capability="compose_risk_memo_v1",
    )

    aggregation_outcome = validator.validate(aggregation, envelope)
    anomaly_outcome = validator.validate(anomaly, envelope)

    assert aggregation_outcome.approved_plan is not None, aggregation_outcome.report.canonical_payload()
    assert anomaly_outcome.approved_plan is not None, anomaly_outcome.report.canonical_payload()
    assert aggregation_outcome.approved_plan.approved_plan_hash != anomaly_outcome.approved_plan.approved_plan_hash
