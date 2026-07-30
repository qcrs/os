from __future__ import annotations

from pathlib import Path
import json

from statebus.contracts import (
    CanonicalTaskSpec,
    HydrationAccountingAudit,
    HydrationRoleAccounting,
    RefStatus,
    ReplayClass,
    StorageKind,
)
from statebus.contracts import CompatibilityVerdict
from statebus.memory import (
    DeterministicEmbeddingEncoder,
    MemoryCommit,
    MemoryCommitStatus,
    MemoryMatchResult,
    MemoryRef,
    MemoryType,
    MemoryValidationStatus,
)
from statebus.provenance import DeterministicFanInBuilder, EvidenceCandidate
from statebus.provenance import evidence_pack_to_dict, manifest_to_dict
from statebus.refs import (
    ExecutionArtifactRef,
    HydrateManifest,
    HydrateManifestEntry,
    SemanticStateRef,
    TextSpanLocator,
)
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.runtime import ReplayLedgerEntry, RuntimeTaskSession
from statebus.runtime.session import RuntimeWorkflowStep
from statebus.runtime import ArtifactManifestItem, ArtifactOutputManifest
from statebus.runtime import InputManifest, InputManifestItem
from statebus.runtime import ExecutionStepRecord, FallbackDag, FallbackAction
from statebus.runtime.codeact import CodeActRequest, CodeActRunner
from statebus.runtime.codeact_sandbox import CodeActSandboxConfig
from statebus.runtime.execution import ExecutionLogCapture
from statebus.runtime.execution import build_extended_output_manifest, capture_execution_logs
from statebus.runtime.workspace import (
    ArtifactInvalidationRecord,
    ArtifactSettlementRecord,
    ArtifactValidatorReport,
    InputValidatorReport,
    MaterializedFile,
)
from statebus.state import JsonContractStore, RefRegistryQuery


