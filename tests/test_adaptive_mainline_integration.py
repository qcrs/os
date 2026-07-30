from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityDescriptor,
    ExecutionKind,
    EvidenceRequest,
    CanonicalTaskSpec,
    PlanProposal,
    PlanStepProposal,
    RefStatus,
    ReplayClass,
    RiskClass,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.adaptive_dispatcher import StoredAdaptiveArtifact
from statebus.runtime.adaptive_mainline import (
    AdaptiveMainlineBindings,
    AdaptiveMainlineRequest,
    AdaptiveMainlineRunner,
)
from statebus.runtime.adaptive_runtime import AdaptiveStepResult
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.retrieval_adapter import AdaptiveRetrievalAdapter
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.utils import sha256_digest, stable_json_dumps


def _memory_loop_request(
    tmp_path: Path,
    *,
    task_id: str,
    value: float,
    family_memory_root: Path,
    program_calls: list[str],
    memory_policy: str = "validated_replay",
    commit_replay_class: ReplayClass = ReplayClass.VALIDATED_REPLAY,
    observed_memory_inputs: list[tuple[dict[str, object], ...]] | None = None,
) -> AdaptiveMainlineRequest:
    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        capability_id="retrieve-memory-evidence",
        owner_role="retriever",
        description="retrieve authorized evidence for a memory-loop test",
        input_ref_kinds=(),
        required_input_ref_kinds=(),
        input_contract_version="input-v1",
        output_ref_kinds=("canonical_evidence_pack",),
        output_contract_version="evidence-v1",
        execution_kind=ExecutionKind.RETRIEVAL_ADAPTER,
        side_effect_class=RiskClass.READ_ONLY,
        max_runtime_ms=20_000,
        supports_replay=False,
    ))
    registry.register(CapabilityDescriptor(
        capability_id="execute-memory-recipe",
        owner_role="executor",
        description="execute a generic verified transform recipe",
        input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
        required_input_ref_kinds=("execution_artifact",),
        input_contract_version="input-v1",
        output_ref_kinds=("execution_artifact",),
        output_contract_version="artifact-v1",
        execution_kind=ExecutionKind.TRANSFORM_DSL,
        side_effect_class=RiskClass.WORKSPACE_WRITE,
        max_runtime_ms=20_000,
        supports_replay=True,
        validator_ids=("generic_analysis",),
    ))
    spec = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="extract_metric",
        required_outputs=("value",),
        required_tools=("finance",),
        arguments={
            "ticker": "ACME",
            "quarter": "2026Q1",
            "metric": "revenue",
            "variant": task_id,
        },
    )
    envelope = AdaptiveTaskEnvelope(
        task_id=task_id,
        canonical_task_spec_hash=spec.spec_hash,
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id="memory-loop-pack",
        allowed_capability_ids=("retrieve-memory-evidence", "execute-memory-recipe"),
        allowed_output_contracts=("evidence-v1", "artifact-v1"),
        allowed_memory_policies=(memory_policy,),
        role_cardinality={"retriever": (1, 1), "executor": (1, 1)},
        max_plan_steps=2,
        max_retrieval_steps=1,
        max_total_attempts=2,
    )
    source_ref_id = f"source:{task_id}"
    proposal = PlanProposal(
        proposal_id=f"proposal:{task_id}",
        task_id=task_id,
        final_output_contract_version="artifact-v1",
        requested_memory_policy=memory_policy,
        steps=(
            PlanStepProposal(
                "retrieve",
                "retriever",
                "retrieve-memory-evidence",
                "retrieve comparable financial evidence",
                output_contract_version="evidence-v1",
            ),
            PlanStepProposal(
                "execute",
                "executor",
                "execute-memory-recipe",
                "select the current authorized value",
                depends_on=("retrieve",),
                input_ref_ids=(source_ref_id,),
                input_ref_kinds=("execution_artifact",),
                output_contract_version="artifact-v1",
            ),
        ),
    )

    source_root = tmp_path / task_id / "source"
    source_root.mkdir(parents=True)
    source_payload = stable_json_dumps([{"value": value}]).encode("utf-8")
    source_path = source_root / "input.json"
    source_path.write_bytes(source_payload)
    source_artifact = ExecutionArtifactRef(
        artifact_id=source_ref_id,
        task_id=task_id,
        step_id="source",
        artifact_type="json",
        root_id=str(source_root),
        relpath=source_path.name,
        blob_hash=sha256_digest(source_payload),
        size_bytes=len(source_payload),
        produced_by="fixture",
        verification_state=RefStatus.VERIFIED,
        replay_ready=True,
        metadata={
            "session_id": f"adaptive-session-{task_id}",
            "attempt_id": "fixture-source",
        },
    )
    pipeline = RetrieverFanoutPipeline.with_embedding_mode("deterministic")

    def retrieve_query(query: str, request: EvidenceRequest):
        return pipeline.run(
            task_id=request.task_id,
            spec=spec,
            planner_scope_payload={"query_text": query},
            enabled_evidence_types=("table",),
        )

    def program_factory(step, grant, input_ref_id, rows, memory_inputs=()):
        del rows
        program_calls.append(task_id)
        if observed_memory_inputs is not None:
            observed_memory_inputs.append(tuple(memory_inputs))
        return TransformProgram(
            program_id=f"program:{task_id}",
            input_artifact_refs=(input_ref_id,),
            operations=(TransformStep("select", {"columns": ["value"]}),),
            output_contract_version=grant.output_contract_version,
        )

    return AdaptiveMainlineRequest(
        trace_id=f"trace:{task_id}",
        task_id=task_id,
        canonical_task_spec_hash=spec.spec_hash,
        canonical_task_spec=spec,
        envelope=envelope,
        registry=registry,
        runtime_root=tmp_path / task_id / "runtime",
        workspace_root=tmp_path / task_id / "workspaces",
        memory_store_root=family_memory_root,
        memory_commit_replay_class=commit_replay_class,
        propose_plan=lambda: proposal,
        bindings=AdaptiveMainlineBindings(
            artifacts={
                source_ref_id: StoredAdaptiveArtifact(
                    artifact=source_artifact,
                    rows=({"value": value},),
                    provenance_item_ids=(f"source-value:{task_id}",),
                ),
            },
            retrieval_adapter=AdaptiveRetrievalAdapter(retrieve_query),
            retrieval_request_factory=lambda step, grant: EvidenceRequest(
                request_id=f"request:{task_id}",
                task_id=grant.task_id,
                step_id=step.step_id,
                queries=("ACME 2026Q1 revenue",),
                evidence_types=("table",),
                corpus_scope_ids=("local-financial",),
                memory_policy=memory_policy,
            ),
            allowed_corpus_scope_ids=("local-financial",),
            transform_program_factory=program_factory,
            output_schema_by_step={"execute": {"value": "number"}},
        ),
        available_input_refs={source_ref_id: "execution_artifact"},
        state_pool_mode="mmap",
    )


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
    assert memory_query.output_contract_version == "artifact-v1"
    assert memory_query.query_embedding.embedding_hash == (
        product_bundle.memory_query_embedding.embedding_hash
    )
    assert result.context.memory_match_results["retrieve"].source_ranks == {
        "keyword": (),
        "tags": (),
        "vector": (),
    }
    assert result.infrastructure.state_store.materializations == {}


