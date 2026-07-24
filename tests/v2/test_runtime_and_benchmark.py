from __future__ import annotations

from pathlib import Path
import json

from v2.benchmark import BenchmarkLayer, BenchmarkRunReport, QualityFloorResult
from v2.contracts import (
    CanonicalTaskSpec,
    CompilerStatus,
    RuntimeCompatibilitySignature,
    StepLifecycleState,
    TaskCompilerInput,
    TaskMode,
)
from v2.runtime import (
    ArtifactLifecycleManager,
    FallbackPlanner,
    ReplayAdmissibilityGate,
    ReplayCandidate,
    ReplayPolicy,
    RuntimeSupervisor,
    TaskCompiler,
    TelemetryEmitter,
    TelemetryEvent,
    WorkspaceManager,
    ArtifactManifestItem,
    ArtifactOutputManifest,
    ExecutionStepRecord,
    build_extended_output_manifest,
    capture_execution_logs,
    InputManifest,
    InputManifestItem,
    build_task_lineage_view,
    capture_runtime_signature,
)
from v2.runtime.runtime_signature import SignatureManifestEntry
from v2.runtime.codeact import CodeActRequest, CodeActRunner
from v2.runtime.codeact_sandbox import CodeActSandboxConfig
from v2.route_tool_catalog import build_route_tool_surface, stable_tool_registry_profiles
from v2.refs import ExecutionArtifactRef


def _runtime_signature(
    os_digest: str = "os-a",
    tool_registry_digest: str = "tool-a",
    prompt_bundle_digest: str = "prompt-a",
    extractor_bundle_digest: str = "extract-a",
) -> RuntimeCompatibilitySignature:
    return RuntimeCompatibilitySignature(
        os_digest=os_digest,
        python_digest="py-a",
        dependency_digest="dep-a",
        tool_registry_digest=tool_registry_digest,
        prompt_bundle_digest=prompt_bundle_digest,
        extractor_bundle_digest=extractor_bundle_digest,
    )


def _stable_tool_registry_manifests() -> tuple[SignatureManifestEntry, ...]:
    return tuple(
        SignatureManifestEntry(
            entry_id=profile.registry_entry_id(),
            entry_version="catalog-v1",
            entry_kind="tool_registry",
            payload=profile.registry_payload(),
        )
        for profile in stable_tool_registry_profiles()
    )


def test_runtime_signature_uses_stable_tool_registry_catalog_not_dynamic_candidate_surface() -> None:
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="extract_metric_series_generic",
        required_outputs=("metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"),
        required_tools=("table_retriever",),
        arguments={"dataset_id": "acme_ops_2026", "metric": "revenue_musd", "quarter": "2026Q3"},
    )
    surface_a = build_route_tool_surface(
        spec,
        query_text="acme_ops_2026 revenue_musd extract_metric_series_generic",
        supporting_doc_ids=("sha256:doc-1",),
    )
    surface_b = build_route_tool_surface(
        spec,
        query_text="acme_ops_2026 gross_margin_pct extract_metric_series_generic",
        supporting_doc_ids=("sha256:doc-9", "sha256:doc-10"),
    )
    dynamic_manifests_a = tuple(
        SignatureManifestEntry(
            entry_id=candidate.candidate_key(),
            entry_version="legacy-v1",
            entry_kind="tool_registry",
            payload={
                "tool_name": candidate.tool_name,
                "route": candidate.route,
                "helper_rank": candidate.helper_rank,
                "support_doc_count": candidate.support_doc_count,
                "support_terms": list(candidate.support_terms),
            },
        )
        for candidate in surface_a
    )
    dynamic_manifests_b = tuple(
        SignatureManifestEntry(
            entry_id=candidate.candidate_key(),
            entry_version="legacy-v1",
            entry_kind="tool_registry",
            payload={
                "tool_name": candidate.tool_name,
                "route": candidate.route,
                "helper_rank": candidate.helper_rank,
                "support_doc_count": candidate.support_doc_count,
                "support_terms": list(candidate.support_terms),
            },
        )
        for candidate in surface_b
    )

    assert surface_a != surface_b
    legacy_a = capture_runtime_signature(tool_registry_manifests=dynamic_manifests_a)
    legacy_b = capture_runtime_signature(tool_registry_manifests=dynamic_manifests_b)
    stable_a = capture_runtime_signature(tool_registry_manifests=_stable_tool_registry_manifests())
    stable_b = capture_runtime_signature(tool_registry_manifests=_stable_tool_registry_manifests())

    assert legacy_a.tool_registry_digest != legacy_b.tool_registry_digest
    assert stable_a.tool_registry_digest == stable_b.tool_registry_digest


