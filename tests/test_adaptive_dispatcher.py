from __future__ import annotations

from pathlib import Path
import time

import pytest

from statebus.contracts import BoundCapabilityGrant, CapabilityGrant, Claim, ClaimSet, EvidenceCoverageStatus, EvidenceRequest, RefStatus, TransformProgram, TransformStep
from statebus.refs import CanonicalEvidencePack, EvidenceItem, ExecutionArtifactRef, TableCellLocator
from statebus.runtime.adaptive_dispatcher import AdaptiveCapabilityDispatcher, AdaptiveDispatchContext, AdaptiveDispatchError, StoredAdaptiveArtifact
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.provider_registry import (
    ExecutionProviderRegistry,
    compute_provider_eligibility,
    create_execution_binding,
    default_provider_runtime_facts,
    select_provider_deterministically,
)
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from tests.test_adaptive_driver import _setup
from statebus.utils import sha256_digest, stable_json_dumps


def _bound_grant(
    registry: CapabilityRegistry,
    grant: CapabilityGrant,
) -> BoundCapabilityGrant:
    descriptor = registry.get(grant.capability_id)
    logical = registry.logical_descriptor(grant.capability_id)
    providers = ExecutionProviderRegistry.from_legacy_capability_registry(registry)
    projection = compute_provider_eligibility(
        task_id=grant.task_id,
        session_id=grant.session_id,
        step_id=grant.step_id,
        attempt_id=grant.attempt_id,
        approved_plan_hash=grant.approved_plan_hash,
        logical_capability=logical,
        provider_registry=providers,
        runtime_facts=default_provider_runtime_facts(providers),
        allowed_risk_class=descriptor.side_effect_class,
        required_runtime_ms=descriptor.max_runtime_ms,
    )
    provider = select_provider_deterministically(projection, providers)
    return BoundCapabilityGrant(
        grant=grant,
        execution_binding=create_execution_binding(
            projection=projection,
            provider=provider,
        ),
    )


def test_runtime_dispatcher_executes_retrieval_projection_dsl_and_registered_builtin(tmp_path) -> None:
    registry, envelope, approved = _setup()
    pack = CanonicalEvidencePack(
        pack_id="pack",
        task_id="task",
        source_doc_hashes=("doc",),
        hard_facts=(
            EvidenceItem(
                item_id="revenue-q1",
                bucket="hard_fact",
                locator=TableCellLocator(source_doc_hash="doc", table_id="income", row_idx=1, col_idx=1),
                metadata={"structured_row": {"quarter": "2026Q1", "revenue_musd": 120.0}},
            ),
        ),
    )

    def request_factory(step, grant) -> EvidenceRequest:
        return EvidenceRequest(
            request_id="retrieve-request",
            task_id=grant.task_id,
            step_id=step.step_id,
            queries=("ACME revenue",),
            evidence_types=("table",),
            corpus_scope_ids=("local",),
        )

    def program_factory(step, grant, input_ref_id, rows) -> TransformProgram:
        assert rows == ({"quarter": "2026Q1", "revenue_musd": 120.0},)
        return TransformProgram(
            program_id="invalid-extract-program",
            input_artifact_refs=(input_ref_id,),
            output_contract_version=grant.output_contract_version,
            operations=(TransformStep("select", {"columns": ["invented_revenue"]}),),
        )

    def repair_program(step, grant, input_ref_id, rows, validation_errors) -> TransformProgram:
        assert validation_errors == ("unknown_column:0",)
        assert rows == ({"quarter": "2026Q1", "revenue_musd": 120.0},)
        return TransformProgram(
            program_id="repaired-extract-program",
            input_artifact_refs=(input_ref_id,),
            output_contract_version=grant.output_contract_version,
            operations=(TransformStep("select", {"columns": ["quarter", "revenue_musd"]}),),
        )

    def report_handler(envelope, plan, step, grant, workspace) -> AdaptiveStepResult:
        del envelope, plan, step, workspace
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            attempt_id=grant.attempt_id,
            success=True,
            output_refs=("report-ref",),
            output_ref_kinds=("execution_artifact",),
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        retrieval_adapter=AdaptiveRetrievalAdapter(lambda query, request: pack),
        retrieval_request_factory=request_factory,
        allowed_corpus_scope_ids=("local",),
        transform_program_factory=program_factory,
        transform_program_repair_factory=repair_program,
        output_schema_by_capability={"extract_metric_series_v1": {"wrong_final_field": "number"}},
        output_schema_by_step={"extract": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": report_handler},
    )
    dispatcher = AdaptiveCapabilityDispatcher(context=context)
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="trace",
            task_id="task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path),
            workspace_root_id="workspace",
            dispatcher=dispatcher,
        )
    )
    assert result.completed
    assert result.session.projection_report_hashes
    assert result.session.capability_quality_report_hashes
    assert result.session.transform_program_hashes
    artifact = next(stored.artifact for stored in context.artifacts.values() if stored.artifact.produced_by == "executor")
    assert artifact.verification_state == RefStatus.VERIFIED
    assert context.projection_reports and context.quality_reports
    metrics = result.telemetry.summarize_task("task")
    assert metrics["evidence_projection_count"] == 1.0
    assert metrics["dsl_execution_count"] == 1.0
    assert metrics["dsl_repair_count"] == 1.0


