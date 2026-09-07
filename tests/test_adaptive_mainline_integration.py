from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

import statebus.control as control_plane
from statebus.control import AckReceived, ErrorResult, Heartbeat, RunStart, SuccessResult
from statebus.contracts import (
    AdaptiveTaskEnvelope,
    ArtifactVerificationDecision,
    ArtifactVerificationReceipt,
    CapabilityDescriptor,
    ExecutionKind,
    EvidenceRequest,
    CanonicalTaskSpec,
    PlanProposal,
    PlanStepProposal,
    RefStatus,
    ReplayClass,
    RiskClass,
    RuntimeIdentity,
    TaskContractIdentity,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from statebus.runtime import adaptive_dispatcher as adaptive_dispatcher_module
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.adaptive_dispatcher import StoredAdaptiveArtifact
from statebus.runtime.adaptive_mainline import (
    AdaptiveMainlineBindings,
    AdaptiveMainlineError,
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
    runtime_identity = RuntimeIdentity(
        runtime_task_id=task_id,
        run_id=f"run-{task_id}",
        session_id=f"adaptive-session-{task_id}",
        trace_id=f"trace:{task_id}",
        task_contract=TaskContractIdentity.from_hash(spec.spec_hash),
    )
    source_grant_hash = sha256_digest({
        "artifact_id": source_ref_id,
        "producer_step_id": "source",
        "producer_attempt_id": "fixture-source",
    })
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
        replay_ready=False,
        metadata={
            "session_id": runtime_identity.session_id,
            "attempt_id": "fixture-source",
            "grant_hash": source_grant_hash,
        },
    )
    source_receipt = ArtifactVerificationReceipt(
        artifact_id=source_ref_id,
        runtime_task_id=task_id,
        run_id=runtime_identity.run_id,
        session_id=runtime_identity.session_id,
        producer_step_id="source",
        producer_attempt_id="fixture-source",
        execution_binding_hash=sha256_digest("fixture-source-binding"),
        capability_grant_hash=source_grant_hash,
        candidate_blob_hash=source_artifact.blob_hash,
        candidate_size_bytes=source_artifact.size_bytes,
        validator_ids=(),
        validator_report_hashes=(),
        decision=ArtifactVerificationDecision.VERIFIED,
        reason="fixture_receipt_backed_source",
    )
    source_artifact = replace(
        source_artifact,
        metadata={
            **source_artifact.metadata,
            "artifact_verification_receipt_hash": source_receipt.receipt_hash,
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
        runtime_identity=runtime_identity,
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
            artifact_verification_receipts={source_ref_id: source_receipt},
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
    assert result.runtime_identity is not None
    assert result.runtime_identity.runtime_task_id == "adaptive-mainline-task"
    assert result.runtime_identity.session_id == "adaptive-session-adaptive-mainline-task"
    assert result.approved_plan_bundle is not None
    assert result.approved_plan_bundle.verify_hash_links()
    assert result.planner.normalization_receipt is not None


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


def test_plan_source_has_no_attempt_factory(tmp_path: Path) -> None:
    request = _mainline_request(tmp_path)
    proposal = replace(
        request.propose_plan(),
        proposal_id="plan-source-requested-attempt-999",
        planner_notes="attempt_id=plan-source-attempt-999",
    )

    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=replace(request, propose_plan=lambda: proposal),
    )

    assert result.completed
    assert [record.attempt_id for record in result.runtime.session.attempt_records] == [
        "adaptive-attempt-1",
        "adaptive-attempt-2",
        "adaptive-attempt-3",
    ]
    assert all(
        record.attempt_id != "plan-source-attempt-999"
        for record in result.runtime.session.attempt_records
    )


def test_mainline_rejects_envelope_identity_mismatch(tmp_path: Path) -> None:
    request = _mainline_request(tmp_path)
    identity = RuntimeIdentity(
        runtime_task_id=request.task_id,
        run_id="run-explicit",
        session_id="session-explicit",
        trace_id=request.trace_id,
        task_contract=TaskContractIdentity.from_hash(request.canonical_task_spec_hash),
    )
    mismatched_envelope = replace(
        request.envelope,
        canonical_task_spec_hash="sha256:other-contract",
    )

    with pytest.raises(AdaptiveMainlineError, match="adaptive_mainline_identity_invalid"):
        AdaptiveMainlineRunner().run(
            replace(
                request,
                envelope=mismatched_envelope,
                runtime_identity=identity,
            )
        )


def test_mainline_identity_separates_reruns_without_changing_logical_task(tmp_path: Path) -> None:
    base = _mainline_request(tmp_path)
    contract = TaskContractIdentity.from_hash(base.canonical_task_spec_hash)
    first_identity = RuntimeIdentity(
        external_case_id="benchmark-case-7",
        runtime_task_id=base.task_id,
        run_id="run-1",
        session_id="session-1",
        trace_id="trace-run-1",
        task_contract=contract,
    )
    second_identity = RuntimeIdentity(
        external_case_id="benchmark-case-7",
        runtime_task_id=base.task_id,
        run_id="run-2",
        session_id="session-2",
        trace_id="trace-run-2",
        task_contract=contract,
    )

    first = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=replace(
            base,
            trace_id="trace-run-1",
            runtime_root=tmp_path / "run-1" / "runtime",
            workspace_root=tmp_path / "run-1" / "workspaces",
            runtime_identity=first_identity,
        ),
    )
    second = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=replace(
            base,
            trace_id="trace-run-2",
            runtime_root=tmp_path / "run-2" / "runtime",
            workspace_root=tmp_path / "run-2" / "workspaces",
            runtime_identity=second_identity,
        ),
    )

    assert first.completed and second.completed
    assert first.runtime_identity is not None and second.runtime_identity is not None
    assert first.runtime_identity.runtime_task_id == second.runtime_identity.runtime_task_id == base.task_id
    assert first.runtime_identity.task_contract == second.runtime_identity.task_contract == contract
    assert first.runtime_identity.run_id != second.runtime_identity.run_id
    assert first.runtime_identity.session_id != second.runtime_identity.session_id
    assert first.planner.approved_plan_hash == second.planner.approved_plan_hash
    assert first.runtime.session.session_id == "session-1"
    assert second.runtime.session.session_id == "session-2"
    assert first.runtime.session.task_id == second.runtime.session.task_id == base.task_id
    first_attempts = {record.attempt_id for record in first.runtime.session.attempt_records}
    second_attempts = {record.attempt_id for record in second.runtime.session.attempt_records}
    assert first_attempts and second_attempts and first_attempts.isdisjoint(second_attempts)
    assert all(attempt.startswith("adaptive-attempt-run-1-") for attempt in first_attempts)
    assert all(attempt.startswith("adaptive-attempt-run-2-") for attempt in second_attempts)

    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert first_manifest["runtime_identity"]["run_id"] == "run-1"
    assert second_manifest["runtime_identity"]["run_id"] == "run-2"
    assert first_manifest["runtime_identity"]["runtime_task_id"] == second_manifest["runtime_identity"]["runtime_task_id"]