def test_task_compiler_rejects_benchmark_strict_without_precompiled_spec() -> None:
    compiler = TaskCompiler()
    result = compiler.compile(
        TaskCompilerInput(
            request_text="Compare ACME revenue with the previous quarter",
            task_mode=TaskMode.BENCHMARK_STRICT,
        )
    )
    assert result.status == CompilerStatus.REJECTED


def test_task_compiler_rejects_benchmark_strict_with_invalid_enum_values() -> None:
    compiler = TaskCompiler()
    result = compiler.compile(
        TaskCompilerInput(
            request_text='{"task_family":"financial_report_analysis","intent_op":"freeform_guess"}',
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=CanonicalTaskSpec(
                task_family="financial_report_analysis",
                intent_op="freeform_guess",
                required_outputs=("summary_text",),
            ),
        )
    )
    assert result.status == CompilerStatus.REJECTED
    assert result.canonical_task_spec is None
    assert "canonical_task_spec_invalid_intent_op" in result.compiler_errors[0]


def test_task_compiler_accepts_precompiled_spec_for_benchmark_strict() -> None:
    compiler = TaskCompiler()
    spec = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        required_tools=("table_retriever", "semantic_retriever"),
        arguments={"ticker": "ACME", "quarter": "2026Q1", "metric": "revenue"},
    )
    result = compiler.compile(
        TaskCompilerInput(
            request_text="Compare ACME revenue with the previous quarter",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=spec,
        )
    )
    assert result.status == CompilerStatus.COMPILED
    assert result.canonical_task_spec == spec


def test_task_compiler_accepts_continuous_csv_precompiled_spec_for_benchmark_strict() -> None:
    compiler = TaskCompiler()
    spec = CanonicalTaskSpec(
        task_family="continuous_csv_table_analysis",
        intent_op="profile_table",
        required_outputs=("schema_profile_ref", "missingness_summary", "summary_text"),
        required_tools=("csv_profiler", "codeact_executor"),
        arguments={
            "dataset_id": "disease_estimates",
            "csv_path": "task/csv/estimated_numbers.csv",
        },
    )
    result = compiler.compile(
        TaskCompilerInput(
            request_text="profile estimated_numbers csv",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=spec,
        )
    )
    assert result.status == CompilerStatus.COMPILED
    assert result.canonical_task_spec == spec


def test_task_compiler_accepts_continuous_long_doc_precompiled_spec_for_benchmark_strict() -> None:
    compiler = TaskCompiler()
    spec = CanonicalTaskSpec(
        task_family="continuous_long_doc_table_analysis",
        intent_op="build_semantic_index",
        required_outputs=("semantic_state_ref", "metric_table_ref", "entity_index_ref"),
        required_tools=("semantic_retriever", "table_extractor"),
        arguments={
            "dataset_id": "acme_ops_2026",
            "document_path": "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md",
        },
    )
    result = compiler.compile(
        TaskCompilerInput(
            request_text="build long-doc semantic index",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=spec,
        )
    )
    assert result.status == CompilerStatus.COMPILED
    assert result.canonical_task_spec == spec


def test_task_compiler_accepts_incident_precompiled_spec_for_benchmark_strict() -> None:
    compiler = TaskCompiler()
    spec = CanonicalTaskSpec(
        task_family="incident_diagnosis_v2",
        intent_op="diagnose_startup_latency",
        required_outputs=(
            "timing_profile_ref",
            "service_name",
            "slow_phase",
            "wait_duration_seconds",
            "root_cause",
            "summary_text",
        ),
        required_tools=("semantic_retriever", "codeact_executor", "artifact_writer"),
        arguments={
            "dataset_id": "inference_gateway_boot",
            "log_path": "v2/benchmark/samples/incident_corpus/inference-gateway/boot_log.txt",
            "journal_path": "v2/benchmark/samples/incident_corpus/inference-gateway/journal.txt",
            "service_name": "inference-gateway.service",
            "phase_hint": "storage_mount",
            "symptom_family": "startup_latency",
        },
    )
    result = compiler.compile(
        TaskCompilerInput(
            request_text="diagnose startup latency",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=spec,
        )
    )
    assert result.status == CompilerStatus.COMPILED
    assert result.canonical_task_spec == spec