def test_runtime_dispatcher_repairs_dsl_after_business_validator_rejection(tmp_path) -> None:
    registry, envelope, approved = _setup()
    pack = CanonicalEvidencePack(
        pack_id="pack-quality-repair",
        task_id="task",
        source_doc_hashes=("doc",),
        hard_facts=(EvidenceItem(
            item_id="revenue-q1",
            bucket="hard_fact",
            locator=TableCellLocator(
                source_doc_hash="doc", table_id="income", row_idx=1, col_idx=1,
            ),
            metadata={"structured_row": {"quarter": "2026Q1", "revenue_musd": 120.0}},
        ),),
    )
    repair_errors: list[tuple[str, ...]] = []

    def initial_program(step, grant, input_ref_id, rows) -> TransformProgram:
        del step, rows
        return TransformProgram(
            program_id="empty-result",
            input_artifact_refs=(input_ref_id,),
            output_contract_version=grant.output_contract_version,
            operations=(
                TransformStep("filter_eq", {"column": "quarter", "value": "2099Q4"}),
                TransformStep("select", {"columns": ["quarter", "revenue_musd"]}),
            ),
        )

    def repair_program(step, grant, input_ref_id, rows, validation_errors) -> TransformProgram:
        del step
        assert rows == ({"quarter": "2026Q1", "revenue_musd": 120.0},)
        repair_errors.append(validation_errors)
        return TransformProgram(
            program_id="quality-repaired",
            input_artifact_refs=(input_ref_id,),
            output_contract_version=grant.output_contract_version,
            operations=(TransformStep(
                "select", {"columns": ["quarter", "revenue_musd"]},
            ),),
        )

    def report_handler(envelope, plan, step, grant, workspace) -> AdaptiveStepResult:
        del envelope, plan, step, workspace
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            attempt_id=grant.attempt_id,
            success=True,
            output_refs=("report-ref",),
            output_ref_kinds=("execution_artifact",),
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        retrieval_adapter=AdaptiveRetrievalAdapter(lambda query, request: pack),
        retrieval_request_factory=lambda step, grant: EvidenceRequest(
            request_id="quality-repair-request",
            task_id=grant.task_id,
            step_id=step.step_id,
            queries=("ACME revenue",),
            evidence_types=("table",),
            corpus_scope_ids=("local",),
        ),
        allowed_corpus_scope_ids=("local",),
        transform_program_factory=initial_program,
        transform_program_repair_factory=repair_program,
        output_schema_by_step={
            "extract": {"quarter": "string", "revenue_musd": "number"},
        },
        builtin_handlers={"compose_cited_report_v1": report_handler},
    )
    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="dsl-quality-repair",
        task_id="task",
        canonical_task_spec_hash="spec",
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path),
        workspace_root_id="workspace",
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
    ))

    assert result.completed
    assert repair_errors == [("empty_output",)]
    assert len(context.quality_reports) == 2
    assert sum(not report.verified for report in context.quality_reports.values()) == 1
    metrics = result.telemetry.summarize_task("task")
    assert metrics["dsl_repair_count"] == 1.0
    assert metrics["dsl_quality_repair_count"] == 1.0
    assert metrics["dsl_quality_rejected_count"] == 1.0