def test_mainline_repair_cannot_replace_semantic_graph_as_schema_repair(tmp_path: Path) -> None:
    request = _mainline_request(tmp_path)
    raw = replace(
        request.propose_plan(),
        steps=(
            replace(request.propose_plan().steps[0], capability_id="unauthorized-capability"),
            *request.propose_plan().steps[1:],
        ),
    )

    with pytest.raises(AdaptiveMainlineError, match="semantic_replan_required"):
        AdaptiveMainlineRunner().run(
            replace(
                request,
                propose_plan=lambda: raw,
                repair_plan=lambda _proposal, _report, _fields: request.propose_plan(),
            )
        )


def test_mainline_schema_repair_records_exact_normalization_provenance(tmp_path: Path) -> None:
    request = _mainline_request(tmp_path)
    valid = request.propose_plan()
    raw = replace(valid, schema_version="statebus.plan_proposal.invalid")

    result = AdaptiveMainlineRunner().run(
        replace(
            request,
            propose_plan=lambda: raw,
            repair_plan=lambda _proposal, _report, _fields: valid,
        )
    )

    assert result.completed
    assert result.planner.policy_repair_used
    assert not result.planner.semantic_replan_required
    assert not result.planner.fallback_used
    assert result.planner.normalization_receipt is not None
    receipt = result.planner.normalization_receipt
    assert receipt.source_proposal_hash == raw.proposal_hash
    assert receipt.effective_proposal_hash == valid.proposal_hash
    assert receipt.before_semantic_hash == receipt.after_semantic_hash
    assert "schema_version" in receipt.changed_fields
    assert "schema_version" in result.planner.schema_repair_fields
    assert result.approved_plan_bundle is not None
    assert result.approved_plan_bundle.verify_hash_links()