def test_quality_floor_result_is_shared_case_level_contract() -> None:
    from v2.benchmark.scoring import FixedAnswerLaneResult, score_fixed_answer_case

    score = score_fixed_answer_case(
        observed=FixedAnswerLaneResult(
            task_id="task-1",
            route="compare_metric",
            tool_name="table_retriever",
            summary_text="ok",
            revenue_value="120",
            selected_doc_hashes=("sha256:doc-acme-2026q1",),
        ),
        expected_route="compare_metric",
        expected_tool_name="table_retriever",
        expected_facts={"revenue_value": "120", "selected_doc_hashes": ["sha256:doc-acme-2026q1"]},
    )
    assert score.quality_floor.quality_floor_pass is True
    assert score.route_exact is True
    assert score.tool_exact is True
    assert score.selected_doc_hashes_exact is True


def test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue() -> None:
    from v2.benchmark.scoring import FixedAnswerLaneResult, score_fixed_answer_case

    expected = {
        "metric_name": "operating_income",
        "metric_value": "19",
        "revenue_value": "19",
        "selected_doc_hashes": ["sha256:doc-acme-2026q1"],
    }
    correct_metric = score_fixed_answer_case(
        observed=FixedAnswerLaneResult(
            task_id="benchmark-sample-7",
            route="compare_metric",
            tool_name="table_retriever",
            summary_text="operating income is 19",
            metric_name="operating_income",
            metric_value="19",
            revenue_value="",
            selected_doc_hashes=("sha256:doc-acme-2026q1",),
        ),
        expected_route="compare_metric",
        expected_tool_name="table_retriever",
        expected_facts=expected,
    )
    wrong_revenue = score_fixed_answer_case(
        observed=FixedAnswerLaneResult(
            task_id="benchmark-sample-7",
            route="compare_metric",
            tool_name="table_retriever",
            summary_text="operating income is 19",
            metric_name="revenue",
            metric_value="120",
            revenue_value="120",
            selected_doc_hashes=("sha256:doc-acme-2026q1",),
        ),
        expected_route="compare_metric",
        expected_tool_name="table_retriever",
        expected_facts=expected,
    )

    assert correct_metric.metric_name_exact is True
    assert correct_metric.metric_value_exact is True
    assert correct_metric.quality_floor.quality_floor_pass is True
    assert wrong_revenue.metric_name_exact is False
    assert wrong_revenue.metric_value_exact is False
    assert wrong_revenue.quality_floor.quality_floor_pass is False


def test_replay_gate_distinguishes_exact_validated_and_assist() -> None:
    compiler = TaskCompiler()
    compiled = compiler.compile(
        TaskCompilerInput(
            request_text="Compare ACME revenue with the previous quarter",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=CanonicalTaskSpec(
                task_family="financial_report_analysis",
                intent_op="compare_metric",
                required_outputs=("summary_text",),
                required_tools=("table_retriever", "semantic_retriever"),
            ),
        )
    )
    assert compiled.canonical_task_spec is not None
    candidate = ReplayCandidate(
        candidate_id="cand-1",
        canonical_task_spec=compiled.canonical_task_spec,
        input_artifact_hashes=("input-1",),
        runtime_signature=_runtime_signature(),
        output_contract_version="output-v1",
        verified_output=True,
        code_template_version="code-v1",
        extractor_version="extract-v1",
    )
    gate = ReplayAdmissibilityGate()

    exact = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(),
        input_artifact_hashes=("input-1",),
        output_contract_version="output-v1",
    )
    assert exact.replay_class.value == "exact_replay"

    validated = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(os_digest="os-b"),
        input_artifact_hashes=("input-1",),
        output_contract_version="output-v1",
    )
    assert validated.replay_class.value == "validated_replay"
    assert validated.reason == "runtime_signature_degraded_validated_replay"

    assist = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, False, False),
        candidate=candidate,
        runtime_signature=_runtime_signature(os_digest="os-b"),
        input_artifact_hashes=("other-input",),
        output_contract_version="output-v2",
    )
    assert assist.replay_class.value == "assist"
    assert assist.reason == "output_contract_mismatch_assist_only"