def test_json_contract_store_persists_registry_and_sidecars(tmp_path: Path) -> None:
    locator = TextSpanLocator(
        source_doc_hash="sha256:doc1",
        canonical_text_id="chunk-1",
        start_char=0,
        end_char=20,
        extractor_version="chunker-v1",
    )
    hydrate_manifest = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(
            HydrateManifestEntry(
                row_idx=0,
                stable_key="text-span-1",
                byte_hint=20,
                locator=locator,
            ),
        ),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    evidence_pack = DeterministicFanInBuilder().build(
        pack_id="pack-1",
        task_id="task-1",
        text_candidates=[
            EvidenceCandidate(
                item_id="ctx-1",
                bucket="semantic_context",
                locator=locator,
                rendered_text="Quarterly revenue improved.",
                source_name="semantic",
                rank=1,
            )
        ],
    )
    semantic_ref = SemanticStateRef(
        state_id="state-1",
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=StorageKind.MMAP_FILE,
        length=32,
        blob_hash="sha256:state",
        manifest_id=hydrate_manifest.manifest_hash,
    )
    artifact_ref = ExecutionArtifactRef(
        artifact_id="artifact-1",
        task_id="task-1",
        step_id="step-1",
        artifact_type="json",
        root_id="workspace-root",
        relpath="outputs/result.json",
        blob_hash="sha256:artifact",
        size_bytes=64,
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
    )
    artifact_manifest = ArtifactOutputManifest(
        task_id="task-1",
        step_id="step-1",
        outputs=(
            ArtifactManifestItem(
                artifact_name="result",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=64,
                sha256="sha256:artifact",
            ),
        ),
    )
    input_manifest = InputManifest(
        task_id="task-1",
        step_id="step-1",
        workspace_root="/tmp/task-1",
        inputs=(
            InputManifestItem(
                name="evidence_pack",
                artifact_type="json",
                relpath="inputs/evidence_pack.json",
                blob_hash=evidence_pack.pack_hash,
                source_ref_id="state-1",
            ),
        ),
    )
    hydration_accounting = HydrationAccountingAudit(
        task_id="task-1",
        evidence_pack_id=evidence_pack.pack_id,
        evidence_pack_hash=evidence_pack.pack_hash,
        hydrate_manifest_id=hydrate_manifest.manifest_id,
        hydrate_manifest_hash=hydrate_manifest.manifest_hash,
        evidence_locator_count=1,
        counting_scope="hydrated_external_evidence_only",
        raw_evidence_bytes_seen_by_llm=42,
        prompt_visible_total_bytes=84,
        non_external_prompt_visible_bytes=12,
        prompt_scaffolding_bytes_total=33,
        semantic_pruning_enabled=True,
        roles=(
            HydrationRoleAccounting(
                role="retriever",
                selected_stable_keys=("text-span-1",),
                external_text_bytes=20,
                external_text_item_count=1,
                table_bytes=0,
                table_item_count=0,
                artifact_bytes=0,
                artifact_item_count=0,
                memory_bytes=0,
                memory_item_count=0,
                external_evidence_bytes=20,
                total_prompt_visible_bytes=20,
                non_external_prompt_visible_bytes=0,
                total_prompt_visible_item_count=1,
                prompt_scaffolding_bytes=9,
                prompt_bytes=29,
                prompt_slice_ref_id="prompt-slice-task-1-retriever",
                prompt_slice_root_id="workspace-root",
                prompt_slice_relpath="logs/prompt_slices/retriever.prompt_slice.json",
                prompt_slice_blob_hash="sha256:prompt-slice",
                prompt_slice_size_bytes=123,
            ),
        ),
    )

    store = JsonContractStore(tmp_path / "contracts")
    persisted = store.persist_contract_bundle(
        registry_entries=[semantic_ref.registry_entry(), artifact_ref.registry_entry()],
        hydrate_manifest=hydrate_manifest,
        evidence_pack=evidence_pack,
        hydration_accounting_audit=hydration_accounting,
        input_manifest=input_manifest,
        artifact_manifest=artifact_manifest,
    )

    reloaded_semantic = store.get_ref_registry_entry("state-1")
    reloaded_artifact = store.get_ref_registry_entry("artifact-1")
    reloaded_manifest = store.read_hydrate_manifest(hydrate_manifest.manifest_hash)
    reloaded_pack = store.read_evidence_pack(evidence_pack.pack_hash)
    reloaded_hydration_accounting = store.read_hydration_accounting_audit("task-1")
    reloaded_input_manifest = store.read_input_manifest(input_manifest.manifest_hash)
    reloaded_output_manifest = store.read_artifact_output_manifest(artifact_manifest.manifest_hash)

    assert persisted.registry_path.exists()
    assert persisted.hydrate_manifest_path is not None and persisted.hydrate_manifest_path.exists()
    assert persisted.evidence_pack_path is not None and persisted.evidence_pack_path.exists()
    assert persisted.hydration_accounting_audit_path is not None and persisted.hydration_accounting_audit_path.exists()
    assert persisted.input_manifest_path is not None and persisted.input_manifest_path.exists()
    assert persisted.artifact_manifest_path is not None and persisted.artifact_manifest_path.exists()
    assert reloaded_semantic.ref_id == "state-1"
    assert reloaded_artifact.ref_id == "artifact-1"
    assert reloaded_manifest.manifest_id == "manifest-1"
    assert reloaded_pack.pack_id == "pack-1"
    assert reloaded_hydration_accounting.task_id == "task-1"
    assert reloaded_hydration_accounting.prompt_scaffolding_bytes_total == 33
    assert reloaded_hydration_accounting.roles[0].role == "retriever"
    assert reloaded_hydration_accounting.roles[0].prompt_slice_ref_id == "prompt-slice-task-1-retriever"
    assert reloaded_hydration_accounting.roles[0].prompt_slice_relpath.endswith("retriever.prompt_slice.json")
    assert reloaded_input_manifest.inputs[0].source_ref_id == "state-1"
    assert reloaded_output_manifest.outputs[0].artifact_name == "result"
    assert store.query_ref_registry(RefRegistryQuery(ref_kind=reloaded_semantic.ref_kind))[0].ref_id == "state-1"
    assert store.query_ref_registry(RefRegistryQuery(status=RefStatus.VERIFIED))[0].ref_id == "artifact-1"


def test_json_contract_store_batch_registry_write_skips_identical_rewrite(tmp_path: Path) -> None:
    store = JsonContractStore(tmp_path / "contracts")
    semantic = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    semantic_ref = SemanticStateRef(
        state_id="state-1",
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=StorageKind.MMAP_FILE,
        length=32,
        blob_hash="sha256:state",
        manifest_id=semantic.manifest_hash,
    )
    artifact_ref = ExecutionArtifactRef(
        artifact_id="artifact-1",
        task_id="task-1",
        step_id="step-1",
        artifact_type="json",
        root_id="workspace-root",
        relpath="outputs/result.json",
        blob_hash="sha256:artifact",
        size_bytes=64,
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
    )

    store.put_ref_registry_entries([semantic_ref.registry_entry(), artifact_ref.registry_entry()])
    first_text = store.registry_path.read_text(encoding="utf-8")
    store.put_ref_registry_entries([semantic_ref.registry_entry(), artifact_ref.registry_entry()])
    second_text = store.registry_path.read_text(encoding="utf-8")

    assert first_text == second_text