def test_mainline_records_fallback_as_policy_fallback_provenance(tmp_path: Path) -> None:
    request = _mainline_request(tmp_path)
    fallback = request.propose_plan()
    raw = replace(
        fallback,
        proposal_id="rejected-mainline-proposal",
        steps=(
            replace(fallback.steps[0], capability_id="unauthorized-capability"),
            *fallback.steps[1:],
        ),
    )

    result = AdaptiveMainlineRunner().run(
        replace(
            request,
            propose_plan=lambda: raw,
            repair_plan=lambda _proposal, _report, _fields: fallback,
            fallback_proposal=fallback,
        )
    )

    assert result.completed
    assert result.planner.semantic_replan_required
    assert result.planner.fallback_used
    assert not result.planner.policy_repair_used
    assert result.planner.fallback_proposal_hash == fallback.proposal_hash
    assert result.planner.approved_plan_bundle is not None
    bundle = result.planner.approved_plan_bundle
    assert bundle.verify_hash_links()
    assert bundle.fallback_used
    assert bundle.plan_policy_report is not None
    assert bundle.plan_policy_report.status.value == "fallback_fixed_plan"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["approved_plan_bundle"]["fallback_used"] is True
    assert manifest["planner"]["semantic_replan_required"] is True


def test_mainline_normalizer_rejects_semantic_mutation(tmp_path: Path) -> None:
    request = _mainline_request(tmp_path)

    with pytest.raises(AdaptiveMainlineError, match="normalization_semantic_change"):
        AdaptiveMainlineRunner().run(
            replace(
                request,
                normalize_plan=lambda proposal: replace(
                    proposal,
                    requested_memory_policy="assist",
                ),
            )
        )