def test_replay_gate_exact_key_changes_when_planner_handoff_hash_changes() -> None:
    compiler = TaskCompiler()
    compiled = compiler.compile(
        TaskCompilerInput(
            request_text="Compare ACME revenue with the previous quarter",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=CanonicalTaskSpec(
                task_family="financial_report_analysis",
                intent_op="compare_metric",
                required_outputs=("summary_text",),
                required_tools=("table_retriever", "semantic_retriever"),
            ),
        )
    )
    assert compiled.canonical_task_spec is not None
    candidate = ReplayCandidate(
        candidate_id="cand-1",
        canonical_task_spec=compiled.canonical_task_spec,
        input_artifact_hashes=("planner-a", "input-1", "manifest-a"),
        runtime_signature=_runtime_signature(),
        output_contract_version="output-v1",
        verified_output=True,
        code_template_version="code-v1",
        extractor_version="extract-v1",
    )
    gate = ReplayAdmissibilityGate()
    decision = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(),
        input_artifact_hashes=("planner-b", "input-1", "manifest-a"),
        output_contract_version="output-v1",
    )
    assert decision.replay_class.value == "validated_replay"
    assert decision.reason == "exact_key_mismatch_validated_replay"


def test_replay_gate_fail_closed_for_incompatible_runtime_and_output_contract() -> None:
    compiler = TaskCompiler()
    compiled = compiler.compile(
        TaskCompilerInput(
            request_text="Compare ACME revenue with the previous quarter",
            task_mode=TaskMode.BENCHMARK_STRICT,
            precompiled_canonical_task_spec=CanonicalTaskSpec(
                task_family="financial_report_analysis",
                intent_op="compare_metric",
                required_outputs=("summary_text",),
                required_tools=("table_retriever", "semantic_retriever"),
            ),
        )
    )
    assert compiled.canonical_task_spec is not None
    candidate = ReplayCandidate(
        candidate_id="cand-1",
        canonical_task_spec=compiled.canonical_task_spec,
        input_artifact_hashes=("input-1",),
        runtime_signature=_runtime_signature(),
        output_contract_version="output-v1",
        verified_output=True,
        code_template_version="code-v1",
        extractor_version="extract-v1",
    )
    gate = ReplayAdmissibilityGate()

    runtime_incompatible = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(True, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(tool_registry_digest="tool-b"),
        input_artifact_hashes=("input-1",),
        output_contract_version="output-v1",
    )
    assert runtime_incompatible.replay_class.value == "assist"
    assert runtime_incompatible.reason == "runtime_signature_incompatible_assist_only"

    output_contract_mismatch = gate.decide(
        compiler_result=compiled,
        policy=ReplayPolicy(False, True, True),
        candidate=candidate,
        runtime_signature=_runtime_signature(),
        input_artifact_hashes=("input-1",),
        output_contract_version="output-v2",
    )
    assert output_contract_mismatch.replay_class.value == "disallowed"
    assert output_contract_mismatch.reason == "policy_disallows_reuse"


def test_runtime_supervisor_enforces_lifecycle_transitions() -> None:
    supervisor = RuntimeSupervisor()
    supervisor.register(task_id="task-1", step_id="step-1", attempt_id="a1", role="executor")
    assert supervisor.dispatch("step-1").state == StepLifecycleState.DISPATCHED
    assert supervisor.ack("step-1").state == StepLifecycleState.ACKED
    assert supervisor.run_start("step-1").state == StepLifecycleState.RUNNING
    assert supervisor.heartbeat("step-1").last_heartbeat_ns > 0
    assert supervisor.complete("step-1").state == StepLifecycleState.COMPLETED
    assert supervisor.gc_pending("step-1").state == StepLifecycleState.GC_PENDING
    assert supervisor.gc_done("step-1").state == StepLifecycleState.GC_DONE
    assert supervisor.snapshot("step-1").state == "GC_DONE"


def test_runtime_supervisor_traps_ack_timeout_and_lease_expiry() -> None:
    supervisor = RuntimeSupervisor()
    supervisor.register(task_id="task-1", step_id="step-1", attempt_id="a1", role="executor")
    dispatched = supervisor.dispatch("step-1")
    ack_timeout = supervisor.trap_if_ack_timed_out(
        "step-1",
        ack_timeout_ms=250,
        now_ns=dispatched.dispatched_at_ns + 251_000_000,
    )
    assert ack_timeout is not None
    assert ack_timeout.state == StepLifecycleState.TRAPPED
    assert ack_timeout.last_error == "ack_timeout"

    supervisor.register(task_id="task-1", step_id="step-2", attempt_id="a1", role="executor")
    supervisor.dispatch("step-2")
    supervisor.ack("step-2")
    running = supervisor.run_start("step-2")
    lease_timeout = supervisor.trap_if_lease_expired(
        "step-2",
        lease_timeout_ms=6000,
        now_ns=running.started_at_ns + 6_001_000_000,
    )
    assert lease_timeout is not None
    assert lease_timeout.state == StepLifecycleState.TRAPPED
    assert lease_timeout.last_error == "heartbeat_timeout"