def test_json_contract_store_persists_memory_sidecars(tmp_path: Path) -> None:
    store = JsonContractStore(tmp_path / "contracts")
    encoder = DeterministicEmbeddingEncoder(dims=8)
    embedding = encoder.encode(embedding_id="embedding-1", text="Revenue increased in APAC.")
    query_embedding = encoder.encode(embedding_id="embedding-query", text="Revenue increased in APAC.")
    memory_ref = MemoryRef(
        memory_id="memory-1",
        memory_type=MemoryType.EXACT_REPLAY,
        replay_class=ReplayClass.EXACT_REPLAY,
        score=0.95,
        source_task_id="task-1",
        source_agent="summarizer",
        created_at_ns=123456789,
        task_theme="financial_report_analysis",
        tags=("finance", "replay"),
        source_role_path=("planner", "retriever", "executor", "summarizer"),
        producer_run_id="trace-test",
        summary="exact replay memory",
        canonical_task_spec_hash="sha256:spec-1",
        artifact_ref_id="artifact-1",
        embedding_ref_id=embedding.embedding_id,
        commit_status=MemoryCommitStatus.COMMITTED,
        validation_status=MemoryValidationStatus.PASSED,
        answer_adopted=True,
    )
    memory_commit = MemoryCommit(
        memory_ref=memory_ref,
        canonical_task_spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
        required_outputs=("summary_text",),
        quality_floor_pass=True,
        created_from_artifact_hash="sha256:artifact-1",
    )
    from statebus.memory import MemoryIndexStore

    memory_index = MemoryIndexStore()
    memory_index.put_embedding(query_embedding)
    memory_index.put_embedding(embedding)
    memory_index.commit_candidate(commit=memory_commit, quality_floor_pass=True, answer_adopted=True)
    memory_match_result = memory_index.lookup(
        query_task_id="task-2",
        query_spec_hash="sha256:spec-2",
        query_embedding=query_embedding,
        allow_replay=True,
    )

    embedding_path = store.write_embedding(embedding)
    commit_path = store.write_memory_commit(memory_commit)
    match_path = store.write_memory_match_result(memory_match_result)

    assert embedding_path.exists()
    assert commit_path.exists()
    assert match_path.exists()
    assert store.read_embedding(embedding.embedding_hash).embedding_id == "embedding-1"
    reloaded_commit = store.read_memory_commit("memory-1")
    assert reloaded_commit.memory_ref.memory_id == "memory-1"
    assert reloaded_commit.memory_ref.source_agent == "summarizer"
    assert reloaded_commit.memory_ref.created_at_ns == 123456789
    assert reloaded_commit.memory_ref.task_theme == "financial_report_analysis"
    assert reloaded_commit.memory_ref.tags == ("finance", "replay")
    assert reloaded_commit.memory_ref.source_role_path == ("planner", "retriever", "executor", "summarizer")
    assert reloaded_commit.memory_ref.producer_run_id == "trace-test"
    memory_commit_payload = json.loads(commit_path.read_text(encoding="utf-8"))
    assert memory_commit_payload["schema_version"] == "statebus.memory_commit.v2"
    assert memory_commit_payload["memory_ref"]["schema_version"] == "statebus.memory_ref.v2"
    assert memory_commit_payload["memory_ref"]["source_agent"] == "summarizer"
    assert memory_commit_payload["memory_ref"]["created_at_ns"] == 123456789
    assert memory_commit_payload["memory_ref"]["task_theme"] == "financial_report_analysis"
    assert memory_commit_payload["memory_ref"]["summary"] == "exact replay memory"
    assert memory_commit_payload["memory_ref"]["tags"] == ["finance", "replay"]
    reloaded_match = store.read_memory_match_result(memory_match_result.result_hash)
    assert reloaded_match.query_task_id == "task-2"
    assert reloaded_match.candidate_pool is not None
    assert reloaded_match.candidate_pool.candidate_taxonomy["exact_replay"] == 1
    assert reloaded_match.rerank_result is not None
    assert reloaded_match.rerank_result.selected_taxonomy["exact_replay"] == 1