def test_adaptive_product_retrieval_owns_cross_process_semantic_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    runtime_identity = RuntimeIdentity(
        runtime_task_id=envelope.task_id,
        run_id="run-adaptive-semantic",
        session_id="session-adaptive-semantic",
        trace_id="trace-adaptive-semantic",
        task_contract=TaskContractIdentity.from_hash(
            envelope.canonical_task_spec_hash
        ),
    )
    observed_physical: dict[str, object] = {}
    original_transport = control_plane.SubprocessExecutorTransport

    class ObservingSubprocessExecutorTransport(original_transport):
        def execute(self, request, **kwargs):
            responses = self.exchange_sequence(request, **kwargs)
            observed_physical["request"] = request
            observed_physical["responses"] = tuple(responses)
            observed_physical["audit"] = self.last_exchange_audit
            observed_physical["admission_receipts"] = self.last_admission_receipts
            return next(
                response
                for response in responses
                if isinstance(response, (SuccessResult, ErrorResult))
            )

    monkeypatch.setattr(
        control_plane,
        "SubprocessExecutorTransport",
        ObservingSubprocessExecutorTransport,
    )
    monkeypatch.setattr(
        adaptive_dispatcher_module,
        "uuid4",
        lambda: UUID("12345678-1234-5678-1234-567812345678"),
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
            runtime_identity=runtime_identity,
        ),
    )

    physical_request = observed_physical["request"]
    physical_responses = observed_physical["responses"]
    physical_audit = observed_physical["audit"]
    admission_receipts = observed_physical["admission_receipts"]
    assert physical_audit is not None
    assert physical_audit.carrier == "typed_protobuf"
    assert physical_audit.backend == "uds_subprocess"
    assert physical_audit.driver_pid != physical_audit.worker_pid
    assert [type(message) for message in physical_responses] == [
        AckReceived,
        RunStart,
        Heartbeat,
        SuccessResult,
    ]

    def invocation_scope(header):
        return {
            "trace_id": header.trace_id,
            "task_id": header.task_id,
            "run_id": header.run_id,
            "session_id": header.session_id,
            "step_id": header.step_id,
            "attempt_id": header.attempt_id,
            "invocation_id": header.invocation_id,
            "execution_binding_hash": header.execution_binding_hash,
            "capability_grant_hash": header.capability_grant_hash,
            "schema_version": header.schema_version,
        }

    expected_scope = invocation_scope(physical_request.header)
    assert expected_scope["trace_id"] == runtime_identity.trace_id
    assert expected_scope["task_id"] == runtime_identity.runtime_task_id
    assert expected_scope["run_id"] == runtime_identity.run_id
    assert expected_scope["session_id"] == runtime_identity.session_id
    assert expected_scope["invocation_id"] == (
        "invocation-12345678123456781234567812345678"
    )
    assert expected_scope["execution_binding_hash"] == (
        result.runtime.execution_bindings[0].binding_hash
    )
    assert expected_scope["capability_grant_hash"] == (
        result.runtime.bound_grants[0].grant.grant_hash
    )
    assert expected_scope["capability_grant_hash"] == (
        physical_request.capability_grant_hash
    )
    assert physical_request.consumer_provider_id == (
        result.runtime.execution_bindings[0].selected_provider_id
    )
    assert len(physical_request.state_access_grants) == 1
    worker_access_grant = physical_request.state_access_grants[0]
    assert worker_access_grant.attempt_id == expected_scope["attempt_id"]
    assert worker_access_grant.execution_binding_hash == expected_scope["execution_binding_hash"]
    assert worker_access_grant.capability_grant_hash == expected_scope["capability_grant_hash"]
    assert worker_access_grant.physical_invocation_id == expected_scope["invocation_id"]
    assert worker_access_grant.consumer_provider_id == physical_request.consumer_provider_id
    assert worker_access_grant.consumer_role == physical_request.header.target_role
    assert worker_access_grant.authority_basis == "RUNTIME_INTERMEDIATE"
    assert worker_access_grant.access_mode == "READ"
    assert all(
        invocation_scope(message.header) == expected_scope
        for message in physical_responses
    )
    assert len(admission_receipts) == len(physical_responses)
    assert all(receipt.admitted for receipt in admission_receipts)
    assert all(receipt.origin.value == "NATIVE_TYPED_WORKER" for receipt in admission_receipts)
    assert [receipt.terminal_count for receipt in admission_receipts] == [0, 0, 0, 1]
    assert admission_receipts[-1].output_contract_decision == "matched"

    physical_observations = result.context.physical_lifecycle_observations
    assert [observation["event_type"] for observation in physical_observations] == [
        "ACK_RECV",
        "RUN_START",
        "HEARTBEAT",
        "RES_SUCC",
    ]
    assert all(
        observation["origin"] == "NATIVE_TYPED_WORKER"
        and observation["runtime_origin"] == "WORKER_OBSERVED"
        and observation["outer_semantic_step_mutated"] is False
        for observation in physical_observations
    )
    retrieve_step = next(
        step for step in result.runtime.session.workflow_steps if step.step_id == "retrieve"
    )
    assert retrieve_step.lifecycle_origin == "LOCAL_RUNTIME"
    outer_retrieve_events = [
        event
        for event in result.runtime.telemetry.events
        if event.step_id == "retrieve"
    ]
    assert not any(event.event_type == "STEP_ACKED" for event in outer_retrieve_events)
    assert all(
        event.payload.get("origin") != "WORKER_OBSERVED"
        for event in outer_retrieve_events
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
    issued_access_grants = result.context.state_access_grants[publication.ref.state_id]
    assert issued_access_grants[0] == worker_access_grant
    assert issued_access_grants[0].state_identity_hash == publication.ref.state_identity_hash
    assert issued_access_grants[1].state_identity_hash == publication.ref.state_identity_hash
    assert issued_access_grants[1].consumer_role == "runtime"
    assert issued_access_grants[1].physical_invocation_id == ""
    assert all(
        access.expires_at_ns <= result.runtime.bound_grants[0].grant.expires_at_ns
        for access in issued_access_grants
    )
    recorded_admission = next(iter(result.context.control_response_admissions.values()))
    assert recorded_admission == admission_receipts
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
    lifetime = result.infrastructure.state_store.lifetimes[publication.ref.state_id]
    assert lifetime.owner_session_id == runtime_identity.session_id
    assert lifetime.producer_step_id == "retrieve"
    assert lifetime.producer_attempt_id == worker_access_grant.attempt_id
    assert lifetime.owner_released
    assert lifetime.live_pin_count == 0
    assert lifetime.physical_reclaimed
    assert {
        pin.consumer_role for pin in lifetime.released_pins.values()
    } == {"executor", "runtime"}
    assert result.infrastructure.state_store.materializations == {}
    (tmp_path / "real_subprocess_scope.txt").write_text(
        json.dumps(
            {
                "mechanism": "UDS -> protobuf -> real subprocess_worker",
                "carrier": physical_audit.carrier,
                "backend": physical_audit.backend,
                "driver_pid": physical_audit.driver_pid,
                "worker_pid": physical_audit.worker_pid,
                "driver_worker_pid_distinct": (
                    physical_audit.driver_pid != physical_audit.worker_pid
                ),
                "request_scope": expected_scope,
                "responses": [
                    {
                        "message_type": type(message).__name__,
                        "event_type": message.header.event_type.name,
                        "scope": invocation_scope(message.header),
                    }
                    for message in physical_responses
                ],
                "all_response_scopes_equal_request": all(
                    invocation_scope(message.header) == expected_scope
                    for message in physical_responses
                ),
                "canonical_semantic_execution_completed": result.completed,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


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


def test_adaptive_memory_commit_gate_requires_runtime_verification_receipt(
    tmp_path: Path,
) -> None:
    request = _memory_loop_request(
        tmp_path,
        task_id="commit-gate-receipt",
        value=17.0,
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
    receipt = result.context.artifact_verification_receipts.pop(stored.artifact.artifact_id)
    approved_plan = AdaptiveMainlineRunner._assemble_plan(request)[1]
    from statebus.memory import MemoryIndexStore

    rejected_store = MemoryIndexStore(store_root=tmp_path / "receipt-missing-memory")
    rejected = AdaptiveMainlineRunner._commit_verified_memory(
        request=request,
        approved_plan=approved_plan,
        runtime=result.runtime,
        context=result.context,
        memory_store=rejected_store,
    )
    assert rejected.attempted is True
    assert rejected.committed is False
    assert rejected.reason == "terminal_executor_artifact_runtime_receipt_mismatch"
    assert rejected_store.commits == {}

    result.context.artifact_verification_receipts[stored.artifact.artifact_id] = receipt
    accepted_store = MemoryIndexStore(store_root=tmp_path / "receipt-backed-memory")
    accepted = AdaptiveMainlineRunner._commit_verified_memory(
        request=request,
        approved_plan=approved_plan,
        runtime=result.runtime,
        context=result.context,
        memory_store=accepted_store,
    )
    assert accepted.attempted is True
    assert accepted.committed is True
    assert accepted.reason == "runtime_quality_and_artifact_hash_verified"


def test_mrr_09a_verified_artifact_does_not_imply_memory_admission(tmp_path: Path) -> None:
    request = replace(
        _memory_loop_request(
            tmp_path,
            task_id="verified-only",
            value=19.0,
            family_memory_root=tmp_path / "verified-only-memory",
            program_calls=[],
        ),
        memory_commit_enabled=False,
    )
    result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)

    executor_artifact = next(
        item.artifact
        for item in result.context.artifacts.values()
        if item.artifact.produced_by == "executor" and item.artifact.step_id == "execute"
    )
    assert executor_artifact.verification_state is RefStatus.VERIFIED
    assert executor_artifact.artifact_id in result.context.artifact_verification_receipts
    assert result.memory_commit_decision.reason == "memory_commit_disabled"
    assert result.infrastructure.memory_store.commits == {}
    assert result.infrastructure.memory_store.admission_receipts == {}


def test_mrr_09a_runtime_admission_persists_exact_receipt_binding(tmp_path: Path) -> None:
    from statebus.memory import MemoryIndexStore

    memory_root = tmp_path / "admitted-memory"
    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="admitted-task",
            value=23.0,
            family_memory_root=memory_root,
            program_calls=[],
        ),
    )

    memory_id = result.memory_commit_decision.memory_id
    commit = result.infrastructure.memory_store.commits[memory_id]
    admission = result.infrastructure.memory_store.admission_receipts[memory_id]
    artifact_receipt = result.context.artifact_verification_receipts[admission.source_artifact_id]
    executor_artifact = result.context.artifacts[admission.source_artifact_id].artifact
    assert admission.memory_commit_hash == commit.commit_hash
    assert admission.memory_type == commit.memory_ref.memory_type.value
    assert admission.source_artifact_id == commit.memory_ref.artifact_ref_id
    assert admission.source_artifact_blob_hash == commit.created_from_artifact_hash
    assert admission.artifact_verification_receipt_hash == artifact_receipt.receipt_hash
    assert admission.runtime_semantic_commit_receipt_hash
    assert admission.runtime_semantic_commit_receipt_hash == (
        next(
            receipt
            for receipt in result.runtime.attempt_result_admissions
            if receipt.step_id == artifact_receipt.producer_step_id
            and receipt.observed_attempt_id == artifact_receipt.producer_attempt_id
        ).receipt_hash
    )
    assert executor_artifact.metadata["attempt_result_admission_receipt_hash"] == (
        admission.runtime_semantic_commit_receipt_hash
    )
    assert commit.memory_ref.metadata["runtime_semantic_commit_receipt_hash"] == (
        admission.runtime_semantic_commit_receipt_hash
    )
    assert admission.decision.value == "ADMITTED"
    assert commit.memory_ref.metadata["replay_ready"] is False
    assert result.memory_commit_decision.memory_admission_receipt_hash == admission.receipt_hash

    restored = MemoryIndexStore(store_root=memory_root)
    restored.load_persisted_state()
    restored_commit = restored.commits[memory_id]
    restored_admission = restored.admission_receipts[memory_id]
    assert restored_commit.commit_hash == commit.commit_hash
    assert restored_admission.canonical_payload() == admission.canonical_payload()
    assert restored._is_admitted(restored_commit)
    same_commit, same_receipt = restored.persist_admitted(
        commit=restored_commit,
        admission_receipt=restored_admission,
    )
    assert same_commit.commit_hash == restored_commit.commit_hash
    assert same_receipt.receipt_hash == restored_admission.receipt_hash


def test_mrr_09a_corrective_runtime_witness_survives_settlement(
    tmp_path: Path,
) -> None:
    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="corrective-authorized",
            value=31.0,
            family_memory_root=tmp_path / "corrective-authorized-memory",
            program_calls=[],
        ),
    )

    assert result.runtime.completed is True
    assert result.memory_commit_decision.committed is True
    assert result.runtime.attempt_result_admissions
    assert all(
        receipt.commit_authorized
        for receipt in result.runtime.attempt_result_admissions
    )
    assert all(
        result.runtime.session.active_attempt_id(receipt.step_id) is None
        for receipt in result.runtime.attempt_result_admissions
    )


