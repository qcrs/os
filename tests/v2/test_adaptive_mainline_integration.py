from __future__ import annotations

from pathlib import Path

from v2.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityDescriptor,
    ExecutionKind,
    EvidenceRequest,
    CanonicalTaskSpec,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    WorkflowMode,
)
from v2.runtime.adaptive_mainline import AdaptiveMainlineBindings, AdaptiveMainlineRequest
from v2.runtime.adaptive_runtime import AdaptiveStepResult
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.driver import RuntimeDriver
from v2.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from v2.retrieval import RetrieverFanoutPipeline


def _mainline_request(tmp_path: Path) -> AdaptiveMainlineRequest:
    registry = CapabilityRegistry()
    descriptors = (
        ("retrieve", "retriever", (), ("canonical_evidence_pack",), "evidence-v1"),
        ("execute", "executor", ("canonical_evidence_pack",), ("execution_artifact",), "artifact-v1"),
        ("summarize", "summarizer", ("execution_artifact",), ("execution_artifact",), "report-v1"),
    )
    for capability_id, role, inputs, outputs, output_contract in descriptors:
        registry.register(CapabilityDescriptor(
            capability_id=capability_id,
            owner_role=role,
            description=f"test {role}",
            input_ref_kinds=inputs,
            required_input_ref_kinds=inputs,
            input_contract_version="input-v1",
            output_ref_kinds=outputs,
            output_contract_version=output_contract,
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=1_000,
            supports_replay=False,
        ))
    envelope = AdaptiveTaskEnvelope(
        task_id="adaptive-mainline-task",
        canonical_task_spec_hash="spec-hash",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="test-pack",
        allowed_capability_ids=("retrieve", "execute", "summarize"),
        allowed_output_contracts=("evidence-v1", "artifact-v1", "report-v1"),
        role_cardinality={"retriever": (1, 1), "executor": (1, 1), "summarizer": (1, 1)},
        max_plan_steps=3,
        max_total_attempts=3,
    )
    proposal = PlanProposal(
        proposal_id="proposal-mainline",
        task_id=envelope.task_id,
        final_output_contract_version="report-v1",
        model_id="deterministic-planner",
        raw_output_hash="planner-output-hash",
        steps=(
            PlanStepProposal("retrieve", "retriever", "retrieve", "retrieve", output_contract_version="evidence-v1"),
            PlanStepProposal("execute", "executor", "execute", "execute", depends_on=("retrieve",), output_contract_version="artifact-v1"),
            PlanStepProposal("summarize", "summarizer", "summarize", "summarize", depends_on=("execute",), output_contract_version="report-v1"),
        ),
    )

    def handler(_envelope, _plan, step, grant, _workspace):
        ref_kind = "canonical_evidence_pack" if step.role == "retriever" else "execution_artifact"
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            output_refs=(f"ref-{step.step_id}",),
            output_ref_kinds=(ref_kind,),
            attempt_id=grant.attempt_id,
        )

    return AdaptiveMainlineRequest(
        trace_id="trace-mainline",
        task_id=envelope.task_id,
        canonical_task_spec_hash=envelope.canonical_task_spec_hash,
        envelope=envelope,
        registry=registry,
        runtime_root=tmp_path / "runtime",
        workspace_root=tmp_path / "workspaces",
        propose_plan=lambda: proposal,
        bindings=AdaptiveMainlineBindings(
            builtin_handlers={descriptor[0]: handler for descriptor in descriptors},
        ),
        planner_model_id="deterministic-planner",
        planner_raw_output_hash="planner-output-hash",
    )