def test_workspace_and_artifact_lifecycle_keep_candidate_verified_invalidated_states() -> None:
    workspace = WorkspaceManager(Path("/statebus/workspaces"))
    layout = workspace.layout_for_task("task-1")
    assert layout.outputs_dir.as_posix().endswith("/task-1/outputs")

    lifecycle = ArtifactLifecycleManager()
    artifact = lifecycle.register_candidate(
        ExecutionArtifactRef(
            artifact_id="artifact-1",
            task_id="task-1",
            step_id="step-1",
            artifact_type="json",
            root_id="workspace-root",
            relpath="outputs/result.json",
            blob_hash="sha256:artifact",
            size_bytes=42,
            produced_by="executor",
        )
    )
    assert artifact.verification_state.value == "candidate"
    verified = lifecycle.mark_verified("artifact-1")
    assert verified.verification_state.value == "verified"
    invalidated = lifecycle.mark_invalidated("artifact-1")
    assert invalidated.verification_state.value == "invalidated"
    lineage = build_task_lineage_view(task_id="task-1", semantic_states=[], artifacts=[verified])
    assert lineage.verified_artifact_ids == ("artifact-1",)


def test_workspace_write_json_reuses_identical_payload_without_rewrite(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path / "workspaces")
    layout = workspace.ensure_layout("task-1")

    first = workspace.write_json(
        layout,
        "inputs/sample.json",
        {"alpha": 1, "beta": ["x"]},
        logical_name="sample",
    )
    second = workspace.write_json(
        layout,
        "inputs/sample.json",
        {"alpha": 1, "beta": ["x"]},
        logical_name="sample",
    )

    assert first.write_performed is True
    assert second.write_performed is False
    assert first.sha256 == second.sha256
    assert first.path.read_text(encoding="utf-8") == second.path.read_text(encoding="utf-8")


def test_workspace_materializes_input_and_output_contract_files(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    layout = workspace.ensure_layout("task-1")
    input_manifest = InputManifest(
        task_id="task-1",
        step_id="step-1",
        workspace_root=str(layout.root),
        inputs=(
            InputManifestItem(
                name="canonical_evidence_pack",
                artifact_type="json",
                relpath="inputs/evidence_pack.json",
                blob_hash="hash-evidence",
                source_ref_id="state-1",
            ),
        ),
    )
    output_manifest = ArtifactOutputManifest(
        task_id="task-1",
        step_id="step-1",
        outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=12,
                sha256="hash-output",
            ),
        ),
    )

    materialized_inputs = workspace.materialize_input_bundle(
        layout,
        input_manifest,
        payload_by_name={"canonical_evidence_pack": {"pack_id": "pack-1"}},
    )
    materialized_outputs = workspace.materialize_output_bundle(
        layout,
        output_manifest,
        payload_by_name={"summary_json": {"summary_text": "ok"}},
    )

    assert materialized_inputs.files[0].path.exists()
    assert materialized_outputs.files[0].path.exists()
    input_snapshot = json.loads(materialized_inputs.manifest_path.read_text(encoding="utf-8"))
    output_snapshot = json.loads(materialized_outputs.manifest_path.read_text(encoding="utf-8"))
    assert input_snapshot["manifest_hash"] == input_manifest.manifest_hash
    assert output_snapshot["manifest_hash"] == output_manifest.manifest_hash