def test_json_contract_store_persists_retrieval_session_and_ledger_sidecars(tmp_path: Path) -> None:
    store = JsonContractStore(tmp_path / "contracts")
    bundle = RetrieverFanoutPipeline().run(
        task_id="task-1",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
    )
    session = RuntimeTaskSession(
        session_id="session-1",
        trace_id="trace-1",
        task_id="task-1",
        layer_name="L3",
        canonical_task_spec_hash="sha256:spec",
        workspace_root="/tmp/workspace",
        state_root="/tmp/state",
        retrieval_log_hash=bundle.log_hash,
        planner_handoff_hash="sha256:planner",
        runtime_signature_hash="sha256:runtime",
        runtime_signature_manifest_bundle_hash="sha256:bundle",
        replay_input_artifact_hashes=("sha256:planner", "sha256:input", "sha256:manifest"),
        workflow_steps=(
            RuntimeWorkflowStep(
                step_id="retriever.fanout",
                role="retriever",
                capability="fanout_retrieval",
                state="COMPLETED",
            ),
        ),
        runtime_fallback_count=1,
        runtime_replan_count=1,
        memory_match_result_hash="sha256:memory-match",
        session_state="GC_DONE",
    )
    ledger_entry = ReplayLedgerEntry(
        ledger_id="ledger-1",
        session_id="session-1",
        task_id="task-1",
        candidate_id="candidate-1",
        memory_id="memory-1",
        artifact_ref_id="artifact-1",
        replay_class=ReplayClass.EXACT_REPLAY,
        decision_reason="exact_replay_key_match",
        compatibility_verdict=CompatibilityVerdict.COMPATIBLE,
        runtime_signature_hash="sha256:runtime",
        runtime_signature_manifest_bundle_hash="sha256:bundle",
        canonical_task_spec_hash="sha256:spec",
        planner_handoff_hash="sha256:planner",
        input_artifact_hashes=("sha256:planner", "sha256:input", "sha256:manifest"),
        output_contract_version="output-v1",
        runtime_signature={"tool_registry_digest": "sha256:tools"},
        exact_key="sha256:exact",
        skipped_step_count=2,
    )

    retrieval_path = store.write_retrieval_log(bundle)
    session_path = store.write_runtime_session(session)
    ledger_path = store.write_replay_ledger_entry(ledger_entry)

    assert retrieval_path.exists()
    assert session_path.exists()
    assert ledger_path.exists()
    session_payload = json.loads(session_path.read_text(encoding="utf-8"))
    assert "attempt_records" not in session_payload
    assert "replan_history" not in session_payload
    assert "can_skip_if" not in session_payload["workflow_steps"][0]
    assert "input_refs" not in session_payload["workflow_steps"][0]
    assert "output_refs" not in session_payload["workflow_steps"][0]
    assert "last_error" not in session_payload["workflow_steps"][0]
    candidate_pool_path = store.write_retrieval_candidate_pool(bundle)
    rerank_path = store.write_retrieval_rerank_result(bundle)
    assert candidate_pool_path.exists()
    assert rerank_path.exists()
    retrieval_log_payload = store.read_retrieval_log(bundle.log_hash)
    assert retrieval_log_payload["task_id"] == "task-1"
    assert retrieval_log_payload["outputs"]
    assert "candidates" not in retrieval_log_payload["outputs"][0]
    assert "query_embedding" not in retrieval_log_payload["outputs"][0]
    assert "log_entry" not in retrieval_log_payload["outputs"][0]
    assert "planner_scope_payload" not in retrieval_log_payload
    assert retrieval_log_payload["planner_scope_payload_hash"]
    assert retrieval_log_payload["outputs"][0]["candidate_count"] >= 1
    assert retrieval_log_payload["outputs"][0]["selected_count"] >= 1
    assert isinstance(retrieval_log_payload["outputs"][0]["diagnostics"], dict)
    assert retrieval_log_payload["outputs"][0]["candidate_ids_hash"]
    assert retrieval_log_payload["outputs"][0]["candidate_id_sample_count"] == len(
        retrieval_log_payload["outputs"][0]["candidate_id_sample"]
    )
    assert retrieval_log_payload["outputs"][0]["selected_ids_hash"]
    assert "selected_id_sample_count" not in retrieval_log_payload["outputs"][0]
    assert "selected_id_sample" not in retrieval_log_payload["outputs"][0]
    assert retrieval_log_payload["outputs"][0]["selected_candidate_audit_hash"]
    assert retrieval_log_payload["outputs"][0]["selected_candidate_audit_sample_count"] == len(
        retrieval_log_payload["outputs"][0]["selected_candidate_audit_sample"]
    )
    assert retrieval_log_payload["outputs"][0].get("query_embedding_hash", "") == ""
    candidate_pool_payload = store.read_retrieval_candidate_pool(bundle.candidate_pool.pool_hash)
    assert candidate_pool_payload["task_id"] == "task-1"
    assert retrieval_log_payload["candidate_pool_relpath"].endswith(f"{bundle.candidate_pool.pool_hash}.json")
    assert retrieval_log_payload["planner_scope_payload_hash"] == candidate_pool_payload["planner_scope_payload_hash"]
    assert candidate_pool_payload["candidate_surface_hash"] == bundle.candidate_pool.candidate_surface_hash
    assert candidate_pool_payload["candidate_audit_hash"]
    assert candidate_pool_payload["candidate_count"] >= candidate_pool_payload["candidate_audit_sample_count"]
    assert store.read_retrieval_rerank_result(bundle.rerank_result.rerank_hash)["task_id"] == "task-1"
    reloaded_session = store.read_runtime_session("session-1")
    assert reloaded_session.session_state == "GC_DONE"
    assert reloaded_session.workflow_steps[0].step_id == "retriever.fanout"
    assert reloaded_session.memory_match_result_hash == "sha256:memory-match"
    assert reloaded_session.planner_handoff_hash == "sha256:planner"
    assert reloaded_session.runtime_signature_hash == "sha256:runtime"
    assert reloaded_session.runtime_signature_manifest_bundle_hash == "sha256:bundle"
    assert reloaded_session.runtime_fallback_count == 1
    assert reloaded_session.runtime_replan_count == 1
    assert reloaded_session.workspace_root == session.workspace_root
    assert reloaded_session.state_root == session.state_root
    assert "workspace_root" not in session_payload
    assert "state_root" not in session_payload
    assert session_payload["workspace_root_relpath"]
    assert session_payload["state_root_relpath"]
    assert reloaded_session.replay_input_artifact_hashes == (
        "sha256:planner",
        "sha256:input",
        "sha256:manifest",
    )
    reloaded_ledger = store.read_replay_ledger_entry("ledger-1")
    assert reloaded_ledger.replay_class == ReplayClass.EXACT_REPLAY
    assert reloaded_ledger.planner_handoff_hash == "sha256:planner"
    assert reloaded_ledger.runtime_signature_manifest_bundle_hash == "sha256:bundle"
    assert reloaded_ledger.runtime_signature["tool_registry_digest"] == "sha256:tools"