def test_mrr_09a_corrective_verified_receipt_alone_cannot_admit(
    tmp_path: Path,
) -> None:
    from statebus.memory import MemoryIndexStore

    request = _memory_loop_request(
        tmp_path,
        task_id="corrective-missing-witness",
        value=37.0,
        family_memory_root=tmp_path / "source-corrective-missing-witness",
        program_calls=[],
    )
    result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
    runtime_without_witness = replace(result.runtime, attempt_result_admissions=())
    rejected_store = MemoryIndexStore(store_root=tmp_path / "rejected-corrective-missing-witness")

    decision = AdaptiveMainlineRunner._commit_verified_memory(
        request=request,
        approved_plan=AdaptiveMainlineRunner._assemble_plan(request)[1],
        runtime=runtime_without_witness,
        context=result.context,
        memory_store=rejected_store,
    )

    assert decision.attempted is True
    assert decision.committed is False
    assert decision.reason == "terminal_executor_runtime_commit_witness_mismatch"
    assert rejected_store.commits == {}
    assert rejected_store.admission_receipts == {}


def test_mrr_09a_corrective_mismatched_runtime_witness_cannot_admit(
    tmp_path: Path,
) -> None:
    from statebus.memory import MemoryIndexStore

    source = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path / "source",
            task_id="corrective-witness-source",
            value=41.0,
            family_memory_root=tmp_path / "source-memory",
            program_calls=[],
        ),
    )
    target_request = _memory_loop_request(
        tmp_path / "target",
        task_id="corrective-witness-target",
        value=43.0,
        family_memory_root=tmp_path / "target-memory",
        program_calls=[],
    )
    target = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=target_request)
    target_executor = next(
        item.artifact
        for item in target.context.artifacts.values()
        if item.artifact.produced_by == "executor" and item.artifact.step_id == "execute"
    )
    source_witness = next(
        receipt
        for receipt in source.runtime.attempt_result_admissions
        if receipt.step_id == "execute"
    )
    mismatched_runtime = replace(
        target.runtime,
        attempt_result_admissions=(source_witness,),
    )
    rejected_store = MemoryIndexStore(store_root=tmp_path / "rejected-corrective-mismatch")

    decision = AdaptiveMainlineRunner._commit_verified_memory(
        request=target_request,
        approved_plan=AdaptiveMainlineRunner._assemble_plan(target_request)[1],
        runtime=mismatched_runtime,
        context=target.context,
        memory_store=rejected_store,
    )

    assert target_executor.verification_state is RefStatus.VERIFIED
    assert decision.attempted is True
    assert decision.committed is False
    assert decision.reason == "terminal_executor_runtime_commit_witness_mismatch"
    assert rejected_store.commits == {}
    assert rejected_store.admission_receipts == {}