def test_adaptive_memory_persists_across_fresh_runners_and_recomputes_current_values(
    tmp_path: Path,
) -> None:
    family_memory_root = tmp_path / "family-memory"
    first_program_calls: list[str] = []
    first = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="memory-task-a",
            value=11.0,
            family_memory_root=family_memory_root,
            program_calls=first_program_calls,
        ),
    )

    assert first.completed
    assert first.memory_commit_decision.committed is True
    assert first.memory_commit_decision.benchmark_gold_used is False
    assert first_program_calls == ["memory-task-a"]
    assert (family_memory_root / "commit_registry.json").is_file()

    second_program_calls: list[str] = []
    second = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="memory-task-b",
            value=22.0,
            family_memory_root=family_memory_root,
            program_calls=second_program_calls,
        ),
    )

    assert second.completed
    assert second.infrastructure.memory_store is not first.infrastructure.memory_store
    assert second_program_calls == []
    memory_result = second.context.memory_match_results["retrieve"]
    assert memory_result.candidate_pool is not None
    assert first.memory_commit_decision.memory_id in memory_result.candidate_pool.candidate_memory_ids
    assert memory_result.matches[0].replay_class == ReplayClass.VALIDATED_REPLAY
    assert second.context.memory_role_inputs_by_step["execute"][0]["ref_kind"] == "memory"
    consumption = next(
        record
        for record in second.context.memory_consumption_records
        if record.consumer_step_id == "execute"
    )
    assert consumption.memory_id == first.memory_commit_decision.memory_id
    assert consumption.recipe_recomputed is True
    assert consumption.skipped_generation_step_count == 1
    assert consumption.skipped_llm_call_count == 1
    output = next(
        stored
        for stored in second.context.artifacts.values()
        if stored.artifact.produced_by == "executor"
        and stored.artifact.step_id == "execute"
    )
    assert output.rows == ({"value": 22.0},)
    assert output.rows != next(
        stored.rows
        for stored in first.context.artifacts.values()
        if stored.artifact.produced_by == "executor"
        and stored.artifact.step_id == "execute"
    )
    metrics = second.runtime.telemetry.summarize_task("memory-task-b")
    assert metrics["memory_candidate_count"] >= 1.0
    assert metrics["memory_compatible_match_count"] >= 1.0
    assert metrics["memory_policy_approved_match_count"] >= 1.0
    assert metrics["memory_consumed_count"] >= 1.0
    assert metrics["memory_behavioral_effect_count"] >= 1.0
    assert metrics["validated_replay_count"] == 1.0
    assert metrics["skipped_step_count"] == 1.0
    assert metrics["skipped_llm_call_count"] == 1.0