def test_dispatcher_rejects_missing_runtime_builtin_before_handler_side_effect(tmp_path) -> None:
    registry, envelope, approved = _setup()
    context = AdaptiveDispatchContext(registry=registry)
    dispatcher = AdaptiveCapabilityDispatcher(context=context)
    report_step = approved.steps[-1]
    # The dispatcher is intentionally called directly here: no registered handler
    # means the Controller returns a failed StepResult before a builtin can run.
    from statebus.contracts import CapabilityGrant
    import time

    capability_grant = CapabilityGrant(
        grant_id="grant", task_id="task", session_id="session", step_id=report_step.step_id,
        attempt_id="attempt", capability_id=report_step.capability_id, capability_version="v1",
        input_ref_ids=("artifact",), output_contract_version=report_step.output_contract_version,
        workspace_root_id="workspace", max_runtime_ms=1_000,
        expires_at_ns=time.time_ns() + 1_000_000_000, approved_plan_hash=approved.approved_plan_hash,
    )
    outcome = dispatcher.dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=report_step,
        grant=_bound_grant(registry, capability_grant),
        attempt_workspace=tmp_path,
    )
    assert not outcome.success
    assert outcome.error_code == "runtime_builtin_handler_not_registered"


def test_runtime_owned_summarizer_validates_candidate_before_issuing_claimset_artifact(tmp_path) -> None:
    registry, envelope, approved = _setup()
    report_step = approved.steps[-1]
    payload = stable_json_dumps([{"quarter": "2026Q1", "revenue_musd": 120.0}]).encode("utf-8")
    input_path = tmp_path / "analysis.json"
    input_path.write_bytes(payload)
    artifact = ExecutionArtifactRef(
        artifact_id="analysis", task_id="task", step_id="extract", artifact_type="json",
        root_id=str(tmp_path), relpath=input_path.name, blob_hash=sha256_digest(payload),
        size_bytes=len(payload), produced_by="executor", verification_state=RefStatus.VERIFIED,
        metadata={"session_id": "session", "attempt_id": "analysis-attempt"},
    )
    locator = TableCellLocator(source_doc_hash="doc", table_id="income", row_idx=1, col_idx=1)
    pack = CanonicalEvidencePack(
        pack_id="pack", task_id="task", source_doc_hashes=("doc",),
        hard_facts=(EvidenceItem(
            item_id="revenue-q1", bucket="hard_fact", locator=locator,
            metadata={"structured_row": {"quarter": "2026Q1", "revenue_musd": 120.0}},
        ),),
    )
    grant = CapabilityGrant(
        grant_id="report-grant", task_id="task", session_id="session", step_id=report_step.step_id,
        attempt_id="attempt", capability_id=report_step.capability_id, capability_version="v1",
        input_ref_ids=("analysis", "evidence"), output_contract_version=report_step.output_contract_version,
        workspace_root_id="workspace", max_runtime_ms=1_000, expires_at_ns=time.time_ns() + 1_000_000_000,
        approved_plan_hash=approved.approved_plan_hash,
    )

    def valid_candidate(step, issued_grant, input_artifact, rows, evidence_pack) -> ClaimSet:
        assert step == report_step and issued_grant == grant and input_artifact == artifact
        assert rows == ({"quarter": "2026Q1", "revenue_musd": 120.0},)
        assert evidence_pack == pack
        return ClaimSet(
            claim_set_id="claims", task_id="task", claims=(Claim(
                claim_id="revenue-q1", claim_text="Revenue was 120.", claim_type="fact",
                supporting_evidence_item_ids=("revenue-q1",), supporting_artifact_ref_ids=("analysis",),
                citation_locators=(repr(locator),), numeric_fields={"revenue_musd": 120.0},
            ),),
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"analysis": StoredAdaptiveArtifact(
            artifact=artifact, rows=({"quarter": "2026Q1", "revenue_musd": 120.0},),
            provenance_item_ids=("revenue-q1",),
        )},
        evidence_packs={"evidence": pack},
        evidence_statuses={"evidence": EvidenceCoverageStatus.COMPLETE},
        evidence_ref_scopes={"evidence": ("session", "retrieval-attempt")},
        claim_set_factory=valid_candidate,
    )
    result = AdaptiveCapabilityDispatcher(context=context).dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=report_step,
        grant=_bound_grant(registry, grant),
        attempt_workspace=tmp_path / "report",
    )
    assert result.success
    assert len(context.claim_sets) == 1
    assert len(context.claim_validation_reports) == 1
    claim_stored = next(stored for stored in context.artifacts.values() if stored.artifact.produced_by == "summarizer")
    claim_artifact = claim_stored.artifact
    assert claim_artifact.verification_state == RefStatus.VERIFIED
    assert claim_artifact.metadata["attempt_id"] == "attempt"
    assert AdaptiveCapabilityDispatcher._read_verified_artifact_rows(claim_stored)[0]["claim_set_id"] == "claims"

    cross_session_context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"analysis": context.artifacts["analysis"]},
        evidence_packs={"evidence": pack},
        evidence_statuses={"evidence": EvidenceCoverageStatus.COMPLETE},
        evidence_ref_scopes={"evidence": ("other-session", "retrieval-attempt")},
        claim_set_factory=lambda *args: (_ for _ in ()).throw(
            AssertionError("summarizer must not run for cross-session evidence")
        ),
    )
    cross_session = AdaptiveCapabilityDispatcher(context=cross_session_context).dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=report_step,
        grant=_bound_grant(registry, grant),
        attempt_workspace=tmp_path / "cross-session",
    )
    assert not cross_session.success
    assert cross_session.error_code == "summarizer_evidence_not_verified"

    rejected_context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"analysis": context.artifacts["analysis"]},
        evidence_packs={"evidence": pack},
        evidence_statuses={"evidence": EvidenceCoverageStatus.COMPLETE},
        evidence_ref_scopes={"evidence": ("session", "retrieval-attempt")},
        claim_set_factory=lambda *args: (_ for _ in ()).throw(RuntimeError("model candidate unavailable")),
    )
    rejected = AdaptiveCapabilityDispatcher(context=rejected_context).dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=report_step,
        grant=_bound_grant(registry, grant),
        attempt_workspace=tmp_path / "rejected",
    )
    assert not rejected.success
    assert rejected.error_code == "summarizer_candidate_generation_failed:RuntimeError"
    assert not rejected_context.claim_sets