def test_mrr_09a_corrective_pass2_runtime_binds_exact_memory_projection(
    tmp_path: Path,
) -> None:
    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="corrective-pass2-authorized",
            value=47.0,
            family_memory_root=tmp_path / "corrective-pass2-memory",
            program_calls=[],
        ),
    )

    memory_id = result.memory_commit_decision.memory_id
    commit = result.infrastructure.memory_store.commits[memory_id]
    admission = result.infrastructure.memory_store.admission_receipts[memory_id]
    binding = next(
        item
        for item in result.runtime.memory_projection_bindings
        if item.source_artifact_id == admission.source_artifact_id
    )
    assert result.runtime.session.active_attempt_id("execute") is None
    assert binding.expected_memory_commit_hash == commit.commit_hash
    assert binding.runtime_semantic_commit_receipt_hash == (
        admission.runtime_semantic_commit_receipt_hash
    )
    assert binding.artifact_verification_receipt_hash == (
        admission.artifact_verification_receipt_hash
    )
    assert admission.memory_projection_binding_hash == binding.binding_hash
    assert binding.projection_spec.created_at_ns == commit.memory_ref.created_at_ns


def test_mrr_09a_corrective_pass2_fresh_store_rejects_modified_projection(
    tmp_path: Path,
) -> None:
    from statebus.memory import MemoryIndexStore

    request = _memory_loop_request(
        tmp_path,
        task_id="corrective-pass2-tamper",
        value=53.0,
        family_memory_root=tmp_path / "corrective-pass2-source-memory",
        program_calls=[],
    )
    result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
    artifact_id = result.memory_commit_decision.artifact_ref_id
    original_recipe = result.context.execution_recipes_by_artifact[artifact_id]
    result.context.execution_recipes_by_artifact[artifact_id] = {
        **original_recipe,
        "tampered_projection": True,
    }
    rejected_store = MemoryIndexStore(store_root=tmp_path / "corrective-pass2-fresh-store")

    decision = AdaptiveMainlineRunner._commit_verified_memory(
        request=request,
        approved_plan=AdaptiveMainlineRunner._assemble_plan(request)[1],
        runtime=result.runtime,
        context=result.context,
        memory_store=rejected_store,
    )

    assert decision.attempted is True
    assert decision.committed is False
    assert decision.reason == "terminal_executor_memory_projection_mismatch"
    assert rejected_store.commits == {}
    assert rejected_store.admission_receipts == {}