def test_workspace_bundle_materialization_reuses_preexisting_files_without_rewrite(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    layout = workspace.ensure_layout("task-1")
    reused_input = workspace.write_json(
        layout,
        "inputs/evidence_pack.json",
        {"pack_id": "pack-1"},
        logical_name="canonical_evidence_pack",
    )
    reused_output = workspace.write_json(
        layout,
        "logs/step-1.stdout.json",
        {"stdout": "ok"},
        logical_name="stdout_log",
    )
    input_manifest = InputManifest(
        task_id="task-1",
        step_id="step-1",
        workspace_root=str(layout.root),
        inputs=(
            InputManifestItem(
                name="canonical_evidence_pack",
                artifact_type="json",
                relpath="inputs/evidence_pack.json",
                blob_hash="hash-evidence",
                source_ref_id="state-1",
            ),
        ),
    )
    output_manifest = ArtifactOutputManifest(
        task_id="task-1",
        step_id="step-1",
        outputs=(
            ArtifactManifestItem(
                artifact_name="stdout_log",
                artifact_type="json",
                relpath="logs/step-1.stdout.json",
                size_bytes=reused_output.size_bytes,
                sha256=reused_output.sha256,
            ),
        ),
    )

    materialized_inputs = workspace.materialize_input_bundle(
        layout,
        input_manifest,
        payload_by_name={},
        materialized_by_name={"canonical_evidence_pack": reused_input},
    )
    materialized_outputs = workspace.materialize_output_bundle(
        layout,
        output_manifest,
        payload_by_name={},
        materialized_by_name={"stdout_log": reused_output},
    )

    assert materialized_inputs.files[0].path == reused_input.path
    assert materialized_outputs.files[0].path == reused_output.path
    assert materialized_inputs.files[0].sha256 == reused_input.sha256
    assert materialized_outputs.files[0].sha256 == reused_output.sha256
    assert materialized_inputs.files[0].write_performed is False
    assert materialized_outputs.files[0].write_performed is False
    assert materialized_inputs.manifest_file.path.exists()
    assert materialized_outputs.manifest_file.path.exists()


def test_execution_log_capture_and_extended_output_manifest_are_formalized(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    layout = workspace.ensure_layout("task-1")
    log_capture = capture_execution_logs(
        workspace=workspace,
        layout=layout,
        step_id="step-1",
        stdout_text="hello stdout",
        stderr_text="warning stderr",
        capture_limit_bytes=8,
    )
    manifest = build_extended_output_manifest(
        task_id="task-1",
        step_id="step-1",
        primary_outputs=(
            ArtifactManifestItem(
                artifact_name="summary_json",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=12,
                sha256="hash-output",
            ),
        ),
        log_capture=log_capture,
    )
    assert log_capture.stdout_artifact.path.exists()
    assert log_capture.stderr_artifact.path.exists()
    assert manifest.outputs[1].artifact_name == "stdout_log"
    assert manifest.outputs[2].artifact_name == "stderr_log"


def test_codeact_runner_uses_single_inputs_bundle_and_candidate_tmp_output(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
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

    bundle_payload = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert result.request_path == result.plan_path
    assert result.request_path.relative_to(layout.root).as_posix().startswith("inputs/")
    assert result.output_path.relative_to(layout.root).as_posix() == "tmp/candidate_result.json"
    assert result.result_path.relative_to(layout.root).as_posix().startswith("tmp/")
    assert bundle_payload["request"]["task_id"] == "task-1"
    assert bundle_payload["plan"]["task_id"] == "task-1"
    assert bundle_payload["plan"]["execution_goal"] == "full_execution_goal"
    assert result.output_payload["route"] == "compare_metric"
    assert result.output_payload["tool_name"] == "table_retriever"
    assert result.record.output_relpath == "tmp/candidate_result.json"
    assert len(result.record.stage_results) == 3
    assert result.record.sandbox_requested_backend == "resource"
    assert result.record.sandbox_backend == "resource"


def test_codeact_runner_records_explicit_no_sandbox_backend(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    layout = workspace.ensure_layout("task-1")
    step_layout = workspace.ensure_step_layout(layout, "step-1")

    result = CodeActRunner(
        sandbox_config=CodeActSandboxConfig(requested_backend="none"),
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

    assert result.record.sandbox_requested_backend == "none"
    assert result.record.sandbox_backend == "none"
    assert result.record.sandbox_fallback_reason == ""


def test_codeact_runner_reuses_cached_result_for_identical_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.runtime import codeact as codeact_module

    workspace_one = WorkspaceManager(tmp_path / "workspace-one")
    layout_one = workspace_one.ensure_layout("task-1")
    step_layout_one = workspace_one.ensure_step_layout(layout_one, "step-1")
    workspace_two = WorkspaceManager(tmp_path / "workspace-two")
    layout_two = workspace_two.ensure_layout("task-1")
    step_layout_two = workspace_two.ensure_step_layout(layout_two, "step-1")

    runner = CodeActRunner(
        sandbox_config=CodeActSandboxConfig(requested_backend="resource"),
    )
    request = CodeActRequest(
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
    )

    sandbox_run_count = 0
    original_run = codeact_module.CodeActSandboxRunner.run

    def counting_run(self, *args, **kwargs):
        nonlocal sandbox_run_count
        sandbox_run_count += 1
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(codeact_module.CodeActSandboxRunner, "run", counting_run)

    first = runner.run(
        workspace=workspace_one,
        layout=layout_one,
        step_layout=step_layout_one,
        request=request,
    )
    second = runner.run(
        workspace=workspace_two,
        layout=layout_two,
        step_layout=step_layout_two,
        request=request,
    )

    assert sandbox_run_count == 1
    assert first.output_payload == second.output_payload
    assert second.request_path != first.request_path
    assert second.request_path.exists()
    assert second.script_path.exists()
    assert second.result_path.exists()
    assert second.output_path.exists()
    assert second.record.sandbox_backend == "resource"


def test_codeact_runner_auto_falls_back_when_bwrap_namespace_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_bwrap = fake_bin / "bwrap"
    fake_bwrap.write_text(
        "#!/bin/sh\n"
        "echo \"bwrap: No permissions to creating new namespace\" >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_bwrap.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}")

    workspace = WorkspaceManager(tmp_path / "workspace")
    layout = workspace.ensure_layout("task-1")
    step_layout = workspace.ensure_step_layout(layout, "step-1")

    result = CodeActRunner(
        sandbox_config=CodeActSandboxConfig(requested_backend="auto"),
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

    assert result.record.sandbox_requested_backend == "auto"
    assert result.record.sandbox_backend == "resource"
    assert result.record.sandbox_fallback_reason.startswith("bwrap_failed:")
    assert "No permissions to creating new namespace" in result.record.sandbox_fallback_reason


def test_execution_step_record_uses_compact_codeact_audit_payload(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
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
    manifest = build_extended_output_manifest(
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
    payload = ExecutionStepRecord(
        task_id="task-1",
        step_id="step-1",
        attempt_id="attempt-1",
        workspace_root=str(layout.root),
        execution_goal="full_execution_goal",
        exit_code=0,
        output_manifest=manifest,
        log_capture=log_capture,
        input_validator_reports=(),
        validator_reports=(),
        codeact_plan=result.plan,
        codeact_record=result.record,
    ).canonical_payload()

    assert payload["codeact_record"]["generated_code_hash"] == result.record.generated_code_hash
    assert payload["codeact_record"]["stdout_bytes"] == len(result.stdout_text.encode("utf-8"))
    assert payload["codeact_record"]["stderr_bytes"] == len(result.stderr_text.encode("utf-8"))
    assert sorted(payload["codeact_record"]["output_payload_field_names"]) == sorted(result.output_payload.keys())
    assert "stdout_text" not in payload["codeact_record"]
    assert "stderr_text" not in payload["codeact_record"]
    assert "output_payload" not in payload["codeact_record"]
    assert payload["codeact_record"]["stage_count"] == len(result.record.stage_results)
    assert payload["codeact_record"]["action_result_count"] == sum(
        len(stage.action_results) for stage in result.record.stage_results
    )
    assert payload["codeact_record"]["sandbox_backend"] == result.record.sandbox_backend
    assert payload["codeact_record"]["sandbox_requested_backend"] == result.record.sandbox_requested_backend
    assert payload["codeact_record"]["audit_relpath"].startswith("sidecars/codeact_record_audits/")
    assert "task_id" not in payload["codeact_record"]
    assert "step_id" not in payload["codeact_record"]
    assert "attempt_id" not in payload["codeact_record"]
    assert "execution_goal" not in payload["codeact_record"]
    assert payload["codeact_plan"]["plan_hash"] == result.plan.plan_hash
    assert payload["codeact_plan"]["stage_count"] == result.plan.stage_count
    assert payload["codeact_plan"]["action_count"] == result.plan.action_count
    assert payload["codeact_plan"]["audit_relpath"].startswith("sidecars/codeact_plan_audits/")
    assert "task_id" not in payload["codeact_plan"]
    assert "step_id" not in payload["codeact_plan"]
    assert "execution_goal" not in payload["codeact_plan"]
    assert "stages" not in payload["codeact_plan"]


def test_fallback_planner_builds_retry_then_downgrade_dag() -> None:
    dag = FallbackPlanner().plan_for_trap(
        task_id="task-1",
        source_step_id="execute-plot",
        requested_outputs=("summary_text", "plot_png"),
        fallback_action="retry_same_step",
    )
    assert len(dag.actions) == 2
    assert dag.actions[0].action_name == "retry_same_step"
    assert dag.actions[1].action_name == "downgrade_execution_goal"
    assert dag.actions[1].downgrade_outputs == ("plot_png",)


def test_telemetry_summary_and_quality_floor_report_are_formal_objects() -> None:
    emitter = TelemetryEmitter()
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="REPLAY_DECIDED",
            metrics={"reuse_gain": 0.25, "skipped_step_count": 2},
        )
    )
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="TASK_SUMMARY_METRICS",
            metrics={"control_bytes": 1024},
        )
    )
    summary = emitter.summarize_task("task-1")
    assert summary["reuse_gain"] == 0.25
    assert summary["control_bytes"] == 1024.0
    assert emitter.summarize_suite(["task-1"])["skipped_step_count"] == 2.0

    report = BenchmarkRunReport(
        layer=BenchmarkLayer.L2,
        task_family="financial_report_analysis",
        quality_floor=QualityFloorResult(
            quality_floor_pass=True,
            deterministic_checks_passed=True,
            fact_coverage_passed=True,
            llm_judge_passed=None,
        ),
        metrics={"latency_ms": 10.0},
    )
    assert report.eligible_for_headline is True


def test_telemetry_emitter_persists_runtime_event_and_fact_logs(tmp_path: Path) -> None:
    emitter = TelemetryEmitter(
        runtime_event_log_path=tmp_path / "runtime_events.jsonl",
        runtime_fact_log_path=tmp_path / "runtime_facts.jsonl",
    )
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="STEP_DISPATCHED",
            metrics={"timeout_ms": 250.0},
        )
    )
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="STEP_HEARTBEAT",
            metrics={"heartbeat_count": 1.0},
        )
    )
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="TASK_SUMMARY_METRICS",
            metrics={"control_bytes": 10.0},
        )
    )
    event_lines = (tmp_path / "runtime_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    fact_lines = (tmp_path / "runtime_facts.jsonl").read_text(encoding="utf-8").strip().splitlines()
    io_metrics = emitter.task_io_metrics("task-1")
    emitter.close()
    assert len(event_lines) == 3
    assert len(fact_lines) == 2
    assert io_metrics["telemetry_event_write_count"] == 3.0
    assert io_metrics["telemetry_fact_write_count"] == 2.0
    assert io_metrics["telemetry_log_handle_open_count"] == 2.0
    assert io_metrics["telemetry_emit_stage_ms"] >= 0.0


def test_telemetry_emitter_batches_flushes_for_benchmark_balanced_profile(tmp_path: Path) -> None:
    emitter = TelemetryEmitter(
        runtime_event_log_path=tmp_path / "runtime_events.jsonl",
        runtime_fact_log_path=tmp_path / "runtime_facts.jsonl",
        flush_interval=10,
    )
    emitter.emit(
        TelemetryEvent.create(
            trace_id="trace-1",
            task_id="task-1",
            event_type="STEP_DISPATCHED",
            metrics={"timeout_ms": 250.0},
        )
    )
    before_close = emitter.task_io_metrics("task-1")
    assert before_close["telemetry_event_write_count"] == 1.0
    assert before_close["telemetry_fact_write_count"] == 1.0
    assert before_close["telemetry_log_flush_count"] == 0.0
    emitter.close()
    after_close = emitter.task_io_metrics("task-1")
    assert after_close["telemetry_log_flush_count"] == 2.0
    event_lines = (tmp_path / "runtime_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    fact_lines = (tmp_path / "runtime_facts.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(event_lines) == 1
    assert len(fact_lines) == 1


def test_expected_fact_pass_supports_minimum_threshold_contract() -> None:
    from v2.runtime.smoke import _expected_fact_pass

    assert _expected_fact_pass(
        expected_facts={"percentage_cases_min": "36.45"},
        output_payload={"percentage_cases_min": 36.45},
    )
    assert _expected_fact_pass(
        expected_facts={"reused_artifact_count_min": "7"},
        output_payload={"reused_artifact_count": "10"},
    )
    assert not _expected_fact_pass(
        expected_facts={"reused_artifact_count_min": "7"},
        output_payload={"reused_artifact_count": "3"},
    )