def test_json_contract_store_persists_execution_step_and_fallback_sidecars(tmp_path: Path) -> None:
    store = JsonContractStore(tmp_path / "contracts")
    artifact_manifest = ArtifactOutputManifest(
        task_id="task-1",
        step_id="step-1",
        outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=64,
                sha256="sha256:artifact",
            ),
            ArtifactManifestItem(
                artifact_name="stdout_log",
                artifact_type="json",
                relpath="logs/step-1.stdout.json",
                size_bytes=32,
                sha256="sha256:stdout",
            ),
            ArtifactManifestItem(
                artifact_name="stderr_log",
                artifact_type="json",
                relpath="logs/step-1.stderr.json",
                size_bytes=16,
                sha256="sha256:stderr",
            ),
        ),
    )
    execution_step = ExecutionStepRecord(
        task_id="task-1",
        step_id="step-1",
        attempt_id="attempt-2",
        workspace_root="/tmp/task-1",
        execution_goal="downgrade_execution_goal",
        exit_code=0,
        output_manifest=artifact_manifest,
        log_capture=ExecutionLogCapture(
            stdout_preview="hello",
            stderr_preview="warn",
            stdout_artifact=MaterializedFile(
                logical_name="stdout_log",
                relpath="logs/step-1.stdout.json",
                path=Path("/tmp/task-1/logs/step-1.stdout.json"),
                sha256="sha256:stdout",
                size_bytes=32,
            ),
            stderr_artifact=MaterializedFile(
                logical_name="stderr_log",
                relpath="logs/step-1.stderr.json",
                path=Path("/tmp/task-1/logs/step-1.stderr.json"),
                sha256="sha256:stderr",
                size_bytes=16,
            ),
            stdout_truncated=False,
            stderr_truncated=False,
        ),
        input_validator_reports=(
            InputValidatorReport(
                task_id="task-1",
                step_id="step-1",
                validation_scope="input_manifest",
                passed=True,
                required_inputs=(),
                observed_inputs=(),
            ),
        ),
        validator_reports=(
            ArtifactValidatorReport(
                task_id="task-1",
                step_id="step-1",
                artifact_id="artifact-1",
                validation_scope="deterministic",
                passed=True,
            ),
        ),
        settlement_record=ArtifactSettlementRecord(
            artifact_id="artifact-1",
            task_id="task-1",
            step_id="step-1",
            from_state="candidate",
            to_state="verified",
            commit_gate_reason="quality_floor_passed",
            quality_floor_pass=True,
        ),
        invalidation_record=ArtifactInvalidationRecord(
            artifact_id="artifact-1",
            task_id="task-1",
            step_id="step-1",
            invalidation_reason="validator_failed",
            invalidated_from_state="candidate",
        ),
        invalidation_reasons=("validator_failed",),
    )
    fallback_dag = FallbackDag(
        dag_id="fallback-task-1-step-1",
        task_id="task-1",
        source_step_id="step-1",
        actions=(
            FallbackAction(
                action_name="retry_same_step",
                target_step_id="step-1",
                reason="transient_runtime_failure",
            ),
        ),
    )

    hydrated = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    evidence_pack = DeterministicFanInBuilder().build(pack_id="pack-1", task_id="task-1", text_candidates=[])
    input_manifest = InputManifest(
        task_id="task-1",
        step_id="step-1",
        workspace_root="/tmp/task-1",
        inputs=(),
    )
    persisted = store.persist_contract_bundle(
        registry_entries=[],
        hydrate_manifest=hydrated,
        evidence_pack=evidence_pack,
        input_manifest=input_manifest,
        artifact_manifest=artifact_manifest,
        execution_step_record=execution_step,
        fallback_dag=fallback_dag,
    )

    reloaded_execution_step = store.read_execution_step_record(
        task_id="task-1",
        step_id="step-1",
        attempt_id="attempt-2",
    )
    reloaded_fallback_dag = store.read_fallback_dag("fallback-task-1-step-1")

    assert persisted.execution_step_path is not None and persisted.execution_step_path.exists()
    assert persisted.fallback_dag_path is not None and persisted.fallback_dag_path.exists()
    execution_step_payload = json.loads(persisted.execution_step_path.read_text(encoding="utf-8"))
    assert "exit_code" not in execution_step_payload
    assert "stdout_truncated" not in execution_step_payload
    assert "stderr_truncated" not in execution_step_payload
    assert "output_manifest" not in execution_step_payload
    assert execution_step_payload["output_manifest_hash"] == artifact_manifest.manifest_hash
    assert execution_step_payload["output_manifest_relpath"].startswith("manifests/artifacts/")
    assert "required_inputs" not in execution_step_payload["input_validator_reports"][0]
    assert "observed_inputs" not in execution_step_payload["input_validator_reports"][0]
    assert reloaded_execution_step.execution_goal == "downgrade_execution_goal"
    assert reloaded_execution_step.output_manifest.outputs[1].artifact_name == "stdout_log"
    assert reloaded_execution_step.input_validator_reports[0].validation_scope == "input_manifest"
    assert reloaded_execution_step.validator_reports[0].validation_scope == "deterministic"
    assert reloaded_execution_step.settlement_record is not None
    assert reloaded_execution_step.invalidation_record is not None
    assert reloaded_execution_step.invalidation_reasons == ("validator_failed",)
    assert reloaded_execution_step.validator_reports[0].report_hash == execution_step.validator_reports[0].report_hash
    assert (
        reloaded_execution_step.input_validator_reports[0].report_hash
        == execution_step.input_validator_reports[0].report_hash
    )
    assert (
        reloaded_execution_step.settlement_record.settlement_hash
        == execution_step.settlement_record.settlement_hash
    )
    assert (
        reloaded_execution_step.invalidation_record.invalidation_hash
        == execution_step.invalidation_record.invalidation_hash
    )
    assert reloaded_fallback_dag.actions[0].action_name == "retry_same_step"

    persisted_payload = json.loads(persisted.execution_step_path.read_text(encoding="utf-8"))
    assert "details" not in persisted_payload["validator_reports"][0]
    assert "details_hash" in persisted_payload["validator_reports"][0]
    assert "details" not in persisted_payload["input_validator_reports"][0]
    assert "details_hash" in persisted_payload["input_validator_reports"][0]
    assert "settlement_hash" in persisted_payload["settlement_record"]
    assert "invalidation_hash" in persisted_payload["invalidation_record"]