def test_mrr_09a_corrective_pass2_exact_projection_is_idempotent(
    tmp_path: Path,
) -> None:
    from statebus.memory import MemoryIndexStore

    memory_root = tmp_path / "corrective-pass2-idempotent-memory"
    result = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="corrective-pass2-idempotent",
            value=59.0,
            family_memory_root=memory_root,
            program_calls=[],
        ),
    )
    memory_id = result.memory_commit_decision.memory_id
    restored = MemoryIndexStore(store_root=memory_root)
    restored.load_persisted_state()
    commit = restored.commits[memory_id]
    receipt = restored.admission_receipts[memory_id]

    same_commit, same_receipt = restored.persist_admitted(
        commit=commit,
        admission_receipt=receipt,
    )

    assert same_commit.commit_hash == commit.commit_hash
    assert same_receipt.receipt_hash == receipt.receipt_hash
    assert tuple(restored.commits) == (memory_id,)
    assert tuple(restored.admission_receipts) == (memory_id,)


@pytest.mark.parametrize("tamper", ("missing_receipt", "wrong_receipt_hash"))
def test_mrr_09a_fake_or_mismatched_verified_artifact_cannot_admit(
    tmp_path: Path,
    tamper: str,
) -> None:
    from statebus.memory import MemoryIndexStore

    request = _memory_loop_request(
        tmp_path,
        task_id=f"admission-{tamper}",
        value=29.0,
        family_memory_root=tmp_path / f"source-{tamper}",
        program_calls=[],
    )
    result = RuntimeDriver().run_mode("adaptive_bounded", adaptive_request=request)
    stored = next(
        item
        for item in result.context.artifacts.values()
        if item.artifact.produced_by == "executor" and item.artifact.step_id == "execute"
    )
    if tamper == "missing_receipt":
        result.context.artifact_verification_receipts.pop(stored.artifact.artifact_id)
    else:
        result.context.artifacts[stored.artifact.artifact_id] = replace(
            stored,
            artifact=replace(
                stored.artifact,
                metadata={
                    **stored.artifact.metadata,
                    "artifact_verification_receipt_hash": "sha256:wrong-receipt",
                },
            ),
        )

    approved_plan = AdaptiveMainlineRunner._assemble_plan(request)[1]
    rejected_store = MemoryIndexStore(store_root=tmp_path / f"rejected-{tamper}")
    decision = AdaptiveMainlineRunner._commit_verified_memory(
        request=request,
        approved_plan=approved_plan,
        runtime=result.runtime,
        context=result.context,
        memory_store=rejected_store,
    )
    assert decision.attempted is True
    assert decision.committed is False
    assert decision.reason == "terminal_executor_artifact_runtime_receipt_mismatch"
    assert rejected_store.commits == {}
    assert rejected_store.admission_receipts == {}


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