def test_adaptive_memory_assist_is_an_actual_executor_input_without_skipping_validation(
    tmp_path: Path,
) -> None:
    family_memory_root = tmp_path / "assist-family-memory"
    RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="assist-task-a",
            value=31.0,
            family_memory_root=family_memory_root,
            program_calls=[],
            memory_policy="assist",
            commit_replay_class=ReplayClass.ASSIST,
        ),
    )
    observed_inputs: list[tuple[dict[str, object], ...]] = []
    second_calls: list[str] = []
    second = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="assist-task-b",
            value=42.0,
            family_memory_root=family_memory_root,
            program_calls=second_calls,
            memory_policy="assist",
            commit_replay_class=ReplayClass.ASSIST,
            observed_memory_inputs=observed_inputs,
        ),
    )

    assert second.completed
    assert second_calls == ["assist-task-b"]
    assert observed_inputs and observed_inputs[0]
    assert observed_inputs[0][0]["ref_kind"] == "memory"
    assert observed_inputs[0][0]["replay_class"] == ReplayClass.ASSIST.value
    record = next(
        item
        for item in second.context.memory_consumption_records
        if item.consumer_step_id == "execute"
    )
    assert record.behavioral_effect == "role_input_augmented"
    assert record.recipe_recomputed is False
    assert record.skipped_generation_step_count == 0
    output = next(
        stored
        for stored in second.context.artifacts.values()
        if stored.artifact.produced_by == "executor"
        and stored.artifact.step_id == "execute"
    )
    assert output.rows == ({"value": 42.0},)


def test_adaptive_memory_commit_gate_rejects_quality_report_artifact_mismatch(
    tmp_path: Path,
) -> None:
    request = _memory_loop_request(
        tmp_path,
        task_id="commit-gate-mismatch",
        value=13.0,
        family_memory_root=tmp_path / "source-memory",
        program_calls=[],
    )
    result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
    stored = next(
        item
        for item in result.context.artifacts.values()
        if item.artifact.produced_by == "executor"
        and item.artifact.step_id == "execute"
    )
    result.context.artifacts[stored.artifact.artifact_id] = replace(
        stored,
        artifact=replace(
            stored.artifact,
            metadata={
                **stored.artifact.metadata,
                "quality_report_hash": "sha256:wrong-quality-report",
            },
        ),
    )
    approved_plan = AdaptiveMainlineRunner._assemble_plan(request)[1]
    from statebus.memory import MemoryIndexStore

    rejected_store = MemoryIndexStore(store_root=tmp_path / "rejected-memory")
    decision = AdaptiveMainlineRunner._commit_verified_memory(
        request=request,
        approved_plan=approved_plan,
        runtime=result.runtime,
        context=result.context,
        memory_store=rejected_store,
    )

    assert decision.attempted is True
    assert decision.committed is False
    assert decision.reason == "terminal_quality_report_artifact_hash_mismatch"
    assert decision.benchmark_gold_used is False
    assert rejected_store.commits == {}


def test_adaptive_memory_runtime_incompatibility_stays_auditable_and_out_of_role_inputs(
    tmp_path: Path,
) -> None:
    source_memory_root = tmp_path / "source-family-memory"
    source = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="memory-source",
            value=7.0,
            family_memory_root=source_memory_root,
            program_calls=[],
        ),
    )
    original_commit = source.infrastructure.memory_store.commits[
        source.memory_commit_decision.memory_id
    ]
    original_embedding = source.infrastructure.memory_store.embeddings[
        original_commit.memory_ref.embedding_ref_id
    ]

    incompatible_root = tmp_path / "incompatible-family-memory"
    from statebus.memory import MemoryIndexStore

    seeded_store = MemoryIndexStore(store_root=incompatible_root)
    seeded_store.put_embedding(original_embedding)
    incompatible_ref = replace(
        original_commit.memory_ref,
        memory_id="memory:incompatible-runtime",
        metadata={
            **original_commit.memory_ref.metadata,
            "runtime_signature_hash": "sha256:obsolete-runtime",
        },
    )
    seeded_store.put_commit(replace(original_commit, memory_ref=incompatible_ref))

    current_program_calls: list[str] = []
    current = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="memory-current",
            value=9.0,
            family_memory_root=incompatible_root,
            program_calls=current_program_calls,
        ),
    )

    assert current.completed
    assert current_program_calls == ["memory-current"]
    memory_result = current.context.memory_match_results["retrieve"]
    assert "memory:incompatible-runtime" in memory_result.candidate_pool.candidate_memory_ids
    decision = next(
        item
        for item in memory_result.compatibility_decisions
        if item.memory_id == "memory:incompatible-runtime"
    )
    assert decision.policy_approved is False
    assert decision.replay_class == ReplayClass.DISALLOWED
    assert "runtime_signature_mismatch" in decision.reasons
    role_input_ids = {
        str(item["ref_id"])
        for inputs in current.context.memory_role_inputs_by_step.values()
        for item in inputs
    }
    assert "memory:incompatible-runtime" not in role_input_ids
    assert all(
        record.memory_id != "memory:incompatible-runtime"
        for record in current.context.memory_consumption_records
    )
    metrics = current.runtime.telemetry.summarize_task("memory-current")
    assert metrics["memory_candidate_count"] >= 1.0
    assert metrics["memory_rejected_incompatible_count"] >= 1.0