def test_json_contract_store_reuses_materialized_workspace_json_when_persisting_bundle(tmp_path: Path) -> None:
    store = JsonContractStore(tmp_path / "runtime")
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    hydrate_manifest = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    evidence_pack = DeterministicFanInBuilder().build(
        pack_id="pack-1",
        task_id="task-1",
        text_candidates=[],
    )
    input_manifest = InputManifest(
        task_id="task-1",
        step_id="step-1",
        workspace_root="/tmp/task-1",
        inputs=(
            InputManifestItem(
                name="canonical_evidence_pack",
                artifact_type="json",
                relpath="inputs/evidence_pack.json",
                blob_hash=evidence_pack.pack_hash,
                source_ref_id="state-1",
            ),
        ),
    )
    artifact_manifest = ArtifactOutputManifest(
        task_id="task-1",
        step_id="step-1",
        outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=32,
                sha256="sha256:artifact",
            ),
        ),
    )
    retrieval_bundle = RetrieverFanoutPipeline().run(
        task_id="task-1",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
    )

    hydrate_workspace_path = workspace_dir / "hydrate_manifest.json"
    evidence_workspace_path = workspace_dir / "evidence_pack.json"
    input_manifest_workspace_path = workspace_dir / "input_manifest.json"
    artifact_manifest_workspace_path = workspace_dir / "artifact_manifest.json"
    retrieval_log_workspace_path = workspace_dir / "retrieval_log.json"

    hydrate_workspace_path.write_text(
        json.dumps(manifest_to_dict(hydrate_manifest), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    evidence_workspace_path.write_text(
        json.dumps(evidence_pack_to_dict(evidence_pack), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    input_manifest_workspace_path.write_text(
        json.dumps(input_manifest.snapshot_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    artifact_manifest_workspace_path.write_text(
        json.dumps(artifact_manifest.snapshot_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    retrieval_log_workspace_path.write_text(
        json.dumps(retrieval_bundle.log_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    persisted = store.persist_contract_bundle(
        registry_entries=[],
        hydrate_manifest=hydrate_manifest,
        evidence_pack=evidence_pack,
        input_manifest=input_manifest,
        artifact_manifest=artifact_manifest,
        retrieval_bundle=retrieval_bundle,
        materialized_json_by_hash={
            hydrate_manifest.manifest_hash: hydrate_workspace_path,
            evidence_pack.pack_hash: evidence_workspace_path,
            input_manifest.manifest_hash: input_manifest_workspace_path,
            artifact_manifest.manifest_hash: artifact_manifest_workspace_path,
            retrieval_bundle.log_hash: retrieval_log_workspace_path,
        },
    )

    assert persisted.hydrate_manifest_path is not None
    assert persisted.evidence_pack_path is not None
    assert persisted.input_manifest_path is not None
    assert persisted.artifact_manifest_path is not None
    assert persisted.retrieval_log_path is not None
    assert persisted.retrieval_pruning_profile_path is not None
    assert persisted.hydrate_manifest_path.read_bytes() == hydrate_workspace_path.read_bytes()
    assert persisted.evidence_pack_path.read_bytes() == evidence_workspace_path.read_bytes()
    assert persisted.input_manifest_path.read_bytes() == input_manifest_workspace_path.read_bytes()
    assert persisted.artifact_manifest_path.read_bytes() == artifact_manifest_workspace_path.read_bytes()
    assert persisted.retrieval_log_path.read_bytes() == retrieval_log_workspace_path.read_bytes()
    reloaded_pruning_profile = store.read_retrieval_pruning_profile(
        retrieval_bundle.pruning_profile.profile_hash
    )
    assert reloaded_pruning_profile.profile_hash == retrieval_bundle.pruning_profile.profile_hash
    assert reloaded_pruning_profile.selected_candidate_ids == retrieval_bundle.pruning_profile.selected_candidate_ids


def test_json_contract_store_externalizes_codeact_audit_details_from_execution_step(tmp_path: Path) -> None:
    store = JsonContractStore(tmp_path / "contracts")
    workspace_root = tmp_path / "workspace"
    from statebus.runtime.workspace import WorkspaceManager

    workspace = WorkspaceManager(workspace_root)
    layout = workspace.ensure_layout("task-1")
    step_layout = workspace.ensure_step_layout(layout, "step-1")
    result = CodeActRunner(
        sandbox_config=CodeActSandboxConfig(requested_backend="resource"),
    ).run(
        workspace=workspace,
        layout=layout,
        step_layout=step_layout,
        request=CodeActRequest(
            task_id="task-1",
            step_id="step-1",
            attempt_id="attempt-1",
            execution_goal="full_execution_goal",
            query_text="Compare ACME revenue with the previous quarter",
            summary_suffix="candidate summary",
            revenue_value="120",
            selected_doc_hashes=("sha256:doc-1",),
            evidence_pack_hash="sha256:pack-1",
            retrieval_log_hash="sha256:retrieval-1",
            runtime_contract="l3-fixed-answer-cold-start",
            required_outputs=("summary_text", "revenue_value"),
            route="compare_metric",
            tool_name="table_retriever",
            action_contract="materialize_validated_artifact",
            supporting_doc_ids=("doc-1",),
            planner_plan_payload={"steps": ["retrieve", "execute"]},
        ),
    )
    log_capture = capture_execution_logs(
        workspace=workspace,
        layout=layout,
        step_id="step-1",
        stdout_text=result.stdout_text,
        stderr_text=result.stderr_text,
        capture_limit_bytes=32,
    )
    artifact_manifest = build_extended_output_manifest(
        task_id="task-1",
        step_id="step-1",
        primary_outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=len(result.output_rendered),
                sha256="hash-output",
            ),
        ),
        log_capture=log_capture,
    )
    execution_step = ExecutionStepRecord(
        task_id="task-1",
        step_id="step-1",
        attempt_id="attempt-1",
        workspace_root=str(layout.root),
        execution_goal="full_execution_goal",
        exit_code=0,
        output_manifest=artifact_manifest,
        log_capture=log_capture,
        input_validator_reports=(),
        validator_reports=(),
        codeact_plan=result.plan,
        codeact_record=result.record,
    )
    hydrate_manifest = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    evidence_pack = DeterministicFanInBuilder().build(pack_id="pack-1", task_id="task-1", text_candidates=[])
    input_manifest = InputManifest(
        task_id="task-1",
        step_id="step-1",
        workspace_root=str(layout.root),
        inputs=(),
    )

    persisted = store.persist_contract_bundle(
        registry_entries=[],
        hydrate_manifest=hydrate_manifest,
        evidence_pack=evidence_pack,
        input_manifest=input_manifest,
        artifact_manifest=artifact_manifest,
        execution_step_record=execution_step,
    )

    assert persisted.execution_step_path is not None and persisted.execution_step_path.exists()
    assert persisted.codeact_plan_audit_path is not None and persisted.codeact_plan_audit_path.exists()
    assert persisted.codeact_record_audit_path is not None and persisted.codeact_record_audit_path.exists()

    execution_payload = json.loads(persisted.execution_step_path.read_text(encoding="utf-8"))
    assert "output_manifest" not in execution_payload
    assert execution_payload["output_manifest_hash"] == artifact_manifest.manifest_hash
    assert execution_payload["output_manifest_relpath"].startswith("manifests/artifacts/")
    assert execution_payload["codeact_plan"]["audit_relpath"].startswith("sidecars/codeact_plan_audits/")
    assert execution_payload["codeact_record"]["audit_relpath"].startswith("sidecars/codeact_record_audits/")
    assert "task_id" not in execution_payload["codeact_plan"]
    assert "step_id" not in execution_payload["codeact_plan"]
    assert "execution_goal" not in execution_payload["codeact_plan"]
    assert "task_id" not in execution_payload["codeact_record"]
    assert "step_id" not in execution_payload["codeact_record"]
    assert "attempt_id" not in execution_payload["codeact_record"]
    assert "execution_goal" not in execution_payload["codeact_record"]
    assert "stages" not in execution_payload["codeact_plan"]
    assert "stage_results" not in execution_payload["codeact_record"]

    plan_detail_payload = json.loads(persisted.codeact_plan_audit_path.read_text(encoding="utf-8"))
    record_detail_payload = json.loads(persisted.codeact_record_audit_path.read_text(encoding="utf-8"))
    assert plan_detail_payload["stages"][0]["actions"][0]["parameters"]
    assert record_detail_payload["stage_results"]

    reloaded_execution_step = store.read_execution_step_record(
        task_id="task-1",
        step_id="step-1",
        attempt_id="attempt-1",
    )
    assert reloaded_execution_step.codeact_plan is not None
    assert reloaded_execution_step.codeact_record is not None
    assert reloaded_execution_step.codeact_plan.plan_hash == result.plan.plan_hash
    assert reloaded_execution_step.codeact_plan.stage_count == result.plan.stage_count
    assert reloaded_execution_step.codeact_record.generated_code_hash == result.record.generated_code_hash
    assert len(reloaded_execution_step.codeact_record.stage_results) == len(result.record.stage_results)