def test_mrr_09b_memory_lookup_hit_is_not_current_grant_authority(
    tmp_path: Path,
) -> None:
    family_memory_root = tmp_path / "lookup-only-memory"
    producer = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="lookup-producer",
            value=7.0,
            family_memory_root=family_memory_root,
            program_calls=[],
            memory_policy="assist",
            commit_replay_class=ReplayClass.ASSIST,
        ),
    )
    observed_inputs: list[tuple[dict[str, object], ...]] = []
    consumer = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="lookup-consumer",
            value=8.0,
            family_memory_root=family_memory_root,
            program_calls=[],
            memory_policy="none",
            commit_replay_class=ReplayClass.ASSIST,
            observed_memory_inputs=observed_inputs,
        ),
    )

    memory_id = producer.memory_commit_decision.memory_id
    memory_result = consumer.context.memory_match_results["retrieve"]
    assert memory_id in memory_result.candidate_pool.candidate_memory_ids
    execute_grant = next(
        bound for bound in consumer.runtime.bound_grants if bound.grant.step_id == "execute"
    )
    assert execute_grant.grant.memory_ref_ids == ()
    assert observed_inputs == [()]


def test_mrr_09b_current_runtime_selection_enters_immutable_grant_and_receipt(
    tmp_path: Path,
) -> None:
    family_memory_root = tmp_path / "grant-memory"
    producer = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="grant-producer",
            value=17.0,
            family_memory_root=family_memory_root,
            program_calls=[],
        ),
    )
    consumer = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="grant-consumer",
            value=18.0,
            family_memory_root=family_memory_root,
            program_calls=[],
        ),
    )

    memory_id = producer.memory_commit_decision.memory_id
    execute_grant = next(
        bound for bound in consumer.runtime.bound_grants if bound.grant.step_id == "execute"
    )
    assert execute_grant.grant.memory_ref_ids == (memory_id,)
    receipt = next(
        item
        for item in consumer.runtime.replay_eligibility_receipts
        if item.memory_id == memory_id
    )
    assert receipt.decision.value == "ELIGIBLE"
    assert receipt.consumer_runtime_task_id == "grant-consumer"
    assert receipt.consumer_attempt_id == execute_grant.grant.attempt_id
    assert receipt.consumer_execution_binding_hash == execute_grant.execution_binding_hash
    assert receipt.consumer_capability_grant_hash == execute_grant.grant.grant_hash
    assert receipt.reuse_mode == "VERIFIED_PROCEDURE_REUSE"


def test_mrr_09b_incompatible_current_runtime_fails_closed_before_grant_memory_binding(
    tmp_path: Path,
) -> None:
    family_memory_root = tmp_path / "incompatible-memory"
    producer = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=_memory_loop_request(
            tmp_path,
            task_id="incompatible-producer",
            value=27.0,
            family_memory_root=family_memory_root,
            program_calls=[],
        ),
    )
    consumer_request = _memory_loop_request(
        tmp_path,
        task_id="incompatible-consumer",
        value=28.0,
        family_memory_root=family_memory_root,
        program_calls=[],
    )
    consumer_request = replace(
        consumer_request,
        runtime_compatibility_signature="runtime-signature-mismatch",
    )
    consumer = RuntimeDriver().run_mode(
        "adaptive_bounded",
        adaptive_request=consumer_request,
    )

    memory_id = producer.memory_commit_decision.memory_id
    memory_result = consumer.context.memory_match_results["retrieve"]
    assert memory_id in memory_result.candidate_pool.candidate_memory_ids
    execute_grant = next(
        bound for bound in consumer.runtime.bound_grants if bound.grant.step_id == "execute"
    )
    assert execute_grant.grant.memory_ref_ids == ()
    assert consumer.runtime.replay_eligibility_receipts == ()