def test_product_adaptive_mainline_owns_runtime_infrastructure_and_role_records(tmp_path: Path) -> None:
    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_mainline_request(tmp_path),
    )

    assert result.completed
    assert result.planner.approved_plan_hash == result.runtime.approved_plan_hash
    assert [step.role for step in result.runtime.session.workflow_steps] == [
        "retriever",
        "executor",
        "summarizer",
    ]
    assert result.infrastructure.state_store.root == tmp_path / "runtime" / "state"
    assert result.infrastructure.memory_store.store_root == tmp_path / "runtime" / "memory_index"
    assert result.infrastructure.workspace_layout.root == tmp_path / "workspaces" / "adaptive-mainline-task"
    assert result.infrastructure.socket_path == tmp_path / "runtime" / "control.sock"
    assert result.manifest_path.is_file()
    assert result.state_cleanup_completed
    metrics = result.runtime.telemetry.summarize_task("adaptive-mainline-task")
    assert metrics["planner_step_completed"] == 1.0
    assert metrics["planner_final_approved_count"] == 1.0
    assert metrics["adaptive_step_completed"] == 3.0


def test_runtime_mode_selector_requires_the_matching_product_request() -> None:
    driver = RuntimeDriver()

    for mode, error in (
        ("strict_fixed", "strict_fixed_runtime_input_required"),
        ("adaptive_bounded", "adaptive_bounded_request_required"),
        ("adaptive_shadow", "adaptive_shadow_inputs_required"),
    ):
        try:
            driver.run_mode(mode)
        except ValueError as exc:
            assert str(exc) == error
        else:
            raise AssertionError(f"{mode} accepted missing request")