def test_runtime_rejects_dsl_program_that_changes_controller_owned_anomaly_semantics() -> None:
    semantics = {
        "operation": "detect_anomaly",
        "period_field": "quarter",
        "value_field": "on_time_delivery_pct",
        "z_threshold": 1.0,
        "baseline_output": "baseline_mean",
        "threshold_output": "threshold",
        "flag_output": "is_anomaly",
    }
    correct = TransformProgram(
        program_id="correct", input_artifact_refs=("metrics",), output_contract_version="statebus.anomaly_report.v1",
        operations=(TransformStep("anomaly_zscore", {
            "period_field": "quarter", "value_field": "on_time_delivery_pct", "z_threshold": 1.0,
        }),),
    )
    AdaptiveCapabilityDispatcher._validate_transform_semantics(correct, semantics)
    changed_threshold = TransformProgram(
        program_id="wrong-threshold", input_artifact_refs=("metrics",), output_contract_version="statebus.anomaly_report.v1",
        operations=(TransformStep("anomaly_zscore", {
            "period_field": "quarter", "value_field": "on_time_delivery_pct", "z_threshold": 1.5,
        }),),
    )
    with pytest.raises(AdaptiveDispatchError, match="transform_program_semantics_argument_mismatch:z_threshold"):
        AdaptiveCapabilityDispatcher._validate_transform_semantics(changed_threshold, semantics)