def test_adaptive_product_retrieval_owns_cross_process_semantic_state(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    for descriptor in (
        CapabilityDescriptor(
            capability_id="retrieve-semantic",
            owner_role="retriever",
            description="retrieve semantic evidence",
            input_ref_kinds=(),
            required_input_ref_kinds=(),
            input_contract_version="input-v1",
            output_ref_kinds=("canonical_evidence_pack",),
            output_contract_version="evidence-v1",
            execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
            side_effect_class=RiskClass.READ_ONLY,
            max_runtime_ms=20_000,
            supports_replay=False,
        ),
        CapabilityDescriptor(
            capability_id="execute-builtin",
            owner_role="executor",
            description="consume evidence",
            input_ref_kinds=("canonical_evidence_pack",),
            required_input_ref_kinds=("canonical_evidence_pack",),
            input_contract_version="evidence-v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="artifact-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=1_000,
            supports_replay=False,
        ),
        CapabilityDescriptor(
            capability_id="summarize-builtin",
            owner_role="summarizer",
            description="summarize artifact",
            input_ref_kinds=("execution_artifact",),
            required_input_ref_kinds=("execution_artifact",),
            input_contract_version="artifact-v1",
            output_ref_kinds=("execution_artifact",),
            output_contract_version="report-v1",
            execution_kind=ExecutionKind.RUNTIME_BUILTIN,
            side_effect_class=RiskClass.WORKSPACE_WRITE,
            max_runtime_ms=1_000,
            supports_replay=False,
        ),
    ):
        registry.register(descriptor)
    envelope = AdaptiveTaskEnvelope(
        task_id="adaptive-semantic-task",
        canonical_task_spec_hash="sha256:adaptive-semantic-spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="test-pack",
        allowed_capability_ids=(
            "retrieve-semantic",
            "execute-builtin",
            "summarize-builtin",
        ),
        allowed_output_contracts=("evidence-v1", "artifact-v1", "report-v1"),
        role_cardinality={"retriever": (1, 1), "executor": (1, 1), "summarizer": (1, 1)},
        max_plan_steps=3,
        max_total_attempts=3,
    )
    proposal = PlanProposal(
        proposal_id="proposal-semantic-mainline",
        task_id=envelope.task_id,
        final_output_contract_version="report-v1",
        steps=(
            PlanStepProposal(
                "retrieve",
                "retriever",
                "retrieve-semantic",
                "retrieve semantic evidence",
                output_contract_version="evidence-v1",
            ),
            PlanStepProposal(
                "execute",
                "executor",
                "execute-builtin",
                "consume selected evidence",
                depends_on=("retrieve",),
                output_contract_version="artifact-v1",
            ),
            PlanStepProposal(
                "summarize",
                "summarizer",
                "summarize-builtin",
                "summarize output",
                depends_on=("execute",),
                output_contract_version="report-v1",
            ),
        ),
    )
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")
    observed_retrieval = {}
    spec = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        required_tools=("finance",),
        arguments={"ticker": "ACME", "quarter": "2026Q1"},
    )

    def retrieve_query(query: str, request: EvidenceRequest):
        return pipeline.run(
            task_id=request.task_id,
            spec=spec,
            planner_scope_payload={"query_text": query},
            enabled_evidence_types=tuple(request.evidence_types),
        )

    def request_factory(step, grant):
        return EvidenceRequest(
            request_id=f"request-{grant.attempt_id}",
            task_id=grant.task_id,
            step_id=step.step_id,
            queries=("ACME revenue increased",),
            evidence_types=("semantic_context",),
            corpus_scope_ids=("local-financial",),
            memory_policy="none",
        )

    def observe_retrieval(retrieval_result, _step, _grant):
        observed_retrieval["result"] = retrieval_result
        return ()

    def builtin_handler(_envelope, _plan, step, grant, _workspace):
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(f"artifact-{step.step_id}",),
            output_ref_kinds=("execution_artifact",),
        )

    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=AdaptiveMainlineRequest(
            trace_id="trace-adaptive-semantic",
            task_id=envelope.task_id,
            canonical_task_spec_hash=envelope.canonical_task_spec_hash,
            envelope=envelope,
            registry=registry,
            runtime_root=tmp_path / "runtime",
            workspace_root=tmp_path / "workspaces",
            propose_plan=lambda: proposal,
            bindings=AdaptiveMainlineBindings(
                retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
                retrieval_request_factory=request_factory,
                retrieval_result_observer=observe_retrieval,
                allowed_corpus_scope_ids=("local-financial",),
                builtin_handlers={
                    "execute-builtin": builtin_handler,
                    "summarize-builtin": builtin_handler,
                },
            ),
            state_pool_mode="shared_memory",
        ),
    )

    event_types = [event.event_type for event in result.runtime.telemetry.events]
    assert result.completed
    assert event_types.count("STATE_PUBLISHED") == 1
    assert event_types.count("STATE_RESOLVED") == 1
    assert event_types.count("STATE_CONSUMED") == 1
    assert event_types.count("STATE_RELEASED") == 1
    assert len(result.context.state_consumption_records) == 1
    assert result.context.state_consumption_records[0].consumer_role == "executor"
    product_bundle = observed_retrieval["result"].retrieval_bundles[0]
    publication = next(iter(result.context.semantic_state_publications.values()))
    selection = next(iter(result.context.semantic_state_selections.values()))
    assert publication.contract.shape[0] == len(product_bundle.semantic_candidate_embeddings) + 1
    assert len(product_bundle.semantic_candidate_embeddings) > len(
        product_bundle.evidence_pack.semantic_contexts
    )
    assert selection.selected_candidate_ids == tuple(
        item.item_id for item in product_bundle.evidence_pack.semantic_contexts
    )
    metrics = result.runtime.telemetry.summarize_task("adaptive-semantic-task")
    assert metrics["hybrid_memory_query_count"] == 1.0
    assert metrics["embedding_encode_count"] == float(publication.contract.shape[0])
    assert metrics["raw_evidence_bytes_seen_by_llm"] > 0.0
    assert len(result.context.memory_queries_by_task) == 1
    memory_query = result.context.memory_queries_by_task["adaptive-semantic-task"]
    assert memory_query.compatibility_signature == registry.digest
    assert memory_query.output_contract_version == "report-v1"
    assert memory_query.query_embedding.embedding_hash == (
        product_bundle.memory_query_embedding.embedding_hash
    )
    assert result.context.memory_match_results["retrieve"].source_ranks == {
        "keyword": (),
        "tags": (),
        "vector": (),
    }
    assert result.infrastructure.state_store.materializations == {}
